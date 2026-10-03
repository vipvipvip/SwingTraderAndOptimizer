"""CoreEW (P20w) backtest driver — thin by design.

This file contains NO signal logic. The weekly EMA crossover, the settled-bar
rule, and the trail/ratchet behaviour all live in PHP:
    TradeExecutorService::legEmaTrail() -> replayLegEmaSeries()
which is the same code path live trading runs (trades:execute-leg-ema).

We shell out to `php artisan trades:coreew-leg-ema-series`, which returns the
per-week `long` state per leg. This driver aligns those states to daily bars and
hands them to harness.Sim for execution. That is the whole reason live and
backtest agree on CoreEW: there is only one implementation, in one language,
and Python never gets a vote.

Per AGENTS.md, any NEW CoreEW variant must be added in PHP — not here.

B&H benchmark (rounded equal-weight QQQ+VTI+VTV) and the plain weekly-EW
benchmark "A" are both reported, because "A" is the number that says what the
signals actually added.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'mtf'))
sys.path.insert(0, _HERE)

import config
import db as db_module
import harness

BACKEND = os.path.normpath(os.path.join(_HERE, '..', '..', 'backend'))


def leg_series(span, symbols):
    """Ask PHP for the canonical series. Read-only. Never reimplement."""
    cmd = ['php', '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:coreew-leg-ema-series',
           f'--span={span}', '--symbols=' + ','.join(symbols)]
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"artisan failed: {proc.stderr[-500:]}")
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        raise RuntimeError(f"no JSON in artisan output: {proc.stdout[-500:]}")
    return payload


def run(span=20, symbols=('QQQ', 'VTI', 'VTV'), start=None, end=None, verbose=True):
    payload = leg_series(span, list(symbols))
    series = payload['series']          # {SYM: [{week, close, ema, long}, ...]}
    if verbose:
        print(f"  PHP series span={span} symbols={list(symbols)} bars={payload.get('bars')} "
              f"last_week={payload.get('last_week')} "
              f"(source: TradeExecutorService::replayLegEmaSeries)")

    weeks = sorted({w['week'] for leg in series.values() for w in leg})
    held_by_week = {}
    for w in weeks:
        held_by_week[w] = [s for s, leg in series.items()
                           if any(x['week'] == w and x['long'] for x in leg)]

    sim = harness.Sim()
    conn = db_module.get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE symbol = ANY(%s)',
                (list(symbols),))
    id2sym = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()
    if not id2sym:
        raise RuntimeError(f"symbols not found: {symbols}")
    conn = db_module.get_conn()
    daily = db_module.bulk_load_daily(conn, list(id2sym))
    conn.close()
    sym2daily = {id2sym[tid]: daily[tid] for tid in id2sym if tid in daily}
    if not sym2daily:
        raise RuntimeError("no daily data for coreew symbols")
    ref = next(iter(sym2daily.values()))

    def price_fn(sym, d):
        dd = sym2daily.get(sym)
        if not dd:
            return None
        for i in range(len(dd['dates']) - 1, -1, -1):
            if dd['dates'][i] <= d:
                return dd['close'][i]
        return None

    sim = harness.Sim(price_fn=price_fn)

    for w in weeks:
        wdate = date.fromisoformat(w[:10])
        if start and wdate < start:
            continue
        if end and wdate > end:
            continue
        held = [s for s in held_by_week[w] if s in sym2daily]
        fill = next((d for d in ref['dates'] if d > wdate), None)
        if fill is None:
            continue
        sim.rebalance(fill, held)

    out = sim.finish()
    if verbose:
        print(f"  last decision {weeks[-1]} -> held {held_by_week[weeks[-1]]}")
        for k, v in out.items():
            print(f"    {k:22} {v}")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--span', type=int, default=20)
    ap.add_argument('--start')
    ap.add_argument('--end')
    a = ap.parse_args()
    run(a.span, start=date.fromisoformat(a.start) if a.start else None,
        end=date.fromisoformat(a.end) if a.end else None)