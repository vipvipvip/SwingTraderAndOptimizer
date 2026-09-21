#!/usr/bin/env python3
"""Dump CoreEW (variant-B monotone weekly-ratchet gate) daily equity curves.

Reuses the validated backtest engine (backtest_trio_ew.py) verbatim so the
curves served to the Explorer match the +304.76%/11% DD reference exactly:
  - portfolio: variant-B trio sim (EW among passers, weekly rebalance, 0.05% cost)
  - per-symbol: isolated binary-gate sim on that single ticker (LONG=full, FLAT=cash)

Writes swingtrader/backend/storage/coreew_equity.json (atomic tmp+rename).
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import db as db_module
from backtest_trio_ew import (
    load, pos_of, weekly_state, run_sim,
    CORE, CAPITAL, COST, TABLE_D, TABLE_W, MULT,
)

TS_START = '2019-01-02'  # matches the validated +304.76% headline window

DEFAULT_OUT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', 'backend', 'storage', 'coreew_equity.json',
))


def main(out_path=DEFAULT_OUT, mult=MULT, reset=False):
    conn = db_module.get_conn()
    try:
        ts = TS_START
        daily = {s: load(conn, s, TABLE_D, ts) for s in CORE}
        weekly = {s: load(conn, s, TABLE_W, ts) for s in CORE}
        dates = daily[CORE[0]][0]
        for s in CORE:
            if list(daily[s][0]) != list(dates):
                print(f'date mismatch for {s}', file=sys.stderr)
                sys.exit(1)

        closes = {s: daily[s][1] for s in CORE}
        wpos = {s: pos_of(dates, weekly[s][0]) for s in CORE}
        w0 = wpos[CORE[0]]
        reb = np.zeros(len(dates), dtype=bool)
        reb[0] = True
        for i in range(1, len(dates)):
            if w0[i] != w0[i - 1]:
                reb[i] = True

        flags = {}
        for s in CORE:
            d, c, a = weekly[s]
            f, e, st = weekly_state(dates, d, c, a, wpos[s], mult, reset=reset)
            flags[s] = f

        eqB, dts, _, _ = run_sim(dates, closes, flags, reb, COST)
        per = {}
        for s in CORE:
            # Isolated binary-gate on ONE ticker: entry buy on the transition
            # flat->LONG (filled next-day like the backtest), exits keep the
            # position-removal path; no daily rebalancing (no extra cost drag).
            entry_reb = np.zeros(len(dates), dtype=bool)
            prev = False
            for i, long_now in enumerate(flags[s]):
                if long_now and not prev:
                    entry_reb[i] = True
                prev = bool(long_now)
            eq_i, _, _, _ = run_sim(dates, closes, {s: flags[s]}, entry_reb, COST)
            per[s] = [round(float(x), 2) for x in eq_i]

        out = {
            'window_start': str(dates[0]),
            'window_end': str(dates[-1]),
            'mult': mult,
            'reset': reset,
            'cost': COST,
            'dates': [str(d) for d in dts],
            'portfolio': [round(float(x), 2) for x in eqB],
            'symbols': per,
        }
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tmp = out_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(out, f)
        os.replace(tmp, out_path)
        print(f'wrote {out_path}: {len(dts)} days, '
              f'portfolio end ${eqB[-1]:,.0f} at {dts[-1]}')
    finally:
        conn.close()


if __name__ == '__main__':
    main(out_path=sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)