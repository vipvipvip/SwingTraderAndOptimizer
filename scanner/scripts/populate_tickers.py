"""Phase 1: Populate scanner tables with SP500 OHLCV data from Alpaca.

Supports weekly and daily timeframes.
"""

import argparse
import os
import sys
from datetime import datetime
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
    'week': {'tf': TimeFrame.Week, 'table': 'tbl_scanner_tickers', 'label': 'weeks'},
    'day': {'tf': TimeFrame.Day, 'table': 'tbl_scanner_tickers_daily', 'label': 'days'},
}


def fetch_sp500_tickers():
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
    resp = requests.get(SP500_URL, headers=headers, timeout=15)
    resp.raise_for_status()
    df = pd.read_html(StringIO(resp.text))[0]
    tickers = sorted(df['Symbol'].tolist())
    print(f"Fetched {len(tickers)} SP500 tickers from Wikipedia")
    return tickers


def fetch_bars(symbol, client, tf_name):
    end = datetime.now(NY)
    start = end.replace(year=2015, month=1, day=1)
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
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            feed='iex',
            limit=10000,
            page_token=page_token,
            adjustment='all',
        )
        response = client.get_stock_bars(request)
        if symbol in response.data:
            all_bars.extend(response.data[symbol])
        page_token = getattr(response, 'next_page_token', None)

    return all_bars


def process_ticker(symbol, client, tf_name):
    try:
        table = TIMEFRAMES[tf_name]['table']
        bars = fetch_bars(symbol, client, tf_name)
        if not bars or len(bars) == 0:
            return symbol, 0, 'no data'

        rows = []
        for bar in bars:
            ts = bar.timestamp
            if ts.tzinfo is not None:
                ts = ts.astimezone(NY)
            rows.append((
                symbol,
                ts.date(),
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                int(bar.volume),
            ))

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE ticker = %s", (symbol,))
                execute_values(
                    cur,
                    f"""
                        INSERT INTO {table}
                        (ticker, date, open, high, low, close, volume)
                        VALUES %s
                        ON CONFLICT (ticker, date) DO NOTHING
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
    parser.add_argument('--workers', type=int, default=10, help='Number of parallel workers')
    args = parser.parse_args()

    table = TIMEFRAMES[args.timeframe]['table']
    label = TIMEFRAMES[args.timeframe]['label']

    print(f"Fetching SP500 ticker list...")
    tickers = fetch_sp500_tickers()
    print(f"Processing {len(tickers)} tickers ({args.timeframe} timeframe) "
          f"with {args.workers} workers into {table}...")

    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

    total = len(tickers)
    done = 0
    ok = 0
    failed = 0
    total_bars = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_ticker, ticker, client, args.timeframe): ticker
            for ticker in tickers
        }

        for future in as_completed(futures):
            ticker = futures[future]
            symbol, bars_inserted, status = future.result()
            done += 1

            if status == 'ok':
                ok += 1
                total_bars += bars_inserted
                print(f"  [{done}/{total}] {symbol}: {bars_inserted} {label} inserted")
            else:
                failed += 1
                reason = 'no data' if status == 'no data' else status
                print(f"  [{done}/{total}] {symbol}: skipped ({reason})")

    print(f"\nDone. {ok} tickers inserted ({total_bars} total {label}), {failed} skipped.")


if __name__ == '__main__':
    main()
