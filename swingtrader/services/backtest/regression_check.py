"""Regression gate — make a refresh or overhaul FAIL LOUDLY instead of silently
rewriting the performance sheet.

Problem this solves: during the 2026-10-05 price refresh, CoreEW P20w appeared to
jump from +364% to +697%. The cause was NOT the data — it was an unpinned fill
convention in the new harness. Two anchors are stable enough to gate on:

  1. SIGNAL FLIPS (exact match required)
     QQQ 45 / VTI 41 / VTV 63 total crossovers from the PHP EMA series. A pure
     function of the price data, so any drift in the tables moves it. Verified
     identical to the pre-refresh baseline, which is what makes it trustworthy.
     Must match EXACTLY — no tolerance.

  2. BUY-AND-HOLD BENCHMARK (tolerance)
     ~+392% / 16.1% CAGR. Has no signal dependence, and the new engine
     reproduces the published +410.41% / 16.4% within ~4%, which is what
     earned it the right to be an anchor.

DELIBERATELY NOT PINNED: P20w absolute figures. The published convention is not
yet identified (see FILL_CONVENTION.md), so pinning an unreconciled number would
replace a reconciled figure with a worse one. They are PRINTED for information
and asserted to be finite/positive only.

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
PINNED_BH = {'total_return_pct': 392.39, 'cagr_pct': 16.12}
BH_TOL = {'total_return_pct': 25.0, 'cagr_pct': 1.5}   # ~6% / ~9% of value
FULL = (date(2016, 1, 4), date(2026, 9, 30))


def counts_flips(series):
    out = {}
    for sym, leg in series.items():
        prev, n = None, 0
        for w in leg:
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

    # --- informational: P20w, not pinnable yet ---
    p20 = coreew.run(20, SYMS, FULL[0], FULL[1], verbose=False)
    print(f"  [INFO] P20w (NOT pinned): ret={p20['total_return_pct']} "
          f"cagr={p20['cagr_pct']} dd={p20['max_dd_pct']} calmar={p20['calmar']}")
    if not (isinstance(p20['total_return_pct'], (int, float))
            and p20['total_return_pct'] > 0):
        fails.append(f"P20w produced a nonsensical figure: {p20}")

    if report_only:
        print("\n  (report-only; not gating)")
        return 0
    if fails:
        print("\n  REGRESSION FAILED")
        for f in fails:
            print(f"    - {f}")
        return 1
    print("\n  REGRESSION OK — signal and benchmark anchors hold")
    print("  (P20w absolute figures remain unreconciled; see FILL_CONVENTION.md)")
    return 0


if __name__ == '__main__':
    sys.exit(main('--report' in sys.argv))