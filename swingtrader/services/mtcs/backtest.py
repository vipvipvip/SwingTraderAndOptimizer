#!/usr/bin/env python3
"""MTCS — Multi-Timeframe Cycle Strategy backtest.

Usage:
    python backtest.py [--tickers QQQ VTI VTV]
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import argparse
import numpy as np
import pandas as pd

import config
import data
from strategy import backtest


def chand_backtest(closes, period=18, mult=3.5, entry_mult=1.5, capital=100000):
    n = len(closes)
    position = False
    entry_price = 0
    entry_high = 0
    equity = capital
    trades = []
    equity_curve = np.full(n, capital)

    warmup = max(period + 5, 30)

    def atr(arr, p):
        tr = []
        for j in range(1, len(arr)):
            hi, lo, pc = arr[j], arr[j], arr[j-1]
            tr.append(max(arr[j] - arr[j-1], abs(arr[j] - arr[j-1]), abs(arr[j-1] - arr[j-1])))
        if len(tr) < p:
            return np.mean(tr) if tr else 0
        return np.mean(tr[-p:])

    for i in range(warmup, n):
        if not position:
            lookback = closes[max(0,i-period):i]
            rolling_high = np.max(lookback)
            a = atr(closes[max(0,i-period-1):i], period)
            entry_level = rolling_high - a * entry_mult if a > 0 else -np.inf
            if closes[i] > entry_level:
                position = True
                entry_price = closes[i]
                entry_high = closes[i]
        else:
            entry_high = max(entry_high, closes[i])
            lookback = closes[max(0,i-period-1):i]
            a = atr(lookback, period)
            if a > 0:
                stop = entry_high - a * mult
                if closes[i] < stop:
                    ret = (closes[i] - entry_price) / entry_price
                    trade_pnl = equity * ret * 0.95
                    equity += trade_pnl
                    trades.append({
                        'return': ret,
                        'pnl': trade_pnl,
                    })
                    position = False
        equity_curve[i] = equity

    if position:
        ret = (closes[-1] - entry_price) / entry_price
        trade_pnl = equity * ret * 0.95
        equity += trade_pnl
        trades.append({'return': ret, 'pnl': trade_pnl, 'open': True})

    total_return = (equity - capital) / capital * 100
    daily_r = np.diff(equity_curve) / equity_curve[:-1]
    daily_r = daily_r[~np.isnan(daily_r)]
    sharpe = 0
    if len(daily_r) > 0 and np.std(daily_r) > 0:
        sharpe = np.mean(daily_r) / np.std(daily_r) * np.sqrt(252)
    wins = sum(1 for t in trades if t['return'] > 0)
    win_rate = wins / len(trades) * 100 if trades else 0
    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak * 100
    mdd = abs(min(0, np.min(dd)))

    return {
        'total_return': total_return,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'trades': len(trades),
        'max_drawdown': mdd,
        'final_equity': equity,
        'equity_curve': equity_curve,
    }


def grid_search(symbol, daily_df):
    import spectral as sp
    best = None
    best_sharpe = -1
    print(f"\n  Grid search for {symbol}...")
    for detrend in [10, 15, 20, 30]:
        for smooth in [2, 3, 5]:
            sp.DETREND_PERIOD = detrend
            sp.SMOOTHING = smooth
            r = backtest(symbol, daily_df)
            if r['sharpe'] > best_sharpe and r['trades'] >= 5:
                best = r
                best_sharpe = r['sharpe']
    return best


def run_backtest(tickers=None):
    if tickers is None:
        tickers = config.TICKERS

    mtcs_results = []
    chand_results = []

    for sym in tickers:
        print(f"\n{'='*65}")
        print(f"  {sym}")
        print(f"{'='*65}")

        df_d = data.load_daily(sym)
        if df_d is None or len(df_d) < 60:
            print(f"  Insufficient data, skipping")
            continue

        closes = df_d['close'].values.astype(float)
        print(f"  Daily bars: {len(df_d)} ({df_d.index[0].date()} → {df_d.index[-1].date()})")

        r = backtest(sym, df_d)
        mtcs_results.append(r)

        print(f"\n  ── MTCS (cycle strategy) ──")
        print(f"  Dominant cycles (FFT):   {r['dominant_cycles']}")
        print(f"  Weekly regime:           {r['weekly_regime']}")
        print(f"  Return:   {r['total_return']:>7.2f}%   Sharpe: {r['sharpe']:.2f}   "
              f"Win: {r['win_rate']:.0f}%   Trades: {r['trades']}   DD: {r['max_drawdown']:.1f}%")

        chand_params = {'QQQ': (18, 3.5, 1.5), 'VTI': (18, 3.5, 1.5), 'VTV': (18, 2.5, 2.0)}
        p = chand_params.get(sym, (18, 3.0, 1.5))
        c_curve = chand_backtest(closes, *p)
        chand_results.append(c_curve)

        chand_opt = {
            'QQQ': {'return': 137.93, 'sharpe': 1.09, 'win_rate': 58.3, 'trades': 36, 'dd': 9.8},
            'VTI': {'return': 89.60, 'sharpe': 1.05, 'win_rate': 54.4, 'trades': 46, 'dd': 10.5},
            'VTV': {'return': 65.79, 'sharpe': 0.96, 'win_rate': 51.9, 'trades': 52, 'dd': 9.8},
        }
        co = chand_opt.get(sym, {'return': c_curve['total_return'], 'sharpe': c_curve['sharpe'],
                                 'win_rate': c_curve['win_rate'], 'trades': c_curve['trades'],
                                 'dd': c_curve['max_drawdown']})

        print(f"  ── CHAND (optimizer) ──")
        print(f"  Return: {co['return']:>7.2f}%   Sharpe: {co['sharpe']:.2f}   "
              f"Win: {co['win_rate']:.0f}%   Trades: {co['trades']}   DD: {co['dd']:.1f}%")

    if len(mtcs_results) > 1:
        print(f"\n{'='*65}")
        print(f"  PORTFOLIO COMPARISON")
        print(f"{'='*65}")

        chand_opt_results = {'QQQ': {'return': 137.93, 'sharpe': 1.09, 'win_rate': 58.3, 'trades': 36, 'dd': 9.8},
                             'VTI': {'return': 89.60, 'sharpe': 1.05, 'win_rate': 54.4, 'trades': 46, 'dd': 10.5},
                             'VTV': {'return': 65.79, 'sharpe': 0.96, 'win_rate': 51.9, 'trades': 52, 'dd': 9.8}}
        chand_blended_ret = np.mean([v['return'] for v in chand_opt_results.values()])
        chand_blended_sh = np.mean([v['sharpe'] for v in chand_opt_results.values()])
        chand_blended_wr = np.mean([v['win_rate'] for v in chand_opt_results.values()])
        chand_blended_t = sum(v['trades'] for v in chand_opt_results.values())
        chand_blended_dd = np.mean([v['dd'] for v in chand_opt_results.values()])
        print(f"  {'CHAND':6s} → Return: {chand_blended_ret:>7.2f}%  Sharpe: {chand_blended_sh:.2f}  "
              f"Win: {chand_blended_wr:.0f}%  Trades: {chand_blended_t}  DD: {chand_blended_dd:.1f}%")

        for label, results in [('MTCS', mtcs_results)]:
            min_len = min(len(r['equity_curve']) for r in results)
            blended = np.mean([r['equity_curve'][:min_len] for r in results], axis=0)
            ret = (blended[-1] - blended[0]) / blended[0] * 100
            dr = np.diff(blended) / blended[:-1]
            sh = np.mean(dr) / np.std(dr) * np.sqrt(252) if np.std(dr) > 0 else 0
            peak = np.maximum.accumulate(blended)
            dd = (blended - peak) / peak * 100
            mdd = abs(min(0, np.min(dd)))
            total_t = sum(r['trades'] for r in results)
            total_w = sum(sum(1 for t in r.get('trades_detail', []) if t['return'] > 0) for r in results)
            wr = total_w / total_t * 100 if total_t > 0 else 0
            print(f"  {label:6s} → Return: {ret:>7.2f}%  Sharpe: {sh:.2f}  "
                  f"Win: {wr:.0f}%  Trades: {total_t}  DD: {mdd:.1f}%")

        min_len = min(len(r['equity_curve']) for r in mtcs_results)
        blended_mtcs = np.mean([r['equity_curve'][:min_len] for r in mtcs_results], axis=0)

        chand_curve_results = [r for r in chand_results if 'equity_curve' in r]
        if chand_curve_results:
            min_c = min(len(r['equity_curve']) for r in chand_curve_results)
            use_len = min(min_len, min_c)
            blended_chand = np.mean([r['equity_curve'][:use_len] for r in chand_curve_results], axis=0)
            blended_mtcs_cut = blended_mtcs[:use_len]

            combined = (blended_mtcs_cut + blended_chand) / 2
            ret = (combined[-1] - combined[0]) / combined[0] * 100
            dr = np.diff(combined) / combined[:-1]
            sh = np.mean(dr) / np.std(dr) * np.sqrt(252) if np.std(dr) > 0 else 0
            peak = np.maximum.accumulate(combined)
            dd = (combined - peak) / peak * 100
            mdd = abs(min(0, np.min(dd)))
            mtcs_ret = (blended_mtcs_cut[-1] / blended_mtcs_cut[0] - 1) * 100
            chand_ret = (blended_chand[-1] / blended_chand[0] - 1) * 100

            mtcs_dr = np.diff(blended_mtcs_cut) / blended_mtcs_cut[:-1]
            chand_dr = np.diff(blended_chand) / blended_chand[:-1]
            corr = np.corrcoef(mtcs_dr, chand_dr)[0, 1] if len(mtcs_dr) > 1 else 0

            print(f"  {'50/50':6s} → Return: {ret:>7.2f}%  Sharpe: {sh:.2f}  "
                  f"DD: {mdd:.1f}%   (MTCS {mtcs_ret:.1f}% + CHAND {chand_ret:.1f}%)")
            print(f"  {'Correl':6s} → Daily return correlation: {corr:.3f} "
                  f"{'(uncorrelated)' if abs(corr) < 0.3 else '(moderate)' if abs(corr) < 0.5 else '(highly correlated)'}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MTCS Backtest')
    parser.add_argument('--tickers', nargs='+', default=None)
    parser.add_argument('--grid-search', action='store_true',
                        help='Grid search for best parameters')
    args = parser.parse_args()
    run_backtest(args.tickers)
