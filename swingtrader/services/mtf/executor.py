import math
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import db as db_module
from emasma_core import rank_key
from portfolio_guard import GuardConfig, GuardState, step as guard_step

NY = ZoneInfo('America/New_York')

# ── Retry-enabled session for Alpaca API ──
# Retries on transient failures (timeouts, 5xx, 429 rate-limit) with
# exponential backoff.  Replaces bare `requests.get/post` calls.
_ALPACA_TIMEOUT = 30  # seconds per attempt (was 10, too aggressive)


def _alpaca_session():
    """Return a requests.Session with automatic retry on transient errors."""
    s = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,          # 0s, 4s, 8s between attempts
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET', 'POST', 'DELETE'],
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


_session = _alpaca_session()

# Current Alpaca credentials (set by execute_rotation based on mode)
_current_api_key = config.ALPACA_API_KEY
_current_api_secret = config.ALPACA_SECRET_KEY

# Slack tag per mode: ETF leg now runs EMA/SMA rotation, not MTF.
STRATEGY_TAG = {'stock': 'MTF-TopN', 'etf': 'EMA-SMA'}
_current_strategy_tag = 'MTF-TopN'


def _set_alpaca_keys(mode):
    global _current_api_key, _current_api_secret, _current_strategy_tag
    _current_strategy_tag = STRATEGY_TAG.get(mode, 'MTF-TopN')
    if mode == 'etf':
        _current_api_key = config.ALPACA_ETF_API_KEY or config.ALPACA_API_KEY
        _current_api_secret = config.ALPACA_ETF_SECRET_KEY or config.ALPACA_SECRET_KEY
    else:
        _current_api_key = config.ALPACA_API_KEY
        _current_api_secret = config.ALPACA_SECRET_KEY


def _alpaca_headers():
    return {
        'APCA-API-KEY-ID': _current_api_key,
        'APCA-API-SECRET-KEY': _current_api_secret,
        'Content-Type': 'application/json',
    }


