#!/usr/bin/env python3
"""Promote optimizer candidate to base case"""
import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from db import StrategyDB


def promote_candidate(symbol, candidate_id):
    """Promote a candidate (base_case=0) to become the new base_case=1"""
    db = StrategyDB()
    conn = db.get_connection()
    cursor = conn.cursor()

    # Get the candidate
    cursor.execute('''
        SELECT id, ticker_id, macd_fast, bb_period, bb_std,
               sharpe_ratio, total_return
        FROM strategy_parameters
        WHERE id = %s AND ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
        AND base_case = false
    ''', (candidate_id, symbol))

    candidate = cursor.fetchone()
    if not candidate:
        print(f"ERROR: Candidate {candidate_id} not found for {symbol}")
        db.close()
        return False

    candidate_id_db = candidate[0]
    ticker_id = candidate[1]
    bb_period = candidate[3]
    bb_std = candidate[4]
    sharpe = candidate[5]
    total_return = candidate[6]

    print(f"\nPromoting {symbol} Candidate {candidate_id_db}:")
    print(f"  BB: period={bb_period}, std={bb_std}")
    print(f"  Metrics: Sharpe={sharpe:.4f}, Return={total_return*100:.2f}%")

    try:
        # Demote current base_case=1 to base_case=0
        cursor.execute('''
            UPDATE strategy_parameters
            SET base_case = false, updated_at = NOW()
            WHERE ticker_id = %s AND base_case = true
        ''', (ticker_id,))
        print(f"  ✓ Demoted old base case")

        # Promote candidate to base_case=1
        cursor.execute('''
            UPDATE strategy_parameters
            SET base_case = true, updated_at = NOW()
            WHERE id = %s
        ''', (candidate_id_db,))
        print(f"  ✓ Promoted candidate to base_case=1")

        conn.commit()
        print(f"  ✓ SUCCESS: {symbol} updated to use new base case")
        print(f"\n  Executor will use these parameters on next trade")
        return True

    except Exception as e:
        conn.rollback()
        print(f"  ERROR: {e}")
        return False
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Promote optimizer candidate to base case')
    parser.add_argument('ticker', help='Ticker symbol (e.g., SPY)')
    parser.add_argument('--candidate-id', type=int, required=True, help='Candidate ID to promote')

    args = parser.parse_args()

    print(f"\n[{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}] Promotion starting...")

    if promote_candidate(args.ticker, args.candidate_id):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
