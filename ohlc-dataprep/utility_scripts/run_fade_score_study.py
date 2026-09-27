"""Driver: test the continuous momentum_fade_calc.fade_score as a graded
early-warning signal, pooled across the full ETF universe -- addresses two
problems with run_divergence_scan_universe.py's binary pivot-to-pivot test:
(1) it only evaluated ~1 comparison per major pivot (68 tops, 109 bottoms
total across 28 ETFs), discarding almost all of the weekly data; (2) it
asked a binary yes/no question, which doesn't support a graded "start
lightening exposure" use case.

This instead scores EVERY week on a continuous scale and checks whether the
score is ELEVATED in the weeks leading into a confirmed major pivot
(offsets -12..0 weeks) compared to its own normal (all-time, all-ticker)
distribution -- reported both as a significance test (Mann-Whitney U, one
side per offset) and as an average percentile ("2 weeks before a major top,
this score typically sits at the Nth percentile of its usual range"), which
is directly usable for a graded threshold rather than a single trigger.

Usage: venv/bin/python3 run_fade_score_study.py
       [--major-threshold 0.15] [--rolling-window 20] [--fade-lookback 4]
       [--offsets -12,-8,-6,-4,-2,-1,0]
"""
import argparse
import os
import sys

import numpy as np
from scipy.stats import mannwhitneyu, percentileofscore

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import acquire_ohlc as ao
from swing_calc import find_swings
from momentum_fade_calc import fade_score


def collect(per_ticker_series, major_pivots_by_ticker, offsets):
    """Returns (baseline_all_scores, {offset: [scores at that offset across
    every major pivot in every ticker]})."""
    baseline = []
    window = {o: [] for o in offsets}
    for symbol, scores in per_ticker_series.items():
        valid = scores[~np.isnan(scores)]
        baseline.extend(valid.tolist())
        for mp in major_pivots_by_ticker[symbol]:
            for o in offsets:
                idx = mp.index + o
                if 0 <= idx < len(scores) and not np.isnan(scores[idx]):
                    window[o].append(scores[idx])
    return np.array(baseline), {o: np.array(v) for o, v in window.items()}


def report(label, baseline, window_by_offset, offsets):
    print(f'\n=== {label}: fade score in the weeks leading into major pivots '
          f'vs its own all-time distribution ({len(baseline)} baseline weeks) ===')
    print(f'{"offset(wk)":>10s} {"n":>5s} {"median":>10s} {"baseline_median":>16s} '
          f'{"avg_percentile":>15s} {"p-value (>baseline)":>20s}')
    baseline_median = np.median(baseline)
    for o in offsets:
        vals = window_by_offset[o]
        if len(vals) < 3:
            print(f'{o:>10d} {len(vals):>5d}  (too few pivots with data at this offset)')
            continue
        _, p = mannwhitneyu(vals, baseline, alternative='greater')
        avg_pctl = np.mean([percentileofscore(baseline, v) for v in vals])
        sig = '  *' if p < 0.05 else ''
        print(f'{o:>10d} {len(vals):>5d} {np.median(vals):>10.4f} {baseline_median:>16.4f} '
              f'{avg_pctl:>14.1f}% {p:>19.4f}{sig}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--major-threshold', type=float, default=0.15)
    parser.add_argument('--rolling-window', type=int, default=20)
    parser.add_argument('--fade-lookback', type=int, default=4)
    parser.add_argument('--offsets', default='-12,-8,-6,-4,-2,-1,0')
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

            top_score, _, _ = fade_score(
                df['high'].tolist(), df['slope_high'].tolist(), 'TOP',
                args.rolling_window, args.fade_lookback)
            bot_score, _, _ = fade_score(
                df['low'].tolist(), df['slope_low'].tolist(), 'BOTTOM',
                args.rolling_window, args.fade_lookback)
            top_series[symbol] = top_score
            bot_series[symbol] = bot_score
    finally:
        conn.close()

    print(f'=== Fade-score study: {len(top_series)} ETFs, rolling_window={args.rolling_window}wk, '
          f'fade_lookback={args.fade_lookback}wk, major={args.major_threshold:.0%} zigzag on close ===')

    top_baseline, top_window = collect(top_series, major_tops, offsets)
    report('TOPs (distribution-warning score)', top_baseline, top_window, offsets)

    bot_baseline, bot_window = collect(bot_series, major_bots, offsets)
    report('BOTTOMs (capitulation-exhaustion score)', bot_baseline, bot_window, offsets)


if __name__ == '__main__':
    main()
