#!/usr/bin/env python3
"""Repair missing bars in the canonical price tables (tbl_prices_weekly / tbl_prices_daily).

This is a thin wrapper over load_prices.py -- the ONLY writer of those tables -- plus
compute_indicators.py. It exists so the readiness gate (data_readiness.py) and humans
have one entry point for "fill what's missing and recompute atr_stop"; it has no fetch
or write logic of its own, so it cannot drift from the loader.

Each ticker is fetched from its own last stored bar (see load_prices.start_for), only
when it is behind the settled cutoff (load_prices.resume_cutoff, which is the same date
data_readiness expects). A normal repair is therefore a handful of one-bar requests.

    backfill_all_missing.py --timeframes week,day
    backfill_all_missing.py --symbols QRVO,AAPL
    backfill_all_missing.py --dry-run

Before 2026-10-05 this wrote the deprecated tbl_scanner_tickers* tables via
populate_tickers.py, so the gate's self-heal "repaired" tables nothing read and left the
real gap in place.
"""

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import load_prices as lp

NY = ZoneInfo('America/New_York')
TIMEFRAMES = tuple(lp.TABLES)          # ('day', 'week')
MAX_WORKERS = 6                        # SIP throttles hard above this (2026-10-05)
COMPUTE_ARG = {'week': 'prices-weekly', 'day': 'prices-daily'}


def get_trading_calendar(start, end):
    """Sorted NYSE trading dates in [start, end] via Alpaca's calendar (used by the gate)."""
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetCalendarRequest
    tc = TradingClient(API_KEY, SECRET_KEY, paper=True)
    return sorted(c.date for c in tc.get_calendar(GetCalendarRequest(start=start, end=end)))


def _recompute_indicators(timeframes):
    compute_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'compute_indicators.py')
    ok = True
    for tf in timeframes:
        print(f'[BACKFILL] Recomputing atr_stop for {tf}...', flush=True)
        r = subprocess.run([sys.executable, compute_script, '--timeframe', COMPUTE_ARG[tf],
                            '--workers', '4'], capture_output=True, text=True)
        if r.returncode != 0:
            ok = False
            print(f'  compute_indicators {tf} FAILED:\n{r.stderr[-500:]}')
        else:
            tail = r.stdout.strip().splitlines()
            print('  ' + (' | '.join(tail[-2:]) if tail else 'done'))
    return ok


def backfill_timeframes(timeframes, symbols=None, workers=4, dry_run=False, recompute=True):
    """Fill every ticker that is behind the settled cutoff, then recompute atr_stop.

    Returns (ok, per_tf). ok is False on any fetch/write error or failed recompute.
    A ticker with nothing newer upstream (halted) is reported, not an error.
    """
    unknown = [t for t in timeframes if t not in lp.TABLES]
    if unknown:
        raise ValueError(f'unsupported timeframe(s) {unknown}; valid: {sorted(lp.TABLES)}')
    workers = max(1, min(workers, MAX_WORKERS))
    universe = lp.get_universe()
    if symbols:
        want = {s.upper() for s in symbols}
        universe = [u for u in universe if u[1] in want]

    per_tf = {}
    for tf in timeframes:
        table = lp.TABLES[tf]
        cutoff = lp.resume_cutoff(tf)
        frontiers = lp.get_frontiers(table)
        pending = [it for it in universe
                   if not (frontiers.get(it[0]) and frontiers[it[0]] >= cutoff)]
        print(f'\n[BACKFILL] {tf}: cutoff {cutoff} -> {len(pending)} behind, '
              f'{len(universe) - len(pending)} current', flush=True)
        errs, no_new, bars = [], [], 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(lp.work, it, tf, table, dry_run, frontiers.get(it[0]), False)
                    for it in pending]
            for fut in as_completed(futs):
                sym, n, status = fut.result()
                if status == 'ok' or status.startswith('dry-run'):
                    bars += n
                elif status == 'no new data':
                    no_new.append(sym)
                else:
                    errs.append((sym, status))
        print(f'[BACKFILL] {tf}: {bars} bars, {len(no_new)} no-new-data, {len(errs)} errors')
        for s, st in errs[:20]:
            print(f'   ERR {s}: {st}')
        per_tf[tf] = {'behind': len(pending), 'no_new': no_new, 'errors': errs, 'bars': bars}

    ok = not any(r['errors'] for r in per_tf.values())
    if recompute and not dry_run:
        ok = _recompute_indicators(timeframes) and ok
    return ok, per_tf


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--timeframes', default='week,day')
    ap.add_argument('--symbols', default='', help='comma-separated subset (default: all enabled)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    tfs = [t.strip() for t in args.timeframes.split(',') if t.strip()]
    syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()] or None
    ok, _ = backfill_timeframes(tfs, symbols=syms, workers=args.workers, dry_run=args.dry_run)
    print('[BACKFILL] done' + ('' if ok else ' (WITH ERRORS)'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
