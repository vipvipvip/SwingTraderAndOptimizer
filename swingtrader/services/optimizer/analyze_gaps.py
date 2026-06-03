#!/usr/bin/env python3
"""Analyze days between exit and next entry for each entry mode"""
import sys
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer
from db import StrategyDB
import pandas as pd


def get_current_params(symbol, db):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT chandelier_period, chandelier_mult
        FROM strategy_parameters
        WHERE ticker_id = (SELECT id FROM tbl_etf_tickers WHERE symbol = %s)
        AND base_case = true
        LIMIT 1
    ''', (symbol,))
    row = cursor.fetchone()
    if not row:
        return {'chandelier_period': 18, 'chandelier_mult': 3.0}
    return {'chandelier_period': int(row[0]), 'chandelier_mult': float(row[1])}


def analyze(symbol, entry_mode, params, alloc_weight):
    df = load_data_from_db(symbol)
    if df is None:
        return None
    opt = ParameterOptimizer(df, initial_capital=100000, symbol=symbol, allocation_weight=alloc_weight)
    trades, metrics, _, _ = opt._backtest_with_params(params, entry_mode=entry_mode)
    if not trades:
        return None

    tdf = pd.DataFrame(trades)
    tdf = tdf.sort_values('entry_at')
    tdf['entry_at'] = pd.to_datetime(tdf['entry_at'])
    tdf['exit_at'] = pd.to_datetime(tdf['exit_at'])

    gaps = []
    for i in range(len(tdf) - 1):
        exit_date = tdf.iloc[i]['exit_at']
        next_entry = tdf.iloc[i + 1]['entry_at']
        days_out = (next_entry - exit_date).days
        gaps.append(days_out)

    gaps = pd.Series(gaps)
    return {
        'gaps': gaps,
        'metrics': metrics,
        'n_trades': len(tdf),
    }


def main():
    tickers = ['SPY', 'QQQ', 'VTI', 'VTV']
    db = StrategyDB()

    configs = [
        ('always', 'Always-enter', {}),
        ('ppo_zero_cross', 'PPO zero-cross', {}),
        ('ema_sma_cross', 'EMA(10)/SMA(40)', {'ema_sma_fast': 10, 'ema_sma_slow': 40}),
        ('chandelier_entry', 'CHAND mult=1.5', {'chandelier_entry_mult': 1.5}),
        ('chandelier_entry', 'CHAND mult=2.0', {'chandelier_entry_mult': 2.0}),
    ]

    print(f"\n{'='*120}")
    print(f"{'Ticker':<8} {'Mode':<22} {'Trades':<8} {'Avg Gap':<10} {'Med Gap':<10} {'Max Gap':<10} {'Min Gap':<10} {'Gap>1d':<10} {'Gap>5d':<10} {'Gap>10d':<10}")
    print(f"{'='*120}")

    for sym in tickers:
        base = get_current_params(sym, db)
        alloc = db.get_laravel_allocation_weight(sym, default=10)
        for mode_key, mode_label, extra in configs:
            p = dict(base)
            p.update(extra)
            res = analyze(sym, mode_key, p, alloc)
            if not res:
                continue
            gaps = res['gaps']
            gt1 = (gaps > 1).sum()
            gt5 = (gaps > 5).sum()
            gt10 = (gaps > 10).sum()
            print(f"{sym:<8} {mode_label:<22} {res['n_trades']:<8} {gaps.mean():<10.1f} {gaps.median():<10.1f} {gaps.max():<10.0f} {gaps.min():<10.0f} {gt1:<10} {gt5:<10} {gt10:<10}")
        print(f"{'-'*120}")

    db.close()


if __name__ == '__main__':
    main()
