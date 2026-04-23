#!/usr/bin/env python3
"""Fetch hourly data from Alpaca and update database"""
import os
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd
from bars_db import BarsDB

# Load credentials from backend .env
env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
load_dotenv(env_path)

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')

if not api_key or not secret_key:
    print("ERROR: ALPACA_API_KEY or ALPACA_SECRET_KEY not found in .env")
    exit(1)

# Create clients
client = StockHistoricalDataClient(api_key, secret_key)
db = BarsDB()

# Get ticker IDs from database
conn = sqlite3.connect(db.db_path)
cursor = conn.cursor()
ticker_map = {}
cursor.execute("SELECT id, symbol FROM tickers")
for ticker_id, symbol in cursor.fetchall():
    ticker_map[symbol] = ticker_id
conn.close()

# Tickers
tickers = ['SPY', 'QQQ', 'IWM']
end_date = datetime.now()

print("Fetching latest hourly data from Alpaca\n")

for symbol in tickers:
    if symbol not in ticker_map:
        print(f"[{symbol}] Ticker not found in database")
        continue

    ticker_id = ticker_map[symbol]

    # Check DB for latest bar timestamp
    latest = db.get_latest_timestamp(ticker_id)

    if latest:
        # Fetch from 1 hour before latest (overlap to catch any gaps)
        start_date = latest - timedelta(hours=1)
        db_count = db.bar_count(ticker_id)
        print(f"[{symbol}] Fetching from {start_date.isoformat()}...", end='', flush=True)
    else:
        # First time: fetch 60 days of history
        start_date = end_date - timedelta(days=60)
        db_count = 0
        print(f"[{symbol}] Fetching {(end_date - start_date).days} days of history...", end='', flush=True)

    try:
        # Request bars
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Hour,
            start=start_date,
            end=end_date,
            feed='iex',
            limit=10000
        )

        bars_dict = client.get_stock_bars(request)

        if symbol not in bars_dict.data:
            print(" NO DATA")
            continue

        # Paginate if needed
        all_bars = list(bars_dict.data[symbol])
        page_token = getattr(bars_dict, 'next_page_token', None)

        while page_token:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Hour,
                start=start_date,
                end=end_date,
                feed='iex',
                limit=10000,
                page_token=page_token
            )
            bars_dict = client.get_stock_bars(request)
            if symbol in bars_dict.data:
                all_bars.extend(bars_dict.data[symbol])
            page_token = getattr(bars_dict, 'next_page_token', None)

        # Convert to DataFrame
        data = []
        for bar in all_bars:
            data.append({
                'timestamp': bar.timestamp,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': int(bar.volume)
            })

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()

        # Insert into database
        inserted = db.insert_bars(ticker_id, df, symbol=symbol)
        new_db_count = db.bar_count(ticker_id)

        print(f" {inserted} new bars ({new_db_count} total, was {db_count})")

    except Exception as e:
        print(f" ERROR: {e}")

print("\nDone!")
