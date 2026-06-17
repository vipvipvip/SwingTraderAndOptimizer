#!/usr/bin/env python3
"""Incremental backfill: fetch missing stock bars from Alpaca and insert into scanner tables.

Only fetches dates after the latest date in each table — avoids re-fetching existing data.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scanner', 'services'))
from config import API_KEY, SECRET_KEY, DB_CONFIG, get_db_conn

NY = ZoneInfo('America/New_York')

TIMEFRAMES = {
    'week': {'tf': TimeFrame.Week, 'table': 'tbl_scanner_tickers', 'label': 'weeks', 'start_lookback_days': 90},
    'day':  {'tf': TimeFrame.Day,  'table': 'tbl_scanner_tickers_daily', 'label': 'days', 'start_lookback_days': 30},
    'hour': {'tf': TimeFrame.Hour, 'table': 'tbl_scanner_tickers_1hour', 'label': 'hours', 'start_lookback_days': 3},
}

def get_latest_date(table):
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MAX(date) FROM {table}")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()

def get_ticker_ids(table=None):
    conn = get_db_conn()
    try:
        if table:
            df = pd.read_sql(
                f"""SELECT DISTINCT s.ticker_id, e.symbol
                    FROM {table} s
                    JOIN tbl_stock_tickers e ON e.id = s.ticker_id
                    ORDER BY e.symbol""", conn)
        else:
            df = pd.read_sql(
                "SELECT id as ticker_id, symbol FROM tbl_stock_tickers ORDER BY symbol", conn)
        return df
    finally:
        conn.close()

def fetch_bars_range(symbol, client, tf, start, end):
    limit = 10000
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf,
        start=start,
        end=end,
        feed='iex',
        limit=limit,
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

def main():
    parser = argparse.ArgumentParser(description='Incremental scanner backfill')
    parser.add_argument('--timeframe', choices=list(TIMEFRAMES.keys()), default='day')
    parser.add_argument('--workers', type=int, default=10, help='Parallel workers (not used in simple impl)')
    args = parser.parse_args()

    tf_config = TIMEFRAMES[args.timeframe]
    tf = tf_config['tf']
    table = tf_config['table']
    label = tf_config['label']

    latest = get_latest_date(table)
    if latest is None:
        print(f"{table} is empty — cannot do incremental backfill. Run populate_tickers.py first.")
        sys.exit(1)

    if isinstance(latest, datetime):
        latest_date = latest.date()
    elif isinstance(latest, date):
        latest_date = latest
    else:
        latest_date = datetime.strptime(str(latest)[:10], '%Y-%m-%d').date()

    start_fetch = datetime.combine(latest_date + timedelta(days=1), datetime.min.time(), tzinfo=NY)
    end_fetch = datetime.now(NY)

    if start_fetch >= end_fetch:
        print(f"{table} is already current (latest: {latest_date}). Nothing to backfill.")
        return

    print(f"{table}: latest={latest_date}, fetching {start_fetch.date()} to {end_fetch.date()}")

    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    tickers_df = get_ticker_ids(table)
    print(f"Processing {len(tickers_df)} tickers...")

    total = len(tickers_df)
    done = ok = failed = total_bars = 0

    for _, row in tickers_df.iterrows():
        ticker_id = row['ticker_id']
        symbol = row['symbol']
        done += 1

        try:
            bars = fetch_bars_range(symbol, client, tf, start_fetch, end_fetch)
            if not bars or len(bars) == 0:
                print(f"  [{done}/{total}] {symbol}: no new data")
                failed += 1
                continue

            rows = []
            for bar in bars:
                ts = bar.timestamp
                if ts.tzinfo is not None:
                    ts = ts.astimezone(NY)
                if args.timeframe == 'hour':
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
                    execute_values(cur, f"""
                        INSERT INTO {table} (ticker_id, date, open, high, low, close, volume)
                        VALUES %s
                        ON CONFLICT (ticker_id, date) DO NOTHING
                    """, rows)
                conn.commit()
            finally:
                conn.close()

            total_bars += len(rows)
            ok += 1
            print(f"  [{done}/{total}] {symbol}: {len(rows)} new {label}")
        except Exception as e:
            failed += 1
            print(f"  [{done}/{total}] {symbol}: error - {e}")

    print(f"\nDone. {ok} tickers updated ({total_bars} new {label}), {failed} skipped/errors.")

if __name__ == '__main__':
    main()
