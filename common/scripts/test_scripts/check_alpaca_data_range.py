"""Check how far back Alpaca API provides data for QQQ and VTI"""
import sys, os
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'backend', '.env')
load_dotenv(env_path)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')
client = StockHistoricalDataClient(api_key, secret_key)

for sym in ['QQQ', 'VTI']:
    print(f'\n=== {sym} ===')
    # Binary search for earliest data
    lo, hi = 1999, 2026
    earliest = hi
    while lo <= hi:
        mid = (lo + hi) // 2
        req = StockBarsRequest(
            symbol_or_symbols=sym, timeframe=TimeFrame.Day,
            start=f'{mid}-01-01', end=f'{mid+1}-01-01',
            feed='iex', limit=3
        )
        bars = client.get_stock_bars(req)
        data = bars.data.get(sym, [])
        if data:
            earliest = mid
            hi = mid - 1
        else:
            lo = mid + 1

    # Get exact first bar
    req = StockBarsRequest(
        symbol_or_symbols=sym, timeframe=TimeFrame.Day,
        start=f'{earliest}-01-01', end=f'{earliest+3}-01-01',
        feed='iex', limit=3
    )
    bars = client.get_stock_bars(req)
    data = bars.data.get(sym, [])
    if data:
        print(f'  First year: {earliest}')
        print(f'  First bar:  {data[0].timestamp} O={data[0].open} H={data[0].high} L={data[0].low} C={data[0].close}')
        if len(data) >= 2:
            print(f'  2nd bar:    {data[1].timestamp} O={data[1].open} C={data[1].close}')

    # Latest data available
    req = StockBarsRequest(
        symbol_or_symbols=sym, timeframe=TimeFrame.Day,
        start='2026-05-01', end='2026-06-10',
        feed='iex', limit=5
    )
    bars = client.get_stock_bars(req)
    data = bars.data.get(sym, [])
    if data:
        print(f'  Last bar:   {data[-1].timestamp} O={data[-1].open} H={data[-1].high} L={data[-1].low} C={data[-1].close}')

print('\nDone')
