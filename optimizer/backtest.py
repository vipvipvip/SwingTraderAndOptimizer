#!/usr/bin/env python3
"""Backtest with current parameters from database (no optimization)"""
import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer
from db import StrategyDB

def validate_sync(symbol, trades, metrics, db):
    """Validate that backtest results are in sync with database"""
    if not trades:
        return True  # No trades to validate

    import pandas as pd
    trades_df = pd.DataFrame(trades)
    calculated_pnl = trades_df['pnl_dollar'].sum()
    expected_return = calculated_pnl / 100000
    reported_return = metrics['total_return']

    tolerance = 0.0001  # 0.01% tolerance
    if abs(expected_return - reported_return) > tolerance:
        print(f"  ⚠ SYNC WARNING: PnL sum (${calculated_pnl:.2f}) doesn't match reported return ({reported_return*100:.2f}%)")
        return False

    return True

def backtest_ticker(symbol, timeframe, allocation_weight=None):
    """Backtest a single ticker with current parameters from DB"""

    # Load current parameters from database
    db = StrategyDB()
    conn = db.get_connection()
    cursor = conn.cursor()

    # If allocation_weight not provided, load from database
    if allocation_weight is None:
        allocation_weight = db.get_laravel_allocation_weight(symbol, default=10)

    # Query strategy_parameters for this ticker (base_case=true only)
    cursor.execute('''
        SELECT macd_fast, macd_slow, macd_signal, bb_period, bb_std
        FROM strategy_parameters
        WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
        AND base_case = true
        LIMIT 1
    ''', (symbol,))

    params_row = cursor.fetchone()

    if not params_row:
        print(f"ERROR: No strategy parameters found for {symbol}")
        db.close()
        return False

    # Extract parameters from database row
    params = {
        'macd_fast': int(params_row[0]),
        'macd_slow': int(params_row[1]),
        'macd_signal': int(params_row[2]),
        'bb_period': int(params_row[3]),
        'bb_std': float(params_row[4]),
    }

    print(f"\n[{symbol}] Backtesting with current parameters:")
    print(f"  MACD: fast={params['macd_fast']}, slow={params['macd_slow']}, signal={params['macd_signal']}")
    print(f"  Bollinger Bands: period={params['bb_period']}, std={params['bb_std']}")

    # Load price data
    data_df = load_data_from_db(symbol)
    if data_df is None or len(data_df) == 0:
        print(f"ERROR: No data found for {symbol}")
        return False

    print(f"  Data: {len(data_df)} rows ({data_df.index[0]} to {data_df.index[-1]})")

    # Run backtest
    optimizer = ParameterOptimizer(data_df, initial_capital=100000, symbol=symbol, allocation_weight=allocation_weight)
    trades, metrics, equity_curve, equity_dates = optimizer._backtest_with_params(params)

    # Store results in database
    if trades:
        # Validate sync before saving
        if not validate_sync(symbol, trades, metrics, db):
            print(f"  ✗ SYNC VALIDATION FAILED - aborting save")
            db.close()
            return False

        db.save_backtest_trades(symbol, trades)
        db.save_equity_curve(symbol, metrics, equity_curve, equity_dates)
        db.update_strategy_metrics(symbol, metrics)
        print(f"  ✓ Stored {len(trades)} trades")
        print(f"  ✓ SYNC VALIDATED: Sharpe={metrics['sharpe_ratio']:.4f}, Return={metrics['total_return']*100:.2f}%, Win Rate={metrics['win_rate']*100:.1f}%")
    else:
        print(f"  ✗ No trades generated")

    db.close()
    return True

def backtest_params_with_id(symbol, params, params_id=None, test_type='baseline'):
    """Backtest specific parameters (used for candidates or baseline)"""
    data_df = load_data_from_db(symbol)
    if data_df is None or len(data_df) == 0:
        return None

    db = StrategyDB()
    allocation_weight = db.get_laravel_allocation_weight(symbol, default=10)
    db.close()

    optimizer = ParameterOptimizer(data_df, initial_capital=100000, symbol=symbol, allocation_weight=allocation_weight)
    trades, metrics, equity_curve, equity_dates = optimizer._backtest_with_params(params)

    return {
        'id': params_id,
        'type': test_type,
        'trades': trades,
        'metrics': metrics,
        'equity_curve': equity_curve,
        'equity_dates': equity_dates,
    }

