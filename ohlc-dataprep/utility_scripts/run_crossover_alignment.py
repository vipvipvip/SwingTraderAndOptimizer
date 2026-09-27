"""Driver: align weekly EMA10/SMA40 crossovers against zigzag swing
tops/bottoms for a single ticker (default VTI). Read-only -- no writes.

For each swing TOP, finds the first 'bear' cross (EMA10 below SMA40) at or
after the top and reports the lag in weeks + how much of the drop the
signal missed. Same for BOTTOM -> 'bull' cross.

Usage: venv/bin/python3 run_crossover_alignment.py [--ticker VTI] [--threshold 0.15]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import acquire_ohlc as ao
from swing_calc import find_swings
from ema_sma_calc import compute_ema_sma, detect_crossovers

_EXPECT = {'TOP': 'bear', 'BOTTOM': 'bull'}


def align(pivots, crossovers, closes, ema, sma):
    """Pair each pivot with the first same-direction crossover at/after it.

    Returns list of (pivot, matching_crossover_or_None, pct_missed, stale).
    TOP expects a 'bear' cross, BOTTOM expects a 'bull' cross -- that's the
    signal a trend-following EMA10/SMA40 strategy would act on to exit/enter
    around that swing. pct_missed is the price move already gone by the
    time the crossover confirms (negative for TOP->bear, positive for
    BOTTOM->bull).

    `stale=True` flags pivots where the crossover state was ALREADY in the
    expected direction at the pivot bar (e.g. a lower-high TOP forming while
    EMA10 is still below SMA40 from an earlier bear cross). For those, the
    "nearest same-direction cross" found afterward belongs to some later,
    unrelated pivot -- there is no fresh signal to measure a lag against, so
    reporting a lag there would overstate how late the system is.
    """
    rows = []
    for p in pivots:
        kind = p.kind.replace(' (ongoing)', '')
        want = _EXPECT[kind]
        already_bull = ema[p.index] > sma[p.index]
        state = 'bull' if already_bull else 'bear'
        stale = (state == want)
        match = None if stale else next(
            (c for c in crossovers if c.index >= p.index and c.direction == want), None)
        pct_missed = None if match is None else (closes[match.index] - p.price) / p.price * 100
        rows.append((p, match, pct_missed, stale))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='VTI')
    parser.add_argument('--threshold', type=float, default=0.15,
                         help='zigzag reversal threshold (default 0.15 = 15%%)')
    parser.add_argument('--ema-period', type=int, default=10)
    parser.add_argument('--sma-period', type=int, default=40)
    args = parser.parse_args()

    conn = ao.get_conn()
    try:
        df = ao.load_weekly(conn, args.ticker)
    finally:
        conn.close()

    dates = df['date'].tolist()
    closes = df['close'].tolist()
    ema, sma = compute_ema_sma(closes, args.ema_period, args.sma_period)
    crossovers = detect_crossovers(dates, ema, sma)
    pivots = find_swings(dates, closes, args.threshold)

    print(f'=== {args.ticker} weekly EMA{args.ema_period}/SMA{args.sma_period} crossovers, '
          f'{dates[0]} -> {dates[-1]} ===')
    for c in crossovers:
        print(f'{c.date}  {c.direction.upper():5s} cross  close={closes[c.index]:8.2f}')

    print(f'\n=== Alignment: {args.ticker} {args.threshold:.0%} zigzag swings vs crossover signal ===')
    rows = align(pivots, crossovers, closes, ema, sma)
    for p, match, pct_missed, stale in rows:
        if stale:
            want = _EXPECT[p.kind.replace(' (ongoing)', '')]
            print(f'{p.date}  {p.kind:16s}  close={p.price:8.2f}  -> already {want} at this bar '
                  f'(no fresh cross here; belongs to an earlier/later pivot)')
        elif match is None:
            print(f'{p.date}  {p.kind:16s}  close={p.price:8.2f}  -> no confirming crossover yet')
        else:
            lag_weeks = match.index - p.index
            print(f'{p.date}  {p.kind:16s}  close={p.price:8.2f}  -> {match.direction.upper()} cross '
                  f'{match.date}  (+{lag_weeks} wk, price already moved {pct_missed:+.1f}%)')


if __name__ == '__main__':
    main()
