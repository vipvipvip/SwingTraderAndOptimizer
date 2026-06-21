"""Portfolio test: all 3 tickers together with Chand+Reg exit"""
"""
How to run
The script imports from the optimizer package but Python can't find it. Add the optimizer directory to the path:
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/optimizer && source venv/bin/activate && PYTHONPATH=. python3 /home/dikesh/data/dev/SwingTraderAndOptimizer/common/scripts/test_scripts/test_portfolio_chandreg.py

"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
from parameter_optimizer import ParameterOptimizer
from test_regression_walkforward import backtest_regression, linear_reg_slope
from data_fetcher import load_data_from_db


def backtest_portfolio_cr(ticker_data, ticker_params, period=18, mult=3.5, entry_mult=1.0,
                          initial_capital=100000, cost_per_trade=0.0005):
    """Portfolio backtest with per-ticker Chandelier+Reg exit params.
    
    ticker_params: {symbol: {'reg_window': int, 'reg_threshold': float, 'reg_type': str} or None for baseline}
    """
    tickers = list(ticker_data.keys())
    empty = {'total_trades': 0, 'winning_trades': 0, 'win_rate': 0,
             'avg_return': 0, 'total_return': 0, 'sharpe_ratio': 0, 'max_drawdown': 0}
    if not tickers:
        return [], empty, [], []

    # Align data
    aligned = {}
    for sym, df in ticker_data.items():
        d = df.copy()
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in d.columns:
                d[col] = d[col].astype(float)
        daily_mask = (d.index.minute == 0) & (d.index.hour.isin([4, 5]))
        if daily_mask.any():
            d = d[daily_mask].copy()
            d.index = d.index.normalize()
        aligned[sym] = d

    common_index = aligned[tickers[0]].index
    for sym in tickers[1:]:
        common_index = common_index.intersection(aligned[sym].index)

    # Precompute ATR, rolling high, and regression slope for each ticker
    atr_data = {}
    rolling_high_data = {}
    slope_data = {}
    for sym in tickers:
        d = aligned[sym].loc[common_index]
        prev_close = d['close'].shift(1)
        tr = pd.concat([
            d['high'] - d['low'],
            (d['high'] - prev_close).abs(),
            (d['low'] - prev_close).abs()
        ], axis=1).max(axis=1)
        atr_data[sym] = tr.rolling(window=period).mean()
        rolling_high_data[sym] = d['high'].rolling(window=period, min_periods=1).max()
        aligned[sym] = d

        # Regression slope
        p = ticker_params.get(sym)
        if p and p.get('mode') != 'chandelier':
            w = p['reg_window']
            close_vals = d['close'].values.astype(float)
            slp = np.full(len(close_vals), np.nan)
            raw = linear_reg_slope(close_vals, w)
            rt = p['reg_type']
            atr_arr = atr_data[sym].values
            close_arr = d['close'].values.astype(float)
            for i in range(len(close_vals)):
                if np.isnan(raw[i]):
                    continue
                if rt == 'slope_atr':
                    if atr_arr[i] and not np.isnan(atr_arr[i]) and atr_arr[i] > 0:
                        slp[i] = raw[i] / atr_arr[i]
                elif rt == 'slope_pct':
                    if close_arr[i] > 0:
                        slp[i] = raw[i] / close_arr[i] * 100
                else:
                    slp[i] = raw[i]
            slope_data[sym] = slp

    warmup = period
    cash = initial_capital
    positions = {}
    pend_entry = {sym: False for sym in tickers}
    pend_exit = {sym: False for sym in tickers}
    high_since = {sym: 0.0 for sym in tickers}

    trades = []
    equity_curve = [initial_capital]
    equity_dates = [str(common_index[0])]

    for i in range(len(common_index)):
        if i < warmup:
            continue
        date = common_index[i]

        for sym in list(positions.keys()):
            if not pend_exit[sym]:
                continue
            ep = aligned[sym]['open'].iloc[i]
            pos = positions[sym]
            cost = pos['shares'] * pos['entry_price']
            net = pos['shares'] * ep * (1 - cost_per_trade)
            pnl = net - cost
            trades.append({
                'symbol': sym, 'entry_price': pos['entry_price'], 'exit_price': ep,
                'entry_at': pos['entry_at'], 'exit_at': str(date),
                'return': pnl / cost if cost else 0, 'pnl_dollar': pnl, 'pnl_pct': pnl / cost if cost else 0,
                'days_held': round(i - pos['entry_idx'], 1), 'simulated_close': False,
            })
            cash += pos['shares'] * ep * (1 - cost_per_trade)
            del positions[sym]
            pend_exit[sym] = False

        entering = [sym for sym in tickers if pend_entry[sym] and sym not in positions]
        if entering and cash > 0:
            amount_each = cash / len(entering)
            total_eq = cash + sum(
                pos['shares'] * aligned[s]['close'].iloc[i] for s, pos in positions.items()
            )
            for sym in entering:
                ep = aligned[sym]['open'].iloc[i]
                shares = amount_each * (1 - cost_per_trade) / ep if ep > 0 else 0
                positions[sym] = {
                    'shares': shares, 'entry_price': ep, 'entry_idx': i,
                    'entry_at': str(date), 'allocation_pct': round(amount_each / total_eq * 100, 2) if total_eq else 0,
                }
                high_since[sym] = aligned[sym]['high'].iloc[i]
                pend_entry[sym] = False
                cash -= amount_each

        for sym in tickers:
            close = aligned[sym]['close'].iloc[i]
            high = aligned[sym]['high'].iloc[i]
            p = ticker_params.get(sym)

            if sym in positions and not pend_exit[sym]:
                high_since[sym] = max(high_since[sym], high)
                if p and p.get('mode') != 'chandelier':
                    reg_hit = (not np.isnan(slope_data[sym][i]) and slope_data[sym][i] < p['reg_threshold'])
                else:
                    reg_hit = False
                ch_hit = close < high_since[sym] - atr_data[sym].iloc[i] * mult
                if ch_hit or reg_hit:
                    pend_exit[sym] = True

            if sym not in positions and not pend_entry[sym]:
                if close > rolling_high_data[sym].iloc[i] - atr_data[sym].iloc[i] * entry_mult:
                    pend_entry[sym] = True

        if i == len(common_index) - 1:
            for sym, pos in list(positions.items()):
                ep = aligned[sym]['close'].iloc[i]
                cost = pos['shares'] * pos['entry_price']
                net = pos['shares'] * ep * (1 - cost_per_trade)
                pnl = net - cost
                trades.append({
                    'symbol': sym, 'entry_price': pos['entry_price'], 'exit_price': ep,
                    'entry_at': pos['entry_at'], 'exit_at': str(date),
                    'return': pnl / cost if cost else 0, 'pnl_dollar': pnl, 'pnl_pct': pnl / cost if cost else 0,
                    'days_held': round(i - pos['entry_idx'], 1), 'simulated_close': not pend_exit.get(sym, False),
                })
                cash += pos['shares'] * ep * (1 - cost_per_trade)
                del positions[sym]

        equity = cash + sum(
            pos['shares'] * aligned[sym]['close'].iloc[i] for sym, pos in positions.items()
        )
        equity_curve.append(equity)
        equity_dates.append(str(date))

    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        metrics = {
            'total_trades': len(trades_df),
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df) if len(trades_df) else 0,
            'avg_return': float(trades_df['return'].mean()),
            'total_return': (equity_curve[-1] - initial_capital) / initial_capital,
            'sharpe_ratio': ParameterOptimizer._calculate_sharpe(equity_curve),
            'max_drawdown': ParameterOptimizer._calculate_max_drawdown(equity_curve),
        }
    else:
        metrics = empty

    return trades, metrics, equity_curve, equity_dates


def run():
    print("=" * 70)
    print("PORTFOLIO BACKTEST — QQQ + VTI + VTV")
    print("=" * 70)

    tickers = ['QQQ', 'VTI', 'VTV']
    ticker_data = {}
    for sym in tickers:
        df = load_data_from_db(sym)
        if df is None:
            print(f"Failed to load {sym}")
            sys.exit(1)
        ticker_data[sym] = df

    # Best params from full-data grid scan
    paramsets = {
        'QQQ': {'mode': 'chandelier_or_reg', 'reg_window': 8, 'reg_threshold': -0.5, 'reg_type': 'slope_atr'},
        'VTI': {'mode': 'chandelier_or_reg', 'reg_window': 10, 'reg_threshold': -0.3, 'reg_type': 'slope_pct'},
        'VTV': {'mode': 'chandelier_or_reg', 'reg_window': 3, 'reg_threshold': -1.0, 'reg_type': 'slope_pct'},
    }

    # Also try second-best params
    paramsets2 = {
        'QQQ': {'mode': 'chandelier_or_reg', 'reg_window': 4, 'reg_threshold': -0.3, 'reg_type': 'slope_pct'},
        'VTI': {'mode': 'chandelier_or_reg', 'reg_window': 3, 'reg_threshold': -1.5, 'reg_type': 'slope_pct'},
        'VTV': {'mode': 'chandelier_or_reg', 'reg_window': 8, 'reg_threshold': -0.3, 'reg_type': 'slope_pct'},
    }

    # Baseline: all Chandelier-only
    base_params = {sym: {'mode': 'chandelier'} for sym in tickers}

    for label, pset in [('Baseline (Chandelier only)', base_params),
                        ('Chand+Reg (per-ticker best)', paramsets),
                        ('Chand+Reg (per-ticker alt)', paramsets2)]:
        trades, metrics, eq, dates = backtest_portfolio_cr(ticker_data, pset)
        by_sym = {}
        for t in trades:
            by_sym.setdefault(t['symbol'], []).append(t)

        print(f"\n{label}:")
        print(f"  Portfolio: {metrics['total_return']*100:.2f}%  {metrics['total_trades']}t  "
              f"Sharpe {metrics['sharpe_ratio']:.2f}  MaxDD {metrics['max_drawdown']*100:.1f}%")
        for sym in tickers:
            st = by_sym.get(sym, [])
            if st:
                rets = [t['return'] for t in st]
                wins = sum(1 for r in rets if r > 0)
                print(f"    {sym}: {len(st)}t  {wins/len(st)*100:.0f}% wins  "
                      f"{sum(rets)/len(rets)*100:.2f}% avg  {sum(rets)*100:.2f}% total")


if __name__ == '__main__':
    run()
