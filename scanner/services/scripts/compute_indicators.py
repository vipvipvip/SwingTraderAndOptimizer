"""Phase 2: Compute MACD and PPO indicators, detect crossovers.

Supports weekly, daily, and 1-hour timeframe tables.
"""

import argparse
import os
import sys
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


def load_ticker_data(ticker_id, table):
    conn = get_db_conn()
    try:
        df = pd.read_sql(
            f"""
            SELECT date, open, high, low, close, volume
            FROM {table}
            WHERE ticker_id = %s
            ORDER BY date ASC
            """,
            conn,
            params=(ticker_id,),
            parse_dates=['date'],
        )
    finally:
        conn.close()

    if df.empty:
        return None
    return df


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
        'macd_line': macd_line,
        'macd_signal': macd_signal,
        'macd_histogram': macd_histogram,
        'macd_crossover': macd_crossover,
        'ppo_line': ppo_line,
        'ppo_signal': ppo_signal,
        'ppo_histogram': ppo_histogram,
        'ppo_crossover': ppo_crossover,
        'sma_crossover': sma_crossover,
        'macd_cross_bearish': macd_cross_bearish,
        'ppo_cross_bearish': ppo_cross_bearish,
        'sma_cross_bearish': sma_cross_bearish,
        'atr_stop': atr_stop,
    })


def get_ticker_id(symbol):
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def process_ticker(ticker, table, ema_fast_period, ema_slow_period, macd_signal_period, ppo_fast_period, ppo_slow_period):
    try:
        ticker_id = get_ticker_id(ticker)
        if ticker_id is None:
            return ticker, 0, f'ticker not found in tbl_stock_tickers'

        df = load_ticker_data(ticker_id, table)
        if df is None or len(df) < max(ema_slow_period, ppo_slow_period) + 1:
            return ticker, 0, f'insufficient data ({len(df) if df is not None else 0} rows)'

        indicators = compute_indicators(
            df, ema_fast_period, ema_slow_period, macd_signal_period, ppo_fast_period, ppo_slow_period
        )

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                for _, row in indicators.iterrows():
                    date_val = row['date']
                    if hasattr(date_val, 'to_pydatetime'):
                        date_param = date_val.to_pydatetime()
                    else:
                        date_param = date_val
                    cur.execute(
                        f"""
                        UPDATE {table}
                        SET macd_line = %s, macd_signal = %s, macd_histogram = %s,
                            macd_crossover = %s, macd_cross_bearish = %s,
                            ppo_line = %s, ppo_signal = %s, ppo_histogram = %s,
                            ppo_crossover = %s, ppo_cross_bearish = %s,
                            sma_crossover = %s, sma_cross_bearish = %s,
                            atr_stop = %s
                        WHERE ticker_id = %s AND date = %s
                        """,
                        (
                            None if pd.isna(row['macd_line']) else float(row['macd_line']),
                            None if pd.isna(row['macd_signal']) else float(row['macd_signal']),
                            None if pd.isna(row['macd_histogram']) else float(row['macd_histogram']),
                            bool(row['macd_crossover']),
                            bool(row['macd_cross_bearish']),
                            None if pd.isna(row['ppo_line']) else float(row['ppo_line']),
                            None if pd.isna(row['ppo_signal']) else float(row['ppo_signal']),
                            None if pd.isna(row['ppo_histogram']) else float(row['ppo_histogram']),
                            bool(row['ppo_crossover']),
                            bool(row['ppo_cross_bearish']),
                            bool(row['sma_crossover']),
                            bool(row['sma_cross_bearish']),
                            None if pd.isna(row['atr_stop']) else float(row['atr_stop']),
                            ticker_id,
                            date_param,
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

        crossovers = (indicators['macd_crossover'].sum() + indicators['ppo_crossover'].sum()
                      + indicators['sma_crossover'].sum()
                      + indicators['macd_cross_bearish'].sum()
                      + indicators['ppo_cross_bearish'].sum()
                      + indicators['sma_cross_bearish'].sum())
        return ticker, crossovers, 'ok'
    except Exception as e:
        return ticker, 0, str(e)


def main():
    parser = argparse.ArgumentParser(description='Compute MACD/PPO indicators for scanner tickers')
    parser.add_argument('--timeframe', choices=list(TABLES.keys()), default='week',
                        help='Timeframe table to process (default: week)')
    parser.add_argument('--ema-fast', type=int, default=EMA_FAST)
    parser.add_argument('--ema-slow', type=int, default=EMA_SLOW)
    parser.add_argument('--macd-signal-period', type=int, default=MACD_SIGNAL_PERIOD)
    parser.add_argument('--ppo-fast', type=int, default=PPO_FAST)
    parser.add_argument('--ppo-slow', type=int, default=PPO_SLOW)
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()

    table = TABLES[args.timeframe]

    conn = get_db_conn()
    try:
        tickers = pd.read_sql(
            f"""SELECT DISTINCT e.symbol
                FROM {table} s
                JOIN tbl_stock_tickers e ON e.id = s.ticker_id
                ORDER BY e.symbol""", conn
        )['symbol'].tolist()
    finally:
        conn.close()

    print(f"Computing indicators for {len(tickers)} tickers on {table} "
          f"(EMA {args.ema_fast}/{args.ema_slow}, "
          f"PPO {args.ppo_fast}/{args.ppo_slow})...")

    total = len(tickers)
    done = 0
    total_crossovers = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_ticker, t, table, args.ema_fast, args.ema_slow,
                args.macd_signal_period, args.ppo_fast, args.ppo_slow,
            ): t for t in tickers
        }

        for future in as_completed(futures):
            ticker, crossovers, status = future.result()
            done += 1
            total_crossovers += crossovers

            if status == 'ok':
                print(f"  [{done}/{total}] {ticker}: {crossovers} crossovers found")
            else:
                print(f"  [{done}/{total}] {ticker}: skipped ({status})")

    print(f"\nDone. {done} tickers processed, {total_crossovers} total crossover signals detected.")


if __name__ == '__main__':
    main()
