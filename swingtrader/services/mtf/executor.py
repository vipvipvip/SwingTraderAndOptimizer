import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import db as db_module

NY = ZoneInfo('America/New_York')

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
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca clock failed: {resp.text}')
    return resp.json()


def _wait_for_market_open(max_wait_sec=6 * 3600):
    """Block until the regular market session is open.

    Fixes boot-time catch-up runs: mtf-executor.timer has Persistent=yes, so
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
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca account failed: {resp.text}')
    return resp.json()


def _get_account_number():
    acct = _get_account()
    return acct.get('account_number', '?')


def _get_order(order_id):
    url = f'{config.ALPACA_BASE_URL}/v2/orders/{order_id}'
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        return None
    return resp.json()


def _cancel_orders_for_symbol(symbol):
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    params = {'symbols': symbol, 'status': 'open'}
    resp = requests.get(url, headers=_alpaca_headers(), params=params, timeout=10)
    if resp.status_code >= 400:
        return
    for order in resp.json():
        oid = order.get('id')
        if oid:
            requests.delete(f'{config.ALPACA_BASE_URL}/v2/orders/{oid}',
                            headers=_alpaca_headers(), timeout=5)
            print(f'[MTF EXECUTOR] Cancelled stale order {oid} for {symbol}')


def _place_order(symbol, qty, side):
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    payload = {
        'symbol': symbol,
        'qty': str(qty),
        'side': side,
        'type': 'market',
        'time_in_force': 'day',
    }
    resp = requests.post(url, headers=_alpaca_headers(), json=payload, timeout=10)
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
        resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


def _get_alpaca_positions():
    url = f'{config.ALPACA_BASE_URL}/v2/positions'
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        return {}
    return {p['symbol']: p for p in resp.json()}


def _latest_trade_price(symbol):
    url = 'https://data.alpaca.markets/v2/stocks/trades/latest'
    try:
        resp = requests.get(url, headers=_alpaca_headers(),
                            params={'symbols': symbol, 'feed': 'iex'}, timeout=5)
        if resp.status_code < 400:
            trade = resp.json().get('trades', {}).get(symbol)
            if trade and 'p' in trade:
                return float(trade['p'])
    except Exception:
        pass
    return None


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    acct_no = _get_account_number()
    try:
        requests.post(config.SLACK_WEBHOOK_URL,
                      json={'text': f'[{_current_strategy_tag}] [Paper:{acct_no}] {msg}'},
                      timeout=10)
    except Exception as e:
        print(f'[MTF EXECUTOR SLACK] Error: {e}')


def _send_slack_error(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    acct_no = _get_account_number()
    try:
        requests.post(config.SLACK_WEBHOOK_URL,
                      json={'text': f'⚠️ [{_current_strategy_tag}] [Paper:{acct_no}] {msg}'},
                      timeout=10)
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


def execute_rotation(top_symbols, score_detail, mode='stock'):
    """Execute MTF rotation: sell dropped positions, buy new entries.

    Args:
        top_symbols: list of symbols in the new top-N
        score_detail: dict of {symbol: {score, close, ...}} for top picks
        mode: 'stock' or 'etf'

    Returns:
        list of human-readable trade summary lines
    """
    _wait_for_network()
    _set_alpaca_keys(mode)
    if not _wait_for_market_open():
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
        symbols_to_buy = target_symbols - held_symbols

        # Guard: don't sell positions that weren't scored today — they either
        # failed the bullish filter or had missing data. Preserve to avoid
        # whipsaw on a marginal filter flip (e.g. IJH 07-31: daily EMA 1c below SMA40).
        data_gap_held = [s for s in symbols_to_sell if s not in score_detail]
        for sym in data_gap_held:
            trade_lines.append(f'  ⚠️ {sym} held but not scored today (filter or data gap) — preserving')
            print(f'[MTF EXECUTOR] ⚠️ {sym} held but not scored today (filter or data gap) — preserving position')
        symbols_to_sell = symbols_to_sell - set(data_gap_held)

        # Cancel all open orders first
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
            sells.append(symbol)
            trade_lines.append(f'  {msg_str}')
            print(f'[MTF EXECUTOR] {msg_str}')

        # ── Buy new entries ──
        if symbols_to_buy:
            total_picks = len(top_symbols)
            per_position = equity / total_picks

            for symbol in sorted(symbols_to_buy):
                sd = score_detail.get(symbol, {})
                price = sd.get('close') or _latest_trade_price(symbol)
                if not price or price <= 0:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: no price available, skipping')
                    continue

                qty = int(per_position * 0.97 / price)
                if qty < 1:
                    trade_lines.append(f'  ⚠️ BUY {symbol}: ${per_position:.0f} < 1 share (${price:.2f}), skipping')
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

        msg = f'Rotation: {len(sells)} sells, {len(buys)} buys — ${equity:,.0f} equity'
        trade_lines.append(f'  {msg}')
        print(f'[MTF EXECUTOR] {msg}')
        if buys or sells:
            _send_slack(f'Rotation complete: {len(sells)} sold, {len(buys)} bought')

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
        resp = requests.get(url, headers=_alpaca_headers(),
                            params={'status': 'filled', 'direction': 'asc', 'limit': 500}, timeout=15)
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
