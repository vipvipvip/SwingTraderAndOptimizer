#!/usr/bin/env python3
"""Load initial bars data from CSV files into database"""
import os
import glob
import sqlite3
from datetime import datetime
import pandas as pd
from bars_db import BarsDB

# Find the most recent CSV files for each ticker
data_dir = os.path.join(os.path.dirname(__file__), 'data')
db = BarsDB()

print("Loading initial bars data into database...\n")

# Get ticker IDs from database
conn = sqlite3.connect(db.db_path)
cursor = conn.cursor()
ticker_map = {}
cursor.execute("SELECT id, symbol FROM tickers")
for ticker_id, symbol in cursor.fetchall():
    ticker_map[symbol] = ticker_id
conn.close()

for symbol in ['SPY', 'QQQ', 'IWM']:
    if symbol not in ticker_map:
        print(f"[{symbol}] Ticker not found in database")
        continue

    ticker_id = ticker_map[symbol]

    # Find the most recent CSV for this symbol
    pattern = os.path.join(data_dir, f"{symbol}_1Hour_*.csv")
    files = sorted(glob.glob(pattern), reverse=True)

    if not files:
        print(f"[{symbol}] No CSV found")
        continue

    csv_file = files[0]
    print(f"[{symbol}] Loading {os.path.basename(csv_file)}...", end='', flush=True)

    try:
        # Read CSV
        df = pd.read_csv(csv_file, index_col='timestamp', parse_dates=True)

        # Insert into database
        count = db.insert_bars(ticker_id, df, symbol=symbol)

        total = db.bar_count(ticker_id)
        print(f" {count} new bars (total: {total})")

    except Exception as e:
        print(f" ERROR: {e}")

print("\nDone!")
