#!/usr/bin/env python3
"""PRE-DOWN / PRE-UP lead signal — canonical Python port of
common/tos/ema_sma_precross_weekly.ts (WIP ThinkScript study).

The study warns of the weekly EMA10/SMA40 crossover a few weeks BEFORE it
happens, using velocity/acceleration of the (scale-free) gap:

    gap = (ema10 - sma40) / sma40
    g1  = EMA3(gap - gap[1])        # velocity of the gap
    g2  = g1 - g1[1]                # acceleration of the gap (2nd derivative)
    eta = -gap / g1                 # weeks until the gap closes at current speed

    PRE-DOWN: gap > 0 (still long), g1 < 0 (closing), g2 < 0 (accelerating),
              eta in (0, etaMax]  -> a down-cross is approaching.
    PRE-UP  : gap < 0 (still flat), g1 > 0 (closing), g2 > 0 (accelerating),
              eta in (0, etaMax]  -> an up-cross is approaching.

Only the FIRST week of a run of flags is marked (preDownOn / preUpOn).

This module is RESEARCH ONLY. It does not touch the live path. The port is
validated against the study's own stated evidence (MRNA flag/cross dates,
2022+ hit rates) before it is trusted for any equity-curve work.

Weekly bars only (no hourly — hourly was retired 2026-10-02). Bars are the
DB's Monday-stamped weekly rows; a decision on Monday D reads the last
COMPLETED week (bar_date + 7 <= D), matching emasma_core.settled_weekly_idx.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np
import pandas as pd

import config
import db as db_module

# Study defaults (ema_sma_precross_weekly.ts input block).
EMA_LEN = 10
SMA_LEN = 40
ETA_MAX = 4
VELOCITY_SPAN = 3


def _ema(values, span):
    """Recursive EMA seeded at values[0], adjust=False (matches the study's
    ExpAverage and db.ema). NaN-free input assumed."""
    s = pd.Series(values, dtype=float)
    return s.ewm(span=span, adjust=False).mean().to_numpy()


def precross_series(closes, ema_len=EMA_LEN, sma_len=SMA_LEN,
                    velocity_span=VELOCITY_SPAN, eta_max=ETA_MAX,
                    require_accel=True):
    """Canonical PRE-DOWN/PRE-UP port. Returns a dict of ndarrays:

        gap      scale-free EMA/SMA gap
        g1       velocity of the gap
        g2       acceleration of the gap
        eta      weeks until gap closes at current speed (NaN if g1 == 0)
        cross_up / cross_down      the crossover itself
        pre_up_run / pre_down_run  the sustained run condition (per week)
        pre_up_on / pre_down_on    FIRST week of each run (the marked signal)

    All series are weekly; index alignment is by position. The caller is
    responsible for only consulting the last SETTLED bar (see settled_idx).
    """
    closes = np.asarray(closes, dtype=float)
    ema_v = _ema(closes, ema_len)
    sma_v = pd.Series(closes).rolling(sma_len).mean().to_numpy()
    gap = (ema_v - sma_v) / sma_v

    gap_prev = np.concatenate([[np.nan], gap[:-1]])
    gap_d = gap - gap_prev
    g1 = _ema(np.where(np.isnan(gap_d), 0.0, gap_d), velocity_span)
    g1_prev = np.concatenate([[np.nan], g1[:-1]])
    g2 = g1 - g1_prev

    with np.errstate(invalid='ignore', divide='ignore'):
        eta = np.where(g1 != 0, -gap / g1, np.nan)

    ema_prev = np.concatenate([[np.nan], ema_v[:-1]])
    sma_prev = np.concatenate([[np.nan], sma_v[:-1]])
    cross_up = (ema_v > sma_v) & (ema_prev <= sma_prev)
    cross_down = (ema_v < sma_v) & (ema_prev >= sma_prev)

    valid = ~(np.isnan(gap) | np.isnan(g1) | np.isnan(g2) | np.isnan(eta))
    accel_ok = (g2 > 0) & (g2 < 0)  # placeholder, refined below
    pre_up_run = (gap < 0) & (g1 > 0) & (eta > 0) & (eta <= eta_max)
    pre_dn_run = (gap > 0) & (g1 < 0) & (eta > 0) & (eta <= eta_max)
    if require_accel:
        pre_up_run = pre_up_run & (g2 > 0)
        pre_dn_run = pre_dn_run & (g2 < 0)
    pre_up_run = pre_up_run & valid
    pre_dn_run = pre_dn_run & valid

    pre_up_on = pre_up_run & ~np.concatenate([[False], pre_up_run[:-1]])
    pre_dn_on = pre_dn_run & ~np.concatenate([[False], pre_dn_run[:-1]])

    return dict(gap=gap, g1=g1, g2=g2, eta=eta,
                cross_up=cross_up, cross_down=cross_down,
                pre_up_run=pre_up_run, pre_down_run=pre_dn_run,
                pre_up_on=pre_up_on, pre_down_on=pre_dn_on)


def settled_idx(dates, target):
    """Position of the last COMPLETED weekly bar for a decision on `target`.
    Mirrors emasma_core.settled_weekly_idx (bar_date + 7 <= target)."""
    cutoff = target - pd.Timedelta(days=7)
    idx = None
    for i, d in enumerate(dates):
        if d <= cutoff:
            idx = i
        else:
            break
    return idx


def _load_weekly(tid):
    conn = db_module.get_conn()
    try:
        w = db_module.bulk_load_weekly(conn, [tid]).get(tid)
    finally:
        conn.close()
    return w


def _validate_mrna():
    """Reproduce the study's MRNA example (its own sanity anchor).

    Claimed in the .ts header:
      flags  2023-02-20, 2023-03-06, 2024-03-04, 2024-07-29, 2025-12-08
      crosses 2023-03-13, 2024-03-25, 2024-08-19, 2025-12-15
    (plus admitted false alarms 2022-08-01, 2025-07-21)."""
    conn = db_module.get_conn()
    try:
        tid = db_module.get_ticker_id_from_symbol(conn, 'MRNA')
    finally:
        conn.close()
    if not tid:
        print('MRNA not found in DB')
        return
    w = _load_weekly(tid)
    if not w:
        print('MRNA has no weekly data')
        return
    r = precross_series(w['close'])
    dates = [pd.Timestamp(d) for d in w['dates']]
    print('\n== MRNA PRE-DOWN flags (study claims 2023-02-20, 2023-03-06, '
          '2024-03-04, 2024-07-29, 2025-12-08) ==')
    for i in np.where(r['pre_down_on'])[0]:
        print(f"  flag {dates[i].date()}  gap={r['gap'][i]:+.4f} "
              f"g1={r['g1'][i]:+.5f} g2={r['g2'][i]:+.5f} eta={r['eta'][i]:.1f}w")
    print('== MRNA DOWN crosses (study claims 2023-03-13, 2024-03-25, '
          '2024-08-19, 2025-12-15) ==')
    for i in np.where(r['cross_down'])[0]:
        print(f"  cross {dates[i].date()}  gap={r['gap'][i]:+.4f}")


def _validate_hitrate(universe_symbols, start='2022-01-01',
                      lead_max_weeks=8, forward_weeks=8):
    """Study's headline: PRE-DOWN flags are followed by a down-cross within 8
    weeks ~77% of the time (random ~18%); PRE-UP ~79% (random ~24%).
    Success = a cross occurs within `forward_weeks` after the flag week."""
    conn = db_module.get_conn()
    tids = {}
    try:
        for sym in universe_symbols:
            t = db_module.get_ticker_id_from_symbol(conn, sym)
            if t:
                tids[sym] = t
        wd = db_module.bulk_load_weekly(conn, list(tids.values()))
    finally:
        conn.close()

    pd_flag = pd_hit = 0
    pu_flag = pu_hit = 0
    for sym, tid in tids.items():
        w = wd.get(tid)
        if not w or len(w['close']) < 60:
            continue
        r = precross_series(w['close'])
        dates = [pd.Timestamp(d) for d in w['dates']]
        start_ts = pd.Timestamp(start)
        n = len(dates)
        for i in range(n):
            if dates[i] < start_ts:
                continue
            for flag_arr, cross_arr, hit_ctr in (
                    (r['pre_down_on'], r['cross_down'], 'dn'),
                    (r['pre_up_on'], r['cross_up'], 'up')):
                if not flag_arr[i]:
                    continue
                hi = min(n, i + forward_weeks + 1)
                hit = bool(cross_arr[i:hi].any())
                if hit_ctr == 'dn':
                    pd_flag += 1
                    pd_hit += hit
                else:
                    pu_flag += 1
                    pu_hit += hit

    print(f'\n== PRE-DOWN hit-rate (flag -> down-cross within {forward_weeks}w, '
          f'from {start}) ==')
    print(f'  flags={pd_flag}  hit={pd_hit}  '
          f'rate={100*pd_hit/max(pd_flag,1):.0f}%   (study: ~77% vs random ~18%)')
    print(f'== PRE-UP hit-rate ==')
    print(f'  flags={pu_flag}  hit={pu_hit}  '
          f'rate={100*pu_hit/max(pu_flag,1):.0f}%   (study: ~79% vs random ~24%)')


def main():
    ap = argparse.ArgumentParser(description='PRE-DOWN/PRE-UP lead-signal port + validation')
    ap.add_argument('--validate-mrna', action='store_true',
                    help="reproduce the study's MRNA flag/cross example")
    ap.add_argument('--validate-hitrate', action='store_true',
                    help="reproduce the study's 2022+ hit-rates")
    ap.add_argument('--symbols', default='MRNA,ELF,CAKE,ANF,CBRL,NTRA,RBRK,P,NKE,DK',
                    help='comma list for the hit-rate validation')
    args = ap.parse_args()

    if args.validate_mrna or (not args.validate_hitrate):
        _validate_mrna()
    if args.validate_hitrate:
        _validate_hitrate([s.strip() for s in args.symbols.split(',') if s.strip()])


if __name__ == '__main__':
    main()
