#!/usr/bin/env python3
"""Compare entry strategies: always, PPO, EMA/SMA, Chandelier breakout"""
import sys
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer
from db import StrategyDB


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


def run_backtest(symbol, params, entry_mode, alloc_weight):
    df = load_data_from_db(symbol)
    if df is None or len(df) == 0:
        return None
    opt = ParameterOptimizer(df, initial_capital=100000, symbol=symbol, allocation_weight=alloc_weight)
    trades, metrics, eq_curve, eq_dates = opt._backtest_with_params(params, entry_mode=entry_mode)
    return metrics


def main():
    tickers = ['SPY', 'QQQ', 'IWM', 'VTI', 'VTV']
    entry_mults = [0.5, 1.0, 1.5, 2.0]

    db = StrategyDB()

    print(f"\n{'='*110}")
    print(f"{'Ticker':<8} {'Mode':<22} {'Sharpe':<10} {'Return':<12} {'Trades':<8} {'Win%':<8} {'MaxDD':<8}")
    print(f"{'='*110}")

    results = []

    for sym in tickers:
        base_params = get_current_params(sym, db)
        alloc = db.get_laravel_allocation_weight(sym, default=10)

        always_m = run_backtest(sym, dict(base_params), 'always', alloc)
        ppo_m = run_backtest(sym, dict(base_params), 'ppo_zero_cross', alloc)

        p = dict(base_params)
        p['ema_sma_fast'] = 10
        p['ema_sma_slow'] = 40
        ema_sma_m = run_backtest(sym, p, 'ema_sma_cross', alloc)

        chand_results = {}
        for mult in entry_mults:
            p = dict(base_params)
            p['chandelier_entry_mult'] = mult
            m = run_backtest(sym, p, 'chandelier_entry', alloc)
            if m:
                chand_results[mult] = m

        if always_m:
            results.append((sym, 'always', always_m, ''))
            print(f"{sym:<8} {'Always-enter':<22} {always_m['sharpe_ratio']:<10.2f} {always_m['total_return']*100:<11.2f}% {always_m['total_trades']:<8} {always_m['win_rate']*100:<7.1f}% {always_m['max_drawdown']*100:<7.1f}%")
        if ppo_m:
            results.append((sym, 'ppo', ppo_m, ''))
            print(f"{sym:<8} {'PPO zero-cross':<22} {ppo_m['sharpe_ratio']:<10.2f} {ppo_m['total_return']*100:<11.2f}% {ppo_m['total_trades']:<8} {ppo_m['win_rate']*100:<7.1f}% {ppo_m['max_drawdown']*100:<7.1f}%")
        if ema_sma_m:
            results.append((sym, 'ema_sma', ema_sma_m, ''))
            print(f"{sym:<8} {'EMA(10)/SMA(40)':<22} {ema_sma_m['sharpe_ratio']:<10.2f} {ema_sma_m['total_return']*100:<11.2f}% {ema_sma_m['total_trades']:<8} {ema_sma_m['win_rate']*100:<7.1f}% {ema_sma_m['max_drawdown']*100:<7.1f}%")
        for mult in entry_mults:
            if mult in chand_results:
                m = chand_results[mult]
                results.append((sym, f'chand_{mult}', m, f'{mult}'))
                print(f"{sym:<8} {'CHAND entry mult=' + str(mult):<22} {m['sharpe_ratio']:<10.2f} {m['total_return']*100:<11.2f}% {m['total_trades']:<8} {m['win_rate']*100:<7.1f}% {m['max_drawdown']*100:<7.1f}%")
        print(f"{'-'*110}")

    # Summary: find best CHAND entry_mult per ticker
    print(f"\n{'='*110}")
    print("BEST CHANDELIER ENTRY MULT VS ALWAYS-ENTER")
    print(f"{'='*110}")
    totals = {}
    for sym in tickers:
        a = next((r for r in results if r[0] == sym and r[1] == 'always'), None)
        if not a:
            continue
        am = a[2]

        best_mult = None
        best_sharpe = -999
        for mult in entry_mults:
            r = next((x for x in results if x[0] == sym and x[1] == f'chand_{mult}'), None)
            if r and r[2]['sharpe_ratio'] > best_sharpe:
                best_sharpe = r[2]['sharpe_ratio']
                best_mult = mult

        if best_mult is not None:
            bm = next(x[2] for x in results if x[0] == sym and x[1] == f'chand_{best_mult}')
            ed = '' if 'key' in locals() else ''
            print(f"{sym:<8}  Best mult={best_mult}  Sharpe: {am['sharpe_ratio']:.2f} → {bm['sharpe_ratio']:.2f} (▼{am['sharpe_ratio']-bm['sharpe_ratio']:.2f})  "
                  f"Return: {am['total_return']*100:.1f}% → {bm['total_return']*100:.1f}%  "
                  f"Trades: {am['total_trades']} → {bm['total_trades']}")
            totals.setdefault('always', {'sharpe': 0, 'return': 0, 'trades': 0, 'count': 0})
            totals.setdefault('chand_entry', {'sharpe': 0, 'return': 0, 'trades': 0, 'count': 0})
            totals['always']['sharpe'] += am['sharpe_ratio']
            totals['always']['return'] += am['total_return']
            totals['always']['trades'] += am['total_trades']
            totals['always']['count'] += 1
            totals['chand_entry']['sharpe'] += bm['sharpe_ratio']
            totals['chand_entry']['return'] += bm['total_return']
            totals['chand_entry']['trades'] += bm['total_trades']
            totals['chand_entry']['count'] += 1

    if totals.get('always') and totals['always']['count'] > 0:
        a = totals['always']
        c = totals['chand_entry']
        print(f"\n{'─'*110}")
        print(f"Avg Sharpe:   Always={a['sharpe']/a['count']:.2f}  CHAND entry={c['sharpe']/c['count']:.2f}  (▼{a['sharpe']/a['count']-c['sharpe']/c['count']:.2f})")
        print(f"Avg Return:   Always={a['return']/a['count']*100:.1f}%  CHAND entry={c['return']/c['count']*100:.1f}%")
        print(f"Total Trades: Always={a['trades']}  CHAND entry={c['trades']}")

    db.close()


if __name__ == '__main__':
    main()
