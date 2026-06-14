"""Test regression-based exits against current Chandelier exit on QQQ"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer


def linear_reg_slope(close_vals, window):
    """Return slope of linear regression over last `window` bars (positive = up, negative = down).
    Value at index i is the slope (price/bar) from i-window+1 to i.
    """
    slope = np.full(len(close_vals), np.nan)
    for i in range(window - 1, len(close_vals)):
        y = close_vals[i - window + 1 : i + 1]
        x = np.arange(window)
        A = np.vstack([x, np.ones(window)]).T
        m, _ = np.linalg.lstsq(A, y, rcond=None)[0]
        slope[i] = m
    return slope


def linreg_slope_pct(close_vals, window):
    """Return regression slope as % of close price (normalized)."""
    slope = linear_reg_slope(close_vals, window)
    slope_pct = np.full(len(close_vals), np.nan)
    for i in range(window - 1, len(close_vals)):
        if close_vals[i] > 0:
            slope_pct[i] = slope[i] / close_vals[i] * 100
    return slope_pct


def backtest_regression(data, period, mult, entry_mult,
                        exit_mode='chandelier',
                        reg_window=5, reg_threshold=0, reg_type='slope',
                        warmup=None):
    """Backtest with configurable exit.

    exit_mode:
      'chandelier'      - current Chandelier stop (baseline)
      'regression'      - exit when linear regression slope < threshold
      'chandelier_or_reg' - exit on EITHER chandelier OR regression signal

    reg_type: 'slope' (raw slope) or 'slope_pct' (slope as % of close)
    reg_threshold: exit when slope < this value
    """
    data = data.copy()
    daily_mask = (data.index.minute == 0) & (data.index.hour.isin([4, 5]))
    if daily_mask.any():
        data = data[daily_mask].copy()
        data.index = data.index.normalize()
    else:
        data = data.resample('1D').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum'
        }).dropna()

    n = len(data)
    if n < 2:
        return [], ParameterOptimizer._empty_metrics(), [], []

    cost_per_trade = 0.0005
    alloc = 1.0

    close_p = data['close'].values.astype(float)
    high_p = data['high'].values.astype(float)
    open_p = data['open'].values.astype(float)

    # Chandelier ATR
    prev_close = np.roll(close_p, 1)
    prev_close[0] = close_p[0]
    tr = np.maximum.reduce([high_p - data['low'].values.astype(float),
                            np.abs(high_p - prev_close),
                            np.abs(data['low'].values.astype(float) - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values

    # Regression slope
    slope = None
    if exit_mode != 'chandelier':
        if reg_type == 'slope':
            slope = linear_reg_slope(close_p, reg_window)
        elif reg_type == 'slope_pct':
            slope = linreg_slope_pct(close_p, reg_window)
        elif reg_type == 'slope_atr':
            raw_slope = linear_reg_slope(close_p, reg_window)
            slope = np.full(len(close_p), np.nan)
            for i in range(len(close_p)):
                if atr[i] and not np.isnan(atr[i]) and atr[i] > 0:
                    slope[i] = raw_slope[i] / atr[i]
                else:
                    slope[i] = 0.0

    # Chandelier entry: rolling high
    rolling_high = pd.Series(high_p).rolling(window=period, min_periods=1).max().values

    if warmup is None:
        warmup = max(period, reg_window if slope is not None else 0)

    trades = []
    bar_equity = [100000]
    trade_equity = [100000]
    trade_dates = [str(data.index[0])]
    position_active = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = 100000
    high_since = 0.0

    for i in range(warmup, n):
        po = open_p[i]
        pc = close_p[i]
        ph = high_p[i]

        if pending_exit and position_active:
            allocated = equity_before * alloc
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price,
                'exit_price': po,
                'entry_at': str(data.index[entry_idx]),
                'exit_at': str(data.index[i]),
                'return': net_pnl,
                'pnl_dollar': net_dollar,
                'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1),
                'allocation_pct': 100,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False
            pending_exit = False

        if pending_entry and not position_active:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            position_active = True
            high_since = ph
            pending_entry = False

        if not position_active and not pending_entry:
            entry_level = rolling_high[i] - atr[i] * entry_mult
            if pc > entry_level:
                pending_entry = True

        if position_active and not pending_exit:
            if ph > high_since:
                high_since = ph

            if exit_mode == 'chandelier':
                stop_level = high_since - atr[i] * mult
                if pc < stop_level:
                    pending_exit = True
            elif exit_mode == 'regression':
                if slope[i] is not None and not np.isnan(slope[i]):
                    if slope[i] < reg_threshold:
                        pending_exit = True
            elif exit_mode == 'chandelier_or_reg':
                stop_level = high_since - atr[i] * mult
                chandelier_hit = pc < stop_level
                reg_hit = (slope[i] is not None and not np.isnan(slope[i])
                           and slope[i] < reg_threshold)
                if chandelier_hit or reg_hit:
                    pending_exit = True

        if i == n - 1 and position_active:
            simulated = not pending_exit
            allocated = equity_before * alloc
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price,
                'exit_price': pc,
                'entry_at': str(data.index[entry_idx]),
                'exit_at': str(data.index[i]),
                'return': net_pnl,
                'pnl_dollar': net_dollar,
                'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1),
                'simulated_close': simulated,
                'allocation_pct': 100,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False
            pending_exit = False

        if position_active:
            shares = (equity_before * alloc) / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        sharpe = ParameterOptimizer._calculate_sharpe(bar_equity)
        total_ret = (trade_equity[-1] - 100000) / 100000
        metrics = {
            'total_trades': len(trades_df),
            'winning_trades': wins,
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'total_return': total_ret,
            'sharpe_ratio': sharpe,
            'max_drawdown': ParameterOptimizer._calculate_max_drawdown(trade_equity),
            'total_pnl': float(trade_equity[-1] - 100000),
        }
    else:
        metrics = ParameterOptimizer._empty_metrics()
        metrics['total_pnl'] = 0
        trades = []

    return trades, metrics, trade_equity, trade_dates


def run_tests():
    print("=" * 70)
    print("REGRESSION EXIT BACKTEST — QQQ Daily Data")
    print("=" * 70)

    df = load_data_from_db('QQQ')
    if df is None:
        print("Failed to load data")
        sys.exit(1)

    # Current active params
    period = 18
    mult = 3.5
    entry_mult = 1.0
    warmup = period

    all_results = []

    # ── Baseline: current Chandelier exit ──
    print(f"\n{'─'*70}")
    print("BASELINE: Chandelier Exit (period=18, mult=3.5)")
    print(f"{'─'*70}")
    trades, metrics, eq, dates = backtest_regression(
        df, period, mult, entry_mult, exit_mode='chandelier', warmup=warmup
    )
    base = metrics
    all_results.append(('chandelier', 'Chandelier Exit (baseline)', '', metrics, eq))

    # ── Regression-only exits ──
    reg_tests = [
        # (window, threshold, type, label)
        (3,  -0.1, 'slope',      'LinReg 3d, slope < -0.1'),
        (3,   0.0, 'slope',      'LinReg 3d, slope < 0'),
        (5,   0.0, 'slope',      'LinReg 5d, slope < 0'),
        (8,   0.0, 'slope',      'LinReg 8d, slope < 0'),
        (3,   0.0, 'slope_pct',  'LinReg 3d, slope_pct < 0'),
        (5,   0.0, 'slope_pct',  'LinReg 5d, slope_pct < 0'),
        (8,   0.0, 'slope_pct',  'LinReg 8d, slope_pct < 0'),
        (3,  -0.5, 'slope_pct',  'LinReg 3d, slope_pct < -0.5'),
        (3,  -1.0, 'slope_pct',  'LinReg 3d, slope_pct < -1.0'),
        (5,  -0.5, 'slope_pct',  'LinReg 5d, slope_pct < -0.5'),
        (5,  -1.0, 'slope_pct',  'LinReg 5d, slope_pct < -1.0'),
        (8,  -0.5, 'slope_pct',  'LinReg 8d, slope_pct < -0.5'),
        (8,  -0.3, 'slope_pct',  'LinReg 8d, slope_pct < -0.3'),
        (8,  -0.7, 'slope_pct',  'LinReg 8d, slope_pct < -0.7'),
        (8,  -1.0, 'slope_pct',  'LinReg 8d, slope_pct < -1.0'),
        (2,  -0.5, 'slope_atr',  'LinReg 2d, slope/ATR < -0.5'),
        (2,  -0.8, 'slope_atr',  'LinReg 2d, slope/ATR < -0.8'),
        (2,  -1.0, 'slope_atr',  'LinReg 2d, slope/ATR < -1.0'),
        (2,  -1.5, 'slope_atr',  'LinReg 2d, slope/ATR < -1.5'),
        (3,  -0.5, 'slope_atr',  'LinReg 3d, slope/ATR < -0.5'),
        (3,  -0.8, 'slope_atr',  'LinReg 3d, slope/ATR < -0.8'),
        (3,  -1.0, 'slope_atr',  'LinReg 3d, slope/ATR < -1.0'),
        (3,  -1.2, 'slope_atr',  'LinReg 3d, slope/ATR < -1.2'),
        (3,  -1.5, 'slope_atr',  'LinReg 3d, slope/ATR < -1.5'),
        (4,  -0.5, 'slope_atr',  'LinReg 4d, slope/ATR < -0.5'),
        (4,  -1.0, 'slope_atr',  'LinReg 4d, slope/ATR < -1.0'),
        (4,  -1.5, 'slope_atr',  'LinReg 4d, slope/ATR < -1.5'),
        (5,  -0.5, 'slope_atr',  'LinReg 5d, slope/ATR < -0.5'),
        (5,  -0.8, 'slope_atr',  'LinReg 5d, slope/ATR < -0.8'),
        (5,  -1.0, 'slope_atr',  'LinReg 5d, slope/ATR < -1.0'),
        (5,  -1.5, 'slope_atr',  'LinReg 5d, slope/ATR < -1.5'),
        (8,  -0.5, 'slope_atr',  'LinReg 8d, slope/ATR < -0.5'),
        (8,  -1.0, 'slope_atr',  'LinReg 8d, slope/ATR < -1.0'),
        (10, -0.5, 'slope_atr',  'LinReg 10d, slope/ATR < -0.5'),
        (10, -1.0, 'slope_atr',  'LinReg 10d, slope/ATR < -1.0'),
    ]

    # ── Chandelier OR regression exits ──
    comb_tests = [
        # (window, threshold, type, label)
        (3,   0.0, 'slope',      'CHAND OR LinReg 3d slope < 0'),
        (3,  -0.5, 'slope_pct',  'CHAND OR LinReg 3d slope_pct < -0.5'),
        (5,  -0.5, 'slope_pct',  'CHAND OR LinReg 5d slope_pct < -0.5'),
        (8,  -0.5, 'slope_pct',  'CHAND OR LinReg 8d slope_pct < -0.5'),
        (3,  -0.5, 'slope_atr',  'CHAND OR LinReg 3d slope/ATR < -0.5'),
    ]

    print(f"\n{'─'*70}")
    print("REGRESSION-ONLY EXITS")
    print(f"{'─'*70}")
    for w, th, rt, lbl in reg_tests:
        trades, metrics, eq, dates = backtest_regression(
            df, period, mult, entry_mult,
            exit_mode='regression', reg_window=w, reg_threshold=th,
            reg_type=rt, warmup=warmup
        )
        all_results.append((f'reg_w{w}_{rt}_{th}', lbl, 'regression', metrics, eq))

    print(f"\n{'─'*70}")
    print("CHANDELIER OR REGRESSION EXITS")
    print(f"{'─'*70}")
    for w, th, rt, lbl in comb_tests:
        trades, metrics, eq, dates = backtest_regression(
            df, period, mult, entry_mult,
            exit_mode='chandelier_or_reg', reg_window=w, reg_threshold=th,
            reg_type=rt, warmup=warmup
        )
        all_results.append((f'chandreg_w{w}_{rt}_{th}', lbl, 'chandelier_or_reg', metrics, eq))

    # ── Results table ──
    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}")
    print(f"{'Label':<45} {'Trades':<7} {'Win%':<7} {'Return':<10} {'Total $':<12} {'Sharpe':<8} {'vs Base':<8}")
    print(f"{'─'*95}")

    # Sort by total return descending
    sorted_results = sorted(all_results, key=lambda r: r[3]['total_return'], reverse=True)

    for key, label, mode, m, eq in sorted_results:
        vs_base = ((m['total_return'] - base['total_return']) / abs(base['total_return']) * 100
                   if base['total_return'] != 0 else 0)
        sign = '+' if vs_base >= 0 else ''
        print(f"{label:<45} {m['total_trades']:<7} {m['win_rate']*100:<7.1f} "
              f"{m['total_return']*100:<9.2f}% ${m['total_pnl']:<9,.0f} "
              f"{m['sharpe_ratio']:<8.2f} {sign}{vs_base:<7.1f}%")

    print(f"\nBaseline: {base['total_trades']} trades, {base['win_rate']*100:.1f}% win rate, "
          f"{base['total_return']*100:.2f}% return, ${base['total_pnl']:,.0f} P&L, "
          f"Sharpe {base['sharpe_ratio']:.2f}")


if __name__ == '__main__':
    run_tests()
