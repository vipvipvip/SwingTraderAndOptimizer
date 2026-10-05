#!/usr/bin/env python3
"""Incremental backfill for the canonical price tables.

Why this exists (2026-10-05): on Monday the 10:25 gate skipped both legs because
runner.py was counting CALENDAR days, not trading sessions. The data was never the
problem -- Friday 2026-10-02 was the correct last settled bar before Monday. Chasing it
anyway meant running load_prices.py across all 1,453 tickers, and because that loader
starts every pending ticker at 2016, a one-day gap turned into ~1,453 requests pulling
~2,650 bars each to insert ONE row. Six minutes, and the SIP feed throttled us from
12.7/s down to 1.2/s.

This script pulls ONLY the missing window: per ticker, start = that ticker's own
frontier + 1 day. A one-day catch-up is one bar per ticker in a tiny response.

Write semantics are NOT reimplemented -- fetch/upsert/retry are imported from
load_prices.py, the only writer of tbl_prices_daily / tbl_prices_weekly. This is a
narrower *reader/window* of the same pipeline, not a second way to write those tables.

Usage:
    backfill_prices_incremental.py --tf day            # pull everything missing today
    backfill_prices_incremental.py --tf both --dry-run
    backfill_prices_incremental.py --symbols QRVO,AAPL
    backfill_prices_incremental.py --tf day --report-only

--report-only prints what is behind and from which frontier, and fetches nothing. Use it
first: on a healthy box it should say "0 tickers behind", which means you do NOT need to
run a backfill at all.
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import load_prices as lp  # noqa: E402  (needs the sys.path insert above)


def behind(table, cutoff, universe, report_only=False):
    """Split the universe into (pending, n_current) using one grouped query."""
    c = lp.get_db_conn()
    try:
        with c.cursor() as cur:
            cur.execute(f'SELECT ticker_id, max(date) FROM {table} GROUP BY ticker_id')
            frontier = {r[0]: r[1] for r in cur.fetchall()}
    finally:
        c.close()
    pending = [it for it in universe
               if not (frontier.get(it[0]) and frontier[it[0]] >= cutoff)]
    for tid, sym in pending:
        f = frontier.get(tid)
        gap = (cutoff - f).days if f else None
        print(f'  behind: {sym:<8} frontier={f} '
              f'{"full history" if f is None else f"gap={gap}d"}')
    return pending, len(universe) - len(pending)


def pull_one(item, tf_name, table, dry_run):
    """Fetch just this ticker's missing window and upsert."""
    tid, sym = item
    c = lp.get_db_conn()
    try:
        with c.cursor() as cur:
            cur.execute(f'SELECT max(date) FROM {table} WHERE ticker_id=%s', (tid,))
            row = cur.fetchone()
    finally:
        c.close()
    frontier = row[0] if row else None
    # THE point of this script: start one day past this ticker's own frontier, so the
    # response holds only what is missing instead of the whole 2016+ history.
    start = (frontier + timedelta(days=1)) if frontier else None
    data, err = lp.fetch_with_retry(sym, tf_name, start)
    if err:
        return sym, 0, err
    # load_prices.fetch() is single-symbol, so it returns a plain list of bar tuples.
    rows = data or []
    if not rows:
        return sym, 0, 'no new data'
    if dry_run:
        return sym, len(rows), f'dry-run {rows[0][0]}..{rows[-1][0]}'
    try:
        return sym, lp.upsert(tid, table, rows), 'ok'
    except Exception as e:
        lp.conn().rollback()
        return sym, 0, f'write failed: {str(e)[:120]}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('Usage:')[0])
    ap.add_argument('--tf', choices=['day', 'week', 'both'], default='both')
    ap.add_argument('--symbols', help='comma-separated subset')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--report-only', action='store_true',
                    help='list what is behind, fetch nothing')
    ap.add_argument('--dry-run', action='store_true',
                    help='fetch and report, write nothing')
    args = ap.parse_args()

    universe = lp.get_universe()
    if args.symbols:
        want = {s.strip().upper() for s in args.symbols.split(',') if s.strip()}
        universe = [u for u in universe if u[1] in want]
    tfs = ['day', 'week'] if args.tf == 'both' else [args.tf]

    mode = 'REPORT-ONLY' if args.report_only else ('DRY-RUN' if args.dry_run else 'LIVE')
    print(f'universe={len(universe)}  tf={args.tf}  workers={args.workers}  [{mode}]')

    failures = []
    noref = []
    for tf in tfs:
        table = lp.TABLES[tf]
        cutoff = lp.resume_cutoff(tf)
        print(f'\n--- {tf}: newest settled session that must exist = {cutoff}')
        pending, n_cur = behind(table, cutoff, universe)
        print(f'    {len(pending)} behind, {n_cur} current')
        if not pending:
            print(f'    {tf} is fully current — nothing to backfill.')
            continue
        if args.report_only:
            continue

        t0 = time.time()
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(pull_one, it, tf, table, args.dry_run): it
                    for it in pending}
            for fut in as_completed(futs):
                sym, n, status = fut.result()
                done += 1
                if status != 'ok' and not status.startswith('dry-run'):
                    if status == 'no new data':
                        # Upstream genuinely has no bar (halted / not published yet).
                        # Not an error -- but the ticker stays behind, so surface it.
                        noref.append((tf, sym))
                    else:
                        failures.append((tf, sym, status))
                    print(f'  [{done}/{len(pending)}] {sym}: {status}', flush=True)
                elif done % 25 == 0 or done == len(pending):
                    rate = done / max(time.time() - t0, 1e-9)
                    print(f'  [{done}/{len(pending)}] {rate:.0f}/s  last={sym} {status}',
                          flush=True)
        if not args.dry_run:
            print(f'  recompute atr_stop: compute_indicators.py '
                  f'--timeframe prices-{tf}')

    if noref:
        print(f'\nstill behind after pull (no upstream bar exists -- not an error):')
        for tf, sym in noref[:20]:
            print(f'   {tf} {sym}')
    if failures:
        print(f'\n!! {len(failures)} failure(s):')
        for tf, sym, status in failures[:20]:
            print(f'   {tf} {sym}: {status}')
        sys.exit(1)
    if args.report_only:
        print('\nReport only — nothing fetched, nothing written.')
    elif args.dry_run:
        print('\nDry run: nothing written.')


if __name__ == '__main__':
    main()