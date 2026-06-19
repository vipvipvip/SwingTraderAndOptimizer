#!/usr/bin/env python3
"""Backtest estimation: EMA(10)/SMA(40) crossover using 1-hour bars as proxy.

Since we can't backtest 30-min candles directly (no data available), this uses
1-hour bars with the same period parameters to estimate strategy viability.

Strategy:
  - BUY:  EMA(10) crosses above SMA(40)
  - SELL: EMA(10) crosses below SMA(40)
  - Exit on opposite crossover (not a fixed stop)
"""
import argparse
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'database': 'swingtrader',
    'user': 'swingtrader',
    'password': 'swingtrader_dev_password',
}

TICKERS = ['QQQ', 'VTI', 'VTV']

EMA_PERIOD = 10
SMA_PERIOD = 40


def load_hourly_bars(symbol):
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT b.timestamp, b.open, b.high, b.low, b.close, b.volume
FROM tbl_etf_tickers_1hour b
JOIN tbl_etf_tickers t ON b.ticker_id = t.id
                WHERE t.symbol = %s
                ORDER BY b.timestamp
            ''', (symbol,))
            rows = cur.fetchall()
            if not rows:
                return None
            cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            df = pd.DataFrame(rows, columns=cols)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df.set_index('timestamp', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
    finally:
        conn.close()


def compute_ema_sma(close_prices, fast_period, slow_period):
    close = pd.Series(close_prices)
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    sma_slow = close.rolling(window=slow_period).mean()
    return ema_fast.values, sma_slow.values


def run_backtest(df):
    n = len(df)
    if n < SMA_PERIOD + 2:
        return None, None, None, None

    open_p = df['open'].values.astype(float)
    close_p = df['close'].values.astype(float)

    ema_fast, sma_slow = compute_ema_sma(close_p, EMA_PERIOD, SMA_PERIOD)
    warmup = SMA_PERIOD + 1

    cost_per_trade = 0.0005
    initial_capital = 100000.0

    trades = []
    bar_equity = [initial_capital]
    trade_equity = [initial_capital]
    trade_dates = [str(df.index[0])]

    position_active = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = initial_capital

    for i in range(warmup, n):
        po = open_p[i]
        pc = close_p[i]

        if pending_exit and position_active:
            allocated = equity_before
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed

            trades.append({
                'entry_price': entry_price,
                'exit_price': po,
                'entry_at': str(df.index[entry_idx]),
                'exit_at': str(df.index[i]),
                'return': net_pnl,
                'pnl_dollar': net_dollar,
                'pnl_pct': net_pnl,
                'bars_held': i - entry_idx,
                'exit_type': 'ema_sma_sell',
            })

            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(df.index[i]))
            position_active = False
            pending_exit = False

        if pending_entry and not position_active:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            position_active = True
            pending_entry = False

        if not position_active and not pending_entry:
            if (not np.isnan(ema_fast[i]) and not np.isnan(sma_slow[i])
                    and not np.isnan(ema_fast[i - 1]) and not np.isnan(sma_slow[i - 1])):
                if ema_fast[i] > sma_slow[i] and ema_fast[i - 1] <= sma_slow[i - 1]:
                    pending_entry = True

        if position_active and not pending_exit:
            if (not np.isnan(ema_fast[i]) and not np.isnan(sma_slow[i])
                    and not np.isnan(ema_fast[i - 1]) and not np.isnan(sma_slow[i - 1])):
                if ema_fast[i] < sma_slow[i] and ema_fast[i - 1] >= sma_slow[i - 1]:
                    pending_exit = True

        if i == n - 1 and position_active:
            simulated_close = not pending_exit
            allocated = equity_before
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed

            trades.append({
                'entry_price': entry_price,
                'exit_price': pc,
                'entry_at': str(df.index[entry_idx]),
                'exit_at': str(df.index[i]),
                'return': net_pnl,
                'pnl_dollar': net_dollar,
                'pnl_pct': net_pnl,
                'bars_held': i - entry_idx,
                'simulated_close': simulated_close,
                'exit_type': 'force_close' if simulated_close else 'ema_sma_sell',
            })

            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(df.index[i]))
            position_active = False
            pending_exit = False

        if position_active:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        sharpe = _calc_sharpe(bar_equity)
        metrics = {
            'total_trades': len(trades_df),
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'total_return': (trade_equity[-1] - initial_capital) / initial_capital,
            'sharpe_ratio': sharpe,
            'max_drawdown': _calc_max_dd(trade_equity),
        }
    else:
        metrics = _empty_metrics()
        trades = []

    return trades, metrics, trade_equity, trade_dates


def _calc_sharpe(equity_curve):
    if len(equity_curve) < 2:
        return 0
    returns = pd.Series(equity_curve).pct_change().dropna()
    if len(returns) == 0 or returns.std() == 0:
        return 0
    periods = 252 * 6.5
    return (returns.mean() * periods) / (returns.std() * (periods ** 0.5))


def _calc_max_dd(equity_curve):
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _empty_metrics():
    return {
        'total_trades': 0, 'winning_trades': 0, 'win_rate': 0,
        'avg_return': 0, 'total_return': 0, 'sharpe_ratio': 0, 'max_drawdown': 0,
    }


def main():
    parser = argparse.ArgumentParser(description='EMA(10)/SMA(40) backtest estimator (1-hour proxy)')
    parser.add_argument('--tickers', nargs='+', default=TICKERS, help='Tickers to backtest')
    args = parser.parse_args()

    print(f'\n{"="*90}')
    print(f'  EMA({EMA_PERIOD}) / SMA({SMA_PERIOD}) CROSSOVER — BACKTEST ESTIMATION')
    print(f'  Data: 1-hour bars as proxy (no 30-min data available)')
    print(f'  Entry: EMA crosses ABOVE SMA  |  Exit: EMA crosses BELOW SMA')
    print(f'{"="*90}\n')

    results = []
    for sym in args.tickers:
        print(f'[{sym}] Loading 1-hour bars...')
        df = load_hourly_bars(sym)
        if df is None or len(df) == 0:
            print(f'  ✗ No data found\n')
            continue

        print(f'  Data: {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})')
        trades, metrics, eq, eq_dates = run_backtest(df)

        if trades and metrics['total_trades'] > 0:
            print(f'  Trades:    {metrics["total_trades"]}  '
                  f'({metrics["winning_trades"]} wins / {metrics["total_trades"] - metrics["winning_trades"]} losses)')
            print(f'  Win Rate:  {metrics["win_rate"]*100:.1f}%')
            print(f'  Avg Ret:   {metrics["avg_return"]*100:+.2f}% per trade')
            print(f'  Total Ret: {metrics["total_return"]*100:+.2f}%')
            print(f'  Sharpe:    {metrics["sharpe_ratio"]:.2f}')
            print(f'  Max DD:    {metrics["max_drawdown"]*100:.1f}%\n')

            results.append((sym, metrics, trades, eq, eq_dates))
        else:
            print(f'  ✗ No trades generated\n')

    if results:
        print(f'{"="*90}')
        print(f'  SUMMARY')
        print(f'{"="*90}')
        print(f'  {"Ticker":<8} {"Trades":<8} {"Win%":<8} {"Avg Ret":<10} {"Total Ret":<12} {"Sharpe":<8} {"Max DD":<8}')
        print(f'  {"-"*62}')
        for sym, m, *_ in results:
            print(f'  {sym:<8} {m["total_trades"]:<8} {m["win_rate"]*100:>6.1f}% '
                  f'{m["avg_return"]*100:>+8.2f}% {m["total_return"]*100:>+10.2f}% '
                  f'{m["sharpe_ratio"]:>8.2f} {m["max_drawdown"]*100:>6.1f}%')

        avg_sharpe = np.mean([r[1]['sharpe_ratio'] for r in results])
        avg_return = np.mean([r[1]['total_return'] for r in results])
        avg_win = np.mean([r[1]['win_rate'] for r in results])
        avg_per_trade = np.mean([r[1]['avg_return'] for r in results])
        total_trades = sum(r[1]['total_trades'] for r in results)
        print(f'  {"-"*62}')
        print(f'  {"AVG":<8} {total_trades:<8} {avg_win*100:>6.1f}% '
              f'{avg_per_trade*100:>+8.2f}% {avg_return*100:>+10.2f}% '
              f'{avg_sharpe:>8.2f}')
        print()

    return 0 if results else 1


if __name__ == '__main__':
    main()
