#!/usr/bin/env python3
"""MTF Top-N Daily Runner — Phase 2 (Live Trading).

Daily one-shot: scores all stocks using Multi-TF criteria,
picks top N, executes live Alpaca rotation, sends Slack alert.
"""

import json
import os
import csv
import sys
import time
import tempfile
import subprocess

from format_etf import etf_table_lines
import argparse
import traceback
import numpy as np
import requests
from datetime import datetime, date as dt_date, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import db as db_module
import executor

NY = ZoneInfo('America/New_York')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
SCANNER_VENV_PYTHON = os.path.join(PROJECT_ROOT, 'scanner', '.venv', 'bin', 'python')
POPULATE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'populate_tickers.py')
COMPUTE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'compute_indicators.py')
DATA_RETRIES = 3
DATA_RETRY_DELAY = 60

MODE_LABEL = {'stock': 'stocks', 'etf': 'ETFs'}
CSV_SUFFIX = {'stock': '_stock', 'etf': '_etf'}


def _suffix(mode, min_score=None):
    s = CSV_SUFFIX[mode]
    if min_score is not None:
        s = f'_min{int(min_score)}{s}'
    return s

MAX_DB_RETRIES = 3
DB_RETRY_DELAY = 5
MAX_STALE_DAYS = 2


def _csv_path(name, mode='stock', min_score=None):
    return os.path.join(BASE_DIR, 'data', f'mtf_{name}{_suffix(mode, min_score)}.csv')


def _state_path(mode, min_score=None):
    base = f'.mtf_state{_suffix(mode, min_score)}'
    return os.path.join(BASE_DIR, f'{base}.json')


def _send_slack(msg, mode='stock'):
    if not config.SLACK_WEBHOOK_URL:
        return
    label = MODE_LABEL.get(mode, mode)
    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[MTF-TopN {label}] {msg}'}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _send_slack_alert(msg, mode='stock'):
    """Send a bright red danger-banner Slack alert."""
    if not config.SLACK_WEBHOOK_URL:
        return
    label = MODE_LABEL.get(mode, mode)
    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={
            'text': f'🚨🔴 *[MTF-TopN {label}] DATA INCOMPLETE* 🔴🚨',
            'attachments': [{'color': 'danger', 'fallback': msg, 'text': msg}]
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _send_crash_alert(exc_info, mode='stock'):
    """Send a Slack alert when the runner crashes unexpectedly."""
    tb = ''.join(traceback.format_exception(*exc_info))
    msg = f'⚠️ *CRASH* — `--mode {mode}`\n```{tb[-2000:]}```'
    _send_slack(msg, mode)


def _get_db_conn():
    for attempt in range(1, MAX_DB_RETRIES + 1):
        try:
            return db_module.get_conn()
        except Exception as e:
            print(f'[DB] Connection attempt {attempt}/{MAX_DB_RETRIES} failed: {e}')
            if attempt < MAX_DB_RETRIES:
                time.sleep(DB_RETRY_DELAY)
    raise RuntimeError(f'Could not connect to database after {MAX_DB_RETRIES} attempts')


def _check_data_freshness(conn, mode='stock'):
    """Verify daily + hourly scanner data is fresh enough to generate reliable signals."""
    latest = db_module.get_latest_daily_bar_date(conn)
    if latest is None:
        _send_slack('❌ No daily bar data found in scanner tables — aborting', mode)
        return False
    age = (dt_date.today() - latest).days
    if age > MAX_STALE_DAYS:
        _send_slack(
            f'❌ Stale daily data: latest bar {latest} ({age}d old) — skipping run',
            mode)
        return False
    if age > 1:
        _send_slack(
            f'⚠️  Daily bar data is {age}d old (latest: {latest}) — picks may be based on stale prices',
            mode)

    # Check hourly ATR data freshness — critical for accurate scoring
    with conn.cursor() as cur:
        cur.execute('SELECT MAX(date) FROM tbl_scanner_tickers_1hour')
        latest_hourly = cur.fetchone()[0]
    if latest_hourly is None:
        _send_slack('❌ No hourly bar data found — aborting', mode)
        return False
    # hourly date is a datetime; compare as date
    hourly_date = latest_hourly.date() if hasattr(latest_hourly, 'date') else latest_hourly
    h_age = (dt_date.today() - hourly_date).days
    if h_age > 1:
        _send_slack(
            f'❌ Stale hourly data: latest bar {latest_hourly} ({h_age}d old) — ATR stops not computed, aborting',
            mode)
        return False

    return True


def _load_state(mode='stock', min_score=None):
    sp = _state_path(mode, min_score)
    if os.path.exists(sp):
        try:
            with open(sp) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f'[STATE] Corrupted state file {sp}: {e}')
            print(f'[STATE] Starting fresh')
            return {}
    # Fallback: migrate old state file for stock mode
    old_sp = os.path.join(BASE_DIR, '.mtf_state.json')
    if mode == 'stock' and min_score is None and os.path.exists(old_sp):
        with open(old_sp) as f:
            data = json.load(f)
        _save_state(data, mode)
        os.rename(old_sp, old_sp + '.bak')
        return data
    return {}


