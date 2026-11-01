"""Regression gate — make a refresh or overhaul FAIL LOUDLY instead of silently
rewriting the performance sheet.

Problem this solves: during the 2026-10-05 price refresh, CoreEW P20w appeared to
jump from +364% to +697%. The cause was NOT the data — it was a lookahead bug in
the new driver (filled on the Tuesday *inside* the decision week). That was fixed
on 2026-10-22, and the published figure then reconciled to within the old
script's sell-only cost bug (~+17pp overstatement). Three anchors are now gated:

  1. SIGNAL FLIPS (exact match required)
     QQQ 45 / VTI 41 / VTV 63 total crossovers, counted through the published
     anchor date 2026-09-25. A pure function of the price data, so any drift in
     the tables moves it. Weeks after the anchor can add flips legitimately and
     are NOT counted — otherwise the gate would fail every week.

  2. BUY-AND-HOLD BENCHMARK (tolerance)
     ~+392% / 16.1% CAGR. Has no signal dependence, and the new engine
     reproduces the published +410.41% / 16.4% within ~4%, which is what
     earned it the right to be an anchor.

  3. P20w ABSOLUTE RETURN (loose tolerance)
     Reconciled 2026-10-22: the pinned convention gives +346.8% / -19.5% DD
     through 2026-10-20. Pinned loosely so a future convention change or engine
     regression fails loudly instead of silently rewriting the sheet.

Usage:
    python3 regression_check.py           # gate; exit 1 on drift
    python3 regression_check.py --report  # print figures without gating
"""
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'mtf'))
sys.path.insert(0, _HERE)

import coreew
import db as db_module
import harness

SYMS = ['QQQ', 'VTI', 'VTV']

# --- pinned anchors ---------------------------------------------------------
PINNED_FLIPS = {'QQQ': 45, 'VTI': 41, 'VTV': 63}
FLIP_ANCHOR = date(2026, 9, 25)          # published-figure anchor; later weeks grow
PINNED_BH = {'total_return_pct': 392.39, 'cagr_pct': 16.12}
BH_TOL = {'total_return_pct': 25.0, 'cagr_pct': 1.5}   # ~6% / ~9% of value
PINNED_P20 = {'total_return_pct': 346.8, 'max_dd_pct': -19.5}
P20_TOL = {'total_return_pct': 20.0, 'max_dd_pct': 2.0}
FULL = (date(2016, 1, 4), date(2026, 10, 20))


def counts_flips(series, anchor=FLIP_ANCHOR):
    out = {}
    cut = anchor.isoformat()
    for sym, leg in series.items():
        prev, n = None, 0
        for w in leg:
            if w['week'][:10] > cut:
                continue
            if prev is not None and w['long'] != prev:
                n += 1
            prev = w['long']
        out[sym] = n
    return out


def price_map(symbols):
    conn = db_module.get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE symbol = ANY(%s)',
                (list(symbols),))
    m = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()
    conn = db_module.get_conn()
    d = db_module.bulk_load_daily(conn, list(m))
    conn.close()
    return {m[t]: d[t] for t in m if t in d}


def price_fn(s2):
    def pf(sym, dt):
        dd = s2.get(sym)
        if not dd:
            return None
        for i in range(len(dd['dates']) - 1, -1, -1):
            if dd['dates'][i] <= dt:
                return dd['close'][i]
        return None
    return pf


def bench_bh(s2):
    pf = price_fn(s2)
    ref = s2['QQQ']
    sim = harness.Sim(price_fn=pf)
    for dt in sorted({x for x in ref['dates'] if FULL[0] <= x <= FULL[1]}):
        if dt.day <= 5 or dt == FULL[0]:
            sim.rebalance(dt, list(s2))
    return sim.finish()


def main(report_only=False):
    print(f"  convention: {harness.CONVENTION}")
    fails = []

    # --- anchor 1: signal flips, exact ---
    series = coreew.leg_series(20, SYMS)['series']
    got = counts_flips(series)
    for sym in SYMS:
        want, have = PINNED_FLIPS[sym], got.get(sym)
        ok = want == have
        print(f"  [{'OK' if ok else 'FAIL'}] flips {sym}: pinned {want}, got {have}")
        if not ok:
            fails.append(f"signal drift {sym}: {want} -> {have} "
                         f"(price data changed the EMA series; re-review the sheet)")

    # --- anchor 2: buy-and-hold benchmark, tolerance ---
    s2 = price_map(SYMS)
    bh = bench_bh(s2)
    for k, tol in BH_TOL.items():
        want, have = PINNED_BH[k], bh[k]
        ok = abs(want - have) <= tol
        print(f"  [{'OK' if ok else 'FAIL'}] B&H {k}: pinned ~{want}, got {have} (tol {tol})")
        if not ok:
            fails.append(f"B&H {k} moved {want} -> {have} (execution engine changed)")

    # --- anchor 3: P20w absolute return, loose ---
    p20 = coreew.run(20, SYMS, FULL[0], FULL[1], verbose=False)
    print(f"  P20w: ret={p20['total_return_pct']} cagr={p20['cagr_pct']} "
          f"dd={p20['max_dd_pct']} calmar={p20['calmar']}")
    for k, tol in P20_TOL.items():
        want, have = PINNED_P20[k], p20[k]
        ok = abs(want - have) <= tol
        print(f"  [{'OK' if ok else 'FAIL'}] P20w {k}: pinned ~{want}, got {have} (tol {tol})")
        if not ok:
            fails.append(f"P20w {k} moved {want} -> {have} "
                         f"(convention or execution changed; re-review the sheet)")

    if report_only:
        print("\n  (report-only; not gating)")
        return 0
    if fails:
        print("\n  REGRESSION FAILED")
        for f in fails:
            print(f"    - {f}")
        return 1
    print("\n  REGRESSION OK — signal, benchmark, and P20w anchors hold")
    return 0


if __name__ == '__main__':
    sys.exit(main('--report' in sys.argv))