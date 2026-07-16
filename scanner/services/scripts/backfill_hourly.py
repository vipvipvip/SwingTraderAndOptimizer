"""Backfill 1-hour data for all scanner tickers, going back up to 3 years.

Fetches data BEFORE what already exists in tbl_scanner_tickers_1hour.
Incremental: for each ticker, finds the oldest date, then fetches from
backfill_start to oldest_date - 1 hour.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY, get_db_conn

TABLE = 'tbl_scanner_tickers_1hour'
NY = ZoneInfo('America/New_York')
TF = TimeFrame.Hour
BACKFILL_YEARS = 3


def get_all_tickers():
    conn = get_db_conn()
    try:
        df = pd.read_sql(
            "SELECT id, symbol FROM tbl_stock_tickers ORDER BY symbol", conn
        )
        return list(df.itertuples(index=False))
    finally:
        conn.close()


def get_oldest_date_for_ticker(ticker_id):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MIN(date) FROM {TABLE} WHERE ticker_id = %s", (ticker_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None
    finally:
        conn.close()


def get_latest_date_for_ticker(ticker_id):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX(date) FROM {TABLE} WHERE ticker_id = %s", (ticker_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None
    finally:
        conn.close()


def fetch_bars_range(client, symbol, start, end):
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TF,
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


def process_backfill(ticker_id, symbol, client, backfill_start):
    try:
        oldest = get_oldest_date_for_ticker(ticker_id)
        if oldest is not None:
            if isinstance(oldest, datetime):
                oldest_date = oldest
            elif isinstance(oldest, date):
                oldest_date = datetime.combine(oldest, datetime.min.time(), tzinfo=NY)
            else:
                oldest_date = datetime.strptime(str(oldest)[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=NY)
            if oldest_date.tzinfo is None:
                oldest_date = oldest_date.replace(tzinfo=NY)
        else:
            oldest_date = None

        if oldest_date is not None and oldest_date <= backfill_start:
            return symbol, 0, 'already backfilled'

        end = oldest_date - timedelta(hours=1) if oldest_date is not None else datetime.now(NY)

        bars = fetch_bars_range(client, symbol, backfill_start, end)
        if not bars or len(bars) == 0:
            return symbol, 0, 'no data'

        rows = []
        for bar in bars:
            ts = bar.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(NY)
            rows.append((
                ticker_id, ts,
                float(bar.open), float(bar.high), float(bar.low),
                float(bar.close), int(bar.volume),
            ))

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                rows_clean = [
                    (r[0], r[1].replace(tzinfo=None) if hasattr(r[1], 'tzinfo') and r[1].tzinfo is not None else r[1], *r[2:])
                    for r in rows
                ]
                execute_values(
                    cur,
                    f"""
                        INSERT INTO {TABLE} (ticker_id, date, open, high, low, close, volume)
                        VALUES %s
                        ON CONFLICT (ticker_id, date) DO NOTHING
                    """,
                    rows_clean,
                )
            conn.commit()
        finally:
            conn.close()

        return symbol, len(rows), 'ok'
    except Exception as e:
        return symbol, 0, str(e)


def main():
    parser = argparse.ArgumentParser(description='Backfill 1-hour data for all scanner tickers')
    parser.add_argument('--workers', type=int, default=10, help='Parallel workers')
    parser.add_argument('--years', type=int, default=3, help='Years of history to backfill')
    args = parser.parse_args()

    global BACKFILL_YEARS
    BACKFILL_YEARS = args.years

    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    tickers = get_all_tickers()
    backfill_start = datetime.now(NY) - timedelta(days=365 * BACKFILL_YEARS)

    print(f"Backfilling {len(tickers)} tickers with {BACKFILL_YEARS}y of 1-hour data")
    print(f"Backfill start: {backfill_start.date()}")
    print(f"Using {args.workers} workers\n")

    total = len(tickers)
    done = 0
    total_bars = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_backfill, tid, sym, client, backfill_start): sym
            for tid, sym in tickers
        }
        for future in as_completed(futures):
            symbol = futures[future]
            sym, bars, status = future.result()
            done += 1
            if status == 'ok':
                total_bars += bars
                print(f"  [{done}/{total}] {symbol}: {bars} bars backfilled")
            elif status == 'already backfilled':
                print(f"  [{done}/{total}] {symbol}: already backfilled (skipped)")
            else:
                failed += 1
                print(f"  [{done}/{total}] {symbol}: {status}")

    print(f"\nDone. {done - failed} tickers updated ({total_bars} total bars), {failed} failed.")


if __name__ == '__main__':
    main()
