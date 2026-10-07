"""Compute the ATR stop (the only stored indicator) into the canonical price tables.

`--timeframe week|prices-weekly` -> tbl_prices_weekly, `day|prices-daily` -> tbl_prices_daily.
Both live strategies invert atr_stop to recover ATR: ATR = (close - atr_stop) / 2.
load_prices.py NULLs atr_stop on every upsert, so run this after every load; the
readiness gate (data_readiness.py) refuses to trade while a ticker with a bar at the
frontier -- or any held position -- has a NULL atr_stop.

Run with at most ~6 workers. The Postgres container has only a 64 MB /dev/shm, so heavy
client concurrency makes parallel-query workers die with "could not resize shared memory
segment ... No space left on device" and those tickers silently keep a NULL atr_stop.
"""

import argparse
import math
import os
import sys
import time
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ATR_PERIOD, ATR_MULT,
    get_db_conn,
)

# week/day and prices-weekly/prices-daily are aliases for the SAME canonical tables.
# The deprecated tbl_scanner_tickers* tables are no longer a target: nothing live reads
# them, and atr_stop must never be computed into a table the gate does not check.
TABLES = {
    'week': 'tbl_prices_weekly',
    'day': 'tbl_prices_daily',
    'prices-weekly': 'tbl_prices_weekly',
    'prices-daily': 'tbl_prices_daily',
}

INDICATOR_COLUMNS = ['atr_stop']


def compute_indicators(df):
    close = df['close'].astype(float)

    high_low = df['high'].astype(float) - df['low'].astype(float)
    high_pc = (df['high'].astype(float) - df['close'].astype(float).shift(1)).abs()
    low_pc = (df['low'].astype(float) - df['close'].astype(float).shift(1)).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    atr = tr.rolling(window=ATR_PERIOD).mean()
    atr_stop = close - atr * ATR_MULT

    return pd.DataFrame({
        'date': df['date'],
        'ticker_id': df['ticker_id'],
        'atr_stop': [None if pd.isna(v) else float(v) for v in atr_stop],
    })


def _bulk_update_from_temp(cur, table, tmp_name):
    """UPDATE target table FROM temp table using COPY'd data."""
    set_clause = ', '.join(f'{col} = {tmp_name}.{col}' for col in INDICATOR_COLUMNS)
    cur.execute(f'''
        UPDATE {table}
        SET {set_clause}
        FROM {tmp_name}
        WHERE {table}.ticker_id = {tmp_name}.ticker_id
          AND {table}.date = {tmp_name}.date
    ''')


def _copy_to_temp(cur, rows, tmp_name):
    """COPY rows to a temp table for bulk update."""
    buf = StringIO()
    for row in rows:
        vals = []
        for v in row:
            # NaN must go over the wire as NULL, not as the text 'nan': a float8
            # column happily parses 'nan' into a NaN value, which then reads back
            # as a number everywhere downstream (Postgres orders NaN above every
            # other value, so `> 0` guards and arithmetic both misbehave). Note
            # that compute_indicators' `None if pd.isna(v)` guard is NOT enough on
            # its own — pandas coerces the resulting list back to float64 NaN.
            if v is None or (isinstance(v, float) and math.isnan(v)):
                vals.append('\\N')
            elif isinstance(v, bool):
                vals.append('t' if v else 'f')
            else:
                vals.append(str(v))
        buf.write('\t'.join(vals) + '\n')
    buf.seek(0)
    cur.execute(f'DROP TABLE IF EXISTS {tmp_name}')
    cur.execute(
        f'CREATE TEMP TABLE {tmp_name} ('
        'ticker_id bigint, date date, '
        'atr_stop float8'
        ') ON COMMIT DROP'
    )
    col_list = 'ticker_id, date, ' + ', '.join(INDICATOR_COLUMNS)
    cur.copy_expert(
        f'COPY {tmp_name} ({col_list}) FROM STDIN WITH (FORMAT text)',
        buf,
    )


