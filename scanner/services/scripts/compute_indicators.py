"""Phase 2: Compute MACD and PPO indicators, detect crossovers.

Partition-aware rewrite: 16 workers (1 per hash partition on tbl_scanner_tickers_1hour),
COPY bulk writes instead of individual UPDATEs. Targets ~5-8 min on 1.5K+ tickers.

Supports weekly, daily (non-partitioned), and 1-hour (hash-partitioned) tables.
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
    EMA_FAST, EMA_SLOW, MACD_SIGNAL_PERIOD,
    PPO_FAST, PPO_SLOW, PPO_SIGNAL_PERIOD,
    ATR_PERIOD, ATR_MULT,
    get_db_conn,
)

TABLES = {
    'week': 'tbl_scanner_tickers',
    'day': 'tbl_scanner_tickers_daily',
    'hour': 'tbl_scanner_tickers_1hour',
}

PARTITION_COUNT = 16

INDICATOR_COLUMNS = [
    'macd_line', 'macd_signal', 'macd_histogram',
    'macd_crossover', 'macd_cross_bearish',
    'ppo_line', 'ppo_signal', 'ppo_histogram',
    'ppo_crossover', 'ppo_cross_bearish',
    'sma_crossover', 'sma_cross_bearish',
    'atr_stop',
]


def compute_indicators(df, ema_fast_period, ema_slow_period, macd_signal_period, ppo_fast_period, ppo_slow_period):
    close = df['close'].astype(float)

    ema_fast = close.ewm(span=ema_fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=ema_slow_period, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=macd_signal_period, adjust=False).mean()
    macd_histogram = macd_line - macd_signal

    ppo_line = ((ema_fast - ema_slow) / ema_slow.replace(0, np.nan)) * 100
    ppo_signal = ppo_line.ewm(span=PPO_SIGNAL_PERIOD, adjust=False).mean()
    ppo_histogram = ppo_line - ppo_signal

    macd_crossover = np.where(
        (macd_line > macd_signal) & (macd_line.shift(1) <= macd_signal.shift(1)),
        True, False,
    )
    macd_cross_bearish = np.where(
        (macd_line < macd_signal) & (macd_line.shift(1) >= macd_signal.shift(1)),
        True, False,
    )
    ppo_crossover = np.where(
        (ppo_line > 0) & (ppo_line.shift(1) <= 0),
        True, False,
    )
    ppo_cross_bearish = np.where(
        (ppo_line < 0) & (ppo_line.shift(1) >= 0),
        True, False,
    )

    sma_slow = close.rolling(window=ema_slow_period).mean()
    sma_crossover = np.where(
        (ema_fast > sma_slow) & (ema_fast.shift(1) <= sma_slow.shift(1)),
        True, False,
    )
    sma_cross_bearish = np.where(
        (ema_fast < sma_slow) & (ema_fast.shift(1) >= sma_slow.shift(1)),
        True, False,
    )

    high_low = df['high'].astype(float) - df['low'].astype(float)
    high_pc = (df['high'].astype(float) - df['close'].astype(float).shift(1)).abs()
    low_pc = (df['low'].astype(float) - df['close'].astype(float).shift(1)).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    atr = tr.rolling(window=ATR_PERIOD).mean()
    atr_stop = close - atr * ATR_MULT

    return pd.DataFrame({
        'date': df['date'],
        'ticker_id': df['ticker_id'],
        'macd_line': [None if pd.isna(v) else float(v) for v in macd_line],
        'macd_signal': [None if pd.isna(v) else float(v) for v in macd_signal],
        'macd_histogram': [None if pd.isna(v) else float(v) for v in macd_histogram],
        'macd_crossover': [bool(v) for v in macd_crossover],
        'macd_cross_bearish': [bool(v) for v in macd_cross_bearish],
        'ppo_line': [None if pd.isna(v) else float(v) for v in ppo_line],
        'ppo_signal': [None if pd.isna(v) else float(v) for v in ppo_signal],
        'ppo_histogram': [None if pd.isna(v) else float(v) for v in ppo_histogram],
        'ppo_crossover': [bool(v) for v in ppo_crossover],
        'ppo_cross_bearish': [bool(v) for v in ppo_cross_bearish],
        'sma_crossover': [bool(v) for v in sma_crossover],
        'sma_cross_bearish': [bool(v) for v in sma_cross_bearish],
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
        'macd_line float8, macd_signal float8, macd_histogram float8, '
        'macd_crossover boolean, macd_cross_bearish boolean, '
        'ppo_line float8, ppo_signal float8, ppo_histogram float8, '
        'ppo_crossover boolean, ppo_cross_bearish boolean, '
        'sma_crossover boolean, sma_cross_bearish boolean, '
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


def worker_process(worker_id, ticker_ids, table, is_hourly,
                   ema_fast, ema_slow, macd_signal_period, ppo_fast, ppo_slow):
    """Process a batch of tickers in a single DB connection. Returns (count, crossovers)."""
    conn = get_db_conn()
    try:
        conn.autocommit = False
        data_map = load_ticker_data_bulk(conn, ticker_ids, table)
        min_rows = max(ema_slow, ppo_slow) + 1

        all_rows = []
        total_crossovers = 0
        processed = 0

        for tid in ticker_ids:
            df = data_map.get(tid)
            if df is None or len(df) < min_rows:
                continue

            indicators = compute_indicators(df, ema_fast, ema_slow, macd_signal_period, ppo_fast, ppo_slow)
            for _, row in indicators.iterrows():
                date_val = row['date']
                if hasattr(date_val, 'to_pydatetime'):
                    date_val = date_val.to_pydatetime()
                if not is_hourly and hasattr(date_val, 'date'):
                    date_val = date_val.date()
                all_rows.append((
                    int(row['ticker_id']), date_val,
                    row['macd_line'], row['macd_signal'], row['macd_histogram'],
                    row['macd_crossover'], row['macd_cross_bearish'],
                    row['ppo_line'], row['ppo_signal'], row['ppo_histogram'],
                    row['ppo_crossover'], row['ppo_cross_bearish'],
                    row['sma_crossover'], row['sma_cross_bearish'],
                    row['atr_stop'],
                ))
            total_crossovers += int(
                indicators['macd_crossover'].sum() + indicators['ppo_crossover'].sum()
                + indicators['sma_crossover'].sum()
                + indicators['macd_cross_bearish'].sum() + indicators['ppo_cross_bearish'].sum()
                + indicators['sma_cross_bearish'].sum()
            )
            processed += 1

        # Bulk update via COPY + UPDATE FROM
        if all_rows:
            cur = conn.cursor()
            tmp_name = f'_ind_w{worker_id}'
            _copy_to_temp(cur, all_rows, tmp_name, date_type='timestamp' if is_hourly else 'date')
            _bulk_update_from_temp(cur, table, tmp_name)
            conn.commit()
            cur.close()

        return worker_id, processed, total_crossovers, 'ok'
    except Exception as e:
        conn.rollback()
        return worker_id, 0, 0, str(e)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Compute MACD/PPO indicators for scanner tickers')
    parser.add_argument('--timeframe', choices=list(TABLES.keys()), default='week',
                        help='Timeframe table to process (default: week)')
    parser.add_argument('--ema-fast', type=int, default=EMA_FAST)
    parser.add_argument('--ema-slow', type=int, default=EMA_SLOW)
    parser.add_argument('--macd-signal-period', type=int, default=MACD_SIGNAL_PERIOD)
    parser.add_argument('--ppo-fast', type=int, default=PPO_FAST)
    parser.add_argument('--ppo-slow', type=int, default=PPO_SLOW)
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
    print(f"Computing indicators for {total_tickers} tickers on {table} "
          f"(EMA {args.ema_fast}/{args.ema_slow}, "
          f"PPO {args.ppo_fast}/{args.ppo_slow}), "
          f"{num_workers} workers...")

    t0 = time.time()
    total_processed = 0
    total_crossovers = 0
    errors = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {}
        for w_id in range(num_workers):
            if worker_groups[w_id]:
                futures[executor.submit(
                    worker_process, w_id, worker_groups[w_id], table, is_hourly,
                    args.ema_fast, args.ema_slow, args.macd_signal_period,
                    args.ppo_fast, args.ppo_slow,
                )] = w_id

        for future in as_completed(futures):
            w_id, count, crossovers, status = future.result()
            total_processed += count
            total_crossovers += crossovers
            if status != 'ok':
                errors.append(f'Worker {w_id}: {status}')
            print(f"  Worker {w_id}: {count} tickers, {crossovers} crossovers {'OK' if status == 'ok' else 'ERROR: ' + status}")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. {total_processed}/{total_tickers} tickers processed, "
          f"{total_crossovers} total crossovers.")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")


if __name__ == '__main__':
    main()
