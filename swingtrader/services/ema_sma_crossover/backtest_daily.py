#!/usr/bin/env python3
"""Backtest: EMA(10)/SMA(40) crossover on DAILY bars using DB data."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import config
import db as db_module

CAPITAL = config.INITIAL_CAPITAL
COST = config.COST_PER_TRADE

def run(df):
    close = df['close'].values.astype(float)
    series = pd.Series(close)
    ema = series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma = series.rolling(window=config.SMA_PERIOD).mean().values

    warmup = config.SMA_PERIOD + 1
    n = len(close)

    trades = []
    equity = CAPITAL
    in_pos = False
    entry_price = 0
    eq_curve = [equity]

    for i in range(warmup, n):
        if np.isnan(ema[i]) or np.isnan(sma[i]) or np.isnan(ema[i-1]) or np.isnan(sma[i-1]):
            continue

        if not in_pos:
            if ema[i] > sma[i]:  # enter on open next day
                entry_price = df['open'].iloc[i]
                in_pos = True
        else:
            if ema[i] < sma[i] and ema[i-1] >= sma[i-1]:  # EMA crossed below
                exit_price = df['open'].iloc[i]
                ret = (exit_price - entry_price) / entry_price - COST
                trades.append({'entry_price': entry_price, 'exit_price': exit_price,
                               'entry_at': str(df.index[i-1].date()), 'exit_at': str(df.index[i].date()),
                               'return': ret})
                equity *= (1 + ret)
                in_pos = False

        if in_pos:
            eq_curve.append(equity / entry_price * df['close'].iloc[i])
        else:
            eq_curve.append(equity)

    if in_pos:
        exit_price = df['close'].iloc[-1]
        ret = (exit_price - entry_price) / entry_price - COST
        trades.append({'entry_price': entry_price, 'exit_price': exit_price,
                       'entry_at': str(df.index[-1].date()), 'exit_at': str(df.index[-1].date()),
                       'return': ret, 'simulated_close': True})
        equity *= (1 + ret)

    if not trades:
        return None, {'total_trades': 0, 'winning_trades': 0, 'win_rate': 0,
                      'avg_return': 0, 'total_return': 0, 'max_drawdown': 0}

    trades_df = pd.DataFrame(trades)
    wins = (trades_df['return'] > 0).sum()
    eq_arr = np.array(eq_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = np.max((peak - eq_arr) / peak)
    metrics = {
        'total_trades': len(trades_df),
        'winning_trades': int(wins),
        'win_rate': wins / len(trades_df),
        'avg_return': float(trades_df['return'].mean()),
        'total_return': (equity - CAPITAL) / CAPITAL,
        'max_drawdown': float(dd),
    }
    return trades, metrics

def main():
    db_module.init_db()
    conn = db_module.get_conn()
    try:
        print(f'\n{"="*90}')
        print(f'  EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) — DAILY BAR BACKTEST (from DB)')
        print(f'  Entry: EMA > SMA  |  Exit: EMA crosses below SMA')
        print(f'{"="*90}\n')

        results = []
        for sym in config.TICKERS:
            tid = db_module.get_ticker_id(conn, sym)
            if not tid:
                print(f'[{sym}] ✗ No ticker_id')
                continue
            rows = db_module.get_daily_candles(conn, tid, limit=2000)
            if not rows:
                print(f'[{sym}] ✗ No daily data')
                continue
            df = pd.DataFrame(rows, columns=['ts','open','high','low','close','volume'])
            for c in ['open','high','low','close','volume']:
                df[c] = df[c].astype(float)
            df['ts'] = pd.to_datetime(df['ts'])
            df.set_index('ts', inplace=True)
            print(f'[{sym}] {len(df)} daily bars  ({df.index[0].date()} → {df.index[-1].date()})')
            bh_ret = (df['close'].iloc[-1] - df['close'].iloc[0]) / df['close'].iloc[0]
            print(f'  BH Ret:  {bh_ret*100:+.2f}%')

            trades, metrics = run(df)
            if not trades:
                print(f'  ✗ No trades\n')
                continue

            print(f'  Trades:   {metrics["total_trades"]}  ({metrics["winning_trades"]}W / {metrics["total_trades"] - metrics["winning_trades"]}L)')
            print(f'  Win Rate: {metrics["win_rate"]*100:.1f}%')
            print(f'  Avg Ret:  {metrics["avg_return"]*100:+.2f}% per trade')
            print(f'  Total:    {metrics["total_return"]*100:+.2f}%')
            print(f'  Max DD:   {metrics["max_drawdown"]*100:.1f}%')
            print(f'  vs BH:    {(metrics["total_return"] - bh_ret)*100:+.2f}%\n')
            results.append((sym, metrics, bh_ret, trades))

        if results:
            print(f'{"="*90}')
            print(f'  SUMMARY')
            print(f'{"="*90}')
            print(f'  {"Ticker":<8} {"Trades":<8} {"Win%":<8} {"Avg Ret":<10} {"Total Ret":<12} {"Max DD":<8} {"BH Ret":<10} {"vs BH":<10}')
            print(f'  {"-"*76}')
            for sym, m, bh, _ in results:
                print(f'  {sym:<8} {m["total_trades"]:<8} {m["win_rate"]*100:>6.1f}% {m["avg_return"]*100:>+8.2f}% {m["total_return"]*100:>+10.2f}% {m["max_drawdown"]*100:>6.1f}% {bh*100:>+8.2f}% {(m["total_return"]-bh)*100:>+8.2f}%')
            avg_r = np.mean([r[1]['total_return'] for r in results])
            avg_w = np.mean([r[1]['win_rate'] for r in results])
            tot = sum(r[1]['total_trades'] for r in results)
            avg_bh = np.mean([r[2] for r in results])
            avg_vs = np.mean([r[1]['total_return'] - r[2] for r in results])
            print(f'  {"-"*76}')
            print(f'  {"AVG":<8} {tot:<8} {avg_w*100:>6.1f}%           {avg_r*100:>+10.2f}%              {avg_bh*100:>+8.2f}% {avg_vs*100:>+8.2f}%')
            print()

    finally:
        conn.close()

if __name__ == '__main__':
    main()
