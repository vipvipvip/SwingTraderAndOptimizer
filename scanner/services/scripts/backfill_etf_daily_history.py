#!/usr/bin/env python3
"""Quarterly dump-and-refresh of ETF daily/weekly OHLCV bars.

Source of truth: Alpaca StockHistoricalDataClient with adjustment='all'
(split + dividend adjusted). Daily and weekly are fetched SEPARATELY as
native intervals from Alpaca and stored in separate tables — never derived
from one another, so no aggregation drift.

Dump-and-refresh model: each symbol's rows are DELETEd and re-inserted from
a fresh query, so once a quarter you simply re-run this and pick up any
dividend re-adjustments Alpaca retroactively applies.

SAFETY — the DELETE is unconditional, so a short or partial fetch silently
destroys history irreversibly (the previous version had no guard and still
exited 0). Alpaca IEX returns only ~1,555 bars from 2020-07-27 versus SIP's
~2,703 from 2016-01-04, so a one-line feed change would truncate four and a
half years for every ETF on the next quarterly run. The end date is checked
as well as the row count, because a per-symbol feed gap can return more rows
than the table holds while still ending years earlier.

Every refresh therefore:
  1. dumps the symbol's current rows to a timestamped JSONL backup and
     verifies the written row count before the table is touched;
  2. refuses to DELETE unless the fetch covers the existing first date, the
     existing last date, and at least the existing row count;
  3. exits non-zero and lists every symbol it refused to touch.
Genuine truncation needs the explicit --i-know-this-truncates flag, which
still forces a verified backup first.

Usage:
    python backfill_etf_daily_history.py --timeframe day|week|both [--symbols A,B]
                                         [--dry-run] [--i-know-this-truncates]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn, API_KEY, SECRET_KEY

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

NY = ZoneInfo('America/New_York')

TABLES = {
    'day': 'tbl_scanner_tickers_daily',
    'week': 'tbl_scanner_tickers',
}

ALPACA_TF = {
    'day': TimeFrame.Day,
    'week': TimeFrame.Week,
}

SCANNER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUP_DIR = os.path.join(SCANNER_ROOT, 'backups', 'etf_bars')
MIN_PLAUSIBLE_BARS = 200


def fetch_alpaca(symbol, tf_name, start_year=2016):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    start = datetime(start_year, 1, 1, tzinfo=NY)
    # end is left open: SIP serves the current session fine (verified 2703 bars
    # through 2026-10-02 with end=None). An older "end 1 day back is allowed"
    # workaround silently capped this script at the previous session, so every
    # refresh dropped the most recent bar and tripped the safety guard.
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=ALPACA_TF[tf_name],
        start=start,
        adjustment='all',
        feed='sip',
    )
    all_bars = []
    page_token = None
    while True:
        if page_token:
            request.page_token = page_token
        response = client.get_stock_bars(request)
        if symbol in response.data:
            all_bars.extend(response.data[symbol])
        page_token = getattr(response, 'next_page_token', None)
        if not page_token:
            break
    rows = []
    for bar in all_bars:
        ts = bar.timestamp
        if ts.tzinfo is not None:
            ts = ts.astimezone(NY)
        rows.append((
            ts.date(),
            float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), int(bar.volume),
        ))
    return rows


def _read_existing(cur, table, tid):
    cur.execute(
        f'SELECT date, open, high, low, close, volume FROM {table} '
        'WHERE ticker_id=%s ORDER BY date',
        (tid,),
    )
    return cur.fetchall()


def _backup(symbol, tf_name, table, tid, existing):
    """Write current rows to JSONL and verify the count before any DELETE."""
    stamp = datetime.now(NY).strftime('%Y%m%d_%H%M%S')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f'{table}_{symbol}_{stamp}.jsonl')
    written = 0
    with open(path, 'w') as fh:
        fh.write(json.dumps({
            'symbol': symbol, 'timeframe': tf_name, 'table': table,
            'ticker_id': tid, 'rows': len(existing), 'backed_up_at': stamp,
        }) + '\n')
        for r in existing:
            fh.write(json.dumps({
                'date': str(r[0]), 'open': float(r[1]), 'high': float(r[2]),
                'low': float(r[3]), 'close': float(r[4]), 'volume': int(r[5]),
            }) + '\n')
            written += 1
    if written != len(existing):
        return None, f'backup wrote {written} of {len(existing)} rows'
    if not os.path.getsize(path):
        return None, 'backup file is empty'
    return path, 'ok'


def _violations(rows, existing):
    """Reasons this fetch would destroy history. Empty list means safe."""
    out = []
    if len(rows) < MIN_PLAUSIBLE_BARS:
        out.append(f'only {len(rows)} bars (min {MIN_PLAUSIBLE_BARS})')
    if not rows or not existing:
        return out
    new_first, new_last = rows[0][0], rows[-1][0]
    old_first, old_last = existing[0][0], existing[-1][0]
    if new_first > old_first:
        out.append(f'loses {(new_first - old_first).days} days of old history '
                   f'(existing starts {old_first}, fetch starts {new_first})')
    if new_last < old_last:
        out.append(f'loses recent bars (existing ends {old_last}, fetch ends {new_last})')
    if len(rows) < len(existing):
        out.append(f'{len(existing) - len(rows)} fewer rows ({len(rows)} vs {len(existing)})')
    return out


def refresh(symbol, tf_name, start_year, dry_run=False, allow_truncation=False):
    # Alpaca only (adjusted). A yfinance source was removed here deliberately:
    # it writes a different price basis into the same table.
    rows = fetch_alpaca(symbol, tf_name, start_year)
    if not rows:
        return 0, 'BLOCKED no data returned'
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol=%s', (symbol,))
            row = cur.fetchone()
            if not row:
                return 0, 'BLOCKED not in tbl_stock_tickers'
            tid = row[0]
            table = TABLES[tf_name]
            existing = _read_existing(cur, table, tid)
            problems = _violations(rows, existing)
            if problems:
                if not allow_truncation:
                    return 0, 'BLOCKED ' + '; '.join(problems)
                print(f'  !! {symbol}: truncation OVERRIDDEN: {"; ".join(problems)}')
            if existing:
                path, status = _backup(symbol, tf_name, table, tid, existing)
                if path is None:
                    return 0, f'BLOCKED backup failed: {status}'
                print(f'     backup -> {os.path.relpath(path, SCANNER_ROOT)} ({len(existing)} rows)')
            else:
                print(f'     no existing rows; insert-only')
            if dry_run:
                return len(rows), f'dry-run ({len(existing)} existing, would write {len(rows)})'
            cur.execute(f'DELETE FROM {table} WHERE ticker_id=%s', (tid,))
            execute_values(
                cur,
                f'INSERT INTO {table} '
                '(ticker_id, date, open, high, low, close, volume) VALUES %s '
                'ON CONFLICT (ticker_id, date) DO NOTHING',
                [(tid, *r) for r in rows],
            )
            with conn.cursor() as verify:
                verify.execute(
                    f'SELECT count(*) FROM {table} WHERE ticker_id=%s', (tid,))
                after = verify.fetchone()[0]
            if after < len(rows):
                conn.rollback()
                return 0, (f'BLOCKED post-write check failed: table has {after} '
                           f'of {len(rows)} rows; rolled back')
        conn.commit()
        return len(rows), 'ok'
    except Exception as e:
        conn.rollback()
        return 0, f'BLOCKED {e}'
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', default=None,
                        help='Comma-separated symbols (default: all enabled ETFs)')
    parser.add_argument('--start-year', type=int, default=None,
                        help='Fetch from this year (default 2016)')
    parser.add_argument('--timeframe', choices=['day', 'week', 'both'], default='both')
    parser.add_argument('--dry-run', action='store_true',
                        help='Back up and report, but never DELETE or INSERT')
    parser.add_argument('--i-know-this-truncates', action='store_true',
                        dest='allow_truncation',
                        help='Proceed even when the fetch loses history (backup still written)')
    args = parser.parse_args()

    tfs = ['day', 'week'] if args.timeframe == 'both' else [args.timeframe]
    start_year = args.start_year or 2016
    label = {args.timeframe} if args.timeframe != 'both' else {'daily', 'weekly'}

    conn = get_db_conn()
    try:
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
        else:
            with conn.cursor() as cur:
                cur.execute('SELECT symbol FROM tbl_stock_tickers '
                            'WHERE enabled AND is_etf ORDER BY symbol')
                syms = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    blocked = []
    for tf in tfs:
        total = 0
        failed = []
        print(f'--- {tf} ({label}) source=alpaca feed=sip from {start_year} '
              f'{"[DRY-RUN] " if args.dry_run else ""}---')
        for sym in syms:
            n, status = refresh(sym, tf, start_year, args.dry_run,
                                args.allow_truncation)
            if status == 'ok':
                total += n
                print(f'  {sym}: {n} {tf} bars')
            elif status.startswith('dry-run'):
                total += n
                print(f'  {sym}: {status}')
            else:
                if status.startswith('BLOCKED'):
                    blocked.append((sym, tf, status[len('BLOCKED'):].strip()))
                failed.append((sym, status))
                print(f'  {sym}: {status}')
        print(f'  Done: {total} {tf} bars for {len(syms)} symbols.')
        if failed:
            print(f'  Not written: {len(failed)} -> {failed[:5]}')

    print('\nRefresh complete.')
    if blocked:
        print(f'\n!! {len(blocked)} symbol/timeframe pair(s) REFUSED to write:')
        for sym, tf, reason in blocked:
            print(f'   {sym} ({tf}): {reason}')
        print('\nNothing above was deleted or inserted. Fix the feed/coverage')
        print('issue, or re-run with --i-know-this-truncates to force it.')
        sys.exit(1)
    if args.dry_run:
        print('Dry run: no rows were written.')


if __name__ == '__main__':
    main()
