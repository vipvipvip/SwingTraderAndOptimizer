#!/usr/bin/env python3
"""Nightly optimizer - lightweight version for testing"""
import sys
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
load_dotenv(env_path)

from db import StrategyDB
from data_fetcher import fetch_historical_data

def run_nightly_lite(tickers=None):
    """Lightweight optimization that just fetches data and logs success"""
    if tickers is None:
        tickers = ['SPY', 'QQQ', 'IWM']
    
    print(f"\n{'='*70}")
    print(f"NIGHTLY OPTIMIZER LITE (Testing Mode)")
    print(f"Timestamp: {datetime.now(ZoneInfo('America/New_York')).isoformat()}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"{'='*70}\n", flush=True)
    
    db = StrategyDB()
    
    for symbol in tickers:
        print(f"\n[{symbol}] Fetching data...", flush=True)
        df = fetch_historical_data(symbol, timeframe='1Hour', years=2)
        if df is not None:
            print(f"[{symbol}] Fetched {len(df)} bars ✓", flush=True)
        else:
            print(f"[{symbol}] Failed to fetch data ✗", flush=True)
    
    print(f"\n{'='*70}")
    print(f"NIGHTLY OPTIMIZATION COMPLETE")
    print(f"{'='*70}\n", flush=True)
    
    db.close()

if __name__ == '__main__':
    try:
        run_nightly_lite()
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
