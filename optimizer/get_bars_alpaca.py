#!/usr/bin/env python3
"""
Fetch historical bars from Alpaca using the official SDK.
Usage: python get_bars_alpaca.py <symbol> <timeframe> <start_date> <end_date>
Output: JSON with bars array
"""

import sys
import json
from datetime import datetime
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import os

def get_bars(symbol, timeframe, start_date, end_date):
    try:
        # Get API credentials from environment or .env file
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')

        # If not in environment, try to read from .env file
        if not api_key or not secret_key:
            env_file = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    for line in f:
                        if line.startswith('ALPACA_API_KEY='):
                            api_key = line.split('=', 1)[1].strip().strip('"\'')
                        elif line.startswith('ALPACA_SECRET_KEY='):
                            secret_key = line.split('=', 1)[1].strip().strip('"\'')

        if not api_key or not secret_key:
            raise Exception('ALPACA_API_KEY or ALPACA_SECRET_KEY not found in environment or .env')

        # Initialize the client
        client = StockHistoricalDataClient(api_key, secret_key)

        # Convert timeframe string to TimeFrame enum
        tf = timeframe.lower()
        if tf in ('1h', '1hour'):
            tf = TimeFrame.Hour
        elif tf in ('1d', '1day'):
            tf = TimeFrame.Day
        elif tf == '1min':
            tf = TimeFrame.Minute
        else:
            tf = TimeFrame.Hour  # Default to hourly

        # Create request
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_date,
            end=end_date
        )

        # Fetch data
        bars_dict = client.get_stock_bars(request_params)

        if not bars_dict or symbol not in bars_dict:
            return []

        bars = []
        for bar in bars_dict[symbol]:
            bars.append({
                't': bar.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                'o': float(bar.open),
                'h': float(bar.high),
                'l': float(bar.low),
                'c': float(bar.close),
                'v': int(bar.volume)
            })

        return bars
    except Exception as e:
        raise Exception(f'Failed to fetch bars for {symbol}: {str(e)}')

if __name__ == '__main__':
    if len(sys.argv) < 5:
        print(json.dumps({'error': 'Usage: get_bars_alpaca.py <symbol> <timeframe> <start_date> <end_date>'}))
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    start_date = sys.argv[3]
    end_date = sys.argv[4]

    try:
        bars = get_bars(symbol, timeframe, start_date, end_date)
        print(json.dumps({'success': True, 'bars': bars}))
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