def compare_and_report(symbol, baseline, candidates):
    """Compare baseline vs candidates and report which are better"""
    print(f"\n{'='*80}")
    print(f"COMPARISON: {symbol} - Baseline vs Candidates")
    print(f"{'='*80}")

    baseline_return = baseline['metrics']['total_return'] * 100
    baseline_sharpe = baseline['metrics']['sharpe_ratio']

    print(f"\nCurrent Base Case (base_case=1):")
    print(f"  Return: {baseline_return:.2f}%, Sharpe: {baseline_sharpe:.4f}, Trades: {len(baseline['trades'])}")

    print(f"\nCandidates (base_case=0):")
    better_count = 0
    for c in candidates:
        cand_return = c['metrics']['total_return'] * 100
        cand_sharpe = c['metrics']['sharpe_ratio']
        return_diff = cand_return - baseline_return
        sharpe_diff = cand_sharpe - baseline_sharpe

        is_better = return_diff > 0 and sharpe_diff > 0
        better_mark = "✓ BETTER" if is_better else "  "
        if is_better:
            better_count += 1

        print(f"  {better_mark} ID {c['id']}: Return {cand_return:.2f}% ({return_diff:+.2f}%), "
              f"Sharpe {cand_sharpe:.4f} ({sharpe_diff:+.4f}), Trades: {len(c['trades'])}")

    print(f"\nSummary: {better_count} candidates better than baseline")
    return better_count

def main():
    parser = argparse.ArgumentParser(description='Backtest with parameter comparison')
    parser.add_argument('--timeframe', default='1Hour', help='Timeframe (default: 1Hour)')
    parser.add_argument('--tickers', nargs='+', default=['QQQ', 'VTI', 'VTV'], help='Tickers to backtest')
    parser.add_argument('--allocation', type=float, default=None, help='Capital allocation % per trade (default: load from database)')
    parser.add_argument('--mode', choices=['baseline', 'candidates', 'all'], default='baseline',
                        help='baseline: test base_case=1, candidates: test base_case=0, all: compare both')

    args = parser.parse_args()

    print(f"\n[{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}] Backtest starting (mode: {args.mode})...")

    if args.mode == 'baseline':
        # Test only base_case=1 (current locked parameters)
        success_count = 0
        for ticker in args.tickers:
            if backtest_ticker(ticker, args.timeframe, args.allocation):
                success_count += 1
        print(f"\n[{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}] Baseline backtest complete ({success_count}/{len(args.tickers)} successful)")

    elif args.mode in ['candidates', 'all']:
        # Test candidates (base_case=0) and optionally compare vs baseline
        db = StrategyDB()
        conn = db.get_connection()
        cursor = conn.cursor()

        for ticker in args.tickers:
            print(f"\n[{ticker}] Loading parameters...")

            # Get baseline (base_case=1)
            cursor.execute('''
                SELECT id, macd_fast, macd_slow, macd_signal, bb_period, bb_std
                FROM strategy_parameters
                WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
                AND base_case = true
                LIMIT 1
            ''', (ticker,))
            baseline_row = cursor.fetchone()
            if not baseline_row:
                print(f"  ERROR: No baseline found for {ticker}")
                continue

            baseline_params = {
                'macd_fast': int(baseline_row[1]),
                'macd_slow': int(baseline_row[2]),
                'macd_signal': int(baseline_row[3]),
                'bb_period': int(baseline_row[4]),
                'bb_std': float(baseline_row[5]),
            }

            # Get candidates (base_case=0)
            cursor.execute('''
                SELECT id, macd_fast, macd_slow, macd_signal, bb_period, bb_std
                FROM strategy_parameters
                WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
                AND base_case = false
                ORDER BY sharpe_ratio DESC
                LIMIT 5
            ''', (ticker,))
            candidate_rows = cursor.fetchall()

            if args.mode == 'all' or not candidate_rows:
                # Backtest baseline
                print(f"  Backtesting baseline...")
                baseline = backtest_params_with_id(ticker, baseline_params, 0, 'baseline')

                # Backtest candidates
                candidates = []
                for cand_row in candidate_rows:
                    cand_id = cand_row[0]
                    cand_params = {
                        'macd_fast': int(cand_row[1]),
                        'macd_slow': int(cand_row[2]),
                        'macd_signal': int(cand_row[3]),
                        'bb_period': int(cand_row[4]),
                        'bb_std': float(cand_row[5]),
                    }
                    print(f"  Backtesting candidate {cand_id}...")
                    result = backtest_params_with_id(ticker, cand_params, cand_id, 'candidate')
                    if result:
                        candidates.append(result)

                # Compare and report
                if baseline and candidates:
                    compare_and_report(ticker, baseline, candidates)

        db.close()

if __name__ == '__main__':
    main()
