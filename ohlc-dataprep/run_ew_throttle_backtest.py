#!/usr/bin/env python3
"""Ad-hoc backtest: apply the throttle logic to the EW trio directly, with
NO EG100 gate underneath it -- i.e. always at least partially invested in
QQQ/VTI/VTV (never a hard cash-out), with the invested FRACTION continuously
modulated by cross-slope-gap conviction. Distinct from
run_eg_throttle_backtest.py, which kept EG100's binary in/out gate and only
throttled the SIZE of each entry.

STRATEGY:
  - Signal: net_gap[t] = gap_bot[t] - gap_top[t] (bottom-confirmation minus
    top-confirmation, both from the same EG100 synthetic index/slopes built
    in the prior session -- see eg100_index_daily.csv). Not previously
    tested in isolation; Phase 3 only ever looked at gap_top/gap_bot
    separately, each anchored to a specific flip direction. This combines
    them into one continuous "net bullish conviction" dial, the natural
    construction for a gate-free version.
  - Every trading day, percentile-rank net_gap[t] against its own CAUSAL
    history (net_gap[0..t] only -- no lookahead; same discipline as
    run_eg_throttle_backtest.py's entry-throttle, just recomputed daily
    instead of only at flip events, since there's no gate here to anchor
    discrete "entry moments" to).
  - Map percentile -> target exposure via the SAME linear ramp as before
    (floor below --pctl-low, 100% above --pctl-high, linear between).
    Warmup/NaN days default to the FLOOR (conservative choice -- unlike the
    EG100-gated version, there's no binary "gate says it's safe to be long"
    backstopping an undefined signal here, so the fallback errs cautious).
  - Rebalance weekly (same cadence as every other trio backtest in this
    experiment) to control turnover/cost.

CAVEAT: same as run_eg_throttle_backtest.py -- full-history, in-sample, no
holdout. Exploratory, not step-5 rigor.

Usage: venv/bin/python3 run_ew_throttle_backtest.py
       [--pctl-low 30] [--pctl-high 70] [--floor 0.25]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from acquire_ohlc import get_conn, load_daily
from run_eg_throttle_backtest import (
    COST, CAPITAL, weekly_boundary_mask, run_throttled_sim, stats,
)


def causal_percentile(values):
    """Percentile of values[i] within values[0..i] (NaNs dropped), computed
    causally (no future data) -- NaN where values[i] itself is NaN. Matches
    percentileofscore's 'mean' convention (average of strict/non-strict
    rank), done via numpy directly for speed over ~2700 expanding windows."""
    out = np.full(len(values), np.nan)
    hist = np.empty(len(values))
    n = 0
    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        hist[n] = v
        n += 1
        window = hist[:n]
        less = np.sum(window < v)
        less_eq = np.sum(window <= v)
        out[i] = (less + less_eq) / (2.0 * n) * 100
    return out


def build_gate_free_weights(net_gap, pctl_low, pctl_high, floor):
    """Daily target exposure from net_gap's causal percentile, ramped
    floor..1.0, decided at close of day i and HELD FROM i+1 (same lag
    convention as every other gate in this experiment)."""
    pctl = causal_percentile(net_gap)
    w = np.where(np.isnan(pctl), floor,
                 np.clip((pctl - pctl_low) / (pctl_high - pctl_low), floor, 1.0))
    return np.concatenate([[floor], w[:-1]]), pctl


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pctl-low', type=float, default=30.0)
    ap.add_argument('--pctl-high', type=float, default=70.0)
    ap.add_argument('--floor', type=float, default=0.25)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--csv', default=os.path.join(here, 'eg100_index_daily.csv'))
    args = ap.parse_args()

    eg_df = pd.read_csv(args.csv, parse_dates=['date'])
    eg_dates = [d.date() for d in eg_df['date']]
    net_gap = (eg_df['gap_bot'] - eg_df['gap_top']).to_numpy()

    conn = get_conn()
    try:
        legs = {s: load_daily(conn, s) for s in config.EG_LEGS}
        spy = load_daily(conn, 'SPY')
    finally:
        conn.close()

    common = sorted(set(eg_dates) & set(spy['date']) &
                     set.intersection(*[set(df['date']) for df in legs.values()]))
    idx_eg = {d: i for i, d in enumerate(eg_dates)}
    keep_eg = [idx_eg[d] for d in common]
    net_gap_c = net_gap[keep_eg]
    closes3 = {s: legs[s].set_index('date').loc[common, 'close'].to_numpy(dtype=float) for s in config.EG_LEGS}
    spy_close = spy.set_index('date').loc[common, 'close'].to_numpy(dtype=float)

    print(f'=== EW trio, gate-free throttle backtest: {len(common)} days '
          f'({common[0]} -> {common[-1]}) ===')
    print(f'  signal: net_gap = gap_bot - gap_top, causal percentile, ramp '
          f'{args.floor:.0%} @<{args.pctl_low:g}pctl -> 100% @>{args.pctl_high:g}pctl, '
          f'NaN/warmup -> {args.floor:.0%}\n')

    reb_mask = weekly_boundary_mask(common)
    weights, pctl = build_gate_free_weights(net_gap_c, args.pctl_low, args.pctl_high, args.floor)
    eq_throttled = run_throttled_sim(common, closes3, weights, COST, reb_mask)

    base3 = {s: closes3[s][0] for s in config.EG_LEGS}
    eq_ew_bh = np.array([sum(CAPITAL / len(config.EG_LEGS) * closes3[s][i] / base3[s]
                              for s in config.EG_LEGS) for i in range(len(common))])
    eq_spy_bh = CAPITAL * spy_close / spy_close[0]

    print(f'  window {common[0]} -> {common[-1]} ({len(common)} days), cost {COST*100:.2f}%')
    print('=' * 78)
    r_spy = stats(eq_spy_bh, 'SPY B&H')
    r_ewbh = stats(eq_ew_bh, 'EW trio B&H (QQQ/VTI/VTV)')
    r_thr = stats(eq_throttled, f'EW trio gate-free throttle')

    print(f'\n  avg invested fraction: {np.mean(weights)*100:.0f}%  '
          f'(days at floor: {100*np.mean(weights <= args.floor + 1e-9):.0f}%, '
          f'days at 100%: {100*np.mean(weights >= 1.0 - 1e-9):.0f}%)')

    def capture(base):
        cap_ret = r_thr["total"] / base["total"] if base["total"] else float('nan')
        cap_cagr = r_thr["cagr"] / base["cagr"] if base["cagr"] else float('nan')
        dd_cut = 1 - r_thr["dd"] / base["dd"] if base["dd"] else float('nan')
        return cap_ret, cap_cagr, dd_cut

    cr, cc, dc = capture(r_ewbh)
    print(f'\n  Throttled vs EW trio B&H:  captures {cr*100:.0f}% of total return '
          f'({cc*100:.0f}% of CAGR), drawdown cut {dc*100:.0f}%')
    cr, cc, dc = capture(r_spy)
    print(f'  Throttled vs SPY B&H:      captures {cr*100:.0f}% of total return '
          f'({cc*100:.0f}% of CAGR), drawdown cut {dc*100:.0f}%')
    print(f'\n  NOTE: full-history, in-sample, no holdout -- exploratory, not step-5 rigor.')
    print(f'  NOTE: net_gap = gap_bot - gap_top as a continuous dial is a NEW construction '
          f'this session -- Phase 2/3 only ever validated gap_top/gap_bot separately, each '
          f'anchored to a specific event type (near a top / near a bottom), not combined '
          f'and applied continuously like this.')


if __name__ == '__main__':
    main()
