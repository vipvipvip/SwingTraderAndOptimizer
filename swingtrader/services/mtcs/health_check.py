#!/usr/bin/env python3
"""MTCS system health check — real-trading enabled."""
import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import db as db_module
import executor
from strategy import check_signal

NY = ZoneInfo('America/New_York')

CSV_PATH = os.path.join(os.path.dirname(__file__), 'mtcs_trades.csv')


def ok(msg):
    print(f'  [OK] {msg}')

def warn(msg):
    print(f'  [WARN] {msg}')

def fail(msg):
    print(f'  [FAIL] {msg}')


def _is_market_hours(now_ny):
    if now_ny.weekday() >= 5:
        return False
    open_min = config.MARKET_OPEN[0] * 60 + config.MARKET_OPEN[1]
    close_min = config.MARKET_CLOSE[0] * 60 + config.MARKET_CLOSE[1]
    now_min = now_ny.hour * 60 + now_ny.minute
    return open_min <= now_min < close_min


def main():
    now_ny = datetime.now(NY)
    market_open = _is_market_hours(now_ny)
    market_label = 'MARKET HOURS' if market_open else 'CLOSED'

    print()
    print('--- MTCS (Daily Hilbert Transform Cycle Strategy) ---')
    print(f'  Market: {market_label} ({now_ny.strftime("%a %Y-%m-%d %H:%M %Z")})')
    print(f'  Config: detrend={config.DETREND_PERIOD}, smoothing={config.SMOOTHING}')
    print(f'  Poll interval: {config.POLL_INTERVAL_SEC}s | Warmup: {config.WARMUP_BARS} bars')
    print(f'  Tickers: {", ".join(config.TICKERS)}')

    db_module.init_db()
    conn = db_module.get_conn()

    # ── Service status ──
    svc_status = os.popen(
        'systemctl is-active mtcs-runner 2>/dev/null || echo "not-found"'
    ).read().strip()
    if svc_status == 'active':
        ok('mtcs-runner.service is active')
    else:
        fail(f'mtcs-runner.service is {svc_status}')

    if svc_status == 'active':
        uptime = os.popen(
            'systemctl show mtcs-runner -p ActiveEnterTimestamp --value 2>/dev/null'
        ).read().strip()
        if uptime:
            print(f'    Started: {uptime}')

    # ── Recent journal errors ──
    errors = os.popen(
        'journalctl -u mtcs-runner --since "1 hour ago" -p err -q --no-pager 2>/dev/null '
        '| tail -5'
    ).read().strip()
    if errors:
        warn('Recent errors in journal:')
        for line in errors.split('\n'):
            print(f'    {line}')
    else:
        ok('No errors in last hour of journal')

    # ── Alpaca account check ──
    print()
    try:
        acct = executor._get_account()
        account_no = acct.get('account_number', '?')
        cash = float(acct.get('cash', 0))
        equity = float(acct.get('equity', 0))
        status = acct.get('status', '?')
        ok(f'Alpaca account #{account_no} ({status}) — cash=${cash:,.0f} equity=${equity:,.0f}')
    except Exception as e:
        fail(f'Alpaca account check failed: {e}')

    # ── Alpaca positions check ──
    try:
        headers = executor._alpaca_headers()
        resp = requests.get(f'{config.ALPACA_BASE_URL}/v2/positions', headers=headers, timeout=10)
        if resp.status_code < 400:
            positions = resp.json()
            if positions:
                print(f'  Alpaca open positions:')
                for pos in positions:
                    sym = pos.get('symbol')
                    qty = float(pos.get('qty', 0))
                    mkt_val = float(pos.get('market_value', 0))
                    upl = float(pos.get('unrealized_pl', 0))
                    print(f'    {sym}: {qty} shares (${mkt_val:,.0f}, P&L ${upl:,.2f})')
            else:
                print(f'  Alpaca open positions: none')
        else:
            warn(f'Cannot fetch Alpaca positions: {resp.status_code}')
    except Exception as e:
        warn(f'Alpaca positions fetch failed: {e}')

    # ── Data freshness & signal state per ticker ──
    print()
    ticker_issues = 0
    for sym in config.TICKERS:
        tid = db_module.get_ticker_id(conn, sym)
        closes, count = db_module.get_daily_candles(conn, tid)

        warmed = count >= config.WARMUP_BARS
        sig, _ = check_signal(conn, tid) if warmed else (None, None)
        sig_label = sig if sig else 'NONE'

        latest_ts = db_module.get_latest_candle_ts(conn, tid)
        last_close = closes[-1] if closes else None

        print(f'  {sym}:')
        print(f'    Daily bars: {count} total {"(warmed up)" if warmed else f"(need {config.WARMUP_BARS} - still warming)"}')
        print(f'    Latest bar: {latest_ts or "NONE"}')
        print(f'    Close: ${last_close:.2f}' if last_close else '    Close: N/A')
        print(f'    Signal: {sig_label}')

        if latest_ts:
            age = (datetime.now(timezone.utc) - latest_ts.replace(tzinfo=timezone.utc)).total_seconds()
            now_utc = datetime.now(timezone.utc)
            bar_dt = latest_ts.replace(tzinfo=timezone.utc) if latest_ts.tzinfo is None else latest_ts
            trading_days = 0
            check = bar_dt
            while check.date() < now_utc.date():
                check += timedelta(days=1)
                if check.weekday() < 5:
                    trading_days += 1
            if trading_days > 2:
                warn(f'    Daily bar is {age/3600:.0f}h old ({trading_days} trading days ago — stale)')
                ticker_issues += 1
            else:
                ok(f'    Bar age: {age/3600:.1f}h (last completed trading day, {trading_days} trading days ago)')

    # ── CSV trade log ──
    csv_issues = 0
    if os.path.exists(CSV_PATH):
        csv_age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(CSV_PATH))).total_seconds()
        with open(CSV_PATH) as f:
            lines = f.readlines()
        if len(lines) > 1:
            ok(f'CSV trade log: {len(lines) - 1} trades logged')
            print(f'    Path: {CSV_PATH}')
            print(f'    Last row: {lines[-1].strip()}')
        else:
            warn('CSV trade log exists but has no trade rows (header only)')
            csv_issues += 1
        if csv_age > 86400 * 60:
            warn(f'CSV trade log last updated {csv_age/86400:.0f}d ago (stale)')
            csv_issues += 1
    else:
        warn('CSV trade log not found (will be created on first SELL)')
        csv_issues += 1

    # ── DB position status ──
    cur = conn.cursor()
    cur.execute(
        'SELECT symbol, quantity, entry_price, entry_at FROM mtcs_positions '
        'WHERE quantity > 0 ORDER BY symbol')
    db_positions = cur.fetchall()
    if db_positions:
        print(f'  DB tracked positions:')
        for symbol, qty, ep, ets in db_positions:
            print(f'    {symbol}: {qty} share(s) @ ${ep:.2f} (since {ets})')
    else:
        print(f'  DB tracked positions: none')

    # ── Trade count ──
    cur.execute('SELECT COUNT(*) FROM mtcs_trades')
    trade_count = cur.fetchone()[0]
    print(f'  Total trades executed (all time): {trade_count}')

    conn.close()

    issues = ticker_issues + csv_issues + (0 if svc_status == 'active' else 1)
    if issues > 0:
        print(f'\n  -> MTCS: ISSUES DETECTED ({issues})')
        return 1
    print(f'\n  -> MTCS: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
