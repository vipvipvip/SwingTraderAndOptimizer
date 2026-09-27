"""Step 3 driver (HANDOFF.md "Plan for next session"): re-anchor the
cross-slope-gap event study to EG100's own historical flips, at DAILY
resolution and TRADING-DAY offsets -- instead of a fresh 15%-zigzag on 28
individual ETFs at weekly resolution (the original Phase 2 test). Reuses the
collect()/report() event-study machinery from run_fade_score_study.py
unchanged -- it only needs a {symbol: score_array} dict and a
{symbol: [pivot-like objects with .index]} dict, which is exactly what
run_eg_index_build.py's cached CSV/flips JSON provide.

Flip mapping onto the existing TOP/BOTTOM framing (flips are EMA-crossover
regime changes, not %-zigzag swing pivots, but the analogy holds: a flip to
cash follows a market weakening the way a TOP does, a flip to long follows a
market strengthening the way a BOTTOM does):
  to=false (exit to cash)  ~ TOP-analog    -> cross_slope_gap(slope_high, slope_close)
  to=true  (re-entry long) ~ BOTTOM-analog -> cross_slope_gap(slope_close, slope_low)

Usage: venv/bin/python3 run_eg_flip_event_study.py
       [--csv ../eg100_index_daily.csv] [--flips ../eg100_flips.json]
       [--offsets -15,-10,-5,-3,-2,-1,0,1,2,3,5,8,12]
"""
import argparse
import json
import os
import sys
from collections import namedtuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_fade_score_study import collect, report

FlipPivot = namedtuple('FlipPivot', ['index', 'date'])


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--csv', default=os.path.join(here, '..', 'eg100_index_daily.csv'))
    ap.add_argument('--flips', default=os.path.join(here, '..', 'eg100_flips.json'))
    ap.add_argument('--offsets', default='-15,-10,-5,-3,-2,-1,0,1,2,3,5,8,12')
    args = ap.parse_args()
    offsets = [int(x) for x in args.offsets.split(',')]

    df = pd.read_csv(args.csv, parse_dates=['date'])
    with open(args.flips) as f:
        flip_payload = json.load(f)
    flips = flip_payload['flips']

    date_to_idx = {d.date().isoformat(): i for i, d in enumerate(df['date'])}

    to_false, to_true = [], []
    for fl in flips:
        idx = date_to_idx.get(fl['date'])
        if idx is None:
            continue
        (to_false if not fl['to'] else to_true).append(FlipPivot(idx, fl['date']))

    print(f'=== EG100 flip event study: {len(df)} daily bars ({df["date"].min().date()} -> '
          f'{df["date"].max().date()}), flip source={flip_payload.get("source", "?")} ===')
    print(f'    {len(to_false)} exit-to-cash flips, {len(to_true)} re-entry flips '
          f'(avg spacing {len(df) / max(1, len(flips)):.1f} trading days)')

    top_baseline, top_window = collect({'EG100': df['gap_top'].to_numpy()},
                                        {'EG100': to_false}, offsets)
    report('EG100 exits (TOP-analog, slope_high - slope_close gap)',
           top_baseline, top_window, offsets)

    bot_baseline, bot_window = collect({'EG100': df['gap_bot'].to_numpy()},
                                        {'EG100': to_true}, offsets)
    report('EG100 re-entries (BOTTOM-analog, slope_close - slope_low gap)',
           bot_baseline, bot_window, offsets)


if __name__ == '__main__':
    main()
