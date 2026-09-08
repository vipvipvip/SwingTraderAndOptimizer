#!/usr/bin/env python3
"""Backfill missing price data for all enabled tickers across all timeframes.

For each enabled ticker x timeframe (week, day, hour), acquire ONLY the bars that
are missing: from the ticker's latest stored bar + 1 trading day forward to the
most recent valid trading day. Uses Alpaca's Market Calendar API to know exactly
which days are trading days, so weekend/holiday gaps are never chased (no wasted
requests for closed days) and a ticker whose data stops before a holiday is
correctly resumed on the next open day.

The plan works either as a full catch-up (default) or as a targeted repair:
  --timeframes week,day,hour   (default: all three)
  --symbols AAPL,MSFT          (default: all enabled tickers)
  --start 2026-08-01           (force-ignore bars before this date when deciding gaps)
  --workers 10                 (threads, default 10)
  --dry-run                    (print what would be fetched, change nothing)

Writes with ON CONFLICT DO NOTHING (idempotent): rerunning never duplicates
bars. After the fetch loop, recomputes indicators for the affected timeframes so
EMA/SMA/ATR/PPO stay valid for scoring. Holidays/weekends (e.g. Sep 7 2026 Labor
Day) are skipped automatically via the calendar: no fetch is attempted for them.
"""

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY, get_db_conn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import populate_tickers as pt

NY = ZoneInfo('America/New_York')
TIMEFRAMES = pt.TIMEFRAMES
DEFAULT_START = date(2015, 1, 1)          # week/day no-history window
HOUR_LOOKBACK_DAYS = 90                    # hour no-history window


def _get_trading_calendar(start, end):
    """Return a sorted list of valid NYSE trading dates in [start, end] via Alpaca calendar."""
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetCalendarRequest
    tc = TradingClient(API_KEY, SECRET_KEY, paper=True)
    cal = tc.get_calendar(GetCalendarRequest(start=start, end=end))
    return sorted(c.date for c in cal)


def _normalize(date_val):
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val
    return date.fromisoformat(str(date_val)[:10])


def _fetch_insert(symbol, ticker_id, client, tf_name, first_missing, as_of, dry_run):
    """Fetch Alpaca/yfinance bars from `first_missing` to `as_of` and insert.
    Returns number of bars inserted."""
    if dry_run:
        return 0
    if first_missing > as_of:
        return 0

    start = datetime.combine(first_missing, datetime.min.time(), tzinfo=NY)
    bars = pt.fetch_bars(symbol, client, tf_name, start)
    if not bars or len(bars) == 0:
        bars = pt.fetch_yfinance_bars(symbol, tf_name, start)
    if not bars or len(bars) == 0:
        if tf_name == 'day':
            price = pt.fetch_stockanalysis_price(symbol)
            if price is not None:
                now = datetime.now(NY)
                bars = [pt._SimpleBar(now, price, price, price, price, 0)]
        else:
            return 0
    if not bars:
        return 0

    is_hourly = tf_name == 'hour'
    table = TIMEFRAMES[tf_name]['table']
    conn = get_db_conn()
    rows = []
    try:
        with conn.cursor() as cur:
            for bar in bars:
                ts = bar.timestamp
                if ts.tzinfo is not None:
                    ts = ts.astimezone(NY)
                if not is_hourly:
                    bar_date = _normalize(ts)
                    # only keep bars inside our needed window (skip stale ones)
                    if bar_date < first_missing or bar_date > as_of:
                        continue
                    rows.append((ticker_id, bar_date,
                                 float(bar.open), float(bar.high), float(bar.low),
                                 float(bar.close), int(bar.volume)))
                else:
                    if ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None) if ts.tzinfo is not None else ts
                    rows.append((ticker_id, ts,
                                 float(bar.open), float(bar.high), float(bar.low),
                                 float(bar.close), int(bar.volume)))
            if rows:
                execute_values(
                    cur,
                    f"""
                        INSERT INTO {table} (ticker_id, date, open, high, low, close, volume)
                        VALUES %s
                        ON CONFLICT (ticker_id, date) DO NOTHING
                    """,
                    rows,
                )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _backfill_ticker(symbol, client, tf_name, trading_days, start_date, dry_run):
    """Backfill one ticker x timeframe. Returns (symbol, tf_name, status, n_bars)."""
    table = TIMEFRAMES[tf_name]['table']
    try:
        ticker_id = pt.ensure_ticker_in_stock(symbol)
        if ticker_id is None:
            return symbol, tf_name, 'no ticker id', 0

        latest = _normalize(pt.get_latest_date_for_ticker(ticker_id, table))
        if latest is not None:
            first_missing = latest + timedelta(days=1)
        else:
            first_missing = start_date or DEFAULT_START
            if tf_name == 'hour':
                first_missing = (datetime.now(NY) - timedelta(days=HOUR_LOOKBACK_DAYS)).date()

        # as_of = the last valid trading session in the fetched window.
        as_of = trading_days[-1]

        if first_missing > as_of:
            return symbol, tf_name, 'up to date', 0

        # Find the first calendar trading day >= first_missing (skip weekends/holidays).
        first_session = next((d for d in trading_days if d >= first_missing), None)
        if first_session is None:
            return symbol, tf_name, 'up to date', 0
        if first_session > as_of:
            return symbol, tf_name, 'up to date', 0

        if dry_run:
            return symbol, tf_name, 'would fetch', (as_of - first_session).days + 1

        n = _fetch_insert(symbol, ticker_id, client, tf_name, first_session, as_of, dry_run)
        status = 'ok' if n else 'no new data'
        return symbol, tf_name, status, n
    except Exception as e:
        return symbol, tf_name, f'error: {e}', 0


