#!/usr/bin/env python3
"""Load clean daily and weekly price bars into tbl_prices_daily /
tbl_prices_weekly from Alpaca.

Deliberate properties:
  - NO DELETE anywhere. Rows are upserted, so truncation is impossible by
    construction rather than by a check. This is the whole point of loading
    into new tables instead of repairing the old ones in place.
  - Each timeframe is queried natively from Alpaca (TimeFrame.Day and
    TimeFrame.Week) and never derived from the other, per your decision.
    Weekly and daily can therefore disagree slightly; validate_prices.py
    measures that and reports it rather than treating it as a failure.
  - feed='sip', adjustment='all' (split + dividend adjusted). SIP is required
    for the full history: IEX on this tier returns only ~1,555 bars from
    2020-07-27 versus SIP's ~2,703 from 2016-01-04.
  - Resumable. Re-running skips tickers already current, so an interrupted
    1,453-ticker run continues where it stopped.
  - atr_stop is set to NULL on every upsert. A refreshed close invalidates the
    stored ATR, and ATR = (close - atr_stop)/2 is what live MTF trades on, so a
    stale value must never survive. Run compute_indicators.py against the new
    tables after every load; until then data_readiness.py will (correctly)
    refuse to trade.

Usage:
    python load_prices.py --dry-run --limit 5
    python load_prices.py --timeframe day --limit 5
    python load_prices.py --resume
    python load_prices.py
"""

import argparse
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Without this, a request that never returns blocks its worker thread forever.
# Observed on MGRC and MHK: both fetched 2,703 bars fine when retried alone,
# but hung indefinitely inside a 1,453-ticker run and stalled the whole load.
# A socket timeout turns a silent hang into a retryable exception.
REQUEST_TIMEOUT = 60
socket.setdefaulttimeout(REQUEST_TIMEOUT)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn, API_KEY, SECRET_KEY

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

NY = ZoneInfo('America/New_York')

TABLES = {'day': 'tbl_prices_daily', 'week': 'tbl_prices_weekly'}
ALPACA_TF = {'day': TimeFrame.Day, 'week': TimeFrame.Week}
FEED = 'sip'
ADJUSTMENT = 'all'
START_YEAR = 2016
MAX_RETRIES = 4

_local = threading.local()


def conn():
    if not hasattr(_local, 'conn'):
        _local.conn = get_db_conn()
    return _local.conn


def fetch(symbol, tf_name, start_year=START_YEAR):
    """Paginated SIP fetch. Returns [(date, o, h, l, c, v), ...] or raises."""
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=ALPACA_TF[tf_name],
        start=datetime(start_year, 1, 1, tzinfo=NY),
        adjustment=ADJUSTMENT,
        feed=FEED,
    )
    bars = []
    page_token = None
    while True:
        if page_token:
            request.page_token = page_token
        response = client.get_stock_bars(request)
        bars.extend(response.data.get(symbol, []))
        page_token = getattr(response, 'next_page_token', None)
        if not page_token:
            break
    out = []
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is not None:
            ts = ts.astimezone(NY)
        out.append((ts.date(), float(b.open), float(b.high), float(b.low),
                    float(b.close), int(b.volume)))
    out.sort(key=lambda r: r[0])
    return out


def fetch_with_retry(symbol, tf_name):
    delay = 2
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch(symbol, tf_name), None
        except Exception as e:
            if attempt == MAX_RETRIES:
                return [], f'{type(e).__name__}: {str(e)[:120]}'
            time.sleep(delay)
            delay *= 2
    return [], 'unreachable'


def upsert(tid, table, rows):
    """Insert or update. Never deletes. atr_stop is nulled because a changed
    close invalidates it and live MTF recovers ATR from it."""
    sql = (
        f'INSERT INTO {table} (ticker_id, date, open, high, low, close, volume, '
        'atr_stop, source, feed, adjustment, fetched_at) VALUES %s '
        'ON CONFLICT (ticker_id, date) DO UPDATE SET '
        'open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, '
        'close=EXCLUDED.close, volume=EXCLUDED.volume, '
        'atr_stop=NULL, source=EXCLUDED.source, feed=EXCLUDED.feed, '
        'adjustment=EXCLUDED.adjustment, fetched_at=EXCLUDED.fetched_at, '
        'updated_at=now()'
    )
    now = datetime.now(NY)
    payload = [(tid, *r, None, 'alpaca', FEED, ADJUSTMENT, now) for r in rows]
    c = conn()
    with c.cursor() as cur:
        execute_values(cur, sql, payload, page_size=1000)
    c.commit()
    return len(rows)


def already_current(cur, table, tid, cutoff):
    cur.execute(f'SELECT max(date) FROM {table} WHERE ticker_id=%s', (tid,))
    row = cur.fetchone()
    return bool(row and row[0] and row[0] >= cutoff)


def get_universe():
    c = get_db_conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers '
                        'WHERE enabled ORDER BY symbol')
            return cur.fetchall()
    finally:
        c.close()