def _save_state(state, mode='stock', min_score=None):
    sp = _state_path(mode, min_score)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=BASE_DIR, suffix='.tmp')
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, sp)
    except Exception:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _ensure_csv():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)


def _ensure_daily_data(conn, mode, today):
    """Check all enabled tickers have today's daily bar. Retry populate+compute if not.
    Returns (success, message, conn). conn may be a new connection after retry."""
    is_etf = mode == 'etf'
    expected = config.EXPECTED_ETFS if is_etf else config.EXPECTED_STOCKS

    for attempt in range(1, DATA_RETRIES + 2):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT d.ticker_id)
                FROM tbl_scanner_tickers_daily d
                JOIN tbl_stock_tickers s ON d.ticker_id = s.id
                WHERE d.date::date = %s AND s.enabled = true AND s.is_etf = %s
            """, (today, is_etf))
            today_count = cur.fetchone()[0]

        if today_count >= expected:
            print(f'[MTF] Data complete: {today_count}/{expected} {MODE_LABEL[mode]}')
            return True, '', conn

        msg = f'[{today}] {today_count}/{expected} {MODE_LABEL[mode]} have today\'s daily bar'
        print(f'[MTF] {msg}')

        if attempt > DATA_RETRIES:
            return False, msg, conn

        print(f'[MTF] Retry {attempt}/{DATA_RETRIES}: running populate_tickers + compute_indicators...')
        conn.close()
        try:
            subprocess.run(
                [SCANNER_VENV_PYTHON, POPULATE_SCRIPT, '--timeframe', 'day', '--workers', '10'],
                check=True, capture_output=True, timeout=300)
            subprocess.run(
                [SCANNER_VENV_PYTHON, COMPUTE_SCRIPT, '--timeframe', 'day', '--workers', '10'],
                check=True, capture_output=True, timeout=300)
        except subprocess.CalledProcessError as e:
            print(f'[MTF] Retry script failed: {e}')
        except subprocess.TimeoutExpired:
            print(f'[MTF] Retry script timed out')

        print(f'[MTF] Waiting {DATA_RETRY_DELAY}s before recheck...')
        time.sleep(DATA_RETRY_DELAY)
        conn = _get_db_conn()

    return False, 'unexpected error', conn


def _compute_score(weekly, daily, hourly, wi, di, hi, sig_date):
    if wi < config.WARMUP_BARS or di < 1 or hi < 1:
        return None

    wc = weekly['close'][wi]
    we = weekly['ema'][wi]
    ws = weekly['sma'][wi]
    dc = daily['close'][di]
    de = daily['ema'][di]
    ds = daily['sma'][di]
    hc = hourly['close'][hi]
    ha = hourly['atr_stop'][hi]

    # Use math.isnan (fast scalar) instead of np.isnan (slow array alloc)
    import math
    if any(math.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
        return None
    if we <= ws or de <= ds:
        return None
    if hc <= ha or hc <= 0:
        return None

    gap_w = (wc - ws) / ws * 100
    atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0

    # Find freshness: walk backward through weekly data to find last EMA/SMA crossover
    days_since = 999
    w_ema = weekly['ema']
    w_sma = weekly['sma']
    w_dates = weekly['dates']
    for j in range(wi, 0, -1):
        wj_ema = w_ema[j]
        wj_sma = w_sma[j]
        wj_ema_prev = w_ema[j - 1]
        wj_sma_prev = w_sma[j - 1]
        if not (math.isnan(wj_ema) or math.isnan(wj_sma) or math.isnan(wj_ema_prev) or math.isnan(wj_sma_prev)):
            if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                days_since = (sig_date - w_dates[j]).days
                break

    gap_pts = min(gap_w / 20, 3)
    atr_pts = min(atr_dist / 1.5, 3)
    fresh_pts = max(0, 2 - days_since / 60)
    score = round(gap_pts + atr_pts + fresh_pts, 1)

    return {
        'score': score,
        'gap_w': round(gap_w, 1),
        'atr_dist': round(atr_dist, 2),
        'freshness': days_since,
        'close': round(dc, 2),
        'name': None,
    }


def _get_ticker_name(conn, tid):
    with conn.cursor() as cur:
        cur.execute('SELECT symbol FROM tbl_stock_tickers WHERE id = %s', (tid,))
        row = cur.fetchone()
        return row[0] if row else None


def _format_regime(pct):
    if pct is None:
        return '--'
    if pct < 35:
        return f'{pct:.0f}% uptrend \u26a0\ufe0f Risk-off'
    elif pct < 55:
        return f'{pct:.0f}% uptrend \u2796 Neutral'
    else:
        return f'{pct:.0f}% uptrend \u2705 Risk-on'


def _run_single_mode(mode, now, today, min_score=None, live=False):
    """Run scoring + portfolio for one mode. Returns (success, slack_lines, sig_date).
    If live=True, also executes real Alpaca trades.
    Does NOT send Slack. Does NOT catch exceptions (caller must handle)."""
    conn = _get_db_conn()
    is_etf = mode == 'etf'
    score_tag = f' score ≥ {min_score}' if min_score else ''
    print(f'[MTF] Mode: {MODE_LABEL[mode]}{score_tag}')

    # Data freshness check
    if not _check_data_freshness(conn, mode):
        conn.close()
        return False, [f'Skipped {MODE_LABEL[mode]} — stale data'], None

    # Guard: all tickers must have today's daily bar before proceeding
    ok, msg, conn = _ensure_daily_data(conn, mode, today)
    if not ok:
        conn.close()
        slack_msg = f'{MODE_LABEL[mode]}: {msg}\nRetried {DATA_RETRIES}x — aborting. No picks or trades today.'
        _send_slack_alert(slack_msg, mode)
        lines = [f'Skipped {MODE_LABEL[mode]} — incomplete daily data', msg]
        print(f'[MTF] {" / ".join(lines)}')
        return False, lines, None

    tickers = db_module.get_all_tickers(conn, is_etf=is_etf)
    print(f'[MTF] Loaded {len(tickers)} {MODE_LABEL[mode]}')

    ticker_names = {}
    company_names = {}
    for tid, sym in tickers:
        ticker_names[tid] = sym
        if is_etf:
            company_names[tid] = db_module.get_etf_name(conn, tid) or sym

    # Bulk load all data (3 queries instead of 3 × N tickers)
    enabled_tids = set(ticker_names.keys())
    print(f'[MTF] Loading weekly data...', flush=True)
    weekly_data = db_module.bulk_load_weekly(conn, enabled_tids)
    print(f'[MTF] Loading daily data...', flush=True)
    daily_data_raw = db_module.bulk_load_daily(conn, enabled_tids)
    print(f'[MTF] Loading hourly data...', flush=True)
    hourly_data_raw = db_module.bulk_load_hourly(conn, enabled_tids)

    # Filter to enabled tickers with all 3 timeframes
    weekly_data = {tid: d for tid, d in weekly_data.items()
                   if tid in enabled_tids and len(d['dates']) >= config.WARMUP_BARS}
    daily_data = {}
    hourly_data = {}
    for tid in weekly_data:
        if tid in daily_data_raw and len(daily_data_raw[tid]['dates']) >= 2:
            daily_data[tid] = daily_data_raw[tid]
        if tid in hourly_data_raw and len(hourly_data_raw[tid]['dates']) >= 2:
            hourly_data[tid] = hourly_data_raw[tid]
    valid_tids = set(weekly_data) & set(daily_data) & set(hourly_data)
    weekly_data = {tid: weekly_data[tid] for tid in valid_tids}
    daily_data = {tid: daily_data[tid] for tid in valid_tids}
    hourly_data = {tid: hourly_data[tid] for tid in valid_tids}
    print(f'[MTF] Tickers with all 3 timeframes: {len(weekly_data)}')

    daily_idx = {}
    daily_dates_sorted = {}
    for tid in daily_data:
        dates = daily_data[tid]['dates']
        daily_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        daily_dates_sorted[tid] = dates
    weekly_idx = {}
    weekly_dates_sorted = {}
    for tid in weekly_data:
        dates = weekly_data[tid]['dates']
        weekly_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        weekly_dates_sorted[tid] = dates
    hourly_idx = {}
    hourly_dates_sorted = {}
    for tid in hourly_data:
        dates = hourly_data[tid]['dates']
        hourly_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        hourly_dates_sorted[tid] = dates

    def _nearest_date_idx(date_map, dates, target):
        if target in date_map:
            return date_map[target]
        for d in reversed(dates):
            if d <= target:
                return date_map.get(d)
        return None

    latest_date = db_module.get_latest_daily_bar_date(conn)
    if latest_date is None:
        conn.close()
        return False, ['No daily data found'], None

    sig_date = latest_date

    print(f'[MTF] Signal date: {sig_date}')

    candidates = []
    for tid in weekly_data:
        di = _nearest_date_idx(daily_idx[tid], daily_dates_sorted[tid], sig_date)
        wi = _nearest_date_idx(weekly_idx[tid], weekly_dates_sorted[tid], sig_date)
        hi = _nearest_date_idx(hourly_idx[tid], hourly_dates_sorted[tid], sig_date)
        if di is None or wi is None or hi is None:
            continue
        result = _compute_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                                wi, di, hi, sig_date)
        if result is None:
            continue
        result['tid'] = tid
        result['symbol'] = ticker_names[tid]
        result['name'] = company_names.get(tid)
        if min_score is not None and result['score'] < min_score:
            continue
        candidates.append(result)

    lines = []
    if not candidates:
        lines.append(f'No qualifying {MODE_LABEL[mode]} on {sig_date}')
        conn.close()
        return False, lines, sig_date

    candidates.sort(key=lambda x: -x['score'])
    top_n = candidates[:config.TOP_N]

    score_detail = {}
    for t in candidates:
        score_detail[t['symbol']] = {
            'score': t['score'], 'gap_w': t['gap_w'],
            'atr_dist': t['atr_dist'], 'freshness': t['freshness'],
            'close': t['close'], 'name': t['name'],
        }
    top_symbols = [t['symbol'] for t in top_n]

    state = _load_state(mode, min_score)
    prev_picks = state.get('last_picks', [])
    prev_scores = state.get('last_scores', {})
    prev_date = state.get('last_date')

    portfolio = state.get('portfolio', {
        'cash': config.INITIAL_CAPITAL, 'positions': {},
        'last_value': config.INITIAL_CAPITAL, 'inception': str(today),
    })
    positions = portfolio['positions']
    cash = portfolio['cash']

    dropped = [s for s in prev_picks if s not in top_symbols]
    # Guard: don't sell positions that had no score data today (data gap)
    data_gap_held = [s for s in dropped if s not in score_detail]
    for sym in data_gap_held:
        print(f'[MTF] ⚠️ {sym} held but no score today (data gap) — preserving position')
    dropped = [s for s in dropped if s in score_detail]
    new_entries = [s for s in top_symbols if s not in prev_picks]
    buys = []
    sells = []
    trade_log_entries = []

    for sym in dropped:
        if sym in positions:
            pos = positions[sym]
            entry_price = pos['entry_price']
            shares = pos['shares']
            close_price = prev_scores.get(sym, {}).get('close') or pos['entry_price']
            proceeds = shares * close_price * (1 - config.COST_PER_TRADE)
            ret = (close_price - entry_price) / entry_price - config.COST_PER_TRADE
            cash += proceeds
            sells.append(f'{sym} {ret*100:+.1f}%')
            pnl = proceeds - shares * entry_price
            trade_log_entries.append((str(sig_date), sym, 'SELL', f'{shares:.4f}',
                                      f'{close_price:.2f}', f'{ret*100:+.2f}%', f'{pnl:.2f}'))
            del positions[sym]

    if new_entries:
        per_stock = (cash / len(new_entries)) if cash > 0 else 0
        for sym in new_entries:
            sd = score_detail.get(sym, {})
            bp = sd.get('close', 0)
            if bp <= 0:
                continue
            shares = (per_stock / bp) * (1 - config.COST_PER_TRADE)
            cost = shares * bp
            cash -= cost
            positions[sym] = {'shares': round(shares, 4), 'entry_price': bp}
            buys.append(f'{sym} @ ${bp:.2f}')
            trade_log_entries.append((str(sig_date), sym, 'BUY', f'{shares:.4f}',
                                      f'{bp:.2f}', '', ''))

    mtm_value = cash
    for sym, pos in list(positions.items()):
        sd = score_detail.get(sym)
        close = sd['close'] if sd else None
        if not close:
            try:
                conn = db_module.get_conn()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT close FROM tbl_scanner_tickers_daily "
                        "WHERE ticker_id=(SELECT id FROM tbl_stock_tickers WHERE symbol=%s) "
                        "ORDER BY date DESC LIMIT 1", (sym,))
                    row = cur.fetchone()
                    close = float(row[0]) if row else None
                conn.close()
            except Exception:
                close = None
        if close:
            mtm_value += pos['shares'] * close * (1 - config.COST_PER_TRADE)

    total_ret = (mtm_value - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL * 100

    portfolio['cash'] = cash
    portfolio['last_value'] = round(mtm_value, 2)

    _ensure_csv()
    picks_csv = _csv_path('picks', mode, min_score)
    picks_header = not os.path.exists(picks_csv)
    with open(picks_csv, 'a', newline='') as f:
        w = csv.writer(f)
        if picks_header:
            w.writerow(['date', 'rank', 'symbol', 'score', 'gap_w', 'atr_dist', 'freshness', 'entry_date', 'close'])
        for i, t in enumerate(top_n, 1):
            if t['freshness'] < 999:
                entry_date = str(sig_date - timedelta(days=t['freshness']))
            else:
                entry_date = ''
            w.writerow([str(sig_date), i, t['symbol'], t['score'],
                        t['gap_w'], t['atr_dist'], t['freshness'], entry_date, t['close']])

    port_csv = _csv_path('portfolio', mode, min_score)
    port_header = not os.path.exists(port_csv)
    with open(port_csv, 'a', newline='') as f:
        w = csv.writer(f)
        if port_header:
            w.writerow(['date', 'cash', 'mtm_value', 'return_pct', 'positions_count', 'buys', 'sells'])
        w.writerow([str(sig_date), f'{cash:.2f}', f'{mtm_value:.2f}',
                    f'{total_ret:+.2f}%', len(positions),
                    '|'.join(buys), '|'.join(sells)])

    trades_csv = _csv_path('trades', mode, min_score)
    trades_header = not os.path.exists(trades_csv)
    with open(trades_csv, 'a', newline='') as f:
        w = csv.writer(f)
        if trades_header:
            w.writerow(['date', 'symbol', 'side', 'shares', 'price', 'return', 'pnl'])
        for entry in trade_log_entries:
            w.writerow(entry)

    # ── Live execution ──
    if live and min_score is None:
        try:
            live_lines = executor.execute_rotation(top_symbols, score_detail, mode)
            if live_lines:
                lines.append('')
                lines.append('Live trades:')
                lines.extend(live_lines)
        except Exception as e:
            lines.append(f'')
            lines.append(f'⚠️ Live execution failed: {e}')
            import traceback
            traceback.print_exc()

    # Build message
    label = MODE_LABEL[mode]
    if min_score is not None:
        label = f'{label} (score \u2265 {min_score})'
    lines.append(f'*Multi-TF Top {config.TOP_N} — {sig_date} ({label})*')
    lines.append('```')

    try:
        pct = db_module.compute_market_breadth_from_data(weekly_data, daily_data, is_etf=is_etf)
        if pct is not None:
            lines.append(f'Breadth: {_format_regime(pct)}')
            lines.append('')
    except Exception:
        pass

    # Track entry prices for all picks (used for Slack P&L and show_picks.py)
    entry_prices = state.get('entry_prices', {})
    for sym in dropped:
        entry_prices.pop(sym, None)
    for sym in new_entries:
        sd = score_detail.get(sym, {})
        sd_close = sd.get('close', 0)
        if sd_close > 0:
            entry_prices[sym] = {'price': sd_close, 'date': str(sig_date)}
    state['entry_prices'] = entry_prices

    if is_etf:
        lines.extend(etf_table_lines(top_n, score_detail, entry_prices))
    else:
        lines.append(f'{"#":<3} {"Ticker":<8} {"Score":>5} {"Gap":>7} {"Fresh":>7}')
        lines.append(f'{"-"*3} {"-"*8} {"-"*5} {"-"*7} {"-"*7}')
        for i, t in enumerate(top_n, 1):
            days_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
            lines.append(
                f'{i:<3} {t["symbol"]:<8} {t["score"]:>5.1f} '
                f'{t["gap_w"]:>+6.1f}% {days_str:>7}'
            )

    if prev_date and (new_entries or dropped):
        lines.append('')
        if new_entries:
            details = [f'{s} ({score_detail.get(s, {}).get("score", 0):.1f})' for s in new_entries]
            lines.append(f'NEW: {", ".join(details)}')
        if dropped:
            lines.append(f'OUT: {", ".join(dropped)}')
    elif prev_date:
        lines.append('')
        lines.append('No changes since last run')

    lines.append('')
    if prev_date and str(prev_date) != str(sig_date):
        prev_val = state.get('portfolio', {}).get('last_value', config.INITIAL_CAPITAL)
        if prev_val and prev_val > 0:
            daily_ret = (mtm_value - prev_val) / prev_val * 100
            lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}% total, {daily_ret:+.2f}% today)')
        else:
            lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}%)')
    else:
        lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}%)')

    lines.append(f'Positions: {len(positions)}  Cash: ${cash:,.0f}')

    # Comma-delimited ticker list
    lines.append('')
    lines.append(','.join(top_symbols))

    lines.append('```')

    # Save state AFTER message is built (so prev_date is available for NEW/OUT)
    state['last_date'] = str(sig_date)
    state['last_picks'] = top_symbols
    state['last_scores'] = score_detail
    state['portfolio'] = portfolio
    _save_state(state, mode, min_score)

    conn.close()
    return True, lines, sig_date


def _run_sector_info(conn, now, today):
    """Score sector ETFs for informational Slack only. No portfolio/state/CSV."""
    print('[MTF] Scoring sector ETFs (info only)...')

    tickers = db_module.get_sector_tickers(conn)
    if not tickers:
        return ['  No sector ETFs found']

    weekly_data = {}
    daily_data = {}
    hourly_data = {}
    ticker_names = {}
    for tid, sym in tickers:
        ticker_names[tid] = sym
        w = db_module.load_weekly(conn, tid)
        d = db_module.load_daily(conn, tid)
        h = db_module.load_hourly(conn, tid)
        if w and d and h:
            weekly_data[tid] = w
            daily_data[tid] = d
            hourly_data[tid] = h

    if not weekly_data:
        return ['  No sector ETFs with all 3 timeframes']

    daily_idx = {}
    for tid in daily_data:
        daily_idx[tid] = {dt: i for i, dt in enumerate(daily_data[tid]['dates'])}
    weekly_idx = {}
    for tid in weekly_data:
        weekly_idx[tid] = {dt: i for i, dt in enumerate(weekly_data[tid]['dates'])}
    hourly_idx = {}
    for tid in hourly_data:
        hourly_idx[tid] = {dt: i for i, dt in enumerate(hourly_data[tid]['dates'])}

    def _nearest(date_map, dates, target):
        if target in date_map:
            return date_map[target]
        for d in reversed(dates):
            if d <= target:
                return date_map.get(d)
        return None

    latest_date = db_module.get_latest_daily_bar_date(conn)
    if latest_date is None:
        return ['  No daily data']

    sig_date = latest_date
    if now.weekday() == 0 and (now.hour < 9 or (now.hour == 9 and now.minute < 30)):
        last_trading = today - timedelta(days=3)
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM tbl_scanner_tickers_daily WHERE date::date = %s LIMIT 1', (last_trading,))
            if cur.fetchone():
                sig_date = last_trading

    candidates = []
    for tid in weekly_data:
        di = _nearest(daily_idx[tid], daily_data[tid]['dates'], sig_date)
        wi = _nearest(weekly_idx[tid], weekly_data[tid]['dates'], sig_date)
        hi = _nearest(hourly_idx[tid], hourly_data[tid]['dates'], sig_date)
        if di is None or wi is None or hi is None:
            continue
        result = _compute_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                                wi, di, hi, sig_date)
        if result is None:
            continue
        result['symbol'] = ticker_names[tid]
        candidates.append(result)

    lines = []
    lines.append(f'*Sector ETFs — {sig_date}*')
    lines.append('```')

    if not candidates:
        lines.append('  No qualifying sector ETFs')
        lines.append('```')
        return lines

    # Tabular header
    lines.append(f'{"#":<3} {"Ticker":<8} {"Score":>5} {"Gap":>7} {"Fresh":>7}')
    lines.append(f'{"-"*3} {"-"*8} {"-"*5} {"-"*7} {"-"*7}')

    candidates.sort(key=lambda x: -x['score'])
    for i, t in enumerate(candidates, 1):
        days_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
        lines.append(
            f'{i:<3} {t["symbol"]:<8} {t["score"]:>5.1f} '
            f'{t["gap_w"]:>+6.1f}% {days_str:>7}'
        )

    # Comma-delimited ticker list
    sector_symbols = [t['symbol'] for t in candidates]
    lines.append('')
    lines.append(','.join(sector_symbols))
    lines.append('```')

    return lines


def run(mode='stock', min_score=None, live=False):
    now = datetime.now(NY)
    today = now.date()
    try:
        success, lines, sig_date = _run_single_mode(mode, now, today, min_score, live=live)
        msg = '\n'.join(lines)
        print(f'\n{msg}\n')
        _send_slack(msg, mode)
    except Exception:
        _send_crash_alert(sys.exc_info(), mode)
        raise


def run_all(live=False):
    """Run stock and ETF modes (default + min-score) + sector info, send ONE combined Slack message."""
    now = datetime.now(NY)
    today = now.date()

    all_lines = []
    sig_date = None

    for mode in ('stock', 'etf'):
        all_lines.append('')
        try:
            success, lines, sd = _run_single_mode(mode, now, today, live=live)
            all_lines.extend(lines)
            if sd:
                sig_date = sd
        except Exception as exc:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            all_lines.append(f'❌ {MODE_LABEL[mode]} crashed: {exc}')
            all_lines.append(f'```{tb[-1500:]}```')
            print(f'[MTF] {mode} crashed: {exc}')

    # Sector ETFs (informational only)
    all_lines.append('')
    try:
        conn = _get_db_conn()
        sector_lines = _run_sector_info(conn, now, today)
        all_lines.extend(sector_lines)
        conn.close()
    except Exception as exc:
        all_lines.append(f'❌ sector info crashed: {exc}')
        print(f'[MTF] sector info crashed: {exc}')

    # Also run min-score 5 variant
    for mode in ('stock', 'etf'):
        all_lines.append('')
        try:
            success, lines, sd = _run_single_mode(mode, now, today, min_score=5)
            all_lines.extend(lines)
            if sd:
                sig_date = sd
        except Exception as exc:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            all_lines.append(f'❌ {MODE_LABEL[mode]} (min 5) crashed: {exc}')
            all_lines.append(f'```{tb[-1500:]}```')
            print(f'[MTF] {mode} min-score crashed: {exc}')

    if not sig_date:
        sig_date = str(today)

    header = f'Multi-TF Top {config.TOP_N} \u2014 {sig_date} (stocks + ETFs + sectors)'
    full_msg = '\n'.join([header, '\u2501' * 32] + all_lines)
    print(f'\n{full_msg}\n')
    _send_slack(full_msg, 'stock')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MTF Top-N Daily Runner')
    parser.add_argument('--mode', choices=['stock', 'etf', 'all'], default='stock',
                        help='Ticker universe to score (default: stock, use "all" for stocks+ETFs)')
    parser.add_argument('--min-score', type=float, default=None,
                        help='Minimum MTF score filter (default: no filter)')
    parser.add_argument('--live', action='store_true',
                        help='Execute live Alpaca trades (default: paper only)')
    args = parser.parse_args()
    if args.mode == 'all':
        run_all(live=args.live)
    else:
        run(mode=args.mode, min_score=args.min_score, live=args.live)
