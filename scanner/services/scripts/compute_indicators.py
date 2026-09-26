"""Compute the ATR stop (the only stored indicator left).

2026-09-26 cleanup: MACD, PPO, the sma_crossover flags and the dead
ema10_sma40_* columns were dropped from the weekly and daily tables. They were
all superseded by the inline EMA10/SMA40 math in the strategies, and several of
them (sma_crossover = EMA24 vs SMA52, ppo_crossover = 24/52 zero-cross) were
misnamed legacy artifacts. `atr_stop` is the sole stored indicator because
both live strategies invert it to recover ATR: ATR = (close - atr_stop)/2.

The hourly table (tbl_scanner_tickers_1hour) still HAS its macd_*/ppo_* columns
— they were intentionally left in place, but this script no longer writes them,
so they are frozen at their last computed values. That is harmless: nothing reads
hourly MACD any more (earnings_screener.py was converted to daily MACD on
2026-09-26). Hourly `close` + `atr_stop` are still maintained because the live
MTF stock leg scores and exits off them.

Partition-aware: 16 workers (1 per hash partition on tbl_scanner_tickers_1hour),
COPY bulk writes instead of individual UPDATEs. Targets ~5-8 min on 1.5K+ tickers.

Supports weekly, daily (non-partitioned), and 1-hour (hash-partitioned) tables.

Note: run this with at most ~6 workers. The Postgres container has only a 64 MB
/dev/shm, so heavy client concurrency makes parallel-query workers die with
"could not resize shared memory segment ... No space left on device" and those
tickers silently keep a NULL atr_stop.
"""

import argparse
import os
import sys
import time
from io import StringIO
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    ATR_PERIOD, ATR_MULT,
    get_db_conn,
)

TABLES = {
    'week': 'tbl_scanner_tickers',
    'day': 'tbl_scanner_tickers_daily',
    'hour': 'tbl_scanner_tickers_1hour',
}

PARTITION_COUNT = 16

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


def _copy_to_temp(cur, rows, tmp_name, date_type='date'):
    """COPY rows to a temp table for bulk update. date_type='timestamp' for the
    hourly table (bars are timestamps; joining on a plain date never matches)."""
    buf = StringIO()
    for row in rows:
        vals = []
        for v in row:
            if v is None:
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
        f'ticker_id bigint, date {date_type}, '
        'atr_stop float8'
        ') ON COMMIT DROP'
    )
    col_list = 'ticker_id, date, ' + ', '.join(INDICATOR_COLUMNS)
    cur.copy_expert(
        f'COPY {tmp_name} ({col_list}) FROM STDIN WITH (FORMAT text)',
        buf,
    )


def load_ticker_data_bulk(conn, ticker_ids, table):
    """Load data for multiple tickers in a single query."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT ticker_id, date, open, high, low, close, volume "
        f"FROM {table} WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date ASC",
        (ticker_ids,),
    )
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=['ticker_id', 'date', 'open', 'high', 'low', 'close', 'volume'])
    return {tid: group.reset_index(drop=True) for tid, group in df.groupby('ticker_id')}


def worker_process(worker_id, ticker_ids, table, is_hourly):
    """Process a batch of tickers in a single DB connection. Returns (count, rows)."""
    conn = get_db_conn()
    try:
        conn.autocommit = False
        data_map = load_ticker_data_bulk(conn, ticker_ids, table)
        min_rows = ATR_PERIOD + 1

        all_rows = []
        total_written = 0
        processed = 0

        for tid in ticker_ids:
            df = data_map.get(tid)
            if df is None or len(df) < min_rows:
                continue

            indicators = compute_indicators(df)
            for _, row in indicators.iterrows():
                date_val = row['date']
                if hasattr(date_val, 'to_pydatetime'):
                    date_val = date_val.to_pydatetime()
                if not is_hourly and hasattr(date_val, 'date'):
                    date_val = date_val.date()
                all_rows.append((
                    int(row['ticker_id']), date_val,
                    row['atr_stop'],
                ))
            total_written += len(indicators)
            processed += 1

        # Bulk update via COPY + UPDATE FROM
        if all_rows:
            cur = conn.cursor()
            tmp_name = f'_ind_w{worker_id}'
            _copy_to_temp(cur, all_rows, tmp_name, date_type='timestamp' if is_hourly else 'date')
            _bulk_update_from_temp(cur, table, tmp_name)
            conn.commit()
            cur.close()

        return worker_id, processed, total_written, 'ok'
    except Exception as e:
        conn.rollback()
        return worker_id, 0, 0, str(e)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Compute the ATR stop for scanner tickers')
    parser.add_argument('--timeframe', choices=list(TABLES.keys()), default='week',
                        help='Timeframe table to process (default: week)')
    parser.add_argument('--workers', type=int, default=16,
                        help='Number of parallel workers (default: 16 = 1 per hash partition)')
    args = parser.parse_args()

    table = TABLES[args.timeframe]
    is_hourly = args.timeframe == 'hour'

    # Load all ticker_ids that have data in this table
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker_id FROM {table} ORDER BY ticker_id"
            )
            ticker_ids = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    if not ticker_ids:
        print(f"No tickers found in {table}")
        return

    # Partition tickers into worker groups
    num_workers = min(args.workers, len(ticker_ids))
    if is_hourly:
        partitions = defaultdict(list)
        for tid in ticker_ids:
            partitions[tid % PARTITION_COUNT].append(tid)
        worker_groups = [[] for _ in range(num_workers)]
        for part_id, pids in partitions.items():
            worker_groups[part_id % num_workers].extend(pids)
    else:
        worker_groups = [[] for _ in range(num_workers)]
        for i, tid in enumerate(ticker_ids):
            worker_groups[i % num_workers].append(tid)

    total_tickers = len(ticker_ids)
    print(f"Computing atr_stop (ATR {ATR_PERIOD} x {ATR_MULT}) for {total_tickers} tickers "
          f"on {table}, {num_workers} workers...")

    t0 = time.time()
    total_processed = 0
    total_written = 0
    errors = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {}
        for w_id in range(num_workers):
            if worker_groups[w_id]:
                futures[executor.submit(
                    worker_process, w_id, worker_groups[w_id], table, is_hourly,
                )] = w_id

        for future in as_completed(futures):
            w_id, count, written, status = future.result()
            total_processed += count
            total_written += written
            if status != 'ok':
                errors.append(f'Worker {w_id}: {status}')
            print(f"  Worker {w_id}: {count} tickers, {written} rows {'OK' if status == 'ok' else 'ERROR: ' + status}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. {total_processed}/{total_tickers} tickers processed, "
          f"{total_written} rows written.")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")


if __name__ == '__main__':
    main()
