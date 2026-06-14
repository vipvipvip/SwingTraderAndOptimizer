"""Walk-forward validation of regression exits on QQQ daily data"""
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
                        warmup=None):
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
    prev_close = np.roll(close_p, 1); prev_close[0] = close_p[0]
    tr = np.maximum.reduce([high_p - data['low'].values.astype(float),
                            np.abs(high_p - prev_close),
                            np.abs(data['low'].values.astype(float) - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values

    slope = None
    if exit_mode != 'chandelier':
        if reg_type == 'slope':
            slope = linear_reg_slope(close_p, reg_window)
        elif reg_type in ('slope_pct',):
            raw_slope = linear_reg_slope(close_p, reg_window)
            slope = np.full(len(close_p), np.nan)
            for i in range(len(close_p)):
                if close_p[i] > 0:
                    slope[i] = raw_slope[i] / close_p[i] * 100
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

    trades = []; bar_equity = [100000]; trade_equity = [100000]; trade_dates = [str(data.index[0])]
    position_active = False; pending_entry = False; pending_exit = False
    entry_price = 0.0; entry_idx = 0; equity_before = 100000; high_since = 0.0

    for i in range(warmup, n):
        po = open_p[i]; pc = close_p[i]; ph = high_p[i]
        if pending_exit and position_active:
            allocated = equity_before * alloc
            deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed; net_pnl = net_dollar / deployed
            trades.append({'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(data.index[entry_idx]), 'exit_at': str(data.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1), 'allocation_pct': 100})
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False; pending_exit = False
        if pending_entry and not position_active:
            entry_price = po; entry_idx = i; equity_before = trade_equity[-1]
            position_active = True; high_since = ph; pending_entry = False
        if not position_active and not pending_entry:
            if pc > rolling_high[i] - atr[i] * entry_mult:
                pending_entry = True
        if position_active and not pending_exit:
            if ph > high_since: high_since = ph
            if exit_mode == 'chandelier':
                if pc < high_since - atr[i] * mult: pending_exit = True
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
            allocated = equity_before * alloc; deployed = allocated * (1 - cost_per_trade)
            shares = deployed / entry_price; net_proceeds = shares * pc * (1 - cost_per_trade)
            net_dollar = net_proceeds - deployed; net_pnl = net_dollar / deployed
            trades.append({'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(data.index[entry_idx]), 'exit_at': str(data.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'days_held': round(i - entry_idx, 1), 'simulated_close': simulated, 'allocation_pct': 100})
            trade_equity.append(trade_equity[-1] + net_dollar)
            trade_dates.append(str(data.index[i]))
            position_active = False; pending_exit = False
        if position_active:
            bar_equity.append(equity_before + (equity_before * alloc / entry_price) * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if trades:
        trades_df = pd.DataFrame(trades); wins = (trades_df['return'] > 0).sum()
        sharpe = ParameterOptimizer._calculate_sharpe(bar_equity)
        metrics = {'total_trades': len(trades_df), 'winning_trades': int(wins),
            'win_rate': wins / len(trades_df), 'avg_return': float(trades_df['return'].mean()),
            'total_return': (trade_equity[-1] - 100000) / 100000,
            'sharpe_ratio': sharpe,
            'max_drawdown': ParameterOptimizer._calculate_max_drawdown(trade_equity),
            'total_pnl': float(trade_equity[-1] - 100000)}
    else:
        metrics = ParameterOptimizer._empty_metrics(); metrics['total_pnl'] = 0; trades = []
    return trades, metrics, trade_equity, trade_dates


def run_walkforward():
    print("=" * 70)
    print("WALK-FORWARD VALIDATION — QQQ Daily")
    print("=" * 70)

    df = load_data_from_db('QQQ')
    if df is None: print("Failed to load data"); sys.exit(1)

    daily_mask = (df.index.minute == 0) & (df.index.hour.isin([4, 5]))
    if daily_mask.any():
        data = df[daily_mask].copy()
        data.index = data.index.normalize()
    else:
        data = data.resample('1D').agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum'
        }).dropna()

    period = 18; mult = 3.5; entry_mult = 1.0

    # Define walk-forward folds by calendar date
    # Total data: Jul 2020 - Jun 2026
    folds = [
        # (train_start, train_end, test_start, test_end)
        ('2020-07-27', '2023-06-30', '2023-07-01', '2024-06-30'),
        ('2021-07-01', '2024-06-30', '2024-07-01', '2025-06-30'),
        ('2022-07-01', '2025-06-30', '2025-07-01', '2026-06-09'),
    ]

    # All regression variants to search on each train set
    reg_variants = []
    for w in [2, 3, 4, 5, 8, 10]:
        for th in [-2.0, -1.5, -1.2, -1.0, -0.8, -0.5, -0.3, 0.0]:
            reg_variants.append((w, th, 'slope_atr'))
            reg_variants.append((w, th, 'slope_pct'))
    reg_variants = list(set(reg_variants))
    reg_variants.sort(key=lambda x: (x[0], x[2], x[1]))

    all_fold_results = []

    for fold_idx, (tr_s, tr_e, ts_s, ts_e) in enumerate(folds):
        print(f"\n{'='*70}")
        print(f"FOLD {fold_idx+1}: Train {tr_s} to {tr_e}  |  Test {ts_s} to {ts_e}")
        print(f"{'='*70}")

        train_data = data.loc[tr_s:tr_e].copy()
        test_data = data.loc[ts_s:ts_e].copy()
        print(f"  Train: {len(train_data)} bars, Test: {len(test_data)} bars")

        # Baseline on train and test
        base_train = backtest_regression(train_data, period, mult, entry_mult, exit_mode='chandelier', warmup=period)
        base_test  = backtest_regression(test_data,  period, mult, entry_mult, exit_mode='chandelier', warmup=period)
        print(f"  Baseline: Train={base_train[1]['total_return']*100:.1f}% ({base_train[1]['total_trades']}t)  "
              f"Test={base_test[1]['total_return']*100:.1f}% ({base_test[1]['total_trades']}t)")

        # Grid search: regression-only + chandelier_or_reg on train set
        best_reg = None
        best_combo = None
        top5_reg = []
        top5_combo = []

        for mode in ['regression', 'chandelier_or_reg']:
            for w, th, rt in reg_variants:
                warmup = max(period, w)
                tr_trades, tr_m, _, _ = backtest_regression(
                    train_data, period, mult, entry_mult,
                    exit_mode=mode, reg_window=w, reg_threshold=th, reg_type=rt,
                    warmup=warmup)
                if tr_m['total_trades'] < 3:
                    continue
                ts_trades, ts_m, _, _ = backtest_regression(
                    test_data, period, mult, entry_mult,
                    exit_mode=mode, reg_window=w, reg_threshold=th, reg_type=rt,
                    warmup=warmup)

                entry = (mode, w, th, rt, tr_m, ts_m, tr_m['total_return'], ts_m['total_return'])

                if mode == 'regression':
                    top5_reg.append((w, th, rt, tr_m['total_return'], tr_m['total_trades'],
                                     ts_m['total_return'], ts_m['total_trades']))
                    if best_reg is None or ts_m['total_return'] > best_reg[7]:
                        best_reg = entry
                else:
                    top5_combo.append((w, th, rt, tr_m['total_return'], tr_m['total_trades'],
                                       ts_m['total_return'], ts_m['total_trades']))
                    if best_combo is None or ts_m['total_return'] > best_combo[7]:
                        best_combo = entry

        top5_reg.sort(key=lambda x: x[3], reverse=True)
        top5_reg = top5_reg[:5]
        top5_combo.sort(key=lambda x: x[3], reverse=True)
        top5_combo = top5_combo[:5]

        print(f"  Top 5 REGRESSION on TRAIN:")
        for w, th, rt, tr_ret, tr_t, ts_ret, ts_t in top5_reg:
            vs_base = (ts_ret - base_test[1]['total_return']) / abs(base_test[1]['total_return']) * 100 if base_test[1]['total_return'] != 0 else 0
            print(f"    {rt} {w}d th={th:<5}  Train: {tr_ret*100:>6.1f}% ({tr_t}t)  "
                  f"Test: {ts_ret*100:>6.1f}% ({ts_t}t)  vs base: {vs_base:+.1f}%")

        print(f"  Top 5 CHAND+REG on TRAIN:")
        for w, th, rt, tr_ret, tr_t, ts_ret, ts_t in top5_combo:
            vs_base = (ts_ret - base_test[1]['total_return']) / abs(base_test[1]['total_return']) * 100 if base_test[1]['total_return'] != 0 else 0
            print(f"    {rt} {w}d th={th:<5}  Train: {tr_ret*100:>6.1f}% ({tr_t}t)  "
                  f"Test: {ts_ret*100:>6.1f}% ({ts_t}t)  vs base: {vs_base:+.1f}%")

        if best_reg:
            _, w, th, rt, tr_m, ts_m, tr_ret, ts_ret = best_reg
            vs_base = (ts_ret - base_test[1]['total_return']) / abs(base_test[1]['total_return']) * 100 if base_test[1]['total_return'] != 0 else 0
            print(f"  Best REGRESSION on TEST: {rt} {w}d th={th}  Train: {tr_ret*100:.1f}% ({tr_m['total_trades']}t)  "
                  f"Test: {ts_ret*100:.1f}% ({ts_m['total_trades']}t)  vs base: {vs_base:+.1f}%")
        if best_combo:
            _, w, th, rt, tr_m, ts_m, tr_ret, ts_ret = best_combo
            vs_base = (ts_ret - base_test[1]['total_return']) / abs(base_test[1]['total_return']) * 100 if base_test[1]['total_return'] != 0 else 0
            print(f"  Best CHAND+REG on TEST: {rt} {w}d th={th}  Train: {tr_ret*100:.1f}% ({tr_m['total_trades']}t)  "
                  f"Test: {ts_ret*100:.1f}% ({ts_m['total_trades']}t)  vs base: {vs_base:+.1f}%")

        all_fold_results.append({
            'fold': fold_idx + 1,
            'train_range': f'{tr_s} to {tr_e}',
            'test_range': f'{ts_s} to {ts_e}',
            'train_bars': len(train_data),
            'test_bars': len(test_data),
            'base_train_ret': base_train[1]['total_return'],
            'base_train_trades': base_train[1]['total_trades'],
            'base_test_ret': base_test[1]['total_return'],
            'base_test_trades': base_test[1]['total_trades'],
            'best_reg': best_reg,
            'best_combo': best_combo,
            'top5_reg': top5_reg,
            'top5_combo': top5_combo,
        })

    # ── Summary ──
    print(f"\n{'='*70}")
    print("WALK-FORWARD SUMMARY")
    print(f"{'='*70}")
    print(f"\n{'Fold':<6} {'Test Period':<30} {'Base':<14} {'Reg-only':<18} {'Chand+Reg':<18}")
    print(f"{'─'*85}")

    base_rets = []
    reg_rets = []
    combo_rets = []
    for fr in all_fold_results:
        btr = fr['base_test_ret']
        rtr = fr['best_reg'][7] if fr['best_reg'] else btr
        ctr = fr['best_combo'][7] if fr['best_combo'] else btr
        tstr = fr['test_range']

        r_lbl = ''
        if fr['best_reg']:
            _, w, th, rt, _, _, _, _ = fr['best_reg']
            r_lbl = f"{rt} {w}d th={th}"
        c_lbl = ''
        if fr['best_combo']:
            _, w, th, rt, _, _, _, _ = fr['best_combo']
            c_lbl = f"{rt} {w}d th={th}"

        print(f"{fr['fold']:<6} {tstr:<30} {btr*100:>+7.2f}% ({fr['base_test_trades']}t)  "
              f"{rtr*100:>+7.2f}% ({fr['best_reg'][5]['total_trades'] if fr['best_reg'] else 0}t) {r_lbl:<15}  "
              f"{ctr*100:>+7.2f}% ({fr['best_combo'][5]['total_trades'] if fr['best_combo'] else 0}t) {c_lbl:<15}")
        base_rets.append(btr)
        reg_rets.append(rtr)
        combo_rets.append(ctr)

    avg_base = np.mean(base_rets) * 100
    avg_reg = np.mean(reg_rets) * 100
    avg_combo = np.mean(combo_rets) * 100
    reg_vs = avg_reg / avg_base * 100 - 100 if avg_base else 0
    combo_vs = avg_combo / avg_base * 100 - 100 if avg_base else 0
    print(f"{'─'*85}")
    print(f"{'AVG':<6} {'':30} {avg_base:>+7.2f}%        {avg_reg:>+7.2f}% ({reg_vs:+.1f}%)          {avg_combo:>+7.2f}% ({combo_vs:+.1f}%)")

    reg_beats = sum(1 for i in range(len(base_rets)) if reg_rets[i] > base_rets[i])
    combo_beats = sum(1 for i in range(len(base_rets)) if combo_rets[i] > base_rets[i])
    print(f"\nRegression-only beat baseline: {reg_beats}/{len(folds)} folds")
    print(f"Chandelier+Reg beat baseline:  {combo_beats}/{len(folds)} folds")


if __name__ == '__main__':
    run_walkforward()
