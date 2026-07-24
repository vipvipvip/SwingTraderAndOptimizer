#!/usr/bin/env python3
"""EMAC system health check — run from health-check.sh or standalone."""
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
import db as db_module
from strategy import check_signal, WARMUP

NY = ZoneInfo('America/New_York')


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
    print('--- EMAC (30-min EMA/SMA + MACD Crossover) ---')
    print(f'  Market: {market_label} ({now_ny.strftime("%a %Y-%m-%d %H:%M %Z")})')
    print(f'  Config: EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) + '
          f'MACD({config.MACD_FAST},{config.MACD_SLOW},{config.MACD_SIGNAL})')
    print(f'  Poll interval: {config.POLL_INTERVAL_SEC}s | Warmup: {WARMUP} candles')

    db_module.init_db()
    conn = db_module.get_conn()

    # ── Service status ──
    svc_status = os.popen(
        'systemctl is-active emac-runner 2>/dev/null || echo "not-found"'
    ).read().strip()
    if svc_status == 'active':
        ok(f'emac-runner.service is active')
    else:
        fail(f'emac-runner.service is {svc_status}')

    if svc_status == 'active':
        uptime = os.popen(
            'systemctl show emac-runner -p ActiveEnterTimestamp --value 2>/dev/null'
        ).read().strip()
        if uptime:
            print(f'    Started: {uptime}')

    # ── Recent errors from log file ──
    log_path = '/var/log/emac-runner.log'
    errors = ''
    if os.path.isfile(log_path):
        errors = os.popen(
            f'tail -200 {log_path} | grep -iE "error|exception|traceback|fail" | tail -5'
        ).read().strip()
    if errors:
        warn(f'Recent errors in log:')
        for line in errors.split('\n'):
            print(f'    {line}')
    else:
        ok('No errors in log')

    # ── Candle freshness & signal state per ticker ──
    print()
    ticker_issues = 0
    for sym in config.TICKERS:
        tid = db_module.get_ticker_id(conn, sym)
        cnt = db_module.candle_count(conn, tid)

        cur = conn.cursor()
        cur.execute(
            'SELECT ts FROM emac_candles WHERE ticker_id = %s ORDER BY ts DESC LIMIT 1',
            (tid,))
        row = cur.fetchone()
        latest_ts = row[0] if row else None

        cur.execute(
            'SELECT ts FROM emac_raw_trades WHERE ticker_id = %s ORDER BY ts DESC LIMIT 1',
            (tid,))
        trade_row = cur.fetchone()
        latest_trade = trade_row[0] if trade_row else None

        warmed = cnt >= WARMUP
        sig = check_signal(conn, tid) if warmed else None
        sig_label = sig if sig else 'NONE'

        print(f'  {sym}:')
        print(f'    Candles: {cnt} total {"(warmed up)" if warmed else f"(need {WARMUP} - still warming)"}')
        print(f'    Latest candle: {latest_ts or "NONE"}')
        print(f'    Latest raw trade: {latest_trade or "NONE"}')
        print(f'    Signal: {sig_label}')

        # Check freshness during market hours
        if market_open and latest_ts:
            age = (datetime.now(timezone.utc) - latest_ts.replace(tzinfo=timezone.utc)).total_seconds()
            if age > 3600:
                warn(f'    Candle is {age/60:.0f} min old (stale > 60 min during market hours)')
                ticker_issues += 1
            else:
                ok(f'    Candle age: {age/60:.0f} min')

        if market_open and not latest_trade:
            fail(f'    No raw trades found during market hours')
            ticker_issues += 1

    # ── Position / trade summary ──
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM emac_trades')
    trade_count = cur.fetchone()[0]
    print(f'\n  Total trades executed (all time): {trade_count}')

    cur.execute(
        'SELECT symbol, quantity, entry_price, entry_at FROM emac_positions '
        'WHERE quantity > 0 ORDER BY symbol')
    positions = cur.fetchall()
    if positions:
        print(f'  Open positions:')
        for symbol, qty, ep, ets in positions:
            print(f'    {symbol}: {qty} shares @ ${ep:.2f} (since {ets})')
    else:
        print(f'  Open positions: none')

    # ── Buffer file ──
    buf_path = os.path.join(os.path.dirname(__file__), '.emac_buffer.json')
    if os.path.exists(buf_path):
        buf_age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(buf_path))).total_seconds()
        if buf_age < 600:
            ok(f'Buffer file exists (updated {buf_age/60:.0f} min ago)')
        else:
            warn(f'Buffer file stale (updated {buf_age/60:.0f} min ago)')
    else:
        warn('Buffer file (.emac_buffer.json) not found')

    conn.close()

    if ticker_issues > 0 or svc_status != 'active':
        print(f'\n  -> EMAC: ISSUES DETECTED')
        return 1
    print(f'\n  -> EMAC: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
