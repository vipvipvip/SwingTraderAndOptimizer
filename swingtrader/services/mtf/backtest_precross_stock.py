#!/usr/bin/env python3
"""Stock-leg A/B: ratchet-ATR exit (live baseline) vs +PRE-DOWN warning exit.

Research only. Weekly score (EMA10>SMA40 on the last settled weekly bar), top-N
equal-weight, weekly rebalance. Daily bars mark the book and drive the ratchet.

Baseline exit  = ratchet-ATR, daily source (matches live --exit ratchet-atr
                 --ratchet-atr-src daily): sell when a settled daily close <
                 (highest close since entry) - 2*ATR, ATR from atr_stop.
Variant exit   = ratchet + PRE-DOWN: also flat a held name while its weekly
                 PRE-DOWN run is active (gap closing + accelerating).
Control        = random exit with matched out-of-market fraction.

Survivorship caveat: the universe is today's enabled list, so read the DELTA
against baseline and the random control, not the absolute level.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, bisect
import numpy as np
import pandas as pd

import config
import db as db_module
from backtest_precross_exit import precross_series

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
TOP_N = config.TOP_N
MULT = config.RATCHET_ATR_MULT


def load_all(conn, symbols):
    tids = {}
    for s in symbols:
        t = db_module.get_ticker_id_from_symbol(conn, s)
        if t:
            tids[s] = t
    daily = db_module.bulk_load_daily(conn, list(tids.values()))
    weekly = db_module.bulk_load_weekly(conn, list(tids.values()))
    return tids, daily, weekly


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', required=True)
    ap.add_argument('--top-n', type=int, default=TOP_N)
    ap.add_argument('--start', default='2021-09-01')
    ap.add_argument('--end', default=None)
    ap.add_argument('--eta-max', type=float, default=4)
    ap.add_argument('--trials', type=int, default=100)
    args = ap.parse_args()

    conn = db_module.get_conn()
    try:
        symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
        tids, daily, weekly = load_all(conn, symbols)
        atr_raw = {}
        cur = conn.cursor()
        for s, tid in tids.items():
            cur.execute('SELECT date, atr_stop FROM tbl_prices_daily '
                        'WHERE ticker_id=%s ORDER BY date ASC', (tid,))
            atr_raw[s] = {r[0]: (float(r[1]) if r[1] else 0.0) for r in cur.fetchall()}
        cur.close()
    finally:
        conn.close()

    syms = list(tids.keys())
    dd = {s: [x.toordinal() for x in daily[tids[s]]['dates']] for s in syms}
    ddates = {s: [pd.Timestamp(x) for x in daily[tids[s]]['dates']] for s in syms}
    wdates = {s: [pd.Timestamp(x) for x in weekly[tids[s]]['dates']] for s in syms}
    cl = {s: np.array(daily[tids[s]]['close'], dtype=float) for s in syms}
    op = {s: np.array(daily[tids[s]]['open'], dtype=float) for s in syms}
    atr_stop = {s: np.array([atr_raw[s].get(x, 0.0)
                             for x in daily[tids[s]]['dates']], dtype=float) for s in syms}
    em = {s: weekly[tids[s]]['ema'] for s in syms}
    sm = {s: weekly[tids[s]]['sma'] for s in syms}
    pc = {s: precross_series(weekly[tids[s]]['close'], eta_max=args.eta_max) for s in syms}

    all_d = sorted({d for s in syms for d in ddates[s]})
    all_d = [d for d in all_d if d >= pd.Timestamp(args.start)
             and (args.end is None or d <= pd.Timestamp(args.end))]
    rebal = []
    seen = set()
    for d in all_d:
        wk = d.isocalendar()[:2]
        if wk not in seen:
            seen.add(wk)
            rebal.append(d)
    rset = set(rebal)

    def oi(s, d):
        i = bisect.bisect_left(dd[s], d.toordinal())
        return i if i < len(dd[s]) else None

    def ci(s, d):
        i = bisect.bisect_right(dd[s], d.toordinal()) - 1
        return i if i >= 0 else None

    def svi(s, d):
        cut = d - pd.Timedelta(days=7)
        wdts = wdates[s]
        i = bisect.bisect_right([x.toordinal() for x in wdts], cut.toordinal()) - 1
        return i if i >= 0 else None

    def score_rank(d):
        cand = []
        for s in syms:
            wi = svi(s, d)
            if wi is None or wi < config.WARMUP_BARS:
                continue
            if not (np.isfinite(em[s][wi]) and np.isfinite(sm[s][wi])):
                continue
            if em[s][wi] <= sm[s][wi]:
                continue
            gap = (cl[s][ci(s, d)] if False else weekly[tids[s]]['close'][wi])
            wgap = (weekly[tids[s]]['close'][wi] - sm[s][wi]) / sm[s][wi] * 100
            cand.append((s, wgap))
        cand.sort(key=lambda kv: -kv[1])
        return [s for s, _ in cand[:args.top_n]]

    def sim(mode):
        """mode: 'base' | 'pre' | callable(d,s,wi)->flat?"""
        cash = CAPITAL
        pos = {}   # s -> {sh, entry, peak, ratchet}
        eq = np.empty(len(all_d))
        sell_pre = set()
        for k, d in enumerate(all_d):
            if d in rset:
                sel = score_rank(d)
                sel_set = set(sel)
                # EXIT
                for s in list(pos):
                    pi = pos[s]
                    i = ci(s, d)
                    reason = None
                    if s not in sel_set:
                        reason = 'rot'
                    else:
                        # ratchet (daily source)
                        if i is not None and np.isfinite(atr_stop[s][i]) and atr_stop[s][i] > 0:
                            atr = (cl[s][i] - atr_stop[s][i]) / 2.0
                            pi['peak'] = max(pi.get('peak', pi['entry']), cl[s][i])
                            pi['ratchet'] = max(pi.get('ratchet', 0.0), pi['peak'] - MULT * atr)
                            if cl[s][i] < pi['ratchet']:
                                reason = 'ratchet'
                        # PRE-DOWN overlay
                        if reason is None and mode in ('pre',) :
                            wi = svi(s, d)
                            if wi is not None and pc[s]['pre_down_run'][wi]:
                                reason = 'pre'
                        if reason is None and callable(mode):
                            wi = svi(s, d)
                            if wi is not None and mode(d, s, wi):
                                reason = 'rnd'
                    if reason:
                        i = oi(s, d)
                        if i is None:
                            continue
                        px = op[s][i]
                        cash += pos[s]['sh'] * px * (1 - COST)
                        if reason == 'pre':
                            sell_pre.add(s)
                        del pos[s]
                # RE-ENTRY / entry into selected (skip names just PRE-sold this cycle)
                for s in sel:
                    if s in pos:
                        continue
                    if s in sell_pre:
                        continue
                    i = oi(s, d)
                    if i is None or op[s][i] <= 0:
                        continue
                    eqv = cash
                    for t, p in pos.items():
                        ti = ci(t, d)
                        if ti is not None:
                            eqv += p['sh'] * cl[t][ti]
                    alloc = eqv / max(1, len(sel))
                    sh = alloc / op[s][i]
                    cash -= sh * op[s][i]
                    cash -= sh * op[s][i] * COST
                    pos[s] = {'sh': sh, 'entry': op[s][i], 'peak': op[s][i], 'ratchet': 0.0}
                sell_pre.clear()
            v = cash
            for s, p in pos.items():
                i = ci(s, d)
                if i is not None:
                    v += p['sh'] * cl[s][i]
            eq[k] = v
        peak = np.maximum.accumulate(eq)
        return (eq[-1] / CAPITAL - 1.0,
                float(np.min(eq / peak - 1.0)),
                float((eq[-1] / CAPITAL) ** (252.0 / max(1, len(eq))) - 1.0))

    base = sim('base')
    pre = sim('pre')
    print(f'universe={len(syms)}  top_n={args.top_n}  window={args.start}..{args.end} etaMax={args.eta_max}')
    print(f'BASELINE ratchet     ret {base[0]:+8.1%}  maxDD {base[1]:7.1%}  CAGR {base[2]:+7.1%}')
    print(f'VARIANT +PRE-DOWN    ret {pre[0]:+8.1%}  maxDD {pre[1]:7.1%}  CAGR {pre[2]:+7.1%}')
    print(f'Delta ret {pre[0]-base[0]:+.1%}   Delta maxDD {pre[1]-base[1]:+.1%}')

    # random control with matched flat-fraction: measure fraction of held-weeks
    # a PRE-DOWN name would have been flat, then randomize.
    tot = fl = 0
    for d in rebal:
        for s in syms:
            wi = svi(s, d)
            if wi is None:
                continue
            if np.isfinite(em[s][wi]) and np.isfinite(sm[s][wi]) and em[s][wi] > sm[s][wi]:
                tot += 1
                if pc[s]['pre_down_run'][wi]:
                    fl += 1
    pflat = fl / max(tot, 1)
    rng = np.random.default_rng(11)
    res = np.array([sim(lambda d, s, wi: rng.random() < pflat)[0]
                    for _ in range(args.trials)])
    print(f'\nflat fraction (PRE-DOWN of long-weeks): {pflat:.3f}')
    print(f'random-control {args.trials}x: mean {res.mean():+.1%} '
          f'p5 {np.percentile(res,5):+.1%} p95 {np.percentile(res,95):+.1%}')
    print(f'PRE-DOWN percentile vs random: {(res<pre[0]).mean()*100:.0f}%')


if __name__ == '__main__':
    main()
