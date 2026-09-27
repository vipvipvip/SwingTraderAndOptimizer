#!/usr/bin/env python3
"""Ad-hoc backtest: throttle EG100's all-in/all-out allocation by the
cross-slope-gap's conviction at each entry flip, and compare against plain
EG100, EW trio buy-and-hold, and SPY buy-and-hold.

STRATEGY (one concrete instance of HANDOFF.md's step-4 "corroboration/
quality filter" reframing, not the only possible one):
  - Same EG100 flip series as the live gate (state = index > EMA(span),
    pure crossover) drives WHEN to be in or out -- this script does not
    change the trigger, only the SIZE of the "in" state.
  - On every flip TO LONG, take gap_bot (close-low gap, the BOTTOM-analog
    series from Phase 3) on the flip day, and its percentile against the
    ENTIRE CAUSAL history of gap_bot up to and including that day (same
    baseline definition run_eg_flip_event_study.py already used -- not a
    new methodology). Map percentile -> exposure weight via a linear ramp
    (mirrors backtest_trio_ew.py's sma_gate_exposure 'ramp' mode, same
    shape, different driver): floor below --pctl-low, 1.0 above
    --pctl-high, linear between. That weight is HELD CONSTANT (equal split
    across QQQ/VTI/VTV) until the next flip.
  - On every flip TO CASH: full exit (weight 0), no throttle. Deliberate
    design choice -- EG100's main value is downside protection, so this
    version doesn't second-guess exits, only how hard it leans into entries.
  - Rebalanced to the target weight weekly (drift control, same cadence as
    the live EG100 backtest's `weekly_mask`) or immediately when the target
    weight itself changes.

CAVEAT: full-history, no holdout -- an exploratory look, not the rigorous
holdout-validated backtest AGENTS.md's Backtest section calls for before any
live conversation (that's step 5, still not done). Numbers here answer "does
this shape look promising," not "this is the expected return."

Usage: venv/bin/python3 run_eg_throttle_backtest.py
       [--pctl-low 30] [--pctl-high 70] [--floor 0.25] [--span 100]
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import percentileofscore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utility_scripts'))
import config
from acquire_ohlc import get_conn, load_daily
from eg_index_calc import ema, crossover_state

# AGENTS.md-documented engine constants (not in this folder's config.py --
# that config is scanner-universe/slope-window only; these are the trio
# backtest conventions from swingtrader/services/mtf/config.py, hardcoded
# here rather than cross-imported to avoid a `config` module-name collision
# between the two folders).
COST = 0.0005
CAPITAL = 100000.0


def weekly_boundary_mask(dates):
    """True on the first trading day of each ISO week (same definition as
    backtest_trio_ew.py's weekly_boundary_mask)."""
    mask = np.zeros(len(dates), dtype=bool)
    prev = None
    for i, d in enumerate(dates):
        iso = d.isocalendar()[:2]
        if iso != prev:
            mask[i] = True
            prev = iso
    return mask


def build_throttled_weights(dates, gap_bot, flips, pctl_low, pctl_high, floor):
    """Piecewise-constant target exposure fraction, decided at close of day i
    and HELD FROM i+1 (same causal lag as ema_gate_flags/live). Returns
    (weights, entry_log) where entry_log records what each long entry's
    percentile/weight was, for the printed summary."""
    n = len(dates)
    date_to_idx = {d.isoformat(): i for i, d in enumerate(dates)}
    state_w = np.zeros(n)  # weight in effect AS DECIDED (pre-lag)
    entry_log = []
    cur_w = 0.0
    j = 0  # walks the flip list
    flips_sorted = sorted(flips, key=lambda f: f['date'])
    for i in range(n):
        while j < len(flips_sorted) and date_to_idx.get(flips_sorted[j]['date']) == i:
            fl = flips_sorted[j]
            if fl['to']:
                g = gap_bot[i]
                if np.isnan(g):
                    pctl, w = float('nan'), 1.0  # warmup fallback: no throttle
                else:
                    hist = gap_bot[:i + 1]
                    hist = hist[~np.isnan(hist)]
                    pctl = percentileofscore(hist, g)
                    w = float(np.clip((pctl - pctl_low) / (pctl_high - pctl_low), floor, 1.0))
                cur_w = w
                entry_log.append({'date': fl['date'], 'gap_bot': None if np.isnan(g) else round(float(g), 6),
                                   'percentile': None if np.isnan(pctl) else round(pctl, 1), 'weight': round(w, 3)})
            else:
                cur_w = 0.0
            j += 1
        state_w[i] = cur_w
    lagged = np.concatenate([[0.0], state_w[:-1]])
    return lagged, entry_log


def run_throttled_sim(dates, closes3, weights, cost, rebalance_mask):
    """Equal-split-across-3-legs exposure sim (self-contained; mirrors
    backtest_trio_ew.py's run_exposure_sim, simplified to the fixed-3-leg
    whole-book case EG100 actually is). Rebalances to `weights[i]` whenever
    `rebalance_mask[i]` is True or the target weight changed since
    yesterday; sells down to target before buying up to it so cash never
    goes negative mid-rebalance."""
    syms = list(closes3)
    positions = {s: 0.0 for s in syms}
    cash = CAPITAL
    eq = []
    prev_w = None
    for i in range(len(dates)):
        px = {s: closes3[s][i] for s in syms}
        val = sum(positions[s] * px[s] for s in syms)
        equity = cash + val
        tgt = float(np.clip(weights[i], 0.0, 1.0))
        need_reb = bool(rebalance_mask[i]) or (prev_w is None) or (tgt != prev_w)
        if need_reb and equity > 0:
            target_val = tgt * equity
            if val > target_val:
                excess = val - target_val
                for s in syms:
                    if excess <= 1e-9:
                        break
                    sell_val = min(positions[s] * px[s], excess)
                    if sell_val <= 0:
                        continue
                    sh = sell_val / px[s]
                    cash += sh * px[s] * (1 - cost)
                    positions[s] -= sh
                    excess -= sell_val
            val = sum(positions[s] * px[s] for s in syms)
            equity = cash + val
            target_val = tgt * equity
            if val < target_val:
                per = (target_val - val) / len(syms)
                for s in syms:
                    sh = per / px[s] * (1 - cost)
                    if sh <= 0:
                        continue
                    cash -= sh * px[s]
                    positions[s] += sh
        prev_w = tgt
        val = sum(positions[s] * px[s] for s in syms)
        eq.append(cash + val)
    return np.array(eq)


def stats(eq, label):
    ret = eq[1:] / eq[:-1] - 1.0
    total = eq[-1] / CAPITAL - 1.0
    peak = np.maximum.accumulate(eq)
    dd = float(np.max((peak - eq) / peak))
    cagr = (eq[-1] / CAPITAL) ** (252.0 / max(1, len(eq))) - 1
    sharpe = (np.mean(ret) / np.std(ret) * np.sqrt(252)) if np.std(ret) > 0 else 0.0
    print(f'  {label:<28} return {total*100:>+9.1f}%  CAGR {cagr*100:>+7.2f}%  '
          f'MaxDD {dd*100:>6.1f}%  Sharpe {sharpe:>5.2f}')
    return {'total': total, 'cagr': cagr, 'dd': dd, 'sharpe': sharpe}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pctl-low', type=float, default=30.0)
    ap.add_argument('--pctl-high', type=float, default=70.0)
    ap.add_argument('--floor', type=float, default=0.25)
    ap.add_argument('--span', type=int, default=config.EG_SPAN)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument('--csv', default=os.path.join(here, 'eg100_index_daily.csv'))
    ap.add_argument('--flips', default=os.path.join(here, 'eg100_flips.json'))
    args = ap.parse_args()

    eg_df = pd.read_csv(args.csv, parse_dates=['date'])
    eg_dates = [d.date() for d in eg_df['date']]
    gap_bot = eg_df['gap_bot'].to_numpy()
    with open(args.flips) as f:
        flip_payload = json.load(f)
    flips = flip_payload['flips']
    print(f'=== EG100 throttled-allocation backtest: {len(eg_dates)} bars '
          f'({eg_dates[0]} -> {eg_dates[-1]}), flip source={flip_payload["source"]} ===')
    print(f'  throttle: pctl<{args.pctl_low:g} -> {args.floor:.0%} floor, '
          f'pctl>{args.pctl_high:g} -> 100%, linear between; exits always full-to-cash\n')

    conn = get_conn()
    try:
        legs = {s: load_daily(conn, s) for s in config.EG_LEGS}
        spy = load_daily(conn, 'SPY')
    finally:
        conn.close()

    common = set(eg_dates) & set(spy['date'])
    for s, df in legs.items():
        common &= set(df['date'])
    common = sorted(common)
    idx_eg = {d: i for i, d in enumerate(eg_dates)}
    keep_eg = [idx_eg[d] for d in common]

    gap_bot_c = gap_bot[keep_eg]
    closes3 = {s: legs[s].set_index('date').loc[common, 'close'].to_numpy(dtype=float) for s in config.EG_LEGS}
    spy_close = spy.set_index('date').loc[common, 'close'].to_numpy(dtype=float)
    print(f'  {len(common)} common trading days after aligning EG legs + SPY '
          f'({common[0]} -> {common[-1]})\n')

    reb_mask = weekly_boundary_mask(common)

    # Plain EG100 binary (verified identical to live in the prior session).
    idx_close_c = eg_df.set_index('date').loc[[pd.Timestamp(d) for d in common], 'close'].to_numpy()
    ema_vals = ema(idx_close_c, args.span)
    state, _ = crossover_state(idx_close_c, ema_vals)
    binary_w = np.concatenate([[0.0], state[:-1].astype(float)])
    eq_binary = run_throttled_sim(common, closes3, binary_w, COST, reb_mask)

    # Throttled EG100.
    throttled_w, entry_log = build_throttled_weights(common, gap_bot_c, flips,
                                                       args.pctl_low, args.pctl_high, args.floor)
    eq_throttled = run_throttled_sim(common, closes3, throttled_w, COST, reb_mask)

    # EW trio B&H (same 3 legs, always fully invested, no gate) and SPY B&H
    # -- no cost, matching backtest_trio_ew.py's B&H convention.
    base3 = {s: closes3[s][0] for s in config.EG_LEGS}
    eq_ew_bh = np.array([sum(CAPITAL / len(config.EG_LEGS) * closes3[s][i] / base3[s]
                              for s in config.EG_LEGS) for i in range(len(common))])
    eq_spy_bh = CAPITAL * spy_close / spy_close[0]

    print(f'  window {common[0]} -> {common[-1]} ({len(common)} days), cost {COST*100:.2f}%')
    print('=' * 78)
    r_spy = stats(eq_spy_bh, 'SPY B&H')
    r_ewbh = stats(eq_ew_bh, 'EW trio B&H (QQQ/VTI/VTV)')
    r_bin = stats(eq_binary, 'EG100 (live, binary)')
    r_thr = stats(eq_throttled, f'EG100 throttled ({args.floor:.0%}-100%)')

    n_entries = len(entry_log)
    avg_w = np.mean([e['weight'] for e in entry_log]) if entry_log else float('nan')
    print(f'\n  {n_entries} long entries, avg throttled weight at entry {avg_w:.0%} '
          f'(1.00 = same as plain EG100)')

    def capture(base):
        cap_ret = r_thr["total"] / base["total"] if base["total"] else float('nan')
        cap_cagr = r_thr["cagr"] / base["cagr"] if base["cagr"] else float('nan')
        dd_cut = 1 - r_thr["dd"] / base["dd"] if base["dd"] else float('nan')
        return cap_ret, cap_cagr, dd_cut

    cr, cc, dc = capture(r_bin)
    print(f'\n  Throttled vs plain EG100:   captures {cr*100:.0f}% of total return '
          f'({cc*100:.0f}% of CAGR), drawdown cut {dc*100:.0f}%')
    cr, cc, dc = capture(r_spy)
    print(f'  Throttled vs SPY B&H:       captures {cr*100:.0f}% of total return '
          f'({cc*100:.0f}% of CAGR), drawdown cut {dc*100:.0f}%')
    print(f'\n  NOTE: full-history, in-sample, no holdout -- exploratory, not step-5 rigor.')


if __name__ == '__main__':
    main()
