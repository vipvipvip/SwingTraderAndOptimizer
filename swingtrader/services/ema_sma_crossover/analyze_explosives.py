#!/usr/bin/env python3
"""Analyze what differentiates explosive stocks at entry time.

For every multi-timeframe entry signal, record features at entry
and subsequent return to find what predicts explosive moves.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from collections import defaultdict
import db as db_module
import config

EMA = config.EMA_PERIOD
SMA = config.SMA_PERIOD
TS_START = datetime(2023, 6, 30)


def compute_ema_sma(close, ema_period=EMA, sma_period=SMA):
    series = pd.Series(close)
    ema = series.ewm(span=ema_period, adjust=False).mean().values
    sma = series.rolling(window=sma_period).mean().values
    return ema, sma


def batch_load_all(conn, ticker_ids, table, date_col, limit=500):
    """Load most recent bars for all tickers."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute(f"""
            SELECT ticker_id, {date_col} AS dt, close::float8 AS close,
                   volume, macd_histogram::float8, ppo_histogram::float8,
                   atr_stop::float8
            FROM (
                SELECT ticker_id, {date_col}, close, volume,
                       macd_histogram, ppo_histogram, atr_stop,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY {date_col} DESC) AS rn
                FROM {table}
                WHERE ticker_id = ANY(%s)
            ) sub
            WHERE rn <= %s
            ORDER BY ticker_id, {date_col} ASC
        """, (list(ticker_ids), limit))
        rows = cur.fetchall()
    finally:
        cur.close()
    return rows


def main():
    print('Loading data...')
    db_module.init_db()
    conn = db_module.get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled = true ORDER BY symbol')
            all_tickers = dict(cur.fetchall())

        ticker_ids = list(all_tickers.keys())
        id_to_symbol = all_tickers
        print(f'  {len(ticker_ids)} tickers')

        # Load ALL data for each timeframe — need maximum history
        weekly_raw = batch_load_all(conn, ticker_ids, 'tbl_scanner_tickers', 'date', limit=300)
        daily_raw = batch_load_all(conn, ticker_ids, 'tbl_scanner_tickers_daily', 'date', limit=1000)
        hourly_raw = batch_load_all(conn, ticker_ids, 'tbl_scanner_tickers_1hour', 'date', limit=2000)

        # Organize
        def organize(raw):
            by_tid = defaultdict(list)
            for r in raw:
                by_tid[r['ticker_id']].append({
                    'dt': r['dt'],
                    'close': float(r['close']),
                    'volume': int(r['volume']) if r['volume'] else 0,
                    'macd_hist': float(r['macd_histogram']) if r['macd_histogram'] else 0.0,
                    'ppo_hist': float(r['ppo_histogram']) if r['ppo_histogram'] else 0.0,
                    'atr_stop': float(r['atr_stop']) if r['atr_stop'] else None,
                })
            return by_tid

        weekly = organize(weekly_raw)
        daily = organize(daily_raw)
        hourly = organize(hourly_raw)

        all_entries = []
        skipped = 0

        for tid, sym in id_to_symbol.items():
            w = weekly.get(tid, [])
            d = daily.get(tid, [])
            h = hourly.get(tid, [])

            if len(w) < SMA + 10 or len(d) < SMA + 10 or len(h) < SMA + 10:
                skipped += 1
                continue

            w_close = np.array([x['close'] for x in w])
            d_close = np.array([x['close'] for x in d])
            h_close = np.array([x['close'] for x in h])

            w_vol = np.array([x['volume'] for x in w], dtype=float)
            d_vol = np.array([x['volume'] for x in d], dtype=float)
            h_vol = np.array([x['volume'] for x in h], dtype=float)

            w_ema, w_sma = compute_ema_sma(w_close)
            d_ema, d_sma = compute_ema_sma(d_close)
            h_ema, h_sma = compute_ema_sma(h_close)

            w_dates = [x['dt'] for x in w]
            d_dates = [x['dt'] for x in d]
            h_dates = [x['dt'] for x in h]

            # Walk through hourly bars looking for entry signals
            for hi in range(2, len(h)):
                h_dt = h_dates[hi]
                h_date = h_dt.date() if hasattr(h_dt, 'date') else h_dt

                # Align weekly/daily
                wi = next((j for j in range(len(w)-1, -1, -1) if w_dates[j] <= h_date), 0)
                di = next((j for j in range(len(d)-1, -1, -1) if d_dates[j] <= h_date), 0)

                if wi < 5 or di < 5:
                    continue

                if any(np.isnan(x) for x in (w_ema[wi], w_sma[wi], d_ema[di], d_sma[di],
                                              h_ema[hi], h_sma[hi], h_ema[hi-1], h_sma[hi-1])):
                    continue

                weekly_bullish = w_ema[wi] > w_sma[wi]
                daily_bullish = d_ema[di] > d_sma[di]
                hourly_fresh = h_ema[hi] > h_sma[hi] and h_ema[hi-1] <= h_sma[hi-1]
                w_fresh = wi > 0 and w_ema[wi] > w_sma[wi] and w_ema[wi-1] <= w_sma[wi-1]
                d_fresh = di > 0 and d_ema[di] > d_sma[di] and d_ema[di-1] <= d_sma[di-1]

                if not (weekly_bullish and daily_bullish and hourly_fresh):
                    continue

                entry_price = float(h[hi]['close'])
                entry_dt = h_dt

                # ── Features at entry ──
                # Days since weekly/daily turned bullish (last crossover date)
                w_cross_date = None
                for j in range(wi, 0, -1):
                    if w_ema[j] > w_sma[j] and w_ema[j-1] <= w_sma[j-1]:
                        w_cross_date = w_dates[j]
                        break
                days_since_weekly = (h_date - w_cross_date).days if w_cross_date else 999

                d_cross_date = None
                for j in range(di, 0, -1):
                    if d_ema[j] > d_sma[j] and d_ema[j-1] <= d_sma[j-1]:
                        d_cross_date = d_dates[j]
                        break
                days_since_daily = (h_date - d_cross_date).days if d_cross_date else 999

                # Gap from SMA(40)
                gap_w = (w_close[wi] - w_sma[wi]) / w_sma[wi] * 100
                gap_d = (d_close[di] - d_sma[di]) / d_sma[di] * 100
                gap_h = (h_close[hi] - h_sma[hi]) / h_sma[hi] * 100

                # Volume ratio (current vs 20-bar avg)
                def vol_ratio(vol_arr, idx, period=20):
                    if idx < period:
                        return 1.0
                    avg = np.mean(vol_arr[idx-period:idx])
                    return vol_arr[idx] / avg if avg > 0 else 1.0

                vol_ratio_w = vol_ratio(w_vol, wi, 10)
                vol_ratio_d = vol_ratio(d_vol, di, 20)
                vol_ratio_h = vol_ratio(h_vol, hi, 20)

                # MACD/PPO momentum
                macd_hist = float(h[hi]['macd_hist'])
                ppo_hist = float(h[hi]['ppo_hist'])
                macd_rising = hi > 0 and h[hi]['macd_hist'] > h[hi-1]['macd_hist']
                ppo_rising = hi > 0 and h[hi]['ppo_hist'] > h[hi-1]['ppo_hist']

                # ATR stop distance %
                atr_stop = float(h[hi]['atr_stop']) if h[hi]['atr_stop'] else None
                atr_dist = (entry_price - atr_stop) / entry_price * 100 if atr_stop and atr_stop > 0 else None

                # Price level
                price_level = entry_price

                # ── Forward return ──
                # Look ahead 30, 60, 90, 180, 365 days or to end
                future_max_90 = entry_price
                future_max_180 = entry_price
                future_return_90 = 0
                future_return_180 = 0
                max_drawdown_90 = 0

                for fj in range(hi + 1, min(hi + 1000, len(h))):
                    f_dt = h_dates[fj]
                    f_date = f_dt.date() if hasattr(f_dt, 'date') else f_dt
                    days_fwd = (f_date - h_date).days
                    f_price = float(h[fj]['close'])
                    fwd_ret = (f_price - entry_price) / entry_price * 100

                    if days_fwd <= 90:
                        future_max_90 = max(future_max_90, f_price)
                        max_drawdown_90 = min(max_drawdown_90, fwd_ret)
                    if days_fwd <= 180:
                        future_max_180 = max(future_max_180, f_price)

                    if days_fwd >= 90 and future_return_90 == 0:
                        future_return_90 = fwd_ret
                    if days_fwd >= 180 and future_return_180 == 0:
                        future_return_180 = fwd_ret
                        break

                if future_return_90 == 0:
                    continue

                all_entries.append({
                    'ticker': sym,
                    'entry_date': str(h_date),
                    'entry_price': entry_price,
                    'weekly_bullish': weekly_bullish,
                    'daily_bullish': daily_bullish,
                    'w_fresh_today': w_fresh,
                    'd_fresh_today': d_fresh,
                    'days_since_weekly': days_since_weekly,
                    'days_since_daily': days_since_daily,
                    'gap_w': gap_w,
                    'gap_d': gap_d,
                    'gap_h': gap_h,
                    'vol_ratio_w': vol_ratio_w,
                    'vol_ratio_d': vol_ratio_d,
                    'vol_ratio_h': vol_ratio_h,
                    'macd_hist': macd_hist,
                    'ppo_hist': ppo_hist,
                    'macd_rising': macd_rising,
                    'ppo_rising': ppo_rising,
                    'atr_dist': atr_dist,
                    'price': price_level,
                    'ret_90d': future_return_90,
                    'ret_180d': future_return_180,
                    'max_90d': (future_max_90 / entry_price - 1) * 100,
                    'max_180d': (future_max_180 / entry_price - 1) * 100,
                    'max_dd_90d': max_drawdown_90,
                })

        print(f'\n  Total entries found: {len(all_entries)}')
        print(f'  Skipped (insufficient data): {skipped}')

        if not all_entries:
            print('  No entries to analyze.')
            return

        df = pd.DataFrame(all_entries)

        # ── Analysis: what predicts top-decile 90-day return? ──
        df['explosive_90'] = df['ret_90d'] >= df['ret_90d'].quantile(0.9)

        print(f'\n{"="*90}')
        print(f'  TOP-DECILE 90-DAY RETURN ANALYSIS')
        print(f'  Top 10% threshold: {df["ret_90d"].quantile(0.9):+.1f}%')
        print(f'  Top decile count: {df["explosive_90"].sum()}')
        print(f'{"="*90}')

        features = [
            'days_since_weekly', 'days_since_daily',
            'gap_w', 'gap_d', 'gap_h',
            'vol_ratio_w', 'vol_ratio_d', 'vol_ratio_h',
            'macd_hist', 'ppo_hist', 'atr_dist', 'price',
        ]

        print(f'\n  {"Feature":<20} {"Top Decile":>12} {"Bottom 90%":>12} {"Diff":>12} {"Predictive":>10}')
        print(f'  {"-"*68}')
        for feat in features:
            if feat not in df.columns:
                continue
            top = df[df['explosive_90']][feat].median()
            bot = df[~df['explosive_90']][feat].median()
            # Simple predictive power: absolute difference / pooled std
            pooled_std = np.sqrt((df[feat].std()**2))
            pred = abs(top - bot) / pooled_std if pooled_std > 0 else 0
            diff_sym = '+' if top > bot else ''
            print(f'  {feat:<20} {top:>10.2f}  {bot:>10.2f}  {diff_sym}{(top-bot):>+9.2f}  {pred:>8.3f}')

        # ── Best features separate by quantiles ──
        print(f'\n\n  TOP FEATURES BY RETURN QUANTILE:')
        print(f'  {"="*90}')
        df['ret_quantile'] = pd.qcut(df['ret_90d'], 5, labels=['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)'])

        for feat in ['days_since_weekly', 'gap_w', 'vol_ratio_h', 'macd_hist', 'price']:
            if feat not in df.columns:
                continue
            print(f'\n  {feat} by return quantile:')
            for q in ['Q1(worst)', 'Q2', 'Q3', 'Q4', 'Q5(best)']:
                vals = df[df['ret_quantile'] == q][feat]
                print(f'    {q:<12} median={vals.median():>10.2f}  mean={vals.mean():>10.2f}  count={len(vals)}')

        # ── Show explosive entries ──
        explosive = df[df['explosive_90']].sort_values('ret_90d', ascending=False)
        print(f'\n\n  EXPLOSIVE ENTRIES (top decile 90d return):')
        print(f'  {"Ticker":<8} {"Date":<12} {"Ret90d":>8} {"Max90d":>8} {"DaysWk":>7} {"GapW%":>7} {"GapH%":>7} {"VolH":>7} {"MACD":>7} {"Price":>8}')
        print(f'  {"-"*80}')
        for _, r in explosive.head(30).iterrows():
            print(f'  {r["ticker"]:<8} {r["entry_date"]:<12} {r["ret_90d"]:>+7.1f}% {r["max_90d"]:>+7.1f}% '
                  f'{r["days_since_weekly"]:>5d}d {r["gap_w"]:>+6.1f}% {r["gap_h"]:>+6.1f}% '
                  f'{r["vol_ratio_h"]:>6.1f}x {r["macd_hist"]:>+6.2f} ${r["price"]:>6.2f}')

        # ── Worst entries ──
        worst = df.nsmallest(20, 'ret_90d')
        print(f'\n\n  WORST ENTRIES (bottom 20):')
        print(f'  {"Ticker":<8} {"Date":<12} {"Ret90d":>8} {"Max90d":>8} {"DaysWk":>7} {"GapW%":>7} {"GapH%":>7} {"VolH":>7} {"MACD":>7} {"Price":>8}')
        print(f'  {"-"*80}')
        for _, r in worst.iterrows():
            print(f'  {r["ticker"]:<8} {r["entry_date"]:<12} {r["ret_90d"]:>+7.1f}% {r["max_90d"]:>+7.1f}% '
                  f'{r["days_since_weekly"]:>5d}d {r["gap_w"]:>+6.1f}% {r["gap_h"]:>+6.1f}% '
                  f'{r["vol_ratio_h"]:>6.1f}x {r["macd_hist"]:>+6.2f} ${r["price"]:>6.2f}')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
