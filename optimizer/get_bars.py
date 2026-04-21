#!/usr/bin/env python3
"""
Fetch historical bars from Yahoo Finance using yfinance.
Usage: python get_bars.py <symbol> <interval> <start_date> <end_date>
Output: JSON with bars array
"""

import sys
import json
from datetime import datetime
import yfinance as yf

def get_bars(symbol, interval, start_date, end_date):
    try:
        # Fetch data from Yahoo Finance
        data = yf.download(
            symbol,
            start=start_date,
            end=end_date,
            interval=interval,
            progress=False
        )

        if data.empty:
            return []

        bars = []
        for index, row in data.iterrows():
            try:
                bar = {
                    't': index.strftime('%Y-%m-%d %H:%M:%S') if hasattr(index, 'strftime') else str(index),
                    'o': float(row['Open'].item() if hasattr(row['Open'], 'item') else row['Open']),
                    'h': float(row['High'].item() if hasattr(row['High'], 'item') else row['High']),
                    'l': float(row['Low'].item() if hasattr(row['Low'], 'item') else row['Low']),
                    'c': float(row['Close'].item() if hasattr(row['Close'], 'item') else row['Close']),
                    'v': int(row['Volume'].item() if hasattr(row['Volume'], 'item') else row['Volume'])
                }
                bars.append(bar)
            except (ValueError, TypeError) as e:
                continue

        return bars
    except Exception as e:
        raise Exception(f"Failed to fetch bars for {symbol}: {str(e)}")

if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(json.dumps({'error': 'Usage: get_bars.py <symbol> <interval> <start_date> <end_date>'}))
        sys.exit(1)

    symbol = sys.argv[1]
    interval = sys.argv[2]
    start_date = sys.argv[3]
    end_date = sys.argv[4]

    try:
        bars = get_bars(symbol, interval, start_date, end_date)
        print(json.dumps({'success': True, 'bars': bars}))
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
