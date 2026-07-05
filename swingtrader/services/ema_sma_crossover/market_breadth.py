#!/usr/bin/env python3
"""Compute % of S&P 500 stocks in multi-TF uptrend over time."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from datetime import date
import db as db_module


def main():
    print('Computing market breadth over time...')
    db_module.init_db()
    conn = db_module.get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled = true')
            tickers = dict(cur.fetchall())

        ticker_ids = list(tickers.keys())
        print(f'  {len(ticker_ids)} tickers')

        # Get all daily dates with close
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticker_id, date, close::float8 AS close
                FROM tbl_scanner_tickers_daily
                WHERE ticker_id = ANY(%s)
                ORDER BY ticker_id, date
            """, (ticker_ids,))
            daily_raw = cur.fetchall()

        # Also get weekly data for weekly SMA/EMA
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticker_id, date, close::float8 AS close
                FROM tbl_scanner_tickers
                WHERE ticker_id = ANY(%s)
                ORDER BY ticker_id, date
            """, (ticker_ids,))
            weekly_raw = cur.fetchall()

        # Organize daily data by ticker
        daily_by_tid = {}
        for r in daily_raw:
            daily_by_tid.setdefault(r[0], []).append((r[1], r[2]))

        weekly_by_tid = {}
        for r in weekly_raw:
            weekly_by_tid.setdefault(r[0], []).append((r[1], r[2]))

        # For each unique date, compute % of stocks in uptrend
        # We need: weekly EMA(10) > SMA(40) AND daily EMA(10) > SMA(40)
        
        # Pre-compute daily EMA/SMA for each ticker
        print('  Computing indicators...')
        daily_status = {}  # date -> list of (ticker_id, bullish)
        for tid, bars in daily_by_tid.items():
            if len(bars) < 45:
                continue
            dates = [b[0] for b in bars]
            close = np.array([b[1] for b in bars])
            ema = pd.Series(close).ewm(span=10, adjust=False).mean().values
            sma = pd.Series(close).rolling(window=40).mean().values
            for i in range(40, len(close)):
                d = dates[i]
                if np.isnan(ema[i]) or np.isnan(sma[i]):
                    continue
                bullish = ema[i] > sma[i]
                daily_status.setdefault(d, []).append((tid, bullish))

        # Weekly same
        weekly_status = {}
        for tid, bars in weekly_by_tid.items():
            if len(bars) < 45:
                continue
            dates = [b[0] for b in bars]
            close = np.array([b[1] for b in bars])
            ema = pd.Series(close).ewm(span=10, adjust=False).mean().values
            sma = pd.Series(close).rolling(window=40).mean().values
            for i in range(40, len(close)):
                d = dates[i]
                if np.isnan(ema[i]) or np.isnan(sma[i]):
                    continue
                bullish = ema[i] > sma[i]
                weekly_status.setdefault(d, []).append((tid, bullish))

        # Join on dates (daily dates)
        daily_dates = sorted(daily_status.keys())
        results = []
        for d in daily_dates:
            if d < date(2023, 7, 1):
                continue
            d_bull = dict(daily_status.get(d, []))
            # Find matching weekly bar for each ticker
            w_bull = dict(weekly_status.get(d, []))
            
            combined = 0
            total = 0
            for tid in d_bull:
                if tid in w_bull:
                    total += 1
                    if d_bull[tid] and w_bull[tid]:
                        combined += 1
            
            if total > 0:
                results.append((d, combined / total * 100, total))

        if not results:
            print('  No results computed')
            return

        df = pd.DataFrame(results, columns=['date', 'pct_uptrend', 'total'])
        df = df.set_index('date')
        
        print(f'\n  {"="*60}')
        print(f'  MARKET BREADTH: % of S&P 500 in Multi-TF Uptrend')
        print(f'  {"="*60}')
        print(f'  Range: {df["pct_uptrend"].min():.0f}% to {df["pct_uptrend"].max():.0f}%')
        print(f'  Current: {df["pct_uptrend"].iloc[-1]:.0f}% ({df.index[-1]})')
        print(f'  Mean: {df["pct_uptrend"].mean():.0f}%')
        print(f'  Median: {df["pct_uptrend"].median():.0f}%')
        print(f'  Std: {df["pct_uptrend"].std():.0f}%')
        
        # Percentiles
        print(f'\n  Historical zones:')
        for p in [10, 25, 50, 75, 90]:
            print(f'    {p}th percentile: {df["pct_uptrend"].quantile(p/100):.0f}%')

        # Regime classification
        p25 = df["pct_uptrend"].quantile(0.25)
        p75 = df["pct_uptrend"].quantile(0.75)
        print(f'\n  Regime thresholds:')
        print(f'    Risk-off (< {p25:.0f}%): {len(df[df["pct_uptrend"] < p25])} days ({len(df[df["pct_uptrend"] < p25])/len(df)*100:.0f}%)')
        print(f'    Neutral ({p25:.0f}%-{p75:.0f}%): {len(df[(df["pct_uptrend"] >= p25) & (df["pct_uptrend"] <= p75)])} days ({(len(df[(df["pct_uptrend"] >= p25) & (df["pct_uptrend"] <= p75)]))/len(df)*100:.0f}%)')
        print(f'    Risk-on (> {p75:.0f}%): {len(df[df["pct_uptrend"] > p75])} days ({len(df[df["pct_uptrend"] > p75])/len(df)*100:.0f}%)')

        # Sample every ~20 days
        sample = df.iloc[::20]
        print(f'\n  Sample history (every ~20 trading days):')
        print(f'  {"Date":<14} {"% Uptrend":>10}')
        print(f'  {"-"*26}')
        for idx, row in sample.iterrows():
            print(f'  {str(idx):<14} {row["pct_uptrend"]:>8.0f}%')

        # Latest 30 days trend
        recent = df.tail(30)
        trend = 'rising' if recent["pct_uptrend"].iloc[-1] > recent["pct_uptrend"].iloc[0] else 'falling'
        print(f'\n  Last 30 days: {recent["pct_uptrend"].iloc[0]:.0f}% → {recent["pct_uptrend"].iloc[-1]:.0f}% ({trend})')

        # Save to CSV for reference
        out = os.path.join(os.path.dirname(__file__), 'data', 'market_breadth.csv')
        df.to_csv(out)
        print(f'\n  Saved to {out}')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
