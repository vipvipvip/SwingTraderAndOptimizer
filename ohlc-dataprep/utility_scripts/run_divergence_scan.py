"""Driver: test the divergence hypothesis from HANDOFF.md -- price makes a
new swing extreme but the corresponding OHLC slope does NOT confirm it
(weaker momentum despite the new high/low). Same idea as classic MACD/RSI
divergence, applied to the high/low price series and their own
slope_high/slope_low columns rather than a derived oscillator on close.

For each MAJOR pivot (default 15% zigzag on weekly close -- the tops/bottoms
already found via swing_calc), takes the two most recent MINOR pivots
(default 5% zigzag) of the matching extreme series bracketing it -- the
swing high right at/before the top and the one before that, for TOPs; same
for BOTTOMs with swing lows -- and checks whether momentum diverged between
them.

Also reports the BASELINE (null) divergence rate across ALL consecutive
minor-pivot pairs in the full history, not just the ones near a major
pivot. If divergence is just as common at random minor swings, it isn't a
useful signal -- that comparison is the actual test of the hypothesis, not
just whether divergence "shows up" near tops/bottoms.

Usage: venv/bin/python3 run_divergence_scan.py [--ticker VTI]
       [--major-threshold 0.15] [--minor-threshold 0.05] [--max-lookback-weeks 52]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import acquire_ohlc as ao
from swing_calc import find_swings
from divergence_calc import check_divergence


def build_pairs(minor_pivots):
    """Consecutive (prior, latest) pairs from a same-kind pivot list."""
    return list(zip(minor_pivots[:-1], minor_pivots[1:]))


def scan_side(major_pivots, minor_pivots, df, price_col, slope_col, kind, max_lookback_weeks):
    """Returns (near_major rows, baseline divergences).

    For "latest" we read price_col/slope_col directly at the major pivot's
    own index rather than waiting for a separately zigzag-confirmed minor
    pivot there: a minor (5%) zigzag can only confirm a peak/trough AFTER it
    sees the reversal, so its confirmation date always lags the actual
    extreme -- sometimes past the major pivot's own date. Reading the raw
    value at the major pivot's index sidesteps that lag entirely and is
    exactly what a trader looking at the chart in hindsight would compare.
    "prior" is still the last zigzag-confirmed minor pivot strictly before
    the major pivot -- that's a genuine, distinct earlier swing extreme.

    near_major rows: list of (major_pivot, prior_minor, result) where result
    is a Divergence, or the string 'too_far'/'no_prior' when no valid
    comparison exists.
    """
    near_major = []
    for mp in major_pivots:
        prior_candidates = [p for p in minor_pivots if p.index < mp.index]
        if not prior_candidates:
            near_major.append((mp, None, 'no_prior'))
            continue
        prior = prior_candidates[-1]
        if mp.index - prior.index > max_lookback_weeks:
            near_major.append((mp, prior, 'too_far'))
            continue
        prior_tuple = (prior.date, prior.price, df[slope_col].iloc[prior.index])
        latest_tuple = (mp.date, df[price_col].iloc[mp.index], df[slope_col].iloc[mp.index])
        div = check_divergence(prior_tuple, latest_tuple, kind)
        near_major.append((mp, prior, div))

    baseline = []
    for prior, latest in build_pairs(minor_pivots):
        prior_tuple = (prior.date, prior.price, df[slope_col].iloc[prior.index])
        latest_tuple = (latest.date, latest.price, df[slope_col].iloc[latest.index])
        baseline.append(check_divergence(prior_tuple, latest_tuple, kind))
    return near_major, baseline


def summarize(divergences):
    applicable = [d for d in divergences if d.diverges is not None]
    if not applicable:
        return 0, 0
    return sum(1 for d in applicable if d.diverges), len(applicable)


def report_row(mp, prior, result, slope_name):
    if result in ('too_far', 'no_prior'):
        reason = 'no comparable prior minor swing within lookback window' \
            if result == 'too_far' else 'no prior minor swing found'
        print(f'{mp.date}  major {mp.kind:8s} close={mp.price:8.2f}  -> {reason}')
        return
    div = result
    if div.diverges is True:
        tag = 'DIVERGES (bearish)' if slope_name == 'slope_high' else 'DIVERGES (bullish)'
    elif div.diverges is False:
        tag = 'confirms (no divergence)'
    else:
        tag = 'n/a (no new price extreme between these two swings)'
    print(f'{mp.date}  major {mp.kind:8s} close={mp.price:8.2f}  minor swings: '
          f'{div.prior_date} price={div.prior_price:.2f} {slope_name}={div.prior_slope:+.2f}  ->  '
          f'{div.latest_date} price={div.latest_price:.2f} {slope_name}={div.latest_slope:+.2f}   [{tag}]')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='VTI')
    parser.add_argument('--major-threshold', type=float, default=0.15)
    parser.add_argument('--minor-threshold', type=float, default=0.05)
    parser.add_argument('--max-lookback-weeks', type=int, default=52)
    args = parser.parse_args()

    conn = ao.get_conn()
    try:
        df = ao.load_weekly_with_slopes(conn, args.ticker)
    finally:
        conn.close()

    dates = df['date'].tolist()

    major = find_swings(dates, df['close'].tolist(), args.major_threshold)
    major_confirmed = [p for p in major if '(ongoing)' not in p.kind]
    major_tops = [p for p in major_confirmed if p.kind == 'TOP']
    major_bottoms = [p for p in major_confirmed if p.kind == 'BOTTOM']

    minor_high = [p for p in find_swings(dates, df['high'].tolist(), args.minor_threshold)
                  if p.kind.startswith('TOP')]
    minor_low = [p for p in find_swings(dates, df['low'].tolist(), args.minor_threshold)
                 if p.kind.startswith('BOTTOM')]

    print(f'=== {args.ticker}: momentum-divergence check ===')
    print(f'major pivots: {args.major_threshold:.0%} zigzag on weekly close '
          f'({len(major_tops)} tops, {len(major_bottoms)} bottoms)')
    print(f'minor pivots: {args.minor_threshold:.0%} zigzag on weekly high/low '
          f'({len(minor_high)} high-pivots, {len(minor_low)} low-pivots)\n')

    print('--- TOPs: does slope_high fail to confirm the swing high leading into each major top? ---')
    near_major_top, baseline_top = scan_side(
        major_tops, minor_high, df, 'high', 'slope_high', 'TOP', args.max_lookback_weeks)
    for mp, prior, result in near_major_top:
        report_row(mp, prior, result, 'slope_high')
    n_div, n_app = summarize(baseline_top)
    hit_rate = f'{n_div}/{n_app} ({n_div / n_app * 100:.0f}%)' if n_app else 'n/a'
    print(f'\nBaseline across ALL {len(minor_high)} minor high-pivots (not just near major tops): '
          f'{hit_rate} showed non-confirming slope_high on a new high')

    print('\n--- BOTTOMs: does slope_low fail to confirm the swing low leading into each major bottom? ---')
    near_major_bot, baseline_bot = scan_side(
        major_bottoms, minor_low, df, 'low', 'slope_low', 'BOTTOM', args.max_lookback_weeks)
    for mp, prior, result in near_major_bot:
        report_row(mp, prior, result, 'slope_low')
    n_div, n_app = summarize(baseline_bot)
    hit_rate = f'{n_div}/{n_app} ({n_div / n_app * 100:.0f}%)' if n_app else 'n/a'
    print(f'\nBaseline across ALL {len(minor_low)} minor low-pivots (not just near major bottoms): '
          f'{hit_rate} showed non-confirming slope_low on a new low')


if __name__ == '__main__':
    main()
