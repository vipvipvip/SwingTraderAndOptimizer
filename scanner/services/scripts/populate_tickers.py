"""Phase 1: Populate scanner tables with OHLCV data from Alpaca.

Supports weekly, daily, and 1-hour timeframes.
Incremental: queries the latest date in the DB and only fetches new bars.
For hourly, tickers are sourced from tbl_scanner_tickers with 3-month lookback.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, date
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
    'hour': {'tf': TimeFrame.Hour, 'table': 'tbl_scanner_tickers_1hour', 'label': 'hours', 'yf_interval': '1h'},
}


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


def fetch_yfinance_bars(symbol, tf_name, start):
    """Fallback data source: yfinance.

    Alpaca's IEX feed sometimes has no bars for ultra-thin names that still
    trade (e.g. CZFS/PDEX/SEB/UTMD). When Alpaca returns nothing, use
    yfinance as a fallback so invested tickers always get a price to generate
    exit signals.

    Returns a list of simple bar objects compatible with Alpaca's Bar
    (attributes: timestamp, open, high, low, close, volume), or None.
    """
    import yfinance as yf

    end = datetime.now(NY)
    interval = TIMEFRAMES[tf_name]['yf_interval']
    try:
        df = yf.download(symbol, start=start, end=end, interval=interval,
                         auto_adjust=False, progress=False)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    bars = []
    for idx, row in df.iterrows():
        ts = idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=NY)
        try:
            bars.append(_SimpleBar(
                ts,
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close']),
                int(row['Volume']),
            ))
        except Exception:
            continue
    return bars or None


class _SimpleBar:
    """Minimal Alpaca-Bar-compatible object for yfinance fallback rows."""
    def __init__(self, timestamp, open, high, low, close, volume):
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


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
        source = 'alpaca'
        if not bars or len(bars) == 0:
            bars = fetch_yfinance_bars(symbol, tf_name, start)
            if not bars or len(bars) == 0:
                return symbol, 0, 'no new data'
            source = 'yfinance'

        rows = []
        for bar in bars:
            ts = bar.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(NY)
            if is_hourly:
                date_val = ts
            else:
                date_val = ts.date()
            rows.append((
                ticker_id, date_val,
                float(bar.open), float(bar.high), float(bar.low),
                float(bar.close), int(bar.volume),
            ))

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                if is_hourly:
                    rows = [(r[0], r[1].replace(tzinfo=None) if hasattr(r[1], 'tzinfo') and r[1].tzinfo is not None else r[1], *r[2:]) for r in rows]
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

        if source == 'yfinance':
            return symbol, len(rows), 'ok (yfinance fallback)'
        return symbol, len(rows), 'ok'
    except Exception as e:
        return symbol, 0, str(e)


def main():
    parser = argparse.ArgumentParser(description='Populate scanner tables with SP500 OHLCV data')
    parser.add_argument('--timeframe', choices=list(TIMEFRAMES.keys()), default='week',
                        help='Bar timeframe to fetch (default: week)')
    parser.add_argument('--workers', type=int, default=10, help='Number of parallel workers')
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
        tickers = pd.read_sql(
            "SELECT symbol FROM tbl_stock_tickers WHERE enabled ORDER BY symbol", conn
        )['symbol'].tolist()
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
                if status == 'ok (yfinance fallback)':
                    print(f"  [{done}/{total}] {symbol}: {bars_inserted} {label} inserted (yfinance fallback)")
                else:
                    print(f"  [{done}/{total}] {symbol}: {bars_inserted} {label} inserted")
            else:
                failed += 1
                reason = 'no data' if status == 'no data' else status
                print(f"  [{done}/{total}] {symbol}: skipped ({reason})")

    print(f"\nDone. {ok} tickers updated ({total_bars} total {label}), {failed} skipped.")


if __name__ == '__main__':
    main()
