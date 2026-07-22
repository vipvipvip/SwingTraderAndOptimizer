#!/usr/bin/env python3
"""MTF Top-N health check — run from health-check.sh or standalone."""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import db as db_module

NY = ZoneInfo('America/New_York')


def ok(msg):
    print(f'  [OK] {msg}')


def warn(msg):
    print(f'  [WARN] {msg}')


def fail(msg):
    print(f'  [FAIL] {msg}')


def main():
    now_ny = datetime.now(NY)
    market_label = 'MARKET HOURS' if now_ny.weekday() < 5 and 9 <= now_ny.hour < 16 else 'CLOSED'

    print()
    print('--- MTF Top-N (Multi-TF Score Rotation) ---')
    print(f'  Time: {now_ny.strftime("%a %Y-%m-%d %H:%M %Z")} ({market_label})')
    print(f'  Top-N: {config.TOP_N} | Score: gap_w/20 + atr_dist/1.5 + freshness')

    # ── Service timer status ──
    svc_status = os.popen(
        'systemctl is-active mtf-daily-runner.timer 2>/dev/null || echo "not-found"'
    ).read().strip()
    if svc_status == 'active':
        ok('mtf-daily-runner.timer is active')
        trigger = os.popen(
            'systemctl show mtf-daily-runner.timer -p TriggerOnCalendar --value 2>/dev/null'
        ).read().strip()
        if trigger:
            print(f'    Schedule: {trigger}')
    elif svc_status == 'waiting':
        ok('mtf-daily-runner.timer is waiting')
    else:
        fail(f'mtf-daily-runner.timer is {svc_status}')

    # ── Recent journal errors ──
    errors = os.popen(
        'journalctl -u mtf-daily-runner --since "1 day ago" -p err -q --no-pager 2>/dev/null '
        '| tail -5'
    ).read().strip()
    if errors:
        warn('Recent errors:')
        for line in errors.split('\n'):
            print(f'    {line}')
    else:
        ok('No errors in last 24h')

    # ── DB freshness ──
    db_module.init_db()
    conn = db_module.get_conn()
    try:
        latest_date = db_module.get_latest_daily_bar_date(conn)
        if latest_date:
            age = (now_ny.date() - latest_date).days
            if age <= 1:
                ok(f'Latest daily bar: {latest_date} (age: {age}d)')
            elif age <= 3:
                warn(f'Latest daily bar: {latest_date} (age: {age}d)')
            else:
                fail(f'Latest daily bar: {latest_date} (age: {age}d)')
        else:
            fail('No daily bar data found')

        # ── Scanner data health ──
        tickers = db_module.get_all_tickers(conn)
        ok(f'{len(tickers)} tickers enabled')

        # Count qualifying tickers (all 3 timeframes present)
        qual = 0
        for tid, sym in tickers:
            w = db_module.load_weekly(conn, tid)
            d = db_module.load_daily(conn, tid)
            h = db_module.load_hourly(conn, tid)
            if w and d and h:
                qual += 1
        ok(f'{qual}/{len(tickers)} tickers have all 3 timeframes')

        # Market breadth
        pct = db_module.get_market_breadth(conn)
        if pct is not None:
            regime = 'Risk-on' if pct >= 55 else ('Neutral' if pct >= 35 else 'Risk-off')
            ok(f'Market breadth: {pct:.0f}% uptrend ({regime})')
        else:
            warn('Could not compute market breadth')

        # ── State file ──
        state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.mtf_state.json')
        if os.path.exists(state_path):
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(state_path))).total_seconds()
            if age < 86400:
                ok(f'State file updated {age/3600:.1f}h ago')
            elif age < 172800:
                warn(f'State file stale ({age/3600:.1f}h ago)')
            else:
                msg = f'State file not updated for {age/3600:.1f}h — runner may be failing silently'
                fail(msg)
        else:
            warn('No state file (not yet run)')

        # ── Data files ──
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        if os.path.exists(data_dir):
            picks = os.path.join(data_dir, 'mtf_picks.csv')
            if os.path.exists(picks):
                ok(f'Picks CSV exists')
            else:
                warn('No picks CSV yet')
        else:
            warn('No data directory (not yet run)')

    finally:
        conn.close()

    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
