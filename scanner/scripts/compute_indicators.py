"""Phase 2: Compute MACD and PPO indicators on weekly data, detect crossovers."""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MACD_FAST, MACD_SLOW, MACD_LENGTH,
    PPO_FAST, PPO_SLOW, PPO_SIGNAL,
    TABLE, get_db_conn,
)


def load_ticker_data(ticker):
    conn = get_db_conn()
    try:
        df = pd.read_sql(
            f"""
            SELECT date, open, high, low, close, volume
            FROM {TABLE}
            WHERE ticker = %s
            ORDER BY date ASC
            """,
            conn,
            params=(ticker,),
            parse_dates=['date'],
        )
    finally:
        conn.close()

    if df.empty:
        return None
    return df


def compute_indicators(df, macd_fast, macd_slow, macd_length, ppo_fast, ppo_slow):
    close = df['close'].astype(float)

    sma_fast = close.rolling(window=macd_fast).mean()
    sma_slow = close.rolling(window=macd_slow).mean()

    macd_line = sma_fast - sma_slow
    macd_signal = macd_line.rolling(window=macd_length).mean()
    macd_histogram = macd_line - macd_signal

    ppo_line = ((sma_fast - sma_slow) / sma_slow.replace(0, np.nan)) * 100
    ppo_signal = ppo_line.ewm(span=PPO_SIGNAL, adjust=False).mean()
    ppo_histogram = ppo_line - ppo_signal

    macd_crossover = np.where(
        (macd_line > macd_signal) & (macd_line.shift(1) <= macd_signal.shift(1)),
        True, False,
    )

    ppo_crossover = np.where(
        (ppo_line > 0) & (ppo_line.shift(1) <= 0),
        True, False,
    )

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
    })


def process_ticker(ticker, macd_fast, macd_slow, macd_length, ppo_fast, ppo_slow):
    try:
        df = load_ticker_data(ticker)
        if df is None or len(df) < max(macd_slow, ppo_slow) + 1:
            return ticker, 0, f'insufficient data ({len(df) if df is not None else 0} rows)'

        indicators = compute_indicators(
            df, macd_fast, macd_slow, macd_length, ppo_fast, ppo_slow
        )

        conn = get_db_conn()
        try:
            with conn.cursor() as cur:
                for _, row in indicators.iterrows():
                    cur.execute(
                        f"""
                        UPDATE {TABLE}
                        SET macd_line = %s, macd_signal = %s, macd_histogram = %s,
                            macd_crossover = %s,
                            ppo_line = %s, ppo_signal = %s, ppo_histogram = %s,
                            ppo_crossover = %s
                        WHERE ticker = %s AND date = %s
                        """,
                        (
                            None if pd.isna(row['macd_line']) else float(row['macd_line']),
                            None if pd.isna(row['macd_signal']) else float(row['macd_signal']),
                            None if pd.isna(row['macd_histogram']) else float(row['macd_histogram']),
                            bool(row['macd_crossover']),
                            None if pd.isna(row['ppo_line']) else float(row['ppo_line']),
                            None if pd.isna(row['ppo_signal']) else float(row['ppo_signal']),
                            None if pd.isna(row['ppo_histogram']) else float(row['ppo_histogram']),
                            bool(row['ppo_crossover']),
                            ticker,
                            row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else row['date'],
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

        crossovers = indicators['macd_crossover'].sum() + indicators['ppo_crossover'].sum()
        return ticker, crossovers, 'ok'
    except Exception as e:
        return ticker, 0, str(e)


def main():
    parser = argparse.ArgumentParser(description='Compute MACD/PPO indicators for scanner tickers')
    parser.add_argument('--macd-fast', type=int, default=MACD_FAST)
    parser.add_argument('--macd-slow', type=int, default=MACD_SLOW)
    parser.add_argument('--macd-length', type=int, default=MACD_LENGTH)
    parser.add_argument('--ppo-fast', type=int, default=PPO_FAST)
    parser.add_argument('--ppo-slow', type=int, default=PPO_SLOW)
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()

    conn = get_db_conn()
    try:
        tickers = pd.read_sql(
            f"SELECT DISTINCT ticker FROM {TABLE} ORDER BY ticker", conn
        )['ticker'].tolist()
    finally:
        conn.close()

    print(f"Computing indicators for {len(tickers)} tickers "
          f"(MACD {args.macd_fast}/{args.macd_slow}/{args.macd_length}, "
          f"PPO {args.ppo_fast}/{args.ppo_slow})...")

    total = len(tickers)
    done = 0
    total_crossovers = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_ticker, t, args.macd_fast, args.macd_slow,
                args.macd_length, args.ppo_fast, args.ppo_slow,
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
