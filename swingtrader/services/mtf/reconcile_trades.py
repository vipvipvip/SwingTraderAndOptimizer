#!/usr/bin/env python3
"""Rebuild mtf_trades from Alpaca's authoritative filled-order history.

Usage:
    python3 reconcile_trades.py --mode all      # both stock + ETF
    python3 reconcile_trades.py --mode stock
    python3 reconcile_trades.py --mode etf

Idempotent: deletes each mode's rows, then re-inserts every filled order
(qty + avg price) from Alpaca. Sell PnL computed from DB entry when available.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import executor


def main():
    parser = argparse.ArgumentParser(description='Rebuild mtf_trades from Alpaca fill history')
    parser.add_argument('--mode', choices=['stock', 'etf', 'all'], default='all',
                        help='Which universe to reconcile (default: all)')
    args = parser.parse_args()

    modes = ['stock', 'etf'] if args.mode == 'all' else [args.mode]
    for mode in modes:
        executor.reconcile_trades(mode)
    print('Reconciliation complete.')


if __name__ == '__main__':
    main()
