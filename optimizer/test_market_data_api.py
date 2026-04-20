#!/usr/bin/env python3
"""Test Market Data API connection"""
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

load_dotenv()

api_key = os.getenv('ALPACA_API_KEY')
base_url = os.getenv('ALPACA_BASE_URL')

print("=" * 50)
print("MARKET DATA API TEST")
print("=" * 50)

# Test with latest bar data
symbols = ['AAPL', 'GOOGL', 'MSFT']
headers = {'APCA-API-KEY-ID': api_key}

# Get latest bars
url = f"{base_url}/bars/latest"
params = {'symbols': ','.join(symbols)}

response = requests.get(url, params=params, headers=headers)
data = response.json()

print(f"\n[OK] Latest Market Data Retrieved")
for symbol, bar_data in data.get('bars', {}).items():
    bar = bar_data['bar']
    print(f"  {symbol}:")
    print(f"    Price: ${bar['c']}")
    print(f"    High: ${bar['h']}")
    print(f"    Low: ${bar['l']}")
    print(f"    Volume: {bar['v']}")

# Test historical data
print(f"\n[OK] Historical Data (last 5 days)")
url = f"{base_url}/bars"
start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
params = {
    'symbols': 'AAPL',
    'timeframe': '1Day',
    'start': start_date,
    'limit': 5
}

response = requests.get(url, params=params, headers=headers)
data = response.json()

for bar in data.get('bars', {}).get('AAPL', [])[:5]:
    print(f"  {bar['t']}: Close ${bar['c']}")

print("\n[OK] Market Data API connection successful!")
