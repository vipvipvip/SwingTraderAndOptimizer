"""Train/test split validation of regression exits on QQQ daily data"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer


def linear_reg_slope(close_vals, window):
    slope = np.full(len(close_vals), np.nan)
    for i in range(window - 1, len(close_vals)):
        y = close_vals[i - window + 1 : i + 1]
        x = np.arange(window)
        A = np.vstack([x, np.ones(window)]).T
        m, _ = np.linalg.lstsq(A, y, rcond=None)[0]
        slope[i] = m
    return slope


def backtest_regression(data, period, mult, entry_mult,
                        exit_mode='chandelier',
                        reg_window=5, reg_threshold=0, reg_type='slope',
                        warmup=None, verbose=False):
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

    prev_close = np.roll(close_p, 1)
    prev_close[0] = close_p[0]
    tr = np.maximum.reduce([high_p - data['low'].values.astype(float),
                            np.abs(high_p - prev_close),
                            np.abs(data['low'].values.astype(float) - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values

    slope = None
    if exit_mode != 'chandelier':
        if reg_type == 'slope':
            slope = linear_reg_slope(close_p, reg_window)
        elif reg_type in ('slope_pct', 'slope_pct_atr'):
            raw_slope = linear_reg_slope(close_p, reg_window)
            slope = np.full(len(close_p), np.nan)
            for i in range(len(close_p)):
                if close_p[i] > 0:
                    pct = raw_slope[i] / close_p[i] * 100
                    if reg_type == 'slope_pct_atr' and atr[i] and not np.isnan(atr[i]) and atr[i] > 0:
                        slope[i] = pct / atr[i] * close_p[i]
                    else:
                        slope[i] = pct
        elif reg_type == 'slope_atr':
            raw_slope = linear_reg_slope(close_p, reg_window)
            slope = np.full(len(close_p), np.nan)
            for i in range(len(close_p)):
                if atr[i] and not np.isnan(atr[i]) and atr[i] > 0:
                    slope[i] = raw_slope[i] / atr[i]
                else:
                    slope[i] = 0.0

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
        po = open_p[i]; pc = close_p[i]; ph = high_p[i]

        if pending_exit and position_active:
            allocated = equity_before * alloc
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(data.index[entry_idx]), 'exit_at': str(data.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1), 'allocation_pct': 100,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False; pending_exit = False

        if pending_entry and not position_active:
            entry_price = po; entry_idx = i
            equity_before = trade_equity[-1]
            position_active = True; high_since = ph; pending_entry = False

        if not position_active and not pending_entry:
            entry_level = rolling_high[i] - atr[i] * entry_mult
            if pc > entry_level:
                pending_entry = True

        if position_active and not pending_exit:
            if ph > high_since:
                high_since = ph
            if exit_mode == 'chandelier':
                if pc < high_since - atr[i] * mult:
                    pending_exit = True
            elif exit_mode == 'regression':
                if slope[i] is not None and not np.isnan(slope[i]) and slope[i] < reg_threshold:
                    pending_exit = True
            elif exit_mode == 'chandelier_or_reg':
                ch = pc < high_since - atr[i] * mult
                reg = slope[i] is not None and not np.isnan(slope[i]) and slope[i] < reg_threshold
                if ch or reg:
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
                'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(data.index[entry_idx]), 'exit_at': str(data.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1), 'simulated_close': simulated,
                'allocation_pct': 100,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False; pending_exit = False

        if position_active:
            shares = (equity_before * alloc) / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        sharpe = ParameterOptimizer._calculate_sharpe(bar_equity)
        metrics = {
            'total_trades': len(trades_df),
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'total_return': (trade_equity[-1] - 100000) / 100000,
            'sharpe_ratio': sharpe,
            'max_drawdown': ParameterOptimizer._calculate_max_drawdown(trade_equity),
            'total_pnl': float(trade_equity[-1] - 100000),
        }
    else:
        metrics = ParameterOptimizer._empty_metrics()
        metrics['total_pnl'] = 0
        trades = []

    return trades, metrics, trade_equity, trade_dates


def run_validation():
    print("=" * 70)
    print("REGRESSION EXIT — 80/20 TRAIN/TEST VALIDATION (QQQ Daily)")
    print("=" * 70)

    df = load_data_from_db('QQQ')
    if df is None:
        print("Failed to load data")
        sys.exit(1)

    daily_mask = (df.index.minute == 0) & (df.index.hour.isin([4, 5]))
    if daily_mask.any():
        data = df[daily_mask].copy()
        data.index = data.index.normalize()
    else:
        data = data.resample('1D').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum'
        }).dropna()

    n = len(data)
    split_idx = int(n * 0.8)
    train_data = data.iloc[:split_idx]
    test_data = data.iloc[split_idx:]

    print(f"\nData split: {n} total bars")
    print(f"  Train: {len(train_data)} bars ({data.index[0].date()} to {data.index[split_idx-1].date()})")
    print(f"  Test:  {len(test_data)} bars ({data.index[split_idx].date()} to {data.index[-1].date()})")

    period = 18
    mult = 3.5
    entry_mult = 1.0

    # ── Baseline: current Chandelier exit ──
    print(f"\n{'─'*70}")
    print("BASELINE: Chandelier Exit (period=18, mult=3.5)")
    print(f"{'─'*70}")

    base_train = backtest_regression(train_data, period, mult, entry_mult, exit_mode='chandelier', warmup=period, verbose=False)
    base_test  = backtest_regression(test_data,  period, mult, entry_mult, exit_mode='chandelier', warmup=period, verbose=False)

    # ── Grid search regression exits on TRAIN set ──
    print(f"\n{'─'*70}")
    print("TRAINING: Grid search regression exit params on train set")
    print(f"{'─'*70}")

    search_results = []
    # Use the same test config array
    reg_variants = []
    for w in [2, 3, 4, 5, 8, 10, 13]:
        for th in [-2.0, -1.5, -1.2, -1.0, -0.8, -0.5, -0.3, 0.0]:
            reg_variants.append((w, th, 'slope_atr'))
        for th in [-2.0, -1.5, -1.0, -0.5, -0.3, 0.0]:
            reg_variants.append((w, th, 'slope_pct'))
        for th in [-2.0, -1.5, -1.0, -0.5, -0.3, 0.0]:
            reg_variants.append((w, th, 'slope'))

    # Deduplicate
    reg_variants = list(set(reg_variants))
    # Sort by window then threshold
    reg_variants.sort(key=lambda x: (x[0], x[2], x[1]))

    for w, th, rt in reg_variants:
        trades, metrics, eq, dates = backtest_regression(
            train_data, period, mult, entry_mult,
            exit_mode='regression', reg_window=w, reg_threshold=th, reg_type=rt,
            warmup=max(period, w), verbose=False
        )
        search_results.append(((w, th, rt, 'regression'), metrics))

    # Chandelier OR regression variants
    for w, th, rt in reg_variants:
        trades, metrics, eq, dates = backtest_regression(
            train_data, period, mult, entry_mult,
            exit_mode='chandelier_or_reg', reg_window=w, reg_threshold=th, reg_type=rt,
            warmup=max(period, w), verbose=False
        )
        search_results.append(((w, th, rt, 'chandelier_or_reg'), metrics))

    # Add baseline to search
    search_results.append((('baseline', None, None, 'chandelier'), base_train[1]))

    # Sort train results by total_return descending
    search_results.sort(key=lambda r: r[1]['total_return'], reverse=True)

    train_baseline = base_train[1]
    print(f"\nTop 15 on TRAIN set:")
    print(f"{'Rank':<5} {'Method':<25} {'Win%':<6} {'Return':<10} {'Sharpe':<7} {'Trades':<6}")
    print(f"{'─'*60}")
    for rank, ((w, th, rt, mode), m) in enumerate(search_results[:15]):
        label = f"{mode} {w}d {rt} {th}" if mode != 'chandelier' else 'Chandelier (baseline)'
        print(f"{rank+1:<5} {label:<25} {m['win_rate']*100:<6.1f} {m['total_return']*100:<9.2f}% {m['sharpe_ratio']:<7.2f} {m['total_trades']:<6}")

    # ── Test top 10 on TEST set ──
    print(f"\n{'─'*70}")
    print("TESTING: Top 10 train params on test set")
    print(f"{'─'*70}")

    print(f"\n{'Label':<48} {'Train Ret':<10} {'Test Ret':<10} {'Test Win%':<10} {'Test Tr':<7} {'Test Shp':<8} {'Test $':<12}")
    print(f"{'─'*95}")

    baseline_test_ret = base_test[1]['total_return']
    results_out = []

    for rank, ((w, th, rt, mode), train_m) in enumerate(search_results[:10]):
        if mode == 'chandelier':
            test_m = base_test[1]
            label = 'Chandelier (baseline)'
        else:
            _, test_m, _, _ = backtest_regression(
                test_data, period, mult, entry_mult,
                exit_mode=mode, reg_window=w, reg_threshold=th, reg_type=rt,
                warmup=max(period, w), verbose=False
            )
            label = f"{mode} {w}d {rt} {th}"[:47]

        results_out.append((label, train_m, test_m))
        print(f"{label:<48} {train_m['total_return']*100:<9.2f}% {test_m['total_return']*100:<9.2f}% "
              f"{test_m['win_rate']*100:<9.1f}% {test_m['total_trades']:<6} {test_m['sharpe_ratio']:<8.2f} "
              f"${test_m['total_pnl']:<9,.0f}")

    # Summary
    print(f"\n{'─'*70}")
    print("SUMMARY")
    print(f"{'─'*70}")
    print(f"Baseline (Chandelier mult=3.5):")
    print(f"  Train: ${base_train[1]['total_pnl']:,.0f}  {base_train[1]['total_return']*100:.2f}%  "
          f"{base_train[1]['total_trades']} trades  Sharpe {base_train[1]['sharpe_ratio']:.2f}")
    print(f"  Test:  ${base_test[1]['total_pnl']:,.0f}  {base_test[1]['total_return']*100:.2f}%  "
          f"{base_test[1]['total_trades']} trades  Sharpe {base_test[1]['sharpe_ratio']:.2f}")

    # Find best on test among top 10 train
    best_test = max(results_out[1:], key=lambda r: r[2]['total_return']) if len(results_out) > 1 else None
    if best_test:
        print(f"\nBest on test set (from top 10 train): {best_test[0]}")
        print(f"  Train: ${best_test[1]['total_pnl']:,.0f}  {best_test[1]['total_return']*100:.2f}%  "
              f"Sharpe {best_test[1]['sharpe_ratio']:.2f}")
        print(f"  Test:  ${best_test[2]['total_pnl']:,.0f}  {best_test[2]['total_return']*100:.2f}%  "
              f"Sharpe {best_test[2]['sharpe_ratio']:.2f}")
        vs_base = best_test[2]['total_return'] / baseline_test_ret - 1 if baseline_test_ret != 0 else 0
        print(f"  vs baseline on test: {vs_base*100:+.1f}%")


if __name__ == '__main__':
    run_validation()
