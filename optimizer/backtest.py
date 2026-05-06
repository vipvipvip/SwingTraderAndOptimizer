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

def backtest_ticker(symbol, timeframe, allocation_weight=10):
    """Backtest a single ticker with current parameters from DB"""

    # Load current parameters from database
    db = StrategyDB()
    conn = db.get_connection()
    cursor = conn.cursor()

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
        print(f"  ✓ Stored {len(trades)} trades")
        print(f"  ✓ SYNC VALIDATED: Sharpe={metrics['sharpe_ratio']:.4f}, Return={metrics['total_return']*100:.2f}%, Win Rate={metrics['win_rate']*100:.1f}%")
    else:
        print(f"  ✗ No trades generated")

    db.close()
    return True

def main():
    parser = argparse.ArgumentParser(description='Backtest with current parameters')
    parser.add_argument('--timeframe', default='1Hour', help='Timeframe (default: 1Hour)')
    parser.add_argument('--tickers', nargs='+', default=['SPY', 'QQQ', 'IWM'], help='Tickers to backtest')
    parser.add_argument('--allocation', type=float, default=10, help='Capital allocation % per trade')

    args = parser.parse_args()

    print(f"\n[{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}] Backtest starting...")

    success_count = 0
    for ticker in args.tickers:
        if backtest_ticker(ticker, args.timeframe, args.allocation):
            success_count += 1

    print(f"\n[{datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}] Backtest complete ({success_count}/{len(args.tickers)} successful)")

if __name__ == '__main__':
    main()