def _get_clock():
    url = f'{config.ALPACA_BASE_URL}/v2/clock'
    resp = _session.get(url, headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca clock failed: {resp.text}')
    return resp.json()


def _wait_for_market_open(max_wait_sec=6 * 3600):
    """Block until the regular market session is open.

    Fixes boot-time catch-up runs: swingtrader-mtf-executor.timer has Persistent=yes, so
    after a multi-day outage the timer fires the moment the machine boots
    (e.g. 09:08), well before the 09:30 open. Market orders placed pre-market
    sit in the queue and exhaust the 5-min _wait_for_fill poll, which logged
    'never filled' and skipped the DB update even though the orders filled at
    open.

    Returns True if the market is (or became) open; False if it won't open
    within max_wait_sec (weekend/holiday).
    """
    try:
        clock = _get_clock()
    except Exception as e:
        print(f'[MTF EXECUTOR] market-open check failed ({e}); proceeding anyway')
        return True

    if clock.get('is_open'):
        return True

    next_open = clock.get('next_open')
    if not next_open:
        print('[MTF EXECUTOR] market closed, next_open unknown — proceeding anyway')
        return True

    try:
        next_open_dt = datetime.fromisoformat(next_open)
        now_dt = datetime.now(NY)
        wait_sec = (next_open_dt - now_dt).total_seconds()
    except Exception:
        print('[MTF EXECUTOR] market-open parse failed — proceeding anyway')
        return True

    if wait_sec < 0:
        # next_open is in the past but is_open is false — treat as closed day.
        print('[MTF EXECUTOR] market closed for the day — aborting execution')
        return False
    if wait_sec > max_wait_sec:
        print(f'[MTF EXECUTOR] market opens in {wait_sec/3600:.1f}h (>{max_wait_sec/3600:.0f}h) — aborting execution')
        return False

    print(f'[MTF EXECUTOR] market not open yet; waiting {wait_sec/60:.0f} min until {next_open}')
    # Poll the clock until open (bounded by wait_sec).
    deadline = time.time() + wait_sec + 120
    while time.time() < deadline:
        time.sleep(30)
        try:
            if _get_clock().get('is_open'):
                print('[MTF EXECUTOR] market open — proceeding')
                return True
        except Exception:
            pass
    print('[MTF EXECUTOR] market did not open within wait window — aborting execution')
    return False


def _get_account():
    url = f'{config.ALPACA_BASE_URL}/v2/account'
    resp = _session.get(url, headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca account failed: {resp.text}')
    return resp.json()


def _get_account_number():
    acct = _get_account()
    return acct.get('account_number', '?')


def _get_order(order_id):
    url = f'{config.ALPACA_BASE_URL}/v2/orders/{order_id}'
    resp = _session.get(url, headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        return None
    return resp.json()


def _cancel_orders_for_symbol(symbol):
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    params = {'symbols': symbol, 'status': 'open'}
    resp = _session.get(url, headers=_alpaca_headers(), params=params, timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        return
    for order in resp.json():
        oid = order.get('id')
        if oid:
            _session.delete(f'{config.ALPACA_BASE_URL}/v2/orders/{oid}',
                            headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
            print(f'[MTF EXECUTOR] Cancelled stale order {oid} for {symbol}')


def _cancel_all_open_orders():
    """Cancel every open order on the active account (market-gate liquidation)."""
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    params = {'status': 'open', 'limit': 500}
    try:
        resp = _session.get(url, headers=_alpaca_headers(), params=params,
                            timeout=_ALPACA_TIMEOUT)
    except Exception:
        return
    if resp.status_code >= 400:
        return
    for order in resp.json():
        oid = order.get('id')
        if oid:
            try:
                _session.delete(f'{config.ALPACA_BASE_URL}/v2/orders/{oid}',
                                headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
                print(f'[MTF EXECUTOR] Cancelled open order {oid} for {order.get("symbol", "?")}')
            except Exception:
                pass


def _place_order(symbol, qty, side):
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    payload = {
        'symbol': symbol,
        'qty': str(qty),
        'side': side,
        'type': 'market',
        'time_in_force': 'day',
    }
    resp = _session.post(url, headers=_alpaca_headers(), json=payload, timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca order failed ({resp.status_code}): {resp.text}')
    return resp.json()


def _wait_for_fill(order_id, max_retries=300, delay=1):
    """Poll an order until it is FULLY filled (or hits a terminal state).
    Returns the final order object; returns None only if the order lookup fails.
    Wait on any partial fill was the root cause of understated mtf_positions."""
    for _ in range(max_retries):
        order = _get_order(order_id)
        if order is None:
            return None
        status = order.get('status')
        if status == 'filled':
            return order
        if status in ('cancelled', 'canceled', 'expired', 'rejected', 'suspended'):
            return order
        time.sleep(delay)
    return _get_order(order_id)


def _get_alpaca_position(symbol):
    url = f'{config.ALPACA_BASE_URL}/v2/positions/{symbol}'
    try:
        resp = _session.get(url, headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def _get_alpaca_positions():
    url = f'{config.ALPACA_BASE_URL}/v2/positions'
    resp = _session.get(url, headers=_alpaca_headers(), timeout=_ALPACA_TIMEOUT)
    if resp.status_code >= 400:
        return {}
    return {p['symbol']: p for p in resp.json()}


# Sliding re-entry tolerance: continuous exponential ramp. The longer since
# the last profit-taking SELL, the more appreciation we tolerate before a
# buyback counts as "chasing". A(d) = 1% * 10^(d/21): 1% at d=0, ~10% at
# d=21, and unrestricted beyond 21 days so a sustained uptrend is never
# locked out forever.
REBUY_RAMP_DAYS = 21
REBUY_BASE_TOLERANCE_PCT = 1.0
REBUY_MAX_TOLERANCE_PCT = 10.0


def _rebuy_tolerance_above_pct(days):
    """Max % above the sell price tolerated at a given days-since-sell.

    Returns (max_above_pct, unrestricted). Continuous exponential curve
    from REBUY_BASE_TOLERANCE_PCT to REBUY_MAX_TOLERANCE_PCT over
    REBUY_RAMP_DAYS days; unrestricted (never block) after the ramp."""
    if days >= REBUY_RAMP_DAYS:
        return None, True
    expo = days / REBUY_RAMP_DAYS
    pct = REBUY_BASE_TOLERANCE_PCT * (REBUY_MAX_TOLERANCE_PCT / REBUY_BASE_TOLERANCE_PCT) ** expo
    return pct, False


def _last_profit_sell(symbol, conn):
    """Return (sell_price, sell_date) of the most recent SELL for a symbol, or None."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT t.price, t.executed_at FROM mtf_trades t '
                'JOIN tbl_stock_tickers s ON s.id = t.ticker_id '
                'WHERE s.symbol = %s AND t.side = \'SELL\' '
                'ORDER BY t.executed_at DESC LIMIT 1', (symbol,))
            row = cur.fetchone()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    return float(row[0]), row[1]


def _block_rebuy(symbol, price, conn):
    """Block a re-entry that chases the last profit-taking exit.

    Tolerance is a continuous exponential ramp A(d) = 1% * 10^(d/21). A
    buyback is blocked ONLY when the re-entry price is more than A(d) above
    the last SELL price (d = days since that SELL), and never once the ramp
    expires (d >= REBUY_RAMP_DAYS). A pullback re-enters immediately, and a
    sustained uptrend becomes re-buyable once tolerance catches up — so this
    never locks a symbol out permanently.

    Returns (blocked, reason) — reason is a human-readable string."""
    if not config.ENABLE_CHASE_GUARD:
        return False, ''
    sell = _last_profit_sell(symbol, conn)
    if not sell:
        return False, ''
    sell_price, sell_dt = sell
    if sell_dt:
        days = max(0, (datetime.now(NY) - sell_dt.replace(tzinfo=NY)).days)
    else:
        days = 0
    above_pct = (price - sell_price) / sell_price * 100
    max_pct, unrestricted = _rebuy_tolerance_above_pct(days)
    if not unrestricted and above_pct > max_pct:
        reason = (f'chase guard: sold {sell_price:.2f} {days}d ago, '
                  f're-entry {price:.2f} (+{above_pct:.1f}%) > '
                  f'+{max_pct:.1f}% allowed at {days}d')
        return True, reason
    return False, ''


def _guard_enabled(mode):
    """True only for modes explicitly opted in (ETF first; stocks later)."""
    return bool(getattr(config, 'GUARD_ENABLED', False)) and mode in tuple(
        getattr(config, 'GUARD_MODES', ('etf',)))


def _guard_setting(mode, name, default):
    """Mode override first, then the shared GUARD_* default."""
    return getattr(config, f'GUARD_{mode.upper()}_{name}',
                   getattr(config, f'GUARD_{name}', default))


def _guard_config(mode):
    return GuardConfig(
        hwm_stop_pct=float(_guard_setting(mode, 'HWM_STOP_PCT', 0.0)) / 100.0,
        sweep_pct=float(_guard_setting(mode, 'PROFIT_SWEEP_PCT', 0.0)) / 100.0,
        cooldown_sessions=int(_guard_setting(mode, 'COOLDOWN_SESSIONS', 5)),
        min_sweep=float(_guard_setting(mode, 'MIN_SWEEP', 0.0)),
    )


def _guard_week_key(d):
    iso = d.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _guard_mark_equity(positions, cash, close_map):
    """Total equity at the last settled close: cash + positions * settled close."""
    total = float(cash or 0.0)
    for sym, pos in (positions or {}).items():
        px = close_map.get(sym)
        if px:
            total += abs(float(pos.get('qty', 0) or 0)) * float(px)
        else:
            total += _position_value(pos)
    return total


def _latest_trade_price(symbol):
    url = 'https://data.alpaca.markets/v2/stocks/trades/latest'
    try:
        resp = _session.get(url, headers=_alpaca_headers(),
                            params={'symbols': symbol, 'feed': 'iex'}, timeout=_ALPACA_TIMEOUT)
        if resp.status_code < 400:
            trade = resp.json().get('trades', {}).get(symbol)
            if trade and 'p' in trade:
                return float(trade['p'])
    except Exception:
        pass
    return None


def _position_value(pos):
    """Market value of an Alpaca position (market_value, else qty x price)."""
    if not pos:
        return 0.0
    try:
        mv = pos.get('market_value')
        if mv is not None:
            return abs(float(mv))
    except (TypeError, ValueError):
        pass
    try:
        qty = abs(float(pos.get('qty', 0) or 0))
        price = abs(float(pos.get('current_price', 0) or 0))
        return qty * price
    except (TypeError, ValueError):
        return 0.0


def _risk_per_position(equity, investable_equity, n_in_play, top_n, size_by_top_n):
    """Target dollar size for each in-play name (stock leg risk sizing).

    SIZE_BY_TOP_N caps every name at equity/TOP_N so a thin book cannot
    concentrate the account, and subtracts preserved (out-of-book) holdings so
    gross exposure never exceeds equity. Falls back to the legacy
    equity/len(in_play) when disabled, and when preserved holdings already
    consume the whole account (never liquidate the book to zero on a data gap).
    """
    n = max(1, n_in_play)
    if not size_by_top_n:
        return equity / n
    if investable_equity <= 0:
        return equity / n
    return max(0.0, min(investable_equity / n, equity / max(1, top_n)))


def _should_trim(value, target, band_pct, min_notional):
    """Trim only when the excess clears both the drift band and min notional."""
    excess = value - target
    if excess <= 0:
        return False
    if excess < target * (band_pct / 100.0):
        return False
    return excess >= min_notional


def _should_top_up(needed, target, band_pct, min_notional):
    """Top up only when the shortfall clears both the drift band and min notional."""
    if needed <= 0:
        return False
    if needed < target * (band_pct / 100.0):
        return False
    return needed >= min_notional


def _compute_ratchet_stops(conn, held_symbols):
    """Compute the ratchet-ATR stop for each held symbol (stateless).

    ratchet = max over holding days t of (running_peak_close(t) - MULT*ATR_t),
    where the running peak is the highest DAILY close since entry and ATR_t is
    that day's ATR (from the daily table's atr_stop column, which is
    close - 2*ATR on daily bars). Peak-anchored and non-decreasing, so it
    never floats down with a crash. Rebuilt from source data every run — no
    stored state to drift or go stale.

    Live == backtest (backtest_topn_multitf.py --ratchet-atr-src daily): the
    backtest evaluates the ratchet on completed DAILY closes and sells at the
    next day's open. We therefore exclude today's in-progress bar (date < now)
    from both the ATR/peak math and the comparison close (see
    latest_settled_daily_closes), so the stop only reacts to a settled daily
    close — matching the backtest and avoiding intraday wicks.

    Returns {symbol: ratchet_price}. Symbols with no completed daily ATR bars
    since entry are omitted (caller skips the ratchet check, conservative)."""
    import math
    today = datetime.now(NY).date()
    stops = {}
    for symbol in held_symbols:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT ticker_id, entry_at, entry_price FROM mtf_positions '
                'WHERE symbol = %s ORDER BY updated_at DESC LIMIT 1', (symbol,))
            row = cur.fetchone()
        if not row or not row[0]:
            continue
        tid = row[0]
        entry_at = row[1]
        entry_price = float(row[2]) if row[2] else 0.0
        since = entry_at.date() if entry_at else None

        # Completed daily bars (close + the day's own atr_stop) since entry.
        # date < today mirrors the settled-close convention of the backtest.
        with conn.cursor() as cur:
            if since:
                cur.execute(
                    'SELECT date, close, atr_stop FROM tbl_prices_daily '
                    'WHERE ticker_id = %s AND date::date >= %s AND date::date < %s '
                    'ORDER BY date ASC', (tid, since, today))
            else:
                cur.execute(
                    'SELECT date, close, atr_stop FROM tbl_prices_daily '
                    'WHERE ticker_id = %s AND date::date < %s ORDER BY date ASC',
                    (tid, today))
            d_rows = cur.fetchall()
        if not d_rows:
            continue

        # Backtest parity: peak is seeded from the entry price (fill), then
        # grows to the highest settled daily close. ATR is the day's own ATR
        # from the daily table (atr_stop = close - 2*ATR on daily bars).
        peak = entry_price if entry_price > 0 else 0.0
        ratchet = 0.0
        for r in d_rows:
            dc = float(r[1]) if r[1] else 0.0
            peak = max(peak, dc)
            atr_stop = float(r[2]) if r[2] else 0.0
            if atr_stop <= 0 or dc <= atr_stop:
                continue
            atr = (dc - atr_stop) / 2.0
            if atr <= 0:
                continue
            ratchet = max(ratchet, peak - config.RATCHET_ATR_MULT * atr)
        # A held name must never reach here with a NULL atr_stop on its newest bar:
        # data_readiness.py hard-blocks that. If it happens anyway, the ratchet silently
        # stops advancing, so say so loudly instead of skipping the bar unnoticed.
        if not d_rows[-1][2] or float(d_rows[-1][2]) <= 0:
            print(f'[MTF EXECUTOR] ⚠️ HELD {symbol}: newest daily bar {d_rows[-1][0]} has '
                  f'NULL/invalid atr_stop — ratchet stop is STALE (no trailing-stop update)',
                  flush=True)
        if peak > 0:
            stops[symbol] = ratchet
    return stops


def _entry_price_map(conn, held_symbols):
    """Map held symbol -> recorded entry fill price (mtf_positions).

    Same anchor the ratchet seeds its peak from; partial trims/top-ups preserve
    it (db.adjust_position_qty only changes quantity)."""
    entries = {}
    for symbol in held_symbols:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT entry_price FROM mtf_positions '
                'WHERE symbol = %s ORDER BY updated_at DESC LIMIT 1', (symbol,))
            r = cur.fetchone()
        if r and r[0]:
            entries[symbol] = float(r[0])
    return entries


def _fixed_stop_hits(entries, closes, pct):
    """Symbols whose settled close is at/below entry * (1 - pct/100).

    Returns {symbol: stop_price}. Pure helper so the threshold logic is unit
    testable; `pct <= 0` disables the rule. Mirrors backtest_topn_multitf.py
    --stop-loss (drop >= pct% from the entry fill, next-open execution)."""
    if not pct or pct <= 0:
        return {}
    hits = {}
    for sym, entry in entries.items():
        c = closes.get(sym)
        if not entry or entry <= 0 or c is None:
            continue
        stop = entry * (1.0 - pct / 100.0)
        if c <= stop:
            hits[sym] = stop
    return hits


def latest_settled_daily_closes(conn, held_symbols):
    """Map held symbol -> last SETTLED daily bar close (ratchet price source).

    Live == backtest: the backtest signals the ratchet exit on day D's daily
    close and fills at day D+1's open. The executor runs once a day during the
    session, so 'day D' is the most recent completed daily bar — the last daily
    row with date strictly before today. Returning it for the comparison means
    the ratchet fires only after a daily bar has genuinely closed below the
    stop, never on an intraday tick or in-progress bar (CNXN/HOOD/MU/SFST
    09-08, GLW 09-10 wick cases).

    Returns {symbol: close}; symbols with no completed daily bar are omitted
    (caller skips the ratchet check, conservative)."""
    today = datetime.now(NY).date()
    closes = {}
    for symbol in held_symbols:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT close FROM tbl_prices_daily '
                'WHERE ticker_id=(SELECT id FROM tbl_stock_tickers WHERE symbol=%s) '
                'AND date::date < %s ORDER BY date DESC LIMIT 1', (symbol, today))
            r = cur.fetchone()
        if r and r[0]:
            closes[symbol] = float(r[0])
    return closes


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    acct_no = _get_account_number()
    try:
        _session.post(config.SLACK_WEBHOOK_URL,
                      json={'text': f'[{_current_strategy_tag}] [Paper:{acct_no}] {msg}'},
                      timeout=_ALPACA_TIMEOUT)
    except Exception as e:
        print(f'[MTF EXECUTOR SLACK] Error: {e}')


def _send_slack_error(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    acct_no = _get_account_number()
    try:
        _session.post(config.SLACK_WEBHOOK_URL,
                      json={'text': f'⚠️ [{_current_strategy_tag}] [Paper:{acct_no}] {msg}'},
                      timeout=_ALPACA_TIMEOUT)
    except Exception as e:
        print(f'[MTF EXECUTOR SLACK] Error: {e}')


def _wait_for_network(timeout_sec=30, check_hosts=['8.8.8.8', 'paper-api.alpaca.markets']):
    """Wait for network connectivity after wake-from-suspend.
    Retries DNS resolution of key hosts until available or timeout.
    
    Fixes timing issue when executor.timer fires immediately after wake,
    before WiFi/network is fully connected."""
    import socket
    start = time.time()
    for host in check_hosts:
        while time.time() - start < timeout_sec:
            try:
                socket.gethostbyname(host)
                print(f'[MTF] Network ready: {host} resolved')
                return True
            except (socket.gaierror, OSError):
                time.sleep(0.5)
                continue
    print(f'[MTF] Warning: network not ready after {timeout_sec}s; proceeding anyway')
    return False


def execute_rotation(top_symbols, score_detail, mode='stock', dry_run=False,
                     market_gate_off=False):
    """Execute MTF rotation: sell dropped positions, buy new entries.

    Args:
        top_symbols: list of symbols in the new top-N
        score_detail: dict of {symbol: {score, close, ...}} for top picks
        mode: 'stock' or 'etf'
        dry_run: preview planned trims/top-ups/sells/buys WITHOUT placing any
            orders or touching the DB (no cancels, no fills, no state writes)
        market_gate_off: stock leg only. When True, liquidate every held name
            and place no buys (CoreEW P20w flat gate); the ETF leg ignores it.

    Returns:
        list of human-readable trade summary lines
    """
    _wait_for_network()
    _set_alpaca_keys(mode)
    if not dry_run and not _wait_for_market_open():
        print('[MTF EXECUTOR] skipping execution: market closed')
        return ['  ⚠️ Market closed — no orders placed (guard)']
    conn = db_module.get_conn()
    now = datetime.now(NY)
    trade_lines = []
    buys = []
    sells = []

    try:
        alpaca_positions = _get_alpaca_positions()
        account = _get_account()
        equity = float(account.get('equity', 0))
        buying_power = float(account.get('buying_power', 0))

        held_symbols = set(alpaca_positions.keys())
        target_symbols = set(top_symbols)

        symbols_to_sell = held_symbols - target_symbols

        # ── Portfolio guard (ETF first, opt-in per mode) ──
        # Marks total equity at the last SETTLED close and applies the pure
        # portfolio_guard policy. Sweep and weekly-close stop run on the first
        # execution of each ISO week, matching the weekly rebalance; the HWM is
        # still updated on every run. The reserve is cash: sizing subtracts it
        # from active equity and the normal equal-weight trim creates it.
        guard_state = None
        guard_last_week = ''
        guard_paused = False
        guard_liquidate = False
        guard_sweep_requested = 0.0
        guard_reserve = 0.0
        if _guard_enabled(mode):
            guard_close_map = latest_settled_daily_closes(conn, held_symbols)
            mark_equity = _guard_mark_equity(
                alpaca_positions, account.get('cash', 0), guard_close_map)
            raw_guard, guard_last_week = db_module.get_guard_state(
                conn, mode, ensure=not dry_run)
            guard_state = (GuardState.from_dict(raw_guard) if raw_guard
                           else GuardState(hwm=mark_equity))
            if guard_state.hwm <= 0:
                guard_state.hwm = mark_equity
                guard_state.sweep_hwm = mark_equity
            week = _guard_week_key(now.date())
            first_of_week = guard_last_week != week
            allow_sweep = (True if not _guard_setting(mode, 'SWEEP_ON_REBALANCE', True)
                           else first_of_week)
            allow_stop = (True if _guard_setting(mode, 'STOP_CHECK', 'weekly') != 'weekly'
                          else first_of_week)
            guard_state, gd = guard_step(
                guard_state, _guard_config(mode), equity=mark_equity,
                session=str(now.date()), allow_sweep=allow_sweep,
                allow_stop=allow_stop)
            if first_of_week:
                guard_last_week = week
            guard_paused = bool(gd.paused)
            guard_liquidate = bool(gd.liquidate)
            guard_sweep_requested = max(0.0, float(gd.sweep_amount))
            guard_reserve = guard_state.reserve + guard_sweep_requested
            if guard_liquidate:
                trade_lines.append(
                    f'  🛑 Guard HWM stop — liquidating {mode.upper()} book, no buys')
                print(f'[MTF EXECUTOR] Guard HWM stop — liquidating {mode.upper()} book')
            elif guard_paused and held_symbols:
                guard_liquidate = True
                trade_lines.append(
                    '  🛑 Guard cooldown with positions still held — retrying liquidation')
                print('[MTF EXECUTOR] Guard cooldown with positions — retrying liquidation')
            if guard_sweep_requested > 0:
                trade_lines.append(
                    f'  💰 Guard sweep ${guard_sweep_requested:,.2f} '
                    f'(reserve target ${guard_reserve:,.2f})')
                print(f'[MTF EXECUTOR] Guard sweep ${guard_sweep_requested:,.2f}')

        # CoreEW P20w flat gate: when the market regime is OFF, the stock book
        # goes to cash (sell everything, no buys). ETF leg unaffected.
        gate_off = bool(market_gate_off and mode == 'stock')
        if gate_off:
            msg_gate = '🛑 Market gate OFF — liquidating the stock book, no buys'
            trade_lines.append(f'  {msg_gate}')
            print(f'[MTF EXECUTOR] {msg_gate}')
            symbols_to_sell = set(held_symbols)
        if guard_liquidate:
            symbols_to_sell = set(held_symbols)

        # ── Ratchet-ATR crash protection (stock leg only) ──
        # Exit any held position whose close < (highest daily close since entry)
        # - RATCHET_ATR_MULT x DAILY ATR. Peak-anchored, so it never floats
        # down with a crash like the close-anchored atr_stop does. Stateless:
        # rebuilt from the DB every run. Live == backtest
        # (backtest_topn_multitf.py --ratchet-atr-src daily): both the ATR and
        # the comparison close come from SETTLED DAILY bars only (today's
        # in-progress bar is excluded), so the ratchet fires only after a daily
        # bar has genuinely closed below the stop — matching the backtest that
        # signals on day D's daily close and fills at day D+1's open.
        ratchet_sold = set()
        fixed_stop_sold = set()
        fixed_stop_prices = {}
        fixed_pct = 0.0
        cooled_out = set()
        ratchet_stops = {}
        close_map = {}
        cooldown_days = int(getattr(config, 'RATCHET_COOLDOWN_TRADING_DAYS', 1))
        if mode == 'stock' and config.RATCHET_EXIT and not gate_off and not guard_liquidate:
            # Multi-day ratchet cool-off (persisted in DB). The stock leg ranks on
            # the last SETTLED weekly bar, so the top-N is static Mon-Fri and the
            # old same-day guard was a no-op once the executor moved to once/day:
            # every mid-week ratchet sell was re-bought the next morning. Block
            # re-entry for RATCHET_COOLDOWN_TRADING_DAYS trading days; freed slots
            # are backfilled from rank N+1 so the book still holds ~TOP_N names.
            cooldown_cutoff = db_module.ratchet_cooldown_cutoff(conn, cooldown_days, now.date())
            db_module.purge_ratchet_cooldowns(conn, mode, cooldown_cutoff)
            cooled_out |= db_module.get_ratchet_cooldowns(conn, mode, cooldown_cutoff)
            ratchet_stops = _compute_ratchet_stops(conn, held_symbols)
            close_map = latest_settled_daily_closes(conn, held_symbols)
            for sym in held_symbols:
                stop = ratchet_stops.get(sym)
                c = close_map.get(sym)
                if stop is not None and c is not None and c < stop:
                    ratchet_sold.add(sym)
            if ratchet_sold:
                for sym in sorted(ratchet_sold):
                    stop = ratchet_stops.get(sym)
                    c = close_map.get(sym)
                    if stop is None or c is None:
                        continue
                    msg_t = f'🛑 {sym} below ratchet stop ${stop:.2f} (close ${c:.2f})'
                    trade_lines.append(f'  {msg_t}')
                    print(f'[MTF EXECUTOR] {msg_t}')

            # Fixed % floor, independent of (and in addition to) the ATR ratchet.
            # Anchored to the recorded entry fill; evaluated on the same settled
            # daily close so live == backtest --stop-loss. Whichever fires first.
            fixed_pct = float(getattr(config, 'FIXED_STOP_PCT', 0) or 0)
            if fixed_pct > 0:
                entries = _entry_price_map(conn, held_symbols)
                fixed_stop_prices = _fixed_stop_hits(entries, close_map, fixed_pct)
                fixed_stop_sold = set(fixed_stop_prices)
                for sym in sorted(fixed_stop_sold):
                    msg_f = (f'🛑 {sym} below fixed {fixed_pct:g}% stop '
                             f'${fixed_stop_prices[sym]:.2f} (close ${close_map[sym]:.2f})')
                    trade_lines.append(f'  {msg_f}')
                    print(f'[MTF EXECUTOR] {msg_f}')
        stop_sold = ratchet_sold | fixed_stop_sold

        # Guard: don't sell positions that weren't scored today — they either
        # failed the bullish filter or had missing data. Preserve to avoid
        # whipsaw on a marginal filter flip (e.g. IJH 07-31: daily EMA 1c below SMA40).
        # Stop exits override the guard: crash protection beats whipsaw avoidance.
        if gate_off or guard_liquidate:
            data_gap_held = []
        else:
            data_gap_held = [s for s in symbols_to_sell if s not in score_detail and s not in stop_sold]
            for sym in data_gap_held:
                trade_lines.append(f'  ⚠️ {sym} held but not scored today (filter or data gap) — preserving')
                print(f'[MTF EXECUTOR] ⚠️ {sym} held but not scored today (filter or data gap) — preserving position')
        symbols_to_sell = (symbols_to_sell - set(data_gap_held)) | stop_sold

        # Cancel all open orders first (skipped in dry-run: never touch live orders).
        # The gate liquidation must also cancel any stray buy orders for names
        # that are not currently held, not just orders on held symbols.
        if not dry_run:
            if gate_off or guard_liquidate:
                _cancel_all_open_orders()
            else:
                for symbol in held_symbols | target_symbols:
                    _cancel_orders_for_symbol(symbol)

        # ── Sell dropped positions ──
        for symbol in sorted(symbols_to_sell):
            pos = alpaca_positions.get(symbol)
            if not pos:
                continue
            qty = abs(int(float(pos.get('qty', 0))))
            if qty < 1:
                continue
            if dry_run:
                trade_lines.append(f'  🧪 [DRY-RUN] SELL {qty} {symbol}')
                print(f'[MTF EXECUTOR] DRY-RUN SELL {qty} {symbol}')
                continue
            try:
                order = _place_order(symbol, qty, 'sell')
            except Exception as e:
                _send_slack_error(f'{symbol} SELL failed: {e}')
                trade_lines.append(f'  ❌ SELL {symbol} failed: {e}')
                continue

            filled_order = order
            if order.get('status') != 'filled':
                filled_order = _wait_for_fill(order.get('id')) or order

            filled_qty = int(float(filled_order.get('filled_qty', qty)))
            fill_price = float(filled_order['filled_avg_price']) if filled_order.get('filled_avg_price') else None
            if filled_qty < 1:
                _send_slack_error(f'{symbol} SELL order {order.get("id")} never filled')
                trade_lines.append(f'  ❌ SELL {symbol} qty={qty} never filled')
                continue
            if not fill_price:
                fill_price = _latest_trade_price(symbol)

            # Update DB
            ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
            entry_price = None
            if ticker_id:
                db_pos = db_module.get_position(conn, ticker_id)
                if db_pos:
                    entry_price = float(db_pos[2]) if db_pos[2] else None
                db_module.delete_position(conn, ticker_id)

            pnl_dollar = (fill_price - (entry_price or fill_price)) * filled_qty
            pnl_pct = (fill_price - (entry_price or fill_price)) / (entry_price or fill_price) * 100 if entry_price else 0

            if ticker_id:
                db_module.insert_trade(conn, ticker_id, symbol, 'SELL', filled_qty, fill_price, now,
                                       pnl_dollar=pnl_dollar, pnl_pct=pnl_pct)

            msg_str = f'SELL {filled_qty} {symbol} @ ${fill_price:.2f}'
            if entry_price:
                msg_str += f'  (PnL: {pnl_pct:+.2f}%)'
            if gate_off:
                msg_str += '  [market gate OFF]'
            elif guard_liquidate:
                msg_str += '  [guard HWM stop]'
            elif symbol in stop_sold:
                if config.RATCHET_EXIT and mode == 'stock':
                    db_module.insert_ratchet_cooldown(conn, mode, symbol, now.date())
                stop = ratchet_stops.get(symbol)
                if symbol in ratchet_sold and stop is not None:
                    msg_str += f'  [ratchet stop @ ${stop:.2f}]'
                if symbol in fixed_stop_sold:
                    msg_str += f'  [fixed {fixed_pct:g}% stop @ ${fixed_stop_prices[symbol]:.2f}]'
            sells.append(symbol)
            trade_lines.append(f'  {msg_str}')
            print(f'[MTF EXECUTOR] {msg_str}')

        if guard_liquidate:
            n_sold = len(sells) if not dry_run else len(symbols_to_sell)
            msg = (f'Guard HWM stop: {n_sold} sells, 0 buys — '
                   f'${equity:,.0f} equity (cash)')
            trade_lines.append(f'  {msg}')
            print(f'[MTF EXECUTOR] {msg}')
            if not dry_run:
                db_module.save_guard_state(
                    conn, mode, guard_state.to_dict(), guard_last_week)
                _send_slack(f'🛑 Guard HWM stop ({mode.upper()}): sold {len(sells)} names, '
                            f'holding cash. Reserve ${guard_state.reserve:,.2f}.')
            return trade_lines

        if gate_off:
            n_sold = len(sells) if not dry_run else len(symbols_to_sell)
            msg = (f'Market gate OFF: {n_sold} sells, 0 buys — '
                   f'${equity:,.0f} equity (cash)')
            trade_lines.append(f'  {msg}')
            print(f'[MTF EXECUTOR] {msg}')
            if not dry_run and sells:
                _send_slack(f'🛑 Market gate OFF (P20w {config.MARKET_GATE_MODE}): '
                            f'sold {len(sells)} names, holding cash.')
            return trade_lines

        # ── Buy new entries ──
        # New top-N names not already held, minus ratchet-sold AND same-day
        # cool-off names (avoid the CNXN/HOOD/MU/SFST re-buy whipsaw). Slots
        # freed by ratchet/cool-off OR chase-guard-blocked top-N names are
        # filled from the next-best scored candidates (rank 11+) so the
        # portfolio stays fully invested.
        blocked_buys = stop_sold | cooled_out
        held_after_sell = held_symbols - symbols_to_sell
        buy_targets = [s for s in target_symbols
                       if s not in held_after_sell and s not in blocked_buys]
        # Pre-check chase-guard blocks so we can backfill from rank 11+.
        pre_blocked = set()
        for sym in buy_targets:
            sd = score_detail.get(sym, {})
            price = sd.get('close') or _latest_trade_price(sym)
            if price and price > 0:
                blocked, _ = _block_rebuy(sym, price, conn)
                if blocked:
                    pre_blocked.add(sym)
        # Backfill slots freed by ratchet-sold (incl. same-day cool-off) AND blocked names.
        blocked_buy_ban = sorted(s for s in target_symbols if s in blocked_buys)
        if blocked_buy_ban:
            msg_ban = ', '.join(blocked_buy_ban)
            trade_lines.append(
                f'  🧊 ratchet cool-off {cooldown_days}d (re-buy skipped, slot backfilled): {msg_ban}')
            print(f'[MTF EXECUTOR] 🧊 ratchet cool-off blocks re-buy: {msg_ban}')
        freed_count = len(blocked_buy_ban) + len(pre_blocked)
        fillers = []
        if freed_count:
            # Rank the pool with the SAME key as the top-N (score DESC, then
            # gap_w DESC — emasma_core.rank_key) so a filler is the genuine
            # next-best, not an arbitrary pick among tie-scored names.
            ranked = sorted(score_detail.items(), key=lambda kv: rank_key(kv[1]))
            for sym, sd in ranked:
                if len(fillers) >= freed_count:
                    break
                if (sym not in held_after_sell and sym not in target_symbols
                        and sym not in symbols_to_sell and sym not in blocked_buys and sym not in pre_blocked):
                    fillers.append(sym)
        symbols_to_buy = [s for s in buy_targets if s not in pre_blocked] + fillers

        # Equal-weight book (CoreEW-style): held names still in the top-N target
        # ∪ new buys ∪ backfill fillers. Preserved data-gap names (held but not
        # scored / not in target) stay untouched — they're a whipsaw guard, not
        # part of the rotation book, so they neither get trimmed nor topped up.
        in_play_names = [s for s in held_after_sell if s in target_symbols] + symbols_to_buy
        in_play_names = [s for s in in_play_names if s not in blocked_buys]
        if guard_paused:
            trade_lines.append('  ⏸️ Guard cooldown — no buys or rebalances this run')
            print('[MTF EXECUTOR] Guard cooldown — holding cash')
            symbols_to_buy = []
            in_play_names = []

        if config.EQUAL_WEIGHT and in_play_names:
            # ── CoreEW-style equal-weight sizing (backtest --equal-weight + live risk caps) ──
            # Both legs (stocks TOP_N, ETFs ETF_TOP_N): trims overweights to target
            # and tops up/rebuilds every underweight or new in-play name.
            # Stock leg (2026-11-02): preserved names are held but sit OUTSIDE the
            # rotation book, so their market value is subtracted from the investable
            # equity and each name is capped at equity/TOP_N — no concentration on a
            # thin book and no margin (gross <= 100% equity). ETF leg keeps the
            # legacy equity/len(book) sizing (frozen experiment).
            risk_sizing = (mode == 'stock' and config.SIZE_BY_TOP_N)
            band_pct = config.REBALANCE_BAND_PCT if mode == 'stock' else 0.0
            min_notional = config.MIN_TRADE_NOTIONAL if mode == 'stock' else 0.0
            top_n_cap = config.TOP_N if mode == 'stock' else config.ETF_TOP_N
            fresh_pos = _get_alpaca_positions()
            try:
                fresh_acct = _get_account()
                equity = float(fresh_acct.get('equity', equity))
            except Exception:
                pass
            in_play = sorted(in_play_names)
            # Any still-held name outside the top-N is preserved (whipsaw guard,
            # failed sell, or data gap). Read from live positions, not the
            # intended sell list, so a failed sell is still counted as capital.
            preserved = [s for s in fresh_pos if s not in target_symbols]
            preserved_value = sum(_position_value(fresh_pos.get(s)) for s in preserved)
            # Guard reserve is permanent cash: size only the active book.
            reserved = guard_reserve
            active_equity = max(0.0, equity - reserved)
            investable_equity = max(0.0, active_equity - preserved_value)
            per_position = _risk_per_position(active_equity, investable_equity, len(in_play),
                                              top_n_cap, risk_sizing)
            gross_now = sum(_position_value(p) for p in fresh_pos.values())
            # A negative-cash leg must be de-levered first: exact equal weight
            # (band/min-notional off for this run) so gross lands at <= active
            # equity. The drift band resumes on the next run once margin is gone.
            deleveraging = bool(risk_sizing and gross_now > active_equity)
            if reserved > 0:
                trade_lines.append(
                    f'  🔒 Guard reserve ${reserved:,.2f}; active equity ${active_equity:,.2f}')
            if deleveraging:
                band_pct = 0.0
                min_notional = 0.0
                trade_lines.append(
                    f'  ⚖️ gross ${gross_now:,.0f} > equity ${equity:,.0f} — '
                    f'exact EW de-lever (no margin)')
            qty_map = {s: abs(int(float(p.get('qty', 0))))
                       for s, p in fresh_pos.items() if p}

            # 1) TRIM overweight held in-play names down to the target.
            for symbol in sorted(in_play_names):
                pos = fresh_pos.get(symbol)
                if not pos:
                    continue
                qty_now = abs(int(float(pos.get('qty', 0))))
                if qty_now < 1:
                    continue
                price = score_detail.get(symbol, {}).get('close') or _latest_trade_price(symbol)
                if not price or price <= 0:
                    continue
                value = qty_now * price
                if not _should_trim(value, per_position, band_pct, min_notional):
                    continue
                # ceil, not floor: never leave the position above target after
                # share rounding (floor is what lets gross drift into margin).
                sell_qty = math.ceil((value - per_position) / price)
                if sell_qty < 1:
                    continue
                sell_qty = min(sell_qty, qty_now - 1)  # never fully close a target name
                if sell_qty * price < min_notional:
                    continue
                if dry_run:
                    trade_lines.append(f'  🧪 [DRY-RUN] TRIM {sell_qty} {symbol} @ ${price:.2f} → ${per_position:,.0f}')
                    print(f'[MTF EXECUTOR] DRY-RUN TRIM {sell_qty} {symbol} @ {price}')
                    continue
                try:
                    order = _place_order(symbol, sell_qty, 'sell')
                except Exception as e:
                    _send_slack_error(f'{symbol} TRIM failed: {e}')
                    trade_lines.append(f'  ❌ TRIM {symbol} failed: {e}')
                    continue
                filled_order = order
                if order.get('status') != 'filled':
                    filled_order = _wait_for_fill(order.get('id')) or order
                filled_qty = int(float(filled_order.get('filled_qty', sell_qty)))
                fill_price = float(filled_order['filled_avg_price']) if filled_order.get('filled_avg_price') else None
                if filled_qty < 1:
                    _send_slack_error(f'{symbol} TRIM order {order.get("id")} never filled')
                    trade_lines.append(f'  ❌ TRIM {symbol} qty={sell_qty} never filled')
                    continue
                if not fill_price:
                    fill_price = price

                ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
                entry_price = None
                if ticker_id:
                    db_pos = db_module.get_position(conn, ticker_id)
                    if db_pos:
                        entry_price = float(db_pos[2]) if db_pos[2] else None
                    new_qty = qty_now - filled_qty
                    qty_map[symbol] = new_qty
                    db_module.adjust_position_qty(conn, ticker_id, symbol, new_qty, fill_price)
                    db_module.insert_trade(conn, ticker_id, symbol, 'SELL',
                                           filled_qty, fill_price, now,
                                           pnl_dollar=(fill_price - (entry_price or fill_price)) * filled_qty,
                                           pnl_pct=((fill_price - (entry_price or fill_price)) / (entry_price or fill_price) * 100) if entry_price else 0)
                msg_str = f'TRIM {filled_qty} {symbol} @ ${fill_price:.2f} (target ${per_position:,.0f})'
                sells.append(symbol)
                trade_lines.append(f'  {msg_str}')
                print(f'[MTF EXECUTOR] {msg_str}')

            # 2) BUY / TOP-UP every underweight or new in-play name up to target.
            for symbol in sorted(in_play):
                price = score_detail.get(symbol, {}).get('close') or _latest_trade_price(symbol)
                if not price or price <= 0:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: no price available, skipping')
                    continue

                held_qty = qty_map.get(symbol, 0)
                needed = per_position - held_qty * price
                if held_qty >= 1:
                    if not _should_top_up(needed, per_position, band_pct, min_notional):
                        continue
                elif needed <= 0:
                    continue
                buy_qty = int(needed / price)
                if buy_qty < 1:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: ${needed:,.0f} < 1 share (${price:.2f}), skipping')
                    continue

                action = 'TOP-UP' if held_qty >= 1 else 'BUY'
                label = 'REBALANCE' if action == 'TOP-UP' else 'NEW BUY'
                if dry_run:
                    trade_lines.append(f'  🧪 [DRY-RUN] {label} {buy_qty} {symbol} @ ${price:.2f} (${buy_qty * price:,.2f}) → ${per_position:,.0f}')
                    print(f'[MTF EXECUTOR] DRY-RUN {label} {buy_qty} {symbol} @ {price}')
                    continue
                try:
                    order = _place_order(symbol, buy_qty, 'buy')
                except Exception as e:
                    _send_slack_error(f'{symbol} BUY failed: {e}')
                    trade_lines.append(f'  ❌ BUY {symbol} failed: {e}')
                    continue

                filled_order = order
                if order.get('status') != 'filled':
                    filled_order = _wait_for_fill(order.get('id')) or order

                filled_qty = int(float(filled_order.get('filled_qty', buy_qty)))
                fill_price = float(filled_order['filled_avg_price']) if filled_order.get('filled_avg_price') else None
                if filled_qty < buy_qty:
                    pos2 = _get_alpaca_position(symbol)
                    if pos2:
                        pos_qty = abs(int(float(pos2.get('qty', 0))))
                        if pos_qty > filled_qty:
                            filled_qty = pos_qty
                if filled_qty < 1:
                    _send_slack_error(f'{symbol} BUY order {order.get("id")} never filled')
                    trade_lines.append(f'  ❌ BUY {symbol} qty={buy_qty} never filled')
                    continue
                if not fill_price:
                    fill_price = price

                spent = fill_price * filled_qty

                ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
                if not ticker_id:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: no ticker_id in scanner DB')
                    continue

                if held_qty >= 1:
                    # Top-up of an existing position: keep original entry_price/at
                    # (ratchet seeds its peak from entry_price).
                    new_qty = held_qty + filled_qty
                    db_module.adjust_position_qty(conn, ticker_id, symbol, new_qty, fill_price)
                else:
                    db_module.upsert_position(conn, ticker_id, symbol, filled_qty, fill_price, now)
                db_module.insert_trade(conn, ticker_id, symbol, 'BUY', filled_qty, fill_price, now)

                msg_str = f'{label} {filled_qty} {symbol} @ ${fill_price:.2f} (${spent:.2f})'
                buys.append(symbol)
                trade_lines.append(f'  {msg_str}')
                print(f'[MTF EXECUTOR] {msg_str}')

        elif symbols_to_buy:
            total_picks = len(top_symbols)
            per_position = max(0.0, equity - guard_reserve) / total_picks

            for symbol in sorted(symbols_to_buy):
                sd = score_detail.get(symbol, {})
                price = sd.get('close') or _latest_trade_price(symbol)
                if not price or price <= 0:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: no price available, skipping')
                    continue

                blocked, reason = _block_rebuy(symbol, price, conn)
                if blocked:
                    _send_slack_error(f'{symbol} BUY blocked — {reason}')
                    trade_lines.append(f'  ⚠️ BUY {symbol}: blocked ({reason})')
                    print(f'[MTF EXECUTOR] ⚠️ BUY {symbol}: blocked ({reason})')
                    continue

                qty = int(per_position * 0.97 / price)
                if qty < 1:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: ${per_position:.0f} < 1 share (${price:.2f}), skipping')
                    continue

                if dry_run:
                    trade_lines.append(f'  🧪 [DRY-RUN] BUY {qty} {symbol} @ ${price:.2f} (${qty * price:,.2f})')
                    print(f'[MTF EXECUTOR] DRY-RUN BUY {qty} {symbol} @ {price}')
                    continue
                try:
                    order = _place_order(symbol, qty, 'buy')
                except Exception as e:
                    _send_slack_error(f'{symbol} BUY failed: {e}')
                    trade_lines.append(f'  ❌ BUY {symbol} failed: {e}')
                    continue

                filled_order = order
                if order.get('status') != 'filled':
                    filled_order = _wait_for_fill(order.get('id')) or order

                filled_qty = int(float(filled_order.get('filled_qty', qty)))
                fill_price = float(filled_order['filled_avg_price']) if filled_order.get('filled_avg_price') else None
                # Safety net: a market buy fully fills; if the poll returned a
                # stale/partial order state, trust the live Alpaca position qty
                # so we never under-record (positions are ground truth).
                if filled_qty < qty:
                    pos = _get_alpaca_position(symbol)
                    if pos:
                        pos_qty = abs(int(float(pos.get('qty', 0))))
                        if pos_qty > filled_qty:
                            filled_qty = pos_qty
                if filled_qty < 1:
                    _send_slack_error(f'{symbol} BUY order {order.get("id")} never filled')
                    trade_lines.append(f'  ❌ BUY {symbol} qty={qty} never filled')
                    continue
                if not fill_price:
                    fill_price = price

                spent = fill_price * filled_qty

                # Update DB
                ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
                if not ticker_id:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: no ticker_id in scanner DB')
                    continue

                db_module.upsert_position(conn, ticker_id, symbol, filled_qty, fill_price, now)
                db_module.insert_trade(conn, ticker_id, symbol, 'BUY', filled_qty, fill_price, now)

                msg_str = f'BUY {filled_qty} {symbol} @ ${fill_price:.2f} (${spent:.2f})'
                buys.append(symbol)
                trade_lines.append(f'  {msg_str}')
                print(f'[MTF EXECUTOR] {msg_str}')

        msg = (f'Rotation: {len(sells)} sells ({len(ratchet_sold)} ratchet, '
               f'{len(fixed_stop_sold)} fixed-stop), {len(buys)} buys — ${equity:,.0f} equity')
        trade_lines.append(f'  {msg}')
        print(f'[MTF EXECUTOR] {msg}')
        if buys or sells:
            _send_slack(f'Rotation complete: {len(sells)} sold, {len(buys)} bought')

        if guard_state is not None and not dry_run:
            if guard_sweep_requested > 0:
                try:
                    fresh_acct = _get_account()
                    cash_now = float(fresh_acct.get('cash', 0) or 0)
                    actual_sweep = max(0.0, min(guard_sweep_requested,
                                               cash_now - guard_state.reserve))
                except Exception:
                    actual_sweep = 0.0
                if actual_sweep > 0:
                    guard_state.record_sweep(actual_sweep)
                    msg_sweep = (f'Guard sweep: ${actual_sweep:,.2f} to reserve '
                                 f'(total ${guard_state.reserve:,.2f})')
                    trade_lines.append(f'  {msg_sweep}')
                    print(f'[MTF EXECUTOR] {msg_sweep}')
                    _send_slack(f'💰 Guard sweep ({mode.upper()}): '
                                f'${actual_sweep:,.2f} moved to reserve '
                                f'(total ${guard_state.reserve:,.2f}).')
                else:
                    trade_lines.append(
                        '  ⚠️ Guard sweep deferred: no active cash above reserve')
            db_module.save_guard_state(
                conn, mode, guard_state.to_dict(), guard_last_week)

    except Exception as e:
        _send_slack_error(f'execute_rotation crashed: {e}')
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()

    return trade_lines


def reconcile_trades(mode='stock'):
    """Rebuild mtf_trades from Alpaca's authoritative filled-order history.

    Idempotent: deletes this mode's rows, then inserts one row per filled
    order from Alpaca (qty + avg price straight from the order). Sell PnL is
    computed from the DB entry price when available, else NULL.

    Use this whenever the fill log disagrees with real fills (e.g. a past
    partial-fill bug under-recorded quantities).
    """
    _set_alpaca_keys(mode)
    is_etf = mode == 'etf'
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM mtf_trades WHERE ticker_id IN '
                '(SELECT id FROM tbl_stock_tickers WHERE is_etf = %s)', (is_etf,))
        conn.commit()

        url = f'{config.ALPACA_BASE_URL}/v2/orders'
        resp = _session.get(url, headers=_alpaca_headers(),
                            params={'status': 'filled', 'direction': 'asc', 'limit': 500}, timeout=_ALPACA_TIMEOUT)
        if resp.status_code >= 400:
            raise Exception(f'Alpaca orders failed: {resp.text}')

        count = 0
        for o in resp.json():
            symbol = o.get('symbol')
            if not symbol:
                continue
            ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
            if not ticker_id:
                print(f'  [RECONCILE] skip {symbol}: not in scanner DB')
                continue
            with conn.cursor() as cur:
                cur.execute('SELECT is_etf FROM tbl_stock_tickers WHERE id = %s', (ticker_id,))
                row = cur.fetchone()
                if not row or bool(row[0]) != is_etf:
                    continue

            side = o.get('side')
            quantity = int(float(o.get('filled_qty', 0)))
            price = float(o.get('filled_avg_price') or 0)
            if side not in ('buy', 'sell') or quantity < 1 or price <= 0:
                print(f'  [RECONCILE] skip {symbol}: bad fill data (qty={o.get("filled_qty")}, avg={o.get("filled_avg_price")})')
                continue

            filled_at = o.get('filled_at')
            if filled_at:
                executed_at = datetime.fromisoformat(filled_at.replace('Z', '+00:00')).replace(tzinfo=None)
            else:
                executed_at = datetime.now(NY).replace(tzinfo=None)

            pnl_dollar = pnl_pct = None
            if side == 'sell':
                db_pos = db_module.get_position(conn, ticker_id)
                entry = float(db_pos[2]) if db_pos and db_pos[2] else None
                if entry:
                    pnl_dollar = (price - entry) * quantity
                    pnl_pct = (price - entry) / entry * 100

            db_module.insert_trade(conn, ticker_id, symbol, side.upper(), quantity, price,
                                   executed_at, pnl_dollar=pnl_dollar, pnl_pct=pnl_pct)
            count += 1
            print(f'  [RECONCILE] {side.upper()} {quantity} {symbol} @ {price:.4f} ({executed_at:%Y-%m-%d %H:%M} UTC)')

        print(f'[RECONCILE {mode}] rebuilt mtf_trades: {count} fills')
    finally:
        conn.close()
