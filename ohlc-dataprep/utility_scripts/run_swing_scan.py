"""Driver: load weekly closes via acquire_ohlc, run swing_calc.find_swings,
print results. Read-only -- no writes.

Usage: venv/bin/python3 run_swing_scan.py [--threshold 0.15] [--tickers VTI QQQ VTV]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import acquire_ohlc as ao
from swing_calc import find_swings


def scan(conn, symbol, threshold):
    """Load weekly closes for `symbol` and return its swing pivots."""
    df = ao.load_weekly(conn, symbol)
    return df, find_swings(df['date'].tolist(), df['close'].tolist(), threshold)


def print_report(symbol, df, pivots, threshold):
    dates = df['date'].tolist()
    print(f'\n=== {symbol} weekly, zigzag threshold={threshold:.0%}, '
          f'{dates[0]} -> {dates[-1]}, {len(df)} bars ===')
    prev_date = dates[0]
    for p in pivots:
        print(f'{p.date}  {p.kind:16s}  close={p.price:8.2f}  '
              f'move from prior pivot: {p.pct_from_prior:+7.1f}%  '
              f'({prev_date} -> {p.date})')
        prev_date = p.date


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threshold', type=float, default=0.15,
                         help='fractional reversal to register a new pivot (default 0.15 = 15%%)')
    parser.add_argument('--tickers', nargs='+', default=config.TICKERS)
    args = parser.parse_args()

    conn = ao.get_conn()
    try:
        for symbol in args.tickers:
            df, pivots = scan(conn, symbol, args.threshold)
            print_report(symbol, df, pivots, args.threshold)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
