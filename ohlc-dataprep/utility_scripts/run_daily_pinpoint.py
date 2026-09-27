"""Driver: pinpoint which day within a weekly swing pivot's trading week the
actual daily high/low printed on, and show the daily slope trajectory
around it. Read-only -- no writes.

Weekly bars are Monday-stamped (see ../HANDOFF.md verification notes), so a
pivot's `date` is the Monday of that trading week -- the actual intraweek
high/low can land on any day Mon-Fri. This narrows "which week" (found via
the weekly zigzag, see swing_calc.find_swings) down to "which day", using
the daily slope_open/high/low/close columns already populated in Phase 1.

Usage: venv/bin/python3 run_daily_pinpoint.py [--ticker VTI] [--threshold 0.15] [--display-window 5]
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import acquire_ohlc as ao
from swing_calc import find_swings, pinpoint_extreme

SLOPE_COLS = ('slope_open', 'slope_high', 'slope_low', 'slope_close')


def week_window(daily_df, monday, span_days=6):
    """Daily rows from `monday` through `span_days` later (inclusive) --
    covers a Mon-Fri trading week plus slack for holiday shifts."""
    lo, hi = monday, monday + datetime.timedelta(days=span_days)
    mask = (daily_df['date'] >= lo) & (daily_df['date'] <= hi)
    return daily_df.loc[mask].reset_index(drop=True)


def display_window(daily_df, center_date, before, after):
    """Slice `before`/`after` trading days of daily_df around center_date.
    Returns (window_df, center_offset_within_window)."""
    idx = daily_df.index[daily_df['date'] == center_date][0]
    lo, hi = max(0, idx - before), min(len(daily_df), idx + after + 1)
    return daily_df.iloc[lo:hi].reset_index(drop=True), idx - lo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='VTI')
    parser.add_argument('--threshold', type=float, default=0.15,
                         help='zigzag reversal threshold used to find the weekly pivots')
    parser.add_argument('--display-window', type=int, default=5,
                         help='trading days shown before/after the pinpointed day')
    args = parser.parse_args()

    conn = ao.get_conn()
    try:
        weekly = ao.load_weekly(conn, args.ticker)
        daily = ao.load_daily_with_slopes(conn, args.ticker)
    finally:
        conn.close()

    pivots = find_swings(weekly['date'].tolist(), weekly['close'].tolist(), args.threshold)
    confirmed = [p for p in pivots if '(ongoing)' not in p.kind]

    print(f'=== {args.ticker}: pinpointing the daily extreme within each weekly '
          f'{args.threshold:.0%}-zigzag pivot week ===')
    for p in confirmed:
        wk = week_window(daily, p.date)
        if wk.empty:
            print(f'\n{p.date}  {p.kind:8s}  (no daily bars found for that week -- skipped)')
            continue

        idx, day, price = pinpoint_extreme(
            wk['date'].tolist(), wk['high'].tolist(), wk['low'].tolist(), p.kind)
        offset_days = (day - p.date).days
        extreme_label = 'high' if p.kind == 'TOP' else 'low'
        print(f'\n{p.date}  {p.kind:8s}  weekly close={p.price:8.2f}  -> actual {extreme_label} on '
              f'{day} ({offset_days:+d}d into the week) = {price:.2f}')

        window, center_offset = display_window(daily, day, args.display_window, args.display_window)
        for i, (_, row) in enumerate(window.iterrows()):
            rel = i - center_offset
            marker = '  <<<' if rel == 0 else ''
            slopes = '  '.join(f'{c[len("slope_"):]}={row[c]:+7.2f}' for c in SLOPE_COLS)
            print(f'  {rel:+3d}  {row["date"]}  close={row["close"]:8.2f}  {slopes}{marker}')


if __name__ == '__main__':
    main()