def _recompute_indicators(timeframes):
    """Recompute indicators for the given timeframes after backfilling bars."""
    compute_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'scripts', 'compute_indicators.py')
    for tf in timeframes:
        print(f'[BACKFILL] Recomputing indicators for {tf}...', flush=True)
        r = subprocess.run(
            [sys.executable, compute_script, '--timeframe', tf, '--workers', '10'],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(f'  compute_indicators {tf} FAILED:\n{r.stderr[-500:]}')
        else:
            tail = r.stdout.strip().splitlines()
            print('  ' + (' | '.join(tail[-3:]) if tail else 'done'))


def main():
    ap = argparse.ArgumentParser(description='Backfill missing price data for all tickers x timeframes')
    ap.add_argument('--timeframes', default='week,day,hour',
                    help='Comma-separated timeframes to backfill (default: week,day,hour)')
    ap.add_argument('--symbols', default='',
                    help='Comma-separated symbols to limit to (default: all enabled)')
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--start', default=None,
                    help='YYYY-MM-DD global start for tickers with no history (default: 2015-01-01 for week/day, 90d for hour)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    timeframes = [t.strip() for t in args.timeframes.split(',') if t.strip()]
    start_date = date.fromisoformat(args.start) if args.start else None

    print(f'[BACKFILL] Loading trading calendar (2015-01-01..today)...')
    calendar_start = min(start_date, DEFAULT_START) if start_date else DEFAULT_START
    calendar_end = datetime.now(NY).date()
    trading_days = _get_trading_calendar(calendar_start, calendar_end)
    if not trading_days:
        print('[BACKFILL] ERROR: could not fetch trading calendar — aborting')
        sys.exit(1)
    print(f'[BACKFILL] {len(trading_days)} trading days in window '
          f'({len([d for d in trading_days if d.weekday() < 5])} weekdays = weekends/holidays skipped)')

    conn = get_db_conn()
    try:
        import pandas as pd
        syms = pd.read_sql(
            "SELECT symbol FROM tbl_stock_tickers WHERE enabled ORDER BY symbol", conn
        )['symbol'].tolist()
    finally:
        conn.close()
    if args.symbols:
        allowed = {s.strip().upper() for s in args.symbols.split(',') if s.strip()}
        syms = [s for s in syms if s in allowed]

    print(f'[BACKFILL] {len(syms)} enabled tickers')

    for tf in timeframes:
        print(f'\n[BACKFILL] == timeframe: {tf} ==', flush=True)
        client = pt.StockHistoricalDataClient(API_KEY, SECRET_KEY)
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_backfill_ticker, s, client, tf, trading_days,
                              start_date, args.dry_run): s for s in syms}
            for idx, fut in enumerate(as_completed(futs), 1):
                results.append(fut.result())
                if idx % 100 == 0:
                    print(f'  {idx}/{len(syms)} done', flush=True)

        ok = sum(1 for _, _, st, _ in results if st in ('ok', 'would fetch'))
        uptodate = sum(1 for _, _, st, _ in results if st in ('up to date',))
        no_new = sum(1 for _, _, st, _ in results if st == 'no new data')
        errs = [(s, st) for s, _, st, _ in results if st not in ('ok', 'would fetch', 'up to date', 'no new data')]
        total = sum(n for _, _, _, n in results)
        action_label = 'would-fetch' if args.dry_run else 'ok'
        print(f'[BACKFILL] {tf}: {ok} {action_label} ({total} bars), {uptodate} up-to-date, '
              f'{no_new} no-new-data, {len(errs)} errors')
        for s, st in errs[:20]:
            print(f'   ERR {s}: {st}')

    if not args.dry_run:
        _recompute_indicators(timeframes)
    else:
        print('\n[BACKFILL] DRY-RUN — no bars fetched, no indicators recomputed.')
    print('[BACKFILL] done.')


if __name__ == '__main__':
    main()