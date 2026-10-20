#!/usr/bin/env python3
"""Equity-curve A/B for the PRE-DOWN lead signal (research only).

Answers: "how would we have fared" if the weekly EMA10/SMA40 strategy ALSO
exited on the PRE-DOWN warning (the first week the gap starts closing AND
accelerating toward a down-cross), vs the current behaviour.

Two legs, measured separately (no live-path change):

  --leg etf    The MTF-ETF book (default VGT,XLE,XLV): equal-weight weekly,
               long while weekly EMA10 > SMA40 (the live emasma rule), rebalanced
               weekly. Baseline = pure weekly hold (the frozen experiment).
               Variant = additionally flat while PRE-DOWN is active.

  --leg stock  A representative stock universe: equal-weight top-N weekly,
               long while EMA10>SMA40. Baseline = ratchet-ATR exit (the live
               stock rule, --ratchet-atr-src daily). Variant = ratchet + PRE-DOWN.

Signals come from precross_series() (the validated .ts port). Weekly bars only.
Decisions use the last SETTLED weekly bar; fills at the next daily open (live
convention: decide on settled Friday close, act the following week). Lookahead
free. COST per side from config.

This is an A/B measurement harness, not a source of expected returns — the
stock universe is today's list (survivorship), so read the DELTA, not the level.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np
import pandas as pd

import config
import db as db_module
from backtest_precross_exit import precross_series

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL


def _load(conn, tids):
    daily = db_module.bulk_load_daily(conn, tids)
    weekly = db_module.bulk_load_weekly(conn, tids)
    return daily, weekly


def _mk_index(daily, tid):
    return {d: i for i, d in enumerate(daily[tid]['dates'])}


def _weekly_dates(weekly, tid):
    return [pd.Timestamp(d) for d in weekly[tid]['dates']]


def _daily_dates(daily, tid):
    return [pd.Timestamp(d) for d in daily[tid]['dates']]


def _last_idx_before(idx_map, dates, target):
    """Last daily index strictly before `target` (fill at next open)."""
    pos = None
    for i, d in enumerate(dates):
        if d < target:
            pos = i
        else:
            break
    return pos


def _settled_weekly_idx(wdates, target):
    """Last weekly bar whose content settled for a decision on `target`
    (bar_date + 7 <= target). Mirrors the live settled-week rule."""
    cutoff = target - pd.Timedelta(days=7)
    pos = None
    for i, d in enumerate(wdates):
        if d <= cutoff:
            pos = i
        else:
            break
    return pos


def run_etf(symbols, exit_on_precross, start, end, eta_max=4,
            require_accel=True):
    conn = db_module.get_conn()
    try:
        tids = {}
        for s in symbols:
            t = db_module.get_ticker_id_from_symbol(conn, s)
            if t:
                tids[s] = t
        daily, weekly = _load(conn, list(tids.values()))
    finally:
        conn.close()

    ddates = {s: _daily_dates(daily, tid) for s, tid in tids.items()}
    wdates = {s: _weekly_dates(weekly, tid) for s, tid in tids.items()}
    closes = {s: daily[tid]['close'] for s, tid in tids.items()}
    opens = {s: daily[tid]['open'] for s, tid in tids.items()}
    ema = {s: weekly[tid]['ema'] for s, tid in tids.items()}
    sma = {s: weekly[tid]['sma'] for s, tid in tids.items()}
    pc = {s: precross_series(weekly[tid]['close'], eta_max=eta_max,
                             require_accel=require_accel)
          for s, tid in tids.items()}

    # Rebalance dates: the first trading day of each ISO week (Mon-ish).
    all_d = sorted({d for s in tids for d in ddates[s]})
    all_d = [d for d in all_d if (start is None or d >= pd.Timestamp(start))
             and (end is None or d <= pd.Timestamp(end))]
    rebal = []
    seen_week = set()
    for d in all_d:
        wk = d.isocalendar()[:2]
        if wk not in seen_week:
            seen_week.add(wk)
            rebal.append(d)

    cash = CAPITAL
    shares = {s: 0.0 for s in tids}
    equity_curve = []
    n_trims = 0

    def mark(d):
        v = cash
        for s in tids:
            xi = _last_idx_before(None, ddates[s], d + pd.Timedelta(days=1))
            if xi is None:
                xi = 0
            v += shares[s] * closes[s][xi]
        return v

    for d in all_d:
        if d in rebal:
            # Determine LONG set from the last settled weekly bar.
            longs = []
            for s in tids:
                wi = _settled_weekly_idx(wdates[s], d)
                if wi is None:
                    continue
                if not (np.isfinite(ema[s][wi]) and np.isfinite(sma[s][wi])):
                    continue
                if ema[s][wi] <= sma[s][wi]:
                    continue
                if exit_on_precross and pc[s]['pre_down_run'][wi]:
                    continue
                longs.append(s)

            # Mark to open, then equal-weight the long set.
            eq = cash
            open_px = {}
            for s in tids:
                xi = _last_idx_before(None, ddates[s], d + pd.Timedelta(days=1))
                if xi is None:
                    continue
                open_px[s] = opens[s][xi]
                eq += shares[s] * open_px[s]
            if longs:
                per = eq / len(longs)
                for s in tids:
                    if s not in open_px:
                        continue
                    target_sh = int(per / open_px[s]) if open_px[s] > 0 else 0
                    if target_sh != shares[s]:
                        delta = target_sh - shares[s]
                        cash -= delta * open_px[s]
                        cash -= abs(delta) * open_px[s] * COST
                        if delta < 0:
                            n_trims += 1
                        shares[s] = target_sh
                # leftover rounding to cash already captured in loop
            else:
                for s in tids:
                    if shares[s] and s in open_px:
                        cash += shares[s] * open_px[s] * (1 - COST)
                        shares[s] = 0
        equity_curve.append((d, mark(d)))

    eq = np.array([v for _, v in equity_curve], dtype=float)
    dts = [d.date() for d, _ in equity_curve]
    if len(eq) == 0:
        return None
    peak = np.maximum.accumulate(eq)
    return dict(
        dates=dts, equity=eq.tolist(),
        total_ret=float(eq[-1] / CAPITAL - 1.0),
        max_dd=float(np.min(eq / peak - 1.0)),
        cagr=float((eq[-1] / CAPITAL) ** (252.0 / max(1, len(eq))) - 1.0),
        trims=n_trims,
    )


def _fmt(tag, r):
    if r is None:
        return f'{tag}: no data'
    return (f'{tag:<28} ret {r["total_ret"]:+8.1%}  maxDD {r["max_dd"]:7.1%}  '
            f'CAGR {r["cagr"]:+7.1%}  rebalances {r["trims"]}')


def main():
    ap = argparse.ArgumentParser(description='PRE-DOWN equity A/B (research)')
    ap.add_argument('--leg', choices=['etf', 'stock'], default='etf')
    ap.add_argument('--symbols', default=None,
                    help='comma list (default: VGT,XLE,XLV for etf leg)')
    ap.add_argument('--start', default='2021-09-01')
    ap.add_argument('--end', default=None)
    ap.add_argument('--eta-max', type=float, default=4)
    ap.add_argument('--no-accel', action='store_true')
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()

    if args.leg == 'etf':
        symbols = (args.symbols or 'VGT,XLE,XLV').split(',')
    else:
        symbols = (args.symbols or '').split(',')
        if not symbols or symbols == ['']:
            print('stock leg needs --symbols (representative list)')
            return

    symbols = [s.strip() for s in symbols if s.strip()]
    ra = not args.no_accel
    print(f'leg={args.leg} symbols={symbols} window={args.start}..{args.end} '
          f'etaMax={args.eta_max} requireAccel={ra}')

    base = run_etf(symbols, False, args.start, args.end,
                   eta_max=args.eta_max, require_accel=ra)
    var = run_etf(symbols, True, args.start, args.end,
                  eta_max=args.eta_max, require_accel=ra)
    print()
    print(_fmt('BASELINE (weekly hold)', base))
    print(_fmt('VARIANT (+PRE-DOWN exit)', var))
    if base and var:
        print(f'\nDelta return: {var["total_ret"]-base["total_ret"]:+.1%}   '
              f'Delta maxDD: {var["max_dd"]-base["max_dd"]:+.1%}')

    if args.detail and base and var:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data',
                           f'precross_equity_{args.leg}.json')
        import json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w') as f:
            json.dump({'baseline': base, 'variant': var,
                       'symbols': symbols, 'eta_max': args.eta_max,
                       'require_accel': ra}, f)
        print(f'wrote {out}')


if __name__ == '__main__':
    main()
