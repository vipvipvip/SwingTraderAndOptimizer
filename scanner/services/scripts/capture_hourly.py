"""Hourly price snapshot: capture current prices for all scanner tickers.

Replaces populate_tickers.py for the 1hour timeframe since Alpaca's free
IEX tier does not provide historical hourly bars. Instead, we capture a
price snapshot from the latest trade once per hour during market hours.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY, get_db_conn

NY = ZoneInfo('America/New_York')
TABLE = 'tbl_scanner_tickers_1hour'
BATCH_SIZE = 200


def get_tickers():
    conn = get_db_conn()
    try:
        tickers = pd.read_sql(
            """SELECT DISTINCT e.symbol
               FROM tbl_scanner_tickers s
               JOIN tbl_stock_tickers e ON e.id = s.ticker_id
               ORDER BY e.symbol""", conn
        )['symbol'].tolist()
    finally:
        conn.close()
    return tickers


def get_ticker_id(symbol):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def capture_prices(tickers):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    prices = {}
    total = len(tickers)
    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        request = StockLatestTradeRequest(
            symbol_or_symbols=batch, feed='iex',
        )
        response = client.get_stock_latest_trade(request)
        for sym, trade in response.items():
            prices[sym] = {
                'price': float(trade.price),
                'size': int(trade.size),
            }
        print(f"  fetched {min(i + BATCH_SIZE, total)}/{total}")
    return prices


def upsert_prices(prices):
    now = datetime.now(NY)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            for ticker, data in prices.items():
                p = data['price']
                ticker_id = get_ticker_id(ticker)
                if ticker_id is None:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO {TABLE} (ticker_id, date, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker_id, date) DO UPDATE SET
                        high = GREATEST({TABLE}.high, EXCLUDED.high),
                        low = LEAST({TABLE}.low, EXCLUDED.low),
                        close = EXCLUDED.close
                    """,
                    (ticker_id, hour_start, p, p, p, p, data['size']),
                )
        conn.commit()
        print(f"Upserted {len(prices)} rows at {hour_start}")
    finally:
        conn.close()


def main():
    now = datetime.now(NY)
    if now.weekday() >= 5:
        print(f"Skipping: weekend ({now.strftime('%A')})")
        return
    if now.hour < 9 or (now.hour == 9 and now.minute < 30) or now.hour > 17:
        print(f"Skipping: outside market hours ({now.hour}:{now.minute:02d} ET)")
        return

    print("Capturing hourly price snapshots...")
    tickers = get_tickers()
    print(f"Processing {len(tickers)} tickers")
    prices = capture_prices(tickers)
    print(f"Got prices for {len(prices)} tickers")
    upsert_prices(prices)
    print("Done.")


if __name__ == '__main__':
    main()
