#!/usr/bin/env python3
"""Dump CoreEW (monotone weekly-ratchet gate) daily equity curves.

Uses the SETTLED-week engine in backtest_trio_ew.py (variant S:
settled_week_flags + run_settled_sim), which is what the live gate does: a
decision on any day reads only the last COMPLETED weekly bar (the DB's
Monday-stamped row holds that week's Friday close, so the current week's row is
never read) and fills at the Monday close.
  - portfolio: trio sim (EW among passers, rebalance when the passer set
    changes, 0.05% cost on sells)
  - per-symbol: isolated binary-gate sim on that single ticker (LONG=full, FLAT=cash)

History: until 2026-09-25 this dumped variant B (pos_of + weekly_state), which
reads the current week's Friday close on Monday-Friday (same-week lookahead) and
showed +304.76% / 11% DD. The settled numbers are far lower - see
common/docs/TRADING_STRATEGIES.md (2026-09-25 audit).

Weekly history in the DB only starts 2020-07-27, so before the first settled
weekly bar the book is in cash.

Writes swingtrader/backend/storage/coreew_equity.json (atomic tmp+rename).
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import db as db_module
from backtest_trio_ew import (
    load, settled_week_flags, run_settled_sim,
    CORE, CAPITAL, COST, TABLE_D, TABLE_W, MULT,
)

TS_START = '2019-01-02'  # dashboard window (weekly history starts 2020-07-27; cash before that)

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

        # Settled weekly gate: flags[s][i] uses only bars completed before day i.
        flags = {s: settled_week_flags(dates, weekly[s][0], weekly[s][1], weekly[s][2],
                                       mult, reset)
                 for s in CORE}

        eqS, dts, buys, sells = run_settled_sim(dates, closes, flags, COST)
        per = {}
        for s in CORE:
            # Isolated binary gate on ONE ticker: all-in when LONG, cash when FLAT;
            # trades only when that ticker's flag flips (no rebalancing drag).
            eq_i, _, _, _ = run_settled_sim(dates, {s: closes[s]}, {s: flags[s]}, COST)
            per[s] = [round(float(x), 2) for x in eq_i]

        peak = np.maximum.accumulate(eqS)
        summary = {
            'total_return': float(eqS[-1] / CAPITAL - 1.0),
            'max_drawdown': float(np.min(eqS / peak - 1.0)),
            # trading-day CAGR, same convention as backtest_trio_ew.stats()
            'cagr': float((eqS[-1] / CAPITAL) ** (252.0 / max(1, len(eqS))) - 1.0),
            'trades': int(buys + sells),
        }

        out = {
            'window_start': str(dates[0]),
            'window_end': str(dates[-1]),
            'variant': 'S settled-week gate',
            'mult': mult,
            'reset': reset,
            'cost': COST,
            'dates': [str(d) for d in dts],
            'portfolio': [round(float(x), 2) for x in eqS],
            'summary': summary,
            'symbols': per,
        }
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tmp = out_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(out, f)
        os.replace(tmp, out_path)
        print(f'wrote {out_path}: {len(dts)} days, '
              f'portfolio end ${eqS[-1]:,.0f} at {dts[-1]} | '
              f"return {summary['total_return']:+.2%} maxDD {summary['max_drawdown']:.1%} "
              f"CAGR {summary['cagr']:.1%} legs {summary['trades']}")
    finally:
        conn.close()


if __name__ == '__main__':
    main(out_path=sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)