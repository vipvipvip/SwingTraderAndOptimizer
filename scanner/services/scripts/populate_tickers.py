"""Phase 1: Populate scanner tables with OHLCV data from Alpaca.

Supports weekly, daily, and 1-hour timeframes.
Incremental: queries the latest date in the DB and only fetches new bars.
For hourly, tickers are sourced from tbl_scanner_tickers with 3-month lookback.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, date, time as dt_time
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from io import StringIO

import requests
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY, DB_CONFIG, get_db_conn

SP500_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
NY = ZoneInfo('America/New_York')

TIMEFRAMES = {
    'week': {'tf': TimeFrame.Week, 'table': 'tbl_scanner_tickers', 'label': 'weeks', 'yf_interval': '1wk'},
    'day': {'tf': TimeFrame.Day, 'table': 'tbl_scanner_tickers_daily', 'label': 'days', 'yf_interval': '1d'},
}

# Delisted / taken-over / dead tickers. Never re-populate or re-add these.
DEAD_TICKERS = {'FBRX', 'SAFT', 'GRAL'}

# How many trailing weeks the weekly populate re-fetches every run. The weekly
# bar is written ONCE, when its week is complete — so a missed run, a partial
# write or a corrected value self-heals on the next one instead of staying
# frozen. Cheap: 4 weeks x ~1,450 tickers.
WEEKLY_REFRESH_WEEKS = 4

# A weekly bar is stamped at the ISO-week start (Monday) but its close is that
# week's LAST session. Alpaca returns the in-progress week alongside completed
# ones, and its close mutates every session — so the Monday row used to be
# overwritten with each day's price until Friday finally landed in it. That
# makes `max(date)` unreliable (it returns a partial bar wearing a complete
# week's date) and makes every consumer re-derive "is this settled?" by hand.
# Instead we persist ONLY completed weeks, so settledness is a property of the
# row: the newest row in the table is always the last fully-closed week.
# A week is treated as complete once its Friday has closed (16:05 ET, past the
# 16:00 bell plus the settlement buffer); holidays only ever make this late,
# never early.
WEEKLY_SETTLE_TIME = dt_time(16, 5)


def week_is_settled(bar_date, now=None):
    """True iff the Monday-stamped weekly bar `bar_date` covers a finished week."""
    now = now or datetime.now(NY)
    friday = bar_date + timedelta(days=4)
    if friday < now.date():
        return True
    if friday == now.date():
        return now.time() >= WEEKLY_SETTLE_TIME
    return False


def earliest_unsettled_week(now=None):
    """Monday-stamped date of the earliest week that is NOT finished yet.

    Everything from this date onward is either in progress or in the future, so
    it must not be in the table. Note this is NOT simply date_trunc('week',
    today): on Friday evening, Saturday and Sunday the current ISO week has
    already closed and its row is valid, final data.
    """
    now = now or datetime.now(NY)
    monday = now.date() - timedelta(days=now.date().weekday())
    if now.date().weekday() < 5 and now.time() < WEEKLY_SETTLE_TIME:
        return monday
    return monday + timedelta(days=7)


def fetch_sp500_tickers():
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
    resp = requests.get(SP500_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    df = pd.read_html(StringIO(resp.text))[0]
    tickers = sorted(df['Symbol'].tolist())
    print(f"Fetched {len(tickers)} SP500 tickers from Wikipedia")
    return tickers


def ensure_ticker_in_stock(symbol):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO tbl_stock_tickers (symbol, enabled, created_at, updated_at) "
                "VALUES (%s, true, NOW(), NOW()) "
                "ON CONFLICT (symbol) DO NOTHING",
                (symbol,)
            )
            conn.commit()
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def get_latest_date_for_ticker(ticker_id, table):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX(date) FROM {table} WHERE ticker_id = %s", (ticker_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None
    finally:
        conn.close()


def get_latest_overall(table):
    """Newest date in `table` across all tickers (None if empty)."""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX(date)::date FROM {table}")
            row = cur.fetchone()
            return row[0] if row and row[0] else None
    finally:
        conn.close()


def fetch_bars(symbol, client, tf_name, start):
    end = datetime.now(NY)
    tf = TIMEFRAMES[tf_name]['tf']

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
        feed='iex',
        limit=10000,
        adjustment='all',
    )
    response = client.get_stock_bars(request)
    if not response or symbol not in response.data:
        return None

    all_bars = list(response.data[symbol])
    page_token = getattr(response, 'next_page_token', None)

    while page_token:
        request.page_token = page_token
        response = client.get_stock_bars(request)
        if symbol in response.data:
            all_bars.extend(response.data[symbol])
        page_token = getattr(response, 'next_page_token', None)

    return all_bars


def process_ticker(symbol, client, tf_name, global_start, priority=False):
    try:
        table = TIMEFRAMES[tf_name]['table']
        is_hourly = tf_name == 'hour'

        ticker_id = ensure_ticker_in_stock(symbol)
        if ticker_id is None:
            return symbol, 0, 'failed to create ticker'

        # Determine start date: latest in DB or the global_start (if first run)
        latest = get_latest_date_for_ticker(ticker_id, table)
        latest_date = None
        if latest is not None:
            if isinstance(latest, datetime):
                latest_date = latest.date()
            elif isinstance(latest, date):
                latest_date = latest
            else:
                latest_date = datetime.strptime(str(latest)[:10], '%Y-%m-%d').date()
            # Weekly bars are stamped at the ISO-week start (Monday) and are only
            # written once their week is complete, so re-fetch a trailing window
            # of weeks on every run (self-healing) instead of latest+1, which
            # would skip the newest settled week forever. Daily/hourly bars are
            # stamped at their own date/hour, so latest+1 is correct for them.
            if tf_name == 'week':
                start = datetime.combine(
                    latest_date - timedelta(days=7 * WEEKLY_REFRESH_WEEKS),
                    datetime.min.time(), tzinfo=NY)
            else:
                start = datetime.combine(latest_date + timedelta(days=1), datetime.min.time(), tzinfo=NY)
        else:
            # No data yet — use the global start (2015-01-01 or computed lookback)
            start = global_start

        now = datetime.now(NY)
        if not priority:
            if is_hourly:
                if start >= now:
                    return symbol, 0, 'up to date'
            else:
                if latest_date is not None and latest_date >= now.date():
                    return symbol, 0, 'up to date'

        bars = fetch_bars(symbol, client, tf_name, start)
        # Alpaca is the ONLY price source (adjusted, `adjustment='all'`). There is
        # deliberately no yfinance/stockanalysis fallback: those return raw,
        # unadjusted closes, so a single fallback row silently mixes a foreign
        # price basis into the table (measured: 156 names >2% off vs the weekly
        # bar, worst 6.8%) and yf weekly bars even stamp the wrong week date.
        # A genuine Alpaca gap must surface as a gap, not be papered over.
        if not bars:
            return symbol, 0, 'no data from alpaca'


        rows = []
        skipped_unsettled = 0
        now = datetime.now(NY)
        for bar in bars:
            ts = bar.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(NY)
            if is_hourly:
                date_val = ts
            else:
                date_val = ts.date()
            # Never persist a partial weekly bar (see WEEKLY_REFRESH_WEEKS).
            if tf_name == 'week' and not week_is_settled(date_val, now):
                skipped_unsettled += 1
                continue
            rows.append((
                ticker_id, date_val,
                float(bar.open), float(bar.high), float(bar.low),
                float(bar.close), int(bar.volume),
            ))

        if not rows:
            return symbol, 0, f'no settled bars yet ({skipped_unsettled} in progress)'

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                if is_hourly:
                    rows = [(r[0], r[1].replace(tzinfo=None) if hasattr(r[1], 'tzinfo') and r[1].tzinfo is not None else r[1], *r[2:]) for r in rows]
                if tf_name == 'week':
                    # Weekly is INSERT-ONLY. `week_is_settled` above already
                    # refuses to persist an in-progress week, so a Monday-stamped
                    # row is only ever written once, carrying that week's final
                    # Friday close. There is no partial-to-settled transition left
                    # to service, so re-upserting the row just churns it (and, with
                    # adjustment='all', rewrites history Alpaca itself has already
                    # finalised). A settled week is immutable here.
                    conflict_clause = 'ON CONFLICT (ticker_id, date) DO NOTHING'
                else:
                    # Daily/hourly still settle IN PLACE: the 09:00 scanner-update
                    # writes today's partial daily bar, which the 16:30 run must
                    # then complete. Guarded so a re-fetch that returns identical
                    # numbers does not rewrite the row.
                    conflict_clause = f"""
                        ON CONFLICT (ticker_id, date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume
                        WHERE ({table}.open, {table}.high, {table}.low,
                               {table}.close, {table}.volume)
                          IS DISTINCT FROM
                              (EXCLUDED.open, EXCLUDED.high, EXCLUDED.low,
                               EXCLUDED.close, EXCLUDED.volume)
                    """
                execute_values(
                    cur,
                    f"""
                        INSERT INTO {table} (ticker_id, date, open, high, low, close, volume)
                        VALUES %s
                        {conflict_clause}
                    """,
                    rows,
                )
            conn.commit()
        finally:
            conn.close()

        return symbol, len(rows), 'ok'
    except Exception as e:
        return symbol, 0, str(e)


def main():
    parser = argparse.ArgumentParser(description='Populate scanner tables with SP500 OHLCV data')
    parser.add_argument('--timeframe', choices=list(TIMEFRAMES.keys()), default='week',
                        help='Bar timeframe to fetch (default: week)')
    parser.add_argument('--workers', type=int, default=3, help='Number of parallel workers')
    parser.add_argument('--full-refetch', action='store_true',
                        help='Delete and re-fetch all data instead of incremental update')
    parser.add_argument('--priority', default='',
                        help='Comma-separated symbols to force-fetch even if "up to date" '
                             '(e.g. currently invested tickers that must have fresh prices for exit signals)')
    args = parser.parse_args()

    priority_set = {s.strip().upper() for s in args.priority.split(',') if s.strip()}

    table = TIMEFRAMES[args.timeframe]['table']
    label = TIMEFRAMES[args.timeframe]['label']

    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

    # Read all enabled tickers from tbl_stock_tickers
    conn = get_db_conn()
    try:
        tickers = [t for t in pd.read_sql(
            "SELECT symbol FROM tbl_stock_tickers WHERE enabled ORDER BY symbol", conn
        )['symbol'].tolist() if t not in DEAD_TICKERS]
    finally:
        conn.close()

    if not tickers:
        print("No enabled tickers found, fetching SP500 list from Wikipedia...")
        tickers = fetch_sp500_tickers()
        print(f"Fetched {len(tickers)} SP500 tickers from Wikipedia")

    now = datetime.now(NY)
    if args.timeframe == 'hour':
        start = now - timedelta(days=90)
        print(f"Processing {len(tickers)} tickers (1-hour timeframe, 3-month lookback) "
              f"with {args.workers} workers into {table}...")
    else:
        start = now.replace(year=2015, month=1, day=1)
        print(f"Processing {len(tickers)} tickers ({args.timeframe} timeframe) "
              f"with {args.workers} workers into {table}...")

    if args.full_refetch:
        print("Full refetch mode: deleting all existing data first...")
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()

    total = len(tickers)
    done = 0
    ok = 0
    failed = 0
    total_bars = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_ticker, ticker, client, args.timeframe, start,
                            ticker in priority_set): ticker
            for ticker in tickers
        }

        for future in as_completed(futures):
            ticker = futures[future]
            symbol, bars_inserted, status = future.result()
            done += 1

            if status.startswith('ok'):
                ok += 1
                total_bars += bars_inserted
                print(f"  [{done}/{total}] {symbol}: {bars_inserted} {label} inserted")
            else:
                failed += 1
                reason = 'no data' if status == 'no data' else status
                print(f"  [{done}/{total}] {symbol}: skipped ({reason})")

    print(f"\nDone. {ok} tickers updated ({total_bars} total {label}), {failed} skipped.")

    if args.timeframe == 'week':
        # Remove rows for weeks that are not finished (written by the old
        # behaviour, which upserted the in-progress week with each session's
        # price). Uses the same settledness rule as the writer above, so a week
        # that legitimately closed on Friday is kept. This is what makes
        # `max(date)` mean "last fully-closed week" again.
        cutoff = earliest_unsettled_week()
        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE date >= %s", (cutoff,))
                removed = cur.rowcount
            conn.commit()
        finally:
            conn.close()
        newest = get_latest_overall(table)
        print(f"Weekly table settled-only: dropped {removed} unsettled row(s) "
              f"(>= {cutoff}); newest row now {newest}.")


if __name__ == '__main__':
    main()
