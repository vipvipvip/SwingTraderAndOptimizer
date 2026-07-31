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

        # Count qualifying tickers (all 3 timeframes present) — single query
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT st.id
                FROM tbl_stock_tickers st
                WHERE st.enabled = true
                  AND EXISTS (SELECT 1 FROM tbl_scanner_tickers w WHERE w.ticker_id = st.id)
                  AND EXISTS (SELECT 1 FROM tbl_scanner_tickers_daily d WHERE d.ticker_id = st.id)
                  AND EXISTS (SELECT 1 FROM tbl_scanner_tickers_1hour h WHERE h.ticker_id = st.id)
            ) sub
        """)
        qual = cur.fetchone()[0]
        ok(f'{qual}/{len(tickers)} tickers have all 3 timeframes')

        # Market breadth
        pct = db_module.get_market_breadth(conn)
        if pct is not None:
            regime = 'Risk-on' if pct >= 55 else ('Neutral' if pct >= 35 else 'Risk-off')
            ok(f'Market breadth: {pct:.0f}% uptrend ({regime})')
        else:
            warn('Could not compute market breadth')

        # ── Runner runs (DB-backed: mtf_runs) ──
        modes = ('stock', 'etf')
        for mode in modes:
            run = db_module.get_last_run(conn, mode, 'score')
            label = f'{mode} scorer'
            if not run:
                warn(f'[{label}] no score run recorded yet')
                continue
            age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - run['created_at']).total_seconds() / 86400
            status = run['status']
            if status != 'ok':
                fail(f'[{label}] last run {run["sig_date"]} ended {status}: {run["detail"] or "no detail"}')
            elif age_days > 2:
                fail(f'[{label}] last ok run {run["sig_date"]} is {age_days:.1f}d old — may be failing silently')
            elif age_days > 1:
                warn(f'[{label}] last ok run {run["sig_date"]} is {age_days:.1f}d old')
            else:
                ok(f'[{label}] last ok run {run["sig_date"]} ({age_days*24:.1f}h ago)')

        # ── Pending execution status ──
        with conn.cursor() as cur:
            cur.execute('SELECT mode, sig_date FROM mtf_pending WHERE consumed_at IS NULL')
            pending = cur.fetchall()
        if pending:
            for mode, sig_date in pending:
                ok(f'[pending] {mode} execution waiting (scored {sig_date})')
        else:
            ok('[pending] no outstanding execution')

        # ── Pick-history CSVs (per mode) ──
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, 'data')
        csv_variants = [
            ('mtf_picks_stock.csv', 'picks stocks'),
            ('mtf_picks_etf.csv', 'picks ETFs'),
        ]
        if os.path.exists(data_dir):
            any_picks = False
            for fname, label in csv_variants:
                fp = os.path.join(data_dir, fname)
                if os.path.exists(fp):
                    any_picks = True
                    ok(f'CSV [{label}] exists')
            if not any_picks:
                warn('No picks CSVs yet')
        else:
            warn('No data directory (not yet run)')

    finally:
        conn.close()

    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
