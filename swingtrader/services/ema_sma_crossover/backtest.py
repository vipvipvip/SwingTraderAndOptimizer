#!/usr/bin/env python3
"""Proper backtest using real 30-min historical bars from Alpaca."""
import argparse
import numpy as np
import pandas as pd
from datetime import datetime

import config
from price_collector import fetch_all_30min_bars


def _bars_to_df(bars):
    """Convert Alpaca bar dicts to a DataFrame indexed by timestamp (NY time)."""
    records = []
    for b in bars:
        records.append({
            'timestamp': b['t'],
            'open': float(b['o']),
            'high': float(b['h']),
            'low': float(b['l']),
            'close': float(b['c']),
            'volume': int(b['v']),
        })
    df = pd.DataFrame(records)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df = df.sort_index()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    return df


def run_backtest(df):
    n = len(df)
    if n < config.SMA_PERIOD + 2:
        return None

    open_p = df['open'].values.astype(float)
    close_p = df['close'].values.astype(float)

    close_series = pd.Series(close_p)
    ema_fast = close_series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma_slow = close_series.rolling(window=config.SMA_PERIOD).mean().values
    macd_fast = close_series.ewm(span=config.MACD_FAST, adjust=False).mean()
    macd_slow = close_series.ewm(span=config.MACD_SLOW, adjust=False).mean()
    macd_line = (macd_fast - macd_slow).values
    macd_signal = pd.Series(macd_line).ewm(span=config.MACD_SIGNAL, adjust=False).mean().values
    macd_hist = macd_line - macd_signal
    warmup = max(config.SMA_PERIOD, config.MACD_SIGNAL) + 1

    cost = config.COST_PER_TRADE
    capital = config.INITIAL_CAPITAL

    trades = []
    bar_equity = [capital]
    trade_equity = [capital]
    trade_dates = [str(df.index[0])]

    in_pos = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = capital

    for i in range(warmup, n):
        po = open_p[i]
        pc = close_p[i]

        if pending_exit and in_pos:
            allocated = equity_before
            deployed = allocated * (1 - cost)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - cost)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed

            trades.append({
                'entry_price': entry_price,
                'exit_price': po,
                'entry_at': str(df.index[entry_idx]),
                'exit_at': str(df.index[i]),
                'return': net_pnl,
                'pnl_dollar': net_dollar,
                'bars_held': i - entry_idx,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(df.index[i]))
            in_pos = False
            pending_exit = False

        if pending_entry and not in_pos:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            in_pos = True
            pending_entry = False

        if not in_pos and not pending_entry:
            if (not np.isnan(ema_fast[i]) and not np.isnan(sma_slow[i]) and not np.isnan(macd_hist[i])
                    and not np.isnan(ema_fast[i - 1]) and not np.isnan(sma_slow[i - 1]) and not np.isnan(macd_hist[i - 1])):
                ema_gt = ema_fast[i] > sma_slow[i]
                prev_ema_gt = ema_fast[i - 1] > sma_slow[i - 1]
                macd_gt = macd_hist[i] > 0
                prev_macd_gt = macd_hist[i - 1] > 0
                both_ok = ema_gt and macd_gt
                either_just_flipped = (ema_gt != prev_ema_gt) or (macd_gt != prev_macd_gt)
                if both_ok and either_just_flipped:
                    pending_entry = True

        if in_pos and not pending_exit:
            if (not np.isnan(ema_fast[i]) and not np.isnan(sma_slow[i]) and not np.isnan(macd_hist[i])
                    and not np.isnan(ema_fast[i - 1]) and not np.isnan(sma_slow[i - 1]) and not np.isnan(macd_hist[i - 1])):
                ema_lt = ema_fast[i] < sma_slow[i]
                prev_ema_lt = ema_fast[i - 1] < sma_slow[i - 1]
                macd_lt = macd_hist[i] < 0
                prev_macd_lt = macd_hist[i - 1] < 0
                both_ok = ema_lt and macd_lt
                either_just_flipped = (ema_lt != prev_ema_lt) or (macd_lt != prev_macd_lt)
                if both_ok and either_just_flipped:
                    pending_exit = True

        if i == n - 1 and in_pos:
            simulated_close = not pending_exit
            allocated = equity_before
            deployed = allocated * (1 - cost)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - cost)
            net_dollar = net_proceeds - deployed

            trades.append({
                'entry_price': entry_price,
                'exit_price': pc,
                'entry_at': str(df.index[entry_idx]),
                'exit_at': str(df.index[i]),
                'return': net_dollar / deployed,
                'pnl_dollar': net_dollar,
                'bars_held': i - entry_idx,
                'simulated_close': simulated_close,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(df.index[i]))
            in_pos = False
            pending_exit = False

        if in_pos:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if not trades:
        return None, _empty(), None, None

    trades_df = pd.DataFrame(trades)
    wins = (trades_df['return'] > 0).sum()
    metrics = {
        'total_trades': len(trades_df),
        'winning_trades': int(wins),
        'win_rate': wins / len(trades_df),
        'avg_return': float(trades_df['return'].mean()),
        'total_return': (trade_equity[-1] - capital) / capital,
        'sharpe_ratio': _calc_sharpe_30min(bar_equity),
        'max_drawdown': _calc_max_dd(trade_equity),
        'avg_bars_held': float(trades_df['bars_held'].mean()),
    }
    return trades, metrics, trade_equity, trade_dates


def _calc_sharpe_30min(equity_curve):
    """Annualized Sharpe for 30-min data: 14 bars/day × 252 days = 3528 periods/year."""
    if len(equity_curve) < 2:
        return 0
    returns = pd.Series(equity_curve).pct_change().dropna()
    if len(returns) == 0 or returns.std() == 0:
        return 0
    periods = 3528
    return (returns.mean() * periods) / (returns.std() * (periods ** 0.5))


def _calc_max_dd(eq):
    peak = eq[0]
    dd = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = max(dd, (peak - v) / peak)
    return dd


def _empty():
    return {'total_trades': 0, 'winning_trades': 0, 'win_rate': 0,
            'avg_return': 0, 'total_return': 0, 'sharpe_ratio': 0, 'max_drawdown': 0,
            'avg_bars_held': 0}


def store_results(conn, ticker_id, symbol, trades, metrics, equity, dates):
    """Store backtest results to emac_candles (for warm-start) and emac_trades."""
    pass  # Future: store for warm-start



def main():
    parser = argparse.ArgumentParser(
        'EMA(10)/SMA(40) 30-min crossover — live backtest')
    parser.add_argument('--tickers', nargs='+', default=config.TICKERS)
    args = parser.parse_args()

    print()
    print('=' * 95)
    print(f'  EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) + MACD({config.MACD_FAST},{config.MACD_SLOW},{config.MACD_SIGNAL}) — 30-MIN BACKTEST')
    print(f'  Using REAL 30-min bars from Alpaca')
    print(f'  Entry: EMA> SMA & MACD hist>0  |  Exit: EMA< SMA & MACD hist<0')
    print(f'  Position: ${config.INITIAL_CAPITAL:,.0f} per ticker')
    print('=' * 95)

    results = []
    for sym in args.tickers:
        print(f'\n[{sym}] Fetching historical 30-min bars...')
        bars = fetch_all_30min_bars(sym)
        if not bars:
            print(f'  ✗ No data')
            continue

        df = _bars_to_df(bars)
        print(f'  {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})')

        trades, metrics, eq, eq_dates = run_backtest(df)

        if not trades:
            print(f'  ✗ No trades generated')
            continue

        print(f'  Trades:    {metrics["total_trades"]}  '
              f'({metrics["winning_trades"]}W / {metrics["total_trades"] - metrics["winning_trades"]}L)')
        print(f'  Win Rate:  {metrics["win_rate"]*100:.1f}%')
        print(f'  Avg Ret:   {metrics["avg_return"]*100:+.2f}% per trade')
        print(f'  Avg Hold:  {metrics["avg_bars_held"]:.0f} bars ({metrics["avg_bars_held"]*0.5:.1f}h)')
        print(f'  Total Ret: {metrics["total_return"]*100:+.2f}%')
        print(f'  Sharpe:    {metrics["sharpe_ratio"]:.2f}')
        print(f'  Max DD:    {metrics["max_drawdown"]*100:.1f}%')
        results.append((sym, metrics, trades))

    if results:
        print()
        print('=' * 95)
        print('  SUMMARY')
        print('=' * 95)
        print(f'  {"Ticker":<8} {"Trades":<8} {"Win%":<8} {"Avg Ret":<10} {"Total Ret":<12} {"Sharpe":<8} {"Max DD":<8} {"Avg Bars":<8}')
        print(f'  {"-"*70}')
        for sym, m, _ in results:
            print(f'  {sym:<8} {m["total_trades"]:<8} {m["win_rate"]*100:>6.1f}% '
                  f'{m["avg_return"]*100:>+8.2f}% {m["total_return"]*100:>+10.2f}% '
                  f'{m["sharpe_ratio"]:>8.2f} {m["max_drawdown"]*100:>6.1f}% '
                  f'{m["avg_bars_held"]:>6.0f}')
        print(f'  {"-"*70}')
        avg_s = np.mean([r[1]['sharpe_ratio'] for r in results])
        avg_r = np.mean([r[1]['total_return'] for r in results])
        avg_w = np.mean([r[1]['win_rate'] for r in results])
        tot_t = sum(r[1]['total_trades'] for r in results)
        print(f'  {"AVG":<8} {tot_t:<8} {avg_w*100:>6.1f}%           '
              f'{avg_r*100:>+10.2f}% {avg_s:>8.2f}')
        print()

    return 0 if results else 1


if __name__ == '__main__':
    main()
