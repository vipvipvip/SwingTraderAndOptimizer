#!/usr/bin/env python3
"""Step 1+2 driver (HANDOFF.md "Plan for next session"): build the synthetic
EG100 index (QQQ/VTI/VTV equal-weight, daily-rebalanced, vs its own EMA
span), verify the close/EMA/flip series against the live gate's ground
truth, compute OHLC slopes + cross-slope gap on top of it, cache to CSV +
a flips JSON so downstream analysis doesn't need DB/PHP access every run.

Usage: venv/bin/python3 run_eg_index_build.py [--span 100] [--window 10]
       [--out eg100_index_daily.csv] [--flips-out eg100_flips.json]
       [--skip-verify]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utility_scripts'))
import config
from acquire_ohlc import get_conn
from slope_calc import add_ohlc_slopes
from eg_index_calc import build_eg_index, ema, crossover_state
from eg_index_acquire import load_eg_legs, fetch_live_flip_ground_truth
from cross_slope_calc import cross_slope_gap


def verify_against_live(idx_df, dates, span, ema_vals, py_flips, ground_truth):
    last_idx = idx_df['close'].iloc[-1]
    last_ema = ema_vals[-1]
    gt_idx = float(ground_truth['index'])
    gt_ema = float(ground_truth['ema'])
    idx_ok = abs(last_idx - gt_idx) < 1e-6
    ema_ok = abs(last_ema - gt_ema) < 1e-6
    print(f'  index: python={last_idx:.6f} php={gt_idx:.6f} '
          f'{"OK" if idx_ok else "MISMATCH"}')
    print(f'  ema{span}: python={last_ema:.6f} php={gt_ema:.6f} '
          f'{"OK" if ema_ok else "MISMATCH"}')

    gt_flips = [{'date': f['date'], 'to': bool(f['to'])} for f in ground_truth['flips']]
    flips_ok = py_flips == gt_flips
    print(f'  flips: python={len(py_flips)} php={len(gt_flips)} '
          f'{"OK" if flips_ok else "MISMATCH"}')
    if not flips_ok:
        for i, (p, g) in enumerate(zip(py_flips, gt_flips)):
            if p != g:
                print(f'    first divergence at flip index {i}: python={p} php={g}')
                break
        if len(py_flips) != len(gt_flips):
            print(f'    length mismatch: python has {len(py_flips)}, php has {len(gt_flips)}')

    if not (idx_ok and ema_ok and flips_ok):
        raise SystemExit(
            '\nEG100 index/EMA/flip parity check FAILED -- the close-index '
            'construction has drifted from the live gate. Fix before trusting '
            'anything built on top of this (slopes, cross-slope gap, event study).')
    print('  PARITY OK (index/EMA to 1e-6, flip list exact match)')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--span', type=int, default=config.EG_SPAN)
    ap.add_argument('--window', type=int, default=config.SLOPE_WINDOW['daily'])
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--out', default=os.path.join(here, 'eg100_index_daily.csv'))
    ap.add_argument('--flips-out', default=os.path.join(here, 'eg100_flips.json'))
    ap.add_argument('--skip-verify', action='store_true',
                     help='skip the read-only PHP ground-truth check (flips '
                          'written are then UNVERIFIED python output)')
    args = ap.parse_args()

    conn = get_conn()
    try:
        legs = load_eg_legs(conn)
    finally:
        conn.close()

    for s, df in legs.items():
        print(f'  {s}: {len(df)} settled daily bars, {df["date"].min()} -> {df["date"].max()}')

    idx_df = build_eg_index(legs)
    dates = idx_df['date'].tolist()
    print(f'\n  synthetic EG index: {len(idx_df)} bars, {dates[0]} -> {dates[-1]}')

    bad = idx_df[(idx_df['high'] < idx_df['close'] - 1e-12) |
                 (idx_df['close'] < idx_df['low'] - 1e-12)]
    if len(bad):
        raise SystemExit(f'order-preservation violated on {len(bad)} rows -- construction bug')
    print('  order check (high >= close >= low, every row): OK')

    ema_vals = ema(idx_df['close'].to_numpy(), args.span)
    _, py_flips_raw = crossover_state(idx_df['close'].to_numpy(), ema_vals)
    py_flips = [{'date': dates[i].isoformat(), 'to': bool(to)} for i, to in py_flips_raw]

    if not args.skip_verify:
        print(f'\n  verifying against live gate (span={args.span})...')
        ground_truth = fetch_live_flip_ground_truth(args.span)
        verify_against_live(idx_df, dates, args.span, ema_vals, py_flips, ground_truth)
        flips_out, flips_source = ground_truth['flips'], 'php-ground-truth'
    else:
        print('\n  SKIPPED live parity check (--skip-verify) -- flips below are UNVERIFIED python output')
        flips_out, flips_source = py_flips, 'python-unverified'

    with open(args.flips_out, 'w') as f:
        json.dump({'source': flips_source, 'span': args.span, 'flips': flips_out}, f, indent=2)
    print(f'  wrote {args.flips_out} ({len(flips_out)} flips, source={flips_source})')

    slopes_df = add_ohlc_slopes(idx_df, args.window)
    slopes_df['gap_top'] = cross_slope_gap(slopes_df['slope_high'], slopes_df['slope_close'])
    slopes_df['gap_bot'] = cross_slope_gap(slopes_df['slope_close'], slopes_df['slope_low'])

    slopes_df.to_csv(args.out, index=False)
    print(f'  wrote {args.out} ({len(slopes_df)} rows, window={args.window})')


if __name__ == '__main__':
    main()
