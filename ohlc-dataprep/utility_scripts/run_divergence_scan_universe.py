"""Driver: run the momentum-divergence check (see run_divergence_scan.py)
across the full ETF universe (config.TICKERS) and pool the results, instead
of eyeballing one ticker at a time. VTI/QQQ/VTV alone only offer ~5-8
independent major swings (they're highly correlated broad-market ETFs);
pooling across sector/style/bond/international ETFs gives more genuinely
independent events to test the divergence hypothesis against, plus enough
counts to run an actual significance test (Fisher's exact) instead of
eyeballing small percentages.

Usage: venv/bin/python3 run_divergence_scan_universe.py
       [--major-threshold 0.15] [--minor-threshold 0.05] [--max-lookback-weeks 52]
"""
import argparse
import os
import sys

from scipy.stats import fisher_exact

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import acquire_ohlc as ao
from swing_calc import find_swings
from run_divergence_scan import scan_side, summarize


def analyze_ticker(df, major_threshold, minor_threshold, max_lookback_weeks):
    dates = df['date'].tolist()

    major = find_swings(dates, df['close'].tolist(), major_threshold)
    major_confirmed = [p for p in major if '(ongoing)' not in p.kind]
    major_tops = [p for p in major_confirmed if p.kind == 'TOP']
    major_bottoms = [p for p in major_confirmed if p.kind == 'BOTTOM']

    minor_high = [p for p in find_swings(dates, df['high'].tolist(), minor_threshold)
                  if p.kind.startswith('TOP')]
    minor_low = [p for p in find_swings(dates, df['low'].tolist(), minor_threshold)
                 if p.kind.startswith('BOTTOM')]

    near_major_top, baseline_top = scan_side(
        major_tops, minor_high, df, 'high', 'slope_high', 'TOP', max_lookback_weeks)
    near_major_bot, baseline_bot = scan_side(
        major_bottoms, minor_low, df, 'low', 'slope_low', 'BOTTOM', max_lookback_weeks)

    return {
        'n_major_tops': len(major_tops), 'n_major_bottoms': len(major_bottoms),
        'near_major_top': near_major_top, 'baseline_top': baseline_top,
        'near_major_bot': near_major_bot, 'baseline_bot': baseline_bot,
    }


def near_major_counts(near_major_rows):
    """(diverged, applicable) among the major-pivot-adjacent comparisons."""
    applicable = [r for _, _, r in near_major_rows
                  if r not in ('too_far', 'no_prior') and r.diverges is not None]
    return sum(1 for r in applicable if r.diverges), len(applicable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--major-threshold', type=float, default=0.15)
    parser.add_argument('--minor-threshold', type=float, default=0.05)
    parser.add_argument('--max-lookback-weeks', type=int, default=52)
    args = parser.parse_args()

    conn = ao.get_conn()
    try:
        per_ticker = {}
        for symbol in config.TICKERS:
            df = ao.load_weekly_with_slopes(conn, symbol)
            if df.empty or df[config.SLOPE_COLUMNS].isna().all(axis=None):
                print(f'{symbol}: no slope data, skipping')
                continue
            per_ticker[symbol] = analyze_ticker(
                df, args.major_threshold, args.minor_threshold, args.max_lookback_weeks)
    finally:
        conn.close()

    print(f'=== Universe-wide momentum-divergence check ({len(per_ticker)} ETFs) ===')
    print(f'major={args.major_threshold:.0%} zigzag on close, '
          f'minor={args.minor_threshold:.0%} zigzag on high/low, '
          f'max_lookback={args.max_lookback_weeks}wk\n')

    header = f'{"ticker":6s} {"tops":>5s} {"top_div/test":>13s} {"base_div/app":>13s}   ' \
             f'{"bots":>5s} {"bot_div/test":>13s} {"base_div/app":>13s}'
    print(header)

    tot_top_div = tot_top_app = tot_top_base_div = tot_top_base_app = 0
    tot_bot_div = tot_bot_app = tot_bot_base_div = tot_bot_base_app = 0

    for symbol, r in per_ticker.items():
        top_div, top_app = near_major_counts(r['near_major_top'])
        top_base_div, top_base_app = summarize(r['baseline_top'])
        bot_div, bot_app = near_major_counts(r['near_major_bot'])
        bot_base_div, bot_base_app = summarize(r['baseline_bot'])

        print(f'{symbol:6s} {r["n_major_tops"]:5d} {f"{top_div}/{top_app}":>13s} '
              f'{f"{top_base_div}/{top_base_app}":>13s}   '
              f'{r["n_major_bottoms"]:5d} {f"{bot_div}/{bot_app}":>13s} '
              f'{f"{bot_base_div}/{bot_base_app}":>13s}')

        tot_top_div += top_div; tot_top_app += top_app
        tot_top_base_div += top_base_div; tot_top_base_app += top_base_app
        tot_bot_div += bot_div; tot_bot_app += bot_app
        tot_bot_base_div += bot_base_div; tot_bot_base_app += bot_base_app

    def pooled_report(label, div, app, base_div, base_app):
        rate = div / app * 100 if app else 0.0
        base_rate = base_div / base_app * 100 if base_app else 0.0
        print(f'\n{label}: near-major-pivot divergence rate = {div}/{app} ({rate:.0f}%), '
              f'baseline rate = {base_div}/{base_app} ({base_rate:.0f}%)')
        if app and base_app and (app - div) >= 0 and (base_app - base_div) >= 0:
            table = [[div, app - div], [base_div, base_app - base_div]]
            odds_ratio, p_value = fisher_exact(table)
            print(f'  Fisher exact test vs baseline: odds ratio={odds_ratio:.2f}, p={p_value:.3f}'
                  + ('  -> significant at p<0.05' if p_value < 0.05 else '  -> NOT significant at p<0.05'))
        else:
            print('  not enough data for a significance test')

    print()
    pooled_report('TOPs (slope_high divergence)', tot_top_div, tot_top_app, tot_top_base_div, tot_top_base_app)
    pooled_report('BOTTOMs (slope_low divergence)', tot_bot_div, tot_bot_app, tot_bot_base_div, tot_bot_base_app)


if __name__ == '__main__':
    main()