def work(item, tf_name, table, dry_run):
    tid, sym = item
    rows, err = fetch_with_retry(sym, tf_name)
    if err:
        return sym, 0, err
    if not rows:
        return sym, 0, 'no data returned'
    if dry_run:
        return sym, len(rows), f'dry-run {rows[0][0]}..{rows[-1][0]}'
    try:
        n = upsert(tid, table, rows)
    except Exception as e:
        c = conn()
        c.rollback()
        return sym, 0, f'write failed: {str(e)[:120]}'
    return sym, n, 'ok'


DAILY_SETTLE_TIME = '16:00'


def _trading_sessions(start, end):
    """NYSE session dates in [start, end]; Mon-Fri fallback if the calendar API fails."""
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetCalendarRequest
        tc = TradingClient(API_KEY, SECRET_KEY, paper=True)
        days = sorted(c.date for c in tc.get_calendar(
            GetCalendarRequest(start=start, end=end)))
        if days:
            return days
    except Exception as e:
        print(f'  ! calendar unavailable ({e}) - falling back to Mon-Fri weekdays')
    return sorted({start + timedelta(days=n)
                   for n in range((end - start).days + 1)
                   if (start + timedelta(days=n)).weekday() < 5})


def resume_cutoff(tf, now=None):
    """Newest date this timeframe must already have for a ticker to count as current.

    MUST stay identical to data_readiness._expected_session_date: if the loader
    considers a ticker current before the readiness gate expects its bar, the loader
    skips it and the gate then blocks the very run the loader was feeding. The old
    `now - 4 days` wall-clock cutoff could not do this - it skipped the whole daily
    universe on Mon and Tue (already "within 4 days") while the gate correctly
    wanted Monday's bar on Tuesday, and it used one cutoff for both timeframes
    although weekly and daily settle on different dates.
    """
    now = now or datetime.now(NY)
    today = now.date()
    if tf == 'week':
        # Alpaca timestamps every weekly bar at the ISO-week start (Monday), holiday
        # or not, and does NOT re-stamp later in the week. So this week's Monday is
        # the newest row the week gate expects - and it only exists once the week has
        # traded, which is why the loader must run after Monday's open.
        return today - timedelta(days=today.weekday())
    # day: the newest fully-completed session. Before 16:00 ET today's bar is still
    # partial, so only the previous session is required.
    sessions = _trading_sessions(today - timedelta(days=14), today)
    if not sessions:
        return today - timedelta(days=1)
    if sessions[-1] == today and now.time() < datetime.strptime(DAILY_SETTLE_TIME, '%H:%M').time():
        sessions = sessions[:-1]
    return sessions[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeframe', choices=['day', 'week', 'both'], default='both')
    ap.add_argument('--symbols', default=None, help='comma-separated symbols')
    ap.add_argument('--limit', type=int, default=None, help='only first N tickers')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--resume', action='store_true',
                    help='skip tickers already current for this timeframe (see resume_cutoff)')
    ap.add_argument('--dry-run', action='store_true', help='fetch and report, write nothing')
    args = ap.parse_args()

    universe = get_universe()
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(',') if s.strip()}
        universe = [u for u in universe if u[1] in wanted]
    if args.limit:
        universe = universe[:args.limit]

    tfs = ['day', 'week'] if args.timeframe == 'both' else [args.timeframe]

    print(f'universe={len(universe)} tickers  feed={FEED} adjustment={ADJUSTMENT} '
          f'workers={args.workers}{"  [DRY-RUN]" if args.dry_run else ""}')

    failures = []
    for tf in tfs:
        table = TABLES[tf]
        cutoff = resume_cutoff(tf)  # per-timeframe: weekly and daily settle differently
        todo = universe
        if args.resume:
            c = get_db_conn()
            try:
                with c.cursor() as cur:
                    todo = [it for it in universe
                            if not already_current(cur, table, it[0], cutoff)]
            finally:
                c.close()
            print(f'--- {tf}: cutoff {cutoff} -> {len(todo)} to load, '
                  f'{len(universe) - len(todo)} already current')
        else:
            print(f'--- {tf}: cutoff {cutoff} -> {len(todo)} to load')

        done = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(work, it, tf, table, args.dry_run): it
                    for it in todo}
            for fut in as_completed(futs):
                sym, n, status = fut.result()
                done += 1
                if status not in ('ok',) and not status.startswith('dry-run'):
                    failures.append((tf, sym, status))
                    print(f'  [{done}/{len(todo)}] {sym}: {status}', flush=True)
                elif done % 50 == 0 or done == len(todo):
                    rate = done / max(time.time() - t0, 1e-9)
                    print(f'  [{done}/{len(todo)}] {rate:.1f}/s  last={sym} {status}',
                          flush=True)

    print('\nLoad complete.')
    if failures:
        print(f'!! {len(failures)} failure(s):')
        for tf, sym, status in failures[:20]:
            print(f'   {tf} {sym}: {status}')
        print('\nRe-run with --resume to retry only what is missing.')
        sys.exit(1)
    if args.dry_run:
        print('Dry run: nothing written.')
    else:
        print('Next: compute_indicators.py must populate atr_stop on the new tables.')


if __name__ == '__main__':
    main()