#!/usr/bin/env python3
"""Standalone script to fetch and update prices without optimization"""
import sys
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from data_fetcher import fetch_incremental_data, load_data_from_db, append_bars_to_db

def fetch_and_update_ticker(symbol, timeframe='1Hour'):
    """Fetch incremental data for a ticker and update database"""
    print(f"\n{'='*60}")
    print(f"Updating {symbol}")
    print(f"{'='*60}")

    try:
        # Load existing data
        df = load_data_from_db(symbol)
        if df is not None:
            last_date = df.index[-1].date()
            print(f"Current data: {len(df)} bars, last: {last_date}")
        else:
            print(f"No existing data for {symbol}")

        # Fetch incremental data
        print(f"Fetching incremental data...")
        new_df = fetch_incremental_data(symbol, timeframe=timeframe)

        if new_df is None:
            print(f"No new data to fetch for {symbol}")
            return True  # Not a failure, just no new data

        # Append to database
        print(f"Appending {len(new_df)} bars to database...")
        append_bars_to_db(symbol, new_df)

        # Verify
        updated_df = load_data_from_db(symbol)
        if updated_df is not None:
            print(f"✓ Updated: {len(updated_df)} total bars, last: {updated_df.index[-1].date()}")
            return True
        else:
            print(f"Failed to verify update")
            return False

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description='Fetch incremental prices for a ticker')
    parser.add_argument('--ticker', type=str, help='Stock symbol (e.g., SPY). If not provided, fetches all tickers from database')
    parser.add_argument('--timeframe', type=str, default='1Hour', help='Bar timeframe (default: 1Hour)')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("PRICE FETCHER - Incremental Data Update")
    print(f"Timestamp: {datetime.now(ZoneInfo('America/New_York')).isoformat()}")
    print(f"{'='*60}")

    # Determine which tickers to fetch
    if args.ticker:
        tickers = [args.ticker]
    else:
        # Fetch all tickers from database
        try:
            import sqlite3
            from db import StrategyDB
            db = StrategyDB()
            all_tickers = db.get_all_tickers()
            db.close()
            tickers = [t['symbol'] for t in all_tickers] if all_tickers else ['SPY', 'QQQ', 'IWM']
        except Exception as e:
            print(f"Error loading tickers from database: {e}")
            tickers = ['SPY', 'QQQ', 'IWM']

    timeframe = args.timeframe

    results = {
        'updated': [],
        'failed': [],
    }

    for symbol in tickers:
        if fetch_and_update_ticker(symbol, timeframe):
            results['updated'].append(symbol)
        else:
            results['failed'].append(symbol)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Updated:  {', '.join(results['updated']) if results['updated'] else 'None'}")
    print(f"Failed:   {', '.join(results['failed']) if results['failed'] else 'None'}")
    print(f"Total:    {len(results['updated'])}/{len(tickers)}")

    return 0 if not results['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
