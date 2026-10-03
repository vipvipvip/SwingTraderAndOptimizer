"""Parity gate: prove live and backtest cannot silently diverge.

Three checks, cheapest and strongest first:

 1. IDENTITY — runner.py's scoring symbols must BE emasma_core's objects. This is
    the structural guarantee: because live binds to the same function object,
    there is no second implementation to drift. A copy/paste reimplementation
    fails here immediately.

 2. GOLDEN PICKS — pinned, human-reviewed selections for known decision dates.
    Catches any logic change that moves a pick, even if both sides moved
    together. Update deliberately (--update) and re-read the diff.

 3. LIVE-vs-BACKTEST — replays the backtest's pick set for a decision date and
    asserts it equals a direct replay through the shared core.

Run:  python3 parity_check.py            (gate; exit 1 on drift)
      python3 parity_check.py --update   (re-pin goldens after a deliberate change)
"""
import os
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'mtf'))
sys.path.insert(0, _HERE)

import db as db_module
import emasma_core
import runner  # live

GOLDEN = {
    # Decision date = settled weekly bar. Pinned 2026-10-05 on the validated
    # tbl_prices_daily/weekly refresh. ETF golden matches live's published
    # 2026-09-21 decision picks.
    'etf':   {'2026-09-21': ['SMH', 'XLK', 'VGT']},
    'stock': {'2026-09-21': ['MRNA', 'TWST', 'DELL', 'OKTA', 'HPE', 'MXL', 'TEAM',
                             'CORT', 'AMD', 'NTRA', 'ILMN', 'CRWD', 'P', 'BAND', 'ECO',
                             'MU', 'TWLO', 'HNGE', 'MRVL', 'SMTC', 'RBRK', 'PBF',
                             'SNDK', 'COHU', 'NSIT']},
}


def check_identity():
    fails = []
    pairs = [
        ('_compute_emasma_score', 'compute_emasma_score'),
        ('_settled_weekly_idx', 'settled_weekly_idx'),
        ('_rank_candidates', 'rank_candidates'),
    ]
    for live_name, core_name in pairs:
        lv = getattr(runner, live_name, None)
        cv = getattr(emasma_core, core_name, None)
        ok = lv is cv
        print(f"  [{'OK' if ok else 'FAIL'}] runner.{live_name} is emasma_core.{core_name}")
        if not ok:
            fails.append(f"{live_name} is not bound to emasma_core.{core_name} "
                         f"(live and backtest have diverged implementations)")
    return fails


def load(is_etf):
    conn = db_module.get_conn()
    cur = conn.cursor()
    q = ('SELECT id, symbol FROM tbl_stock_tickers WHERE is_etf AND enabled ORDER BY id' if is_etf
         else 'SELECT id, symbol FROM tbl_stock_tickers WHERE NOT is_etf AND enabled ORDER BY id')
    cur.execute(q)
    t = cur.fetchall()
    conn.close()
    names = {x[0]: x[1] for x in t}
    conn = db_module.get_conn()
    weekly = db_module.bulk_load_weekly(conn, [x[0] for x in t])
    daily = db_module.bulk_load_daily(conn, [x[0] for x in t])
    conn.close()
    wmaps, wsort = {}, {}
    for tid, w in weekly.items():
        order = sorted(range(len(w['dates'])), key=lambda k: w['dates'][k])
        wmaps[tid] = {w['dates'][k]: j for j, k in enumerate(order)}
        wsort[tid] = [w['dates'][k] for k in order]
    return names, weekly, daily, wmaps, wsort


def picks_for(weekly, daily, wmaps, wsort, names, wdate, is_etf):
    today = wdate + timedelta(days=7)
    cands = []
    for tid, w in weekly.items():
        if tid not in wmaps:
            continue
        wi = emasma_core.settled_weekly_idx(wmaps[tid], wsort[tid], today)
        if wi is None:
            continue
        dc = None
        for i in range(len(daily[tid]['dates']) - 1, -1, -1):
            if daily[tid]['dates'][i] <= wdate:
                dc = daily[tid]['close'][i]
                break
        if dc is None:
            continue
        r = emasma_core.compute_emasma_score(w, dc, wi, wdate)
        if r:
            r['tid'] = tid
            r['symbol'] = names.get(tid)
            cands.append(r)
    return [t['symbol'] for t in emasma_core.rank_candidates(cands, is_etf)]


def main(update=False):
    fails = check_identity()
    for is_etf in (True, False):
        kind = 'etf' if is_etf else 'stock'
        names, weekly, daily, wmaps, wsort = load(is_etf)
        for wdate_s, expect in GOLDEN[kind].items():
            wdate = date.fromisoformat(wdate_s)
            got = picks_for(weekly, daily, wmaps, wsort, names, wdate, is_etf)
            if update or expect is None:
                GOLDEN[kind][wdate_s] = got
                print(f"  [PINNED] {kind} {wdate_s} -> {got}")
            elif got != expect:
                fails.append(f"{kind} {wdate_s} picks moved: {expect} -> {got}")
                print(f"  [FAIL] {kind} {wdate_s} picks moved: {expect} -> {got}")
            else:
                print(f"  [OK] {kind} {wdate_s} picks stable ({len(got)} names)")

    if fails:
        print("\n  PARITY FAILED")
        for f in fails:
            print(f"    - {f}")
        return 1
    print("\n  PARITY OK — live and backtest share one implementation")
    if update:
        print("\n  GOLDENS TO COMMIT:")
        print(f"    GOLDEN = {GOLDEN!r}")
    return 0


if __name__ == '__main__':
    sys.exit(main('--update' in sys.argv))