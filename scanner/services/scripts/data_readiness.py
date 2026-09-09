#!/usr/bin/env python3
"""Data Readiness Gate — verify data integrity & completeness before indicators/trades.

The gate is the "verify -> repair -> verify -> trade" checkpoint every data
consumer (MTF scorer/executor, Daily Signal) runs before generating signals.

Per timeframe (week/day/hour) it checks:
  1. Bar coverage frontier   — the newest date where >= COVERAGE[tf]% of the
     mode's enabled universe has a bar (robust to intraday partial backfills).
  2. Expected frontier       — the newest trading session (Alpaca Market
     Calendar) that MUST already be present at this time of day. This catches
     multi-day server-off gaps, including the *permanent hourly holes* that
     capture_hourly.py cannot heal (it only snapshots the current hour).
  3. Per-ticker staleness    — tickers whose latest bar lags the frontier by
     more than STALE_LAG_DAYS are REPORTED as warnings (halted tickers like
     APGE, new IPOs), but do not block — the frontier/expected + indicator
     coverage gates are what catch a broad outage.
  4. Indicator coverage      — atr_stop present on each ticker's latest bar
     (only for tickers with >= MIN_ROWS history, the same bar count
     compute_indicators.py requires). Catches interrupted compute runs that
     leave NULL indicators on fresh bars -> silent wrong signals.

`ensure_readiness()` chains verify -> repair (calendar-aware backfill of missing
bars for the failing timeframes via backfill_all_missing, then recompute
indicators) -> re-verify, returning NOT-ready (exit 2) if still failing, so a
consumer NEVER generates signals on incomplete data.

Consumers subprocess this script with the scanner venv:
    python data_readiness.py --check  --tf day,hour --mode stock
    python data_readiness.py --ensure --tf day,hour --mode stock
exit 0 = ready | 2 = not ready (after repair, if --ensure).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn, EMA_SLOW, PPO_SLOW

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backfill_all_missing as bf

NY = ZoneInfo('America/New_York')
TABLES = {
    'week': 'tbl_scanner_tickers',
    'day': 'tbl_scanner_tickers_daily',
    'hour': 'tbl_scanner_tickers_1hour',
}
# compute_indicators.py skips tickers with fewer than max(EMA_SLOW,PPO_SLOW)+1
# bars; the gate applies the same bar so young listings are never false-failures.
MIN_ROWS = max(EMA_SLOW, PPO_SLOW) + 1
STALE_LAG_DAYS = 1
COVERAGE = {'week': 0.90, 'day': 0.90, 'hour': 0.75}  # intraday hour is partial
FRONTIER_LOOKBACK_DAYS = 15
# windows used to count bars per ticker (must comfortably exceed MIN_ROWS bars)
BARCOUNT_WINDOW = {'week': timedelta(days=400), 'day': timedelta(days=150),
                   'hour': timedelta(days=10)}


def _get_trading_days(now):
    """Trading days [today-45d, today] from Alpaca's market calendar.
    Falls back to Mon-Fri weekdays if the calendar API is unreachable (the
    repair path is idempotent, so a drifted expected date self-corrects)."""
    start = now.date() - timedelta(days=45)
    days = bf.get_trading_calendar(start, now.date())
    if days:
        return days
    return sorted({d for d in (start + timedelta(n) for n in range(46))
                   if d.weekday() < 5 and d <= now.date()})


def _expected_session_date(tf_name, trading_days, now):
    """Newest trading session whose bars MUST exist by `now` (calendar-aware)."""
    today = now.date()
    last_td = trading_days[-1]

    def prev_session():
        return trading_days[-2] if len(trading_days) >= 2 else last_td

    if tf_name == 'week':
        # Alpaca timestamps every weekly bar at the ISO-week start (Monday),
        # holiday or not: the current week's bar is stamped this week's Monday
        # and is NOT re-stamped on later sessions. Expect that Monday — never
        # "today" — or the week gate would fail on every non-Monday session.
        return today - timedelta(days=today.weekday())
    if tf_name == 'day':
        # daily expects the newest fully-completed session. An intraday run
        # before 16:00 ET expects data through yesterday (today is partial).
        if last_td == today and now.time() < datetime.strptime('16:00', '%H:%M').time():
            return prev_session()
        return last_td
    # hour: after 10:00 ET on a session day, today's bars are expected (the
    # 10:10 capture writes the 10:00 bar for every ticker). Before that, or
    # outside a session, the previous session suffices.
    if last_td == today:
        if now.time() >= datetime.strptime('10:00', '%H:%M').time():
            return today
        return prev_session()
    return last_td


def _enabled_tickers(conn, mode):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled AND is_etf=%s '
            'ORDER BY symbol', (mode == 'etf',))
        return cur.fetchall()


def _coverage_frontier(conn, tf_name, ticker_ids, pct):
    """Newest date where >= pct of ticker_ids have a bar (None if none)."""
    if not ticker_ids:
        return None
    required = max(int(len(ticker_ids) * pct), 1)
    table = TABLES[tf_name]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {table}.date::date AS d, COUNT(DISTINCT ticker_id) AS n "
            f"FROM {table} "
            f"WHERE ticker_id = ANY(%s) "
            f"AND {table}.date >= CURRENT_DATE - {FRONTIER_LOOKBACK_DAYS} "
            f"GROUP BY d ORDER BY d DESC", (list(ticker_ids),))
        for d, n in cur.fetchall():
            if n >= required:
                return d
    return None


def _ticker_stats(conn, tf_name, ticker_ids):
    """Per ticker: bars in window, latest bar date, atr_stop on latest bar."""
    table = TABLES[tf_name]
    since = (datetime.now(NY).date() - BARCOUNT_WINDOW[tf_name])
    stats = {}
    if not ticker_ids:
        return stats
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT ticker_id, COUNT(*) AS n, MAX({table}.date)::date AS last_dt, "
            f"(ARRAY_AGG(atr_stop ORDER BY {table}.date DESC))[1] AS last_atr "
            f"FROM {table} "
            f"WHERE ticker_id = ANY(%s) AND {table}.date >= %s "
            f"GROUP BY ticker_id", (list(ticker_ids), since))
        for tid, n, last_dt, last_atr in cur.fetchall():
            stats[tid] = (n, last_dt, last_atr)
    return stats


def verify_frame(conn, tf_name, mode, trading_days, now):
    """Verify a single timeframe. Returns a report dict with `ready`."""
    ids = _enabled_tickers(conn, mode)
    tid_list = [tid for tid, _ in ids]
    symbol_of = lambda tid: dict(ids).get(tid, str(tid))  # noqa: E731
    frontier = _coverage_frontier(conn, tf_name, tid_list, COVERAGE[tf_name])
    expected = _expected_session_date(tf_name, trading_days, now)
    stats = _ticker_stats(conn, tf_name, tid_list)

    problems = []
    if frontier is None:
        problems.append(f'no bar coverage frontier in last {FRONTIER_LOOKBACK_DAYS}d')
    elif frontier < expected:
        problems.append(f'bars behind (frontier {frontier} < expected {expected})')

    n_outliers = 0
    outlier_syms = []
    if frontier is not None:
        floor = frontier - timedelta(days=STALE_LAG_DAYS)
        for tid, (n, last_dt, _atr) in stats.items():
            if last_dt is not None and last_dt < floor:
                n_outliers += 1
                if len(outlier_syms) < 10:
                    outlier_syms.append(symbol_of(tid))
    # NOTE: outliers are informational (single halted/young tickers must not
    # block trading). The hard cohort gates are frontier/expected (below) and
    # indicator coverage.

    n_ind = 0
    ind_syms = []
    for tid, (n, last_dt, atr) in stats.items():
        if n >= MIN_ROWS and last_dt is not None and atr is None:
            n_ind += 1
            if len(ind_syms) < 10:
                ind_syms.append(symbol_of(tid))
    if n_ind:
        problems.append(f'{n_ind} tickers missing indicators on latest bar')

    ready = (not problems) and bool(tid_list)
    return {
        'tf': tf_name, 'mode': mode, 'ready': ready,
        'frontier': str(frontier), 'expected': str(expected),
        'tickers': len(tid_list), 'problems': problems,
        'n_outliers': n_outliers, 'outliers': outlier_syms,
        'n_missing_indicators': n_ind, 'missing_indicators': ind_syms,
    }


def _verify_all(tfs, mode, now):
    trading_days = _get_trading_days(now)
    conn = get_db_conn()
    try:
        return {tf: verify_frame(conn, tf, mode, trading_days, now) for tf in tfs}
    finally:
        conn.close()


def ensure_readiness(tfs, mode, now=None, workers=10):
    """verify -> repair (backfill + recompute) -> re-verify. Returns (ready, report)."""
    now = now or datetime.now(NY)
    report = _verify_all(tfs, mode, now)
    failing = [tf for tf, r in report.items() if not r['ready']]
    if failing:
        print(f'[READINESS] Repairing missing data for: {", ".join(failing)}', flush=True)
        ok, _ = bf.backfill_timeframes(failing, workers=workers, recompute=True)
        if not ok:
            print('[READINESS] backfill reported errors — re-verifying anyway')
        report = _verify_all(tfs, mode, now)
        still = [tf for tf, r in report.items() if not r['ready']]
        for tf in still:
            print(f'[READINESS] STILL NOT READY {tf}: {report[tf]["problems"]}', flush=True)
    ready = all(r['ready'] for r in report.values())
    return ready, report


def _print_report(report):
    for tf, r in sorted(report.items()):
        status = 'READY' if r['ready'] else 'NOT READY'
        problems = '; '.join(r['problems']) if r['problems'] else '-'
        print(f"[READINESS] {tf:<5} {status}  frontier={r['frontier']:<12} "
              f"expected={r['expected']:<12} outliers={r['n_outliers']:<3} "
              f"missing_ind={r['n_missing_indicators']}  {problems}")
        if r['outliers']:
            print(f'[READINESS]     stale tickers: {", ".join(r["outliers"])}')
        if r['missing_indicators']:
            print(f'[READINESS]     missing indicators: {", ".join(r["missing_indicators"])}')


def _run_for_mode(mode, tfs, ensure, workers, now):
    modes = ['stock', 'etf'] if mode == 'all' else [mode]
    overall = True
    all_reports = {}
    for m in modes:
        if ensure:
            ready, report = ensure_readiness(tfs, m, now=now, workers=workers)
        else:
            report = _verify_all(tfs, m, now)
            ready = all(r['ready'] for r in report.values())
        all_reports[m] = report
        print(f'\n[READINESS] mode={m} -> {"READY" if ready else "NOT READY"}')
        _print_report(report)
        overall &= ready
    return overall, all_reports


def main():
    ap = argparse.ArgumentParser(description='Data Readiness Gate')
    ap.add_argument('--ensure', action='store_true',
                    help='Repair missing data + recompute indicators, then re-verify')
    ap.add_argument('--check', dest='ensure', action='store_false')
    ap.set_defaults(ensure=True)
    ap.add_argument('--tf', default='day,hour',
                    help='Comma-separated timeframes (default: day,hour)')
    ap.add_argument('--mode', default='stock', choices=['stock', 'etf', 'all'])
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    tfs = [t.strip() for t in args.tf.split(',') if t.strip()]
    now = datetime.now(NY)
    ready, all_reports = _run_for_mode(args.mode, tfs, args.ensure, args.workers, now)

    if args.json:
        print(json.dumps({'ready': ready, 'modes': all_reports}, default=str))
    print(f'\n[READINESS] overall: {"READY" if ready else "NOT READY"}', flush=True)
    return 0 if ready else 2


if __name__ == '__main__':
    sys.exit(main())