def find_pending(conn, table):
    """ticker_id -> 1-based row number of its FIRST bar that still needs an atr_stop.

    A bar needs one when atr_stop IS NULL and it is far enough into the history for a
    14-bar ATR to exist (rn >= ATR_PERIOD; earlier bars are legitimately NULL forever).
    load_prices.py NULLs atr_stop on every row it upserts, so "NULL beyond warm-up" is
    exactly "new or restated since the last compute" -- on a normal day that is one bar
    per ticker, which is what makes this incremental. A plain `--full` pass ignores it.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT ticker_id, MIN(rn) FROM ("
            f"  SELECT ticker_id, atr_stop, "
            f"         ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date) AS rn "
            f"  FROM {table}) t "
            f"WHERE atr_stop IS NULL AND rn >= %s GROUP BY ticker_id", (ATR_PERIOD,))
        return {tid: int(rn) for tid, rn in cur.fetchall()}


def load_ticker_slices(conn, table, start_rn):
    """Bars for each ticker from row (start_rn - ATR_PERIOD) onward -- just enough
    look-back for the first pending bar's 14-bar ATR window (plus the prev close)."""
    tids = list(start_rn)
    cur = conn.cursor()
    cur.execute(
        f"SELECT ticker_id, rn, date, high, low, close FROM ("
        f"  SELECT ticker_id, date, high, low, close, "
        f"         ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date) AS rn "
        f"  FROM {table} WHERE ticker_id = ANY(%s)) r "
        f"ORDER BY ticker_id, rn", (tids,))
    rows = cur.fetchall()
    cur.close()
    data = {}
    for tid, rn, d, h, l, c in rows:
        if rn >= max(1, start_rn[tid] - ATR_PERIOD):
            data.setdefault(tid, []).append((rn, d, h, l, c))
    return data


def worker_process(worker_id, start_rn, table):
    """Compute and write atr_stop for one batch of tickers (a {ticker_id: first_rn} dict)."""
    conn = get_db_conn()
    try:
        conn.autocommit = False
        data = load_ticker_slices(conn, table, start_rn)
        all_rows = []
        processed = 0
        for tid, bars in data.items():
            first_rn = start_rn[tid]
            df = pd.DataFrame(bars, columns=['rn', 'date', 'high', 'low', 'close'])
            df['ticker_id'] = tid
            # Needs the whole ticker to have enough history, as before.
            if bars[-1][0] < ATR_PERIOD + 1:
                continue
            out = compute_indicators(df)
            keep = (df['rn'] >= first_rn).to_numpy()
            for d, v, k in zip(out['date'], out['atr_stop'], keep):
                if k:
                    d = d.date() if hasattr(d, 'date') else d
                    all_rows.append((int(tid), d, v))
            processed += 1

        if all_rows:
            cur = conn.cursor()
            tmp_name = f'_ind_w{worker_id}'
            _copy_to_temp(cur, all_rows, tmp_name)
            _bulk_update_from_temp(cur, table, tmp_name)
            conn.commit()
            cur.close()
        return worker_id, processed, len(all_rows), 'ok'
    except Exception as e:
        conn.rollback()
        return worker_id, 0, 0, str(e)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Compute the ATR stop for scanner tickers')
    parser.add_argument('--timeframe', choices=list(TABLES.keys()), default='week',
                        help='Timeframe to process (default: week)')
    parser.add_argument('--workers', type=int, default=4,
                        help='Parallel workers (default 4; keep <= 6, see module docstring)')
    parser.add_argument('--full', action='store_true',
                        help='recompute every bar of every ticker (repair); default is '
                             'incremental: only bars whose atr_stop is NULL')
    args = parser.parse_args()

    table = TABLES[args.timeframe]
    t0 = time.time()

    conn = get_db_conn()
    try:
        if args.full:
            with conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT ticker_id FROM {table} ORDER BY ticker_id")
                pending = {row[0]: 1 for row in cur.fetchall()}
        else:
            pending = find_pending(conn, table)
    finally:
        conn.close()

    if not pending:
        print(f"{table}: atr_stop already current -- nothing to compute.")
        return

    ticker_ids = sorted(pending)
    num_workers = min(args.workers, len(ticker_ids))
    groups = [{} for _ in range(num_workers)]
    for i, tid in enumerate(ticker_ids):
        groups[i % num_workers][tid] = pending[tid]

    print(f"Computing atr_stop (ATR {ATR_PERIOD} x {ATR_MULT}) for {len(ticker_ids)} tickers "
          f"on {table} ({'FULL' if args.full else 'incremental'}), {num_workers} workers...")

    total_processed = 0
    total_written = 0
    errors = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(worker_process, w, groups[w], table): w
                   for w in range(num_workers) if groups[w]}
        for future in as_completed(futures):
            w_id, count, written, status = future.result()
            total_processed += count
            total_written += written
            if status != 'ok':
                errors.append(f'Worker {w_id}: {status}')
            print(f"  Worker {w_id}: {count} tickers, {written} rows {'OK' if status == 'ok' else 'ERROR: ' + status}")

    print(f"\nDone in {time.time() - t0:.1f}s. {total_processed}/{len(ticker_ids)} tickers processed, "
          f"{total_written} rows written.")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
