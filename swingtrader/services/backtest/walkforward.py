"""Walk-forward span selection + turn-timing audit for CoreEW P20w.

Two questions, deliberately separated:

1. WALK-FORWARD: choose a span in-sample, score it only on unseen data, roll
   forward. The OOS figure is the honest one. IS sweep results are selection
   noise and are never reported as performance.

2. TURN TIMING: does the crossover fire near swing tops and bottoms, or late?
   Measured per event, so n = total crossovers (~149), not 1 compounded path.
   Lateness is in WEEKS between the local swing extreme and the flip:
       exit  (long->cash): weeks AFTER the local high   (lower = better)
       entry (cash->long): weeks AFTER the local low    (lower = better)
   Negative = flipped BEFORE the extreme (early, will miss part of the move).
   This is the statistic behind "I can see it near the tops on the chart".

Both read the PHP series, so the signal is identical to live.
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
SPANS = [5, 10, 15, 20, 30, 50]
SWING = 8        # weeks either side to define a local extreme
LATE_CAP = 8    # flips later than this are "late", not "near the extreme"

FOLDS = [
    ('2016-01-04', '2019-12-31', '2020-01-01', '2021-12-31'),
    ('2016-01-04', '2021-12-31', '2022-01-01', '2023-12-31'),
    ('2016-01-04', '2023-12-31', '2024-01-01', '2026-09-30'),
]


def d(s):
    return date.fromisoformat(s)


def price_map(symbols=SYMS):
    conn = db_module.get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE symbol = ANY(%s)',
                (list(symbols),))
    m = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()
    conn = db_module.get_conn()
    data = db_module.bulk_load_daily(conn, list(m))
    conn.close()
    return {m[t]: data[t] for t in m if t in data}


def mk_pf(s2):
    def pf(sym, dt):
        dd = s2.get(sym)
        if not dd:
            return None
        for i in range(len(dd['dates']) - 1, -1, -1):
            if dd['dates'][i] <= dt:
                return dd['close'][i]
        return None
    return pf


def swing_extremes(weeks, closes, kind):
    """Local extreme index within +/-SWING weeks. kind='high'|'low'."""
    n = len(closes)
    out = {}
    for i in range(SWING, n - SWING):
        w = closes[i - SWING:i + SWING + 1]
        if kind == 'high' and closes[i] == max(w) and closes.count(closes[i]) == 1:
            out[i] = 'high'
        elif kind == 'low' and closes[i] == min(w) and closes.count(closes[i]) == 1:
            out[i] = 'low'
    return out


def turn_timing(span):
    """Lateness in weeks between each flip and the nearest preceding swing."""
    ser = coreew.leg_series(span, SYMS)['series']
    exits, entries = [], []
    detail = []
    for sym, leg in ser.items():
        weeks = [w['week'] for w in leg]
        closes = [w['close'] for w in leg]
        highs = swing_extremes(weeks, closes, 'high')
        lows = swing_extremes(weeks, closes, 'low')
        idx = {w: i for i, w in enumerate(weeks)}
        prev = None
        for w in leg:
            cur = w['long']
            if prev is not None and cur != prev:
                i = idx[w['week']]
                table, kind = (highs, 'exit') if not cur else (lows, 'entry')
                ref = [j for j in table if j <= i and i - j <= LATE_CAP + 4]
                if ref:
                    lag = i - max(ref)
                    (exits if kind == 'exit' else entries).append(lag)
                    detail.append((sym, w['week'], kind, lag, closes[i]))
            prev = cur

    def stat(v):
        if not v:
            return None
        v = sorted(v)
        near = sum(1 for x in v if x <= 3) / len(v) * 100
        return {'n': len(v), 'median': v[len(v) // 2],
                'mean': round(sum(v) / len(v), 1),
                'near_pct': round(near, 1)}
    return stat(exits), stat(entries), detail


def main():
    s2 = price_map()
    print("=" * 78)
    print("WALK-FORWARD SPAN SELECTION  (span chosen in-sample, scored out-of-sample)")
    print("=" * 78)
    chosen = []
    for is_a, is_b, o_a, o_b in FOLDS:
        best, best_stat = None, None
        for sp in SPANS:
            r = coreew.run(sp, SYMS, d(is_a), d(is_b), verbose=False)
            key = r['calmar']
            if best_stat is None or key > best_stat:
                best, best_stat = sp, key
        oos = coreew.run(best, SYMS, d(o_a), d(o_b), verbose=False)
        chosen.append(best)
        print(f"  IS {is_a}..{is_b}  -> picked span {best:>2} "
              f"(IS Calmar {best_stat:.2f})   |   OOS {o_a}..{o_b}: "
              f"ret {oos['total_return_pct']:>8}  dd {oos['max_dd_pct']:>6}  "
              f"calmar {oos['calmar']:>5}")

    from collections import Counter
    c = Counter(chosen)
    print(f"\n  spans picked per fold: {chosen}")
    print(f"  most frequently picked: {c.most_common(1)[0][0]}w "
          f"(appearing in {c.most_common(1)[0][1]}/{len(FOLDS)} folds)")

    print()
    print("=" * 78)
    print("TURN TIMING  (weeks between the flip and the local swing extreme)")
    print("=" * 78)
    for sp in SPANS:
        ex, en, _ = turn_timing(sp)
        if not ex or not en:
            continue
        print(f"  span {sp:>2}w: exits  median {ex['median']:>2}w mean {ex['mean']:>4} "
              f"n={ex['n']:<3} within 3w {ex['near_pct']:>5}%"
              f"   |   entries median {en['median']:>2}w mean {en['mean']:>4} "
              f"n={en['n']:<3} within 3w {en['near_pct']:>5}%")

    print("\n  NOTE: lower = fires closer to the extreme. Exactly 0 = at the extreme.")


if __name__ == '__main__':
    main()