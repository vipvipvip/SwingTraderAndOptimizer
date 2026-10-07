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
  - INCREMENTAL BY DEFAULT, PER TICKER. Each ticker is fetched from its OWN last
    stored bar (daily: frontier+1; weekly: the frontier bar itself, so a partial week
    stamped earlier gets completed), never from 2016. A ticker with no rows at all is
    the only case that pulls full history. This is what keeps a one-day catch-up at
    one small request per ticker instead of ~2,650 bars each (the 2026-10-05 run that
    took six minutes and got the SIP feed throttled). `--full-refresh` is the explicit,
    opt-in way to re-pull history (needed after a split/dividend, because
    adjustment='all' re-bases OLD bars and an incremental pull cannot fix those).
  - Resumable. Re-running with --resume skips tickers already current, so an
    interrupted full-universe run continues where it stopped.
  - atr_stop is set to NULL on every upsert. A refreshed close invalidates the
    stored ATR, and ATR = (close - atr_stop)/2 is what live MTF trades on, so a
    stale value must never survive. Run compute_indicators.py against the new
    tables after every load; until then data_readiness.py will (correctly)
    refuse to trade.

Usage:
    python load_prices.py --report-only            # what is behind, fetch nothing
    python load_prices.py --dry-run --limit 5
    python load_prices.py --timeframe day --limit 5
    python load_prices.py --resume                 # incremental, skip already-current
    python load_prices.py --symbols QRVO --full-refresh
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
# but hung indefinitely inside a 1,450-ticker run and stalled the whole load.
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


def fetch(symbol, tf_name, start_year=START_YEAR, start=None):
    """Paginated SIP fetch. Returns [(date, o, h, l, c, v), ...] or raises.

    `start` narrows the window to a ticker's own frontier (see start_for); when omitted
    it pulls from start_year (new tickers and --full-refresh only).
    """
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=ALPACA_TF[tf_name],
        start=start or datetime(start_year, 1, 1, tzinfo=NY),
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
    if tf_name == 'week':
        # Never persist the still-forming week (see settled_week_monday).
        final = settled_week_monday()
        out = [r for r in out if r[0] <= final]
    return out


def fetch_with_retry(symbol, tf_name, start=None):
    delay = 2
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch(symbol, tf_name, start=start), None
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


def get_frontiers(table):
    """ticker_id -> newest stored bar date, in one grouped query."""
    c = get_db_conn()
    try:
        with c.cursor() as cur:
            cur.execute(f'SELECT ticker_id, max(date) FROM {table} GROUP BY ticker_id')
            return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        c.close()


def start_for(tf_name, frontier, full_refresh=False):
    """Per-ticker fetch start. None = full history from START_YEAR.

    Daily starts the day after the frontier. Weekly starts the Monday after it: the
    loader only ever stores FINAL weekly bars (see fetch / settled_week_monday), so the
    frontier bar is complete and is never re-pulled or re-written.
    """
    if full_refresh or frontier is None:
        return None
    if tf_name == 'week':
        nxt = frontier + timedelta(days=7)
        return datetime(nxt.year, nxt.month, nxt.day, tzinfo=NY)
    nxt = frontier + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=NY)


def get_universe():
    c = get_db_conn()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers '
                        'WHERE enabled ORDER BY symbol')
            return cur.fetchall()
    finally:
        c.close()


def work(item, tf_name, table, dry_run, frontier, full_refresh, cutoff):
    tid, sym = item
    start = start_for(tf_name, frontier, full_refresh)
    rows, err = fetch_with_retry(sym, tf_name, start)
    if err:
        return sym, 0, err
    # Write only bars that are new AND settled: never re-write a stored bar (an upsert
    # NULLs its atr_stop and forces a recompute) and never store today's partial daily
    # bar if the run happens mid-session. --full-refresh bypasses the frontier check.
    rows = [r for r in rows if r[0] <= cutoff
            and (full_refresh or frontier is None or r[0] > frontier)]
    if not rows:
        # A ticker that already has history and simply has nothing newer (halted, or
        # the bar is not published yet) is not a failure -- but it stays behind, so the
        # caller reports it. Only a ticker with NO history and no data is an error.
        return sym, 0, 'no new data' if frontier is not None else 'no data returned'
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


WEEKLY_SETTLE_TIME = '16:05'


def settled_week_monday(now=None):
    """Monday stamp of the newest weekly bar that is FINAL.

    Weekly bars are loaded once a week: Friday after the close (>= 16:05 ET). Alpaca
    stamps every weekly bar at the ISO-week Monday, so Mon-Thu the newest final bar is
    LAST week's Monday and the forming week is deliberately not loaded. data_readiness
    and weekly_takeoff use this same rule; keep them in lockstep.
    """
    now = now or datetime.now(NY)
    monday = now.date() - timedelta(days=now.weekday())
    settle = datetime.strptime(WEEKLY_SETTLE_TIME, '%H:%M').time()
    done = now.weekday() > 4 or (now.weekday() == 4 and now.time() >= settle)
    return monday if done else monday - timedelta(days=7)


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
        return settled_week_monday(now)
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
    ap.add_argument('--full-refresh', action='store_true',
                    help='re-pull full history (2016+) for the selected tickers instead of '
                         'each ticker\'s own frontier; use after a split/dividend')
    ap.add_argument('--report-only', action='store_true',
                    help='list tickers behind the settled cutoff and fetch nothing')
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
    noref = []
    for tf in tfs:
        table = TABLES[tf]
        cutoff = resume_cutoff(tf)  # per-timeframe: weekly and daily settle differently
        frontiers = get_frontiers(table)
        behind = [it for it in universe
                  if not (frontiers.get(it[0]) and frontiers[it[0]] >= cutoff)]
        todo = behind if args.resume or args.report_only else universe
        print(f'--- {tf}: settled cutoff {cutoff} -> {len(behind)} behind, '
              f'{len(universe) - len(behind)} current, {len(todo)} to fetch')
        if args.report_only:
            for tid, sym in behind:
                f = frontiers.get(tid)
                print(f'  behind: {sym:<8} frontier={f} '
                      f'{"NO HISTORY" if f is None else f"gap={(cutoff - f).days}d"}')
            continue

        done = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(work, it, tf, table, args.dry_run,
                                frontiers.get(it[0]), args.full_refresh, cutoff): it
                    for it in todo}
            for fut in as_completed(futs):
                sym, n, status = fut.result()
                done += 1
                if status == 'no new data':
                    noref.append((tf, sym))
                elif status not in ('ok',) and not status.startswith('dry-run'):
                    failures.append((tf, sym, status))
                    print(f'  [{done}/{len(todo)}] {sym}: {status}', flush=True)
                if done % 50 == 0 or done == len(todo):
                    rate = done / max(time.time() - t0, 1e-9)
                    print(f'  [{done}/{len(todo)}] {rate:.1f}/s  last={sym} {status}',
                          flush=True)

    if args.report_only:
        return
    if noref:
        print(f'\n{len(noref)} ticker(s) had no newer bar upstream (halted / not yet '
              f'published): ' + ', '.join(f'{s}({tf})' for tf, s in noref[:20]))

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