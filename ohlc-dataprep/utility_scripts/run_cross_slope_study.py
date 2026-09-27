"""Driver: test cross_slope_calc.cross_slope_gap as a potentially LEADING
(not lagging) warning signal, reusing the event-study machinery from
run_fade_score_study.py (collect/report). Motivation: that script's fade
score (a slope compared to ITS OWN past) came back flat-to-LOWER approaching
major pivots -- expected, since a slope typically peaks on/after the actual
extreme (see HANDOFF.md daily-pinpoint finding), so "recent deceleration" is
structurally a lagging measure. A same-bar cross-series comparison doesn't
have that lag built in, so it's a fairer test of whether ANY slope-based
feature actually leads a turn, at both negative (before) and positive
(after) offsets -- this run checks both to see the full shape.

Usage: venv/bin/python3 run_cross_slope_study.py [--major-threshold 0.15]
       [--offsets -12,-8,-6,-4,-2,-1,0,1,2,4,6,8]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import acquire_ohlc as ao
from swing_calc import find_swings
from cross_slope_calc import cross_slope_gap
from run_fade_score_study import collect, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--major-threshold', type=float, default=0.15)
    parser.add_argument('--offsets', default='-12,-8,-6,-4,-2,-1,0,1,2,4,6,8')
    args = parser.parse_args()
    offsets = [int(x) for x in args.offsets.split(',')]

    conn = ao.get_conn()
    try:
        top_series, bot_series = {}, {}
        major_tops, major_bots = {}, {}
        for symbol in config.TICKERS:
            df = ao.load_weekly_with_slopes(conn, symbol)
            if df.empty or df[config.SLOPE_COLUMNS].isna().all(axis=None):
                continue
            dates = df['date'].tolist()
            major = find_swings(dates, df['close'].tolist(), args.major_threshold)
            confirmed = [p for p in major if '(ongoing)' not in p.kind]
            major_tops[symbol] = [p for p in confirmed if p.kind == 'TOP']
            major_bots[symbol] = [p for p in confirmed if p.kind == 'BOTTOM']

            top_series[symbol] = cross_slope_gap(df['slope_high'], df['slope_close'])
            bot_series[symbol] = cross_slope_gap(df['slope_close'], df['slope_low'])
    finally:
        conn.close()

    print(f'=== Cross-slope-gap study: {len(top_series)} ETFs, '
          f'major={args.major_threshold:.0%} zigzag on close ===')

    top_baseline, top_window = collect(top_series, major_tops, offsets)
    report('TOPs (slope_high - slope_close gap)', top_baseline, top_window, offsets)

    bot_baseline, bot_window = collect(bot_series, major_bots, offsets)
    report('BOTTOMs (slope_close - slope_low gap)', bot_baseline, bot_window, offsets)


if __name__ == '__main__':
    main()
