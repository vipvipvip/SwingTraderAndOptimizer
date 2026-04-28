"""Nightly optimizer - runs parameter optimization for all tickers"""
import argparse
import os
import sys
import time
import platform
from datetime import datetime
from zoneinfo import ZoneInfo
from joblib import Parallel, delayed
from dotenv import load_dotenv
from data_fetcher import load_data_from_db
from parameter_optimizer import ParameterOptimizer
from db import StrategyDB

load_dotenv()

# Parameter grids tuned per timeframe
PARAM_GRIDS = {
    '1Day': {
        'macd_fast':   [10, 12, 14],
        'macd_slow':   [24, 26, 28],
        'macd_signal': [7,  9,  11],
        'sma_short':   [40,  50,  60],
        'sma_long':    [180, 200, 220],
        'bb_period':   [18, 20, 22],
        'bb_std':      [1.8, 2.0, 2.2],
    },
    '1Hour': {
        'macd_fast':   [3,  5,  8],
        'macd_slow':   [13, 21, 34],
        'macd_signal': [3,  5,  8],
        'sma_short':   [20,  30,  50],
        'sma_long':    [100, 150, 200],
        'bb_period':   [14, 20, 26],
        'bb_std':      [1.8, 2.0, 2.2],
    },
}


def get_param_grid(timeframe):
    """Return default param grid for the given timeframe."""
    if timeframe in PARAM_GRIDS:
        return PARAM_GRIDS[timeframe]
    # Fallback: use 1Day grid with a warning
    print(f"Warning: no preset param grid for timeframe '{timeframe}', using 1Day grid")
    return PARAM_GRIDS['1Day']


def optimize_ticker(symbol, timeframe, param_grid=None, use_cache=True, allocation_weight=10):
    """
    Optimize strategy parameters for a single ticker.

    Args:
        symbol:     Stock symbol (e.g., 'SPY')
        timeframe:  Alpaca bar timeframe (e.g., '1Hour', '1Day')
        param_grid: Parameter ranges to test (defaults to timeframe preset)
        use_cache:  Use cached data if available
        allocation_weight: Capital allocation percentage per trade (default 10)

    Returns:
        dict with optimization results
    """

    print(f"\n{'='*70}")
    print(f"Optimizing {symbol} [{timeframe}]...")
    print(f"{'='*70}")

    start_time = time.time()

    if param_grid is None:
        param_grid = get_param_grid(timeframe)

    # Load data from database (already fetched in run_nightly_optimization)
    df = load_data_from_db(symbol)
    if df is None or len(df) == 0:
        print(f"Failed to load data for {symbol}")
        return None

    combos = 3 ** len(param_grid)
    print(f"Testing {combos} parameter combinations...")
    optimizer = ParameterOptimizer(df, symbol=symbol, allocation_weight=allocation_weight)
    results = optimizer.optimize(param_grid)

    best_result = results[0]
    runtime = time.time() - start_time

    print(f"\nResults for {symbol}:")
    print(f"  Best Sharpe: {best_result['metrics']['sharpe_ratio']:.2f}")
    print(f"  Win Rate: {best_result['metrics']['win_rate']*100:.1f}%")
    print(f"  Total Return: {best_result['metrics']['total_return']*100:.2f}%")
    print(f"  Trades: {best_result['metrics']['total_trades']}")
    print(f"  Runtime: {runtime:.1f}s")

    return {
        'symbol': symbol,
        'params': best_result['params'],
        'metrics': best_result['metrics'],
        'trades': best_result.get('trades', []),
        'equity_curve': best_result.get('equity_curve', []),
        'equity_dates': best_result.get('equity_dates', []),
        'runtime': runtime,
        'combos': combos,
    }


def _optimize_with_ticker_label(symbol, timeframe, param_grid):
    """Wrapper to show ticker label in parallel output."""
    print(f"\n[{symbol}] Starting optimization...")
    # Create DB connection inside worker to avoid pickle issues
    db = StrategyDB()
    allocation_weight = db.get_laravel_allocation_weight(symbol, default=10)
    db.close()
    return optimize_ticker(symbol, timeframe, param_grid=param_grid, use_cache=True, allocation_weight=allocation_weight)


def run_nightly_optimization(tickers=None, timeframe=None, param_grid=None, n_jobs=None):
    """
    Run nightly optimization for multiple tickers in parallel.

    Args:
        tickers:    List of symbols to optimize
        timeframe:  Bar timeframe (reads TRADING_TIMEFRAME env var, defaults to '1Hour')
        param_grid: Override param grid (defaults to timeframe preset)
        n_jobs:     Number of parallel jobs (default: -1 for all CPUs)
    """

    if tickers is None:
        tickers = ['SPY', 'QQQ', 'IWM']
    if timeframe is None:
        timeframe = os.getenv('TRADING_TIMEFRAME', '1Hour')
    if n_jobs is None:
        # Use parallel on Linux, sequential on Windows (Loky backend issues)
        n_jobs = -1 if platform.system() != 'Windows' else 1

    print(f"\n{'='*70}")
    print(f"NIGHTLY OPTIMIZER RUN")
    print(f"Timestamp: {datetime.now(ZoneInfo('America/New_York')).isoformat()}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Timeframe: {timeframe}")
    print(f"{'='*70}\n")

    db = StrategyDB()

    for symbol in tickers:
        db.add_ticker(symbol)

    # Step 1: Fetch incremental prices for each ticker
    print(f"\n{'='*70}")
    print("STEP 1: FETCHING INCREMENTAL PRICES")
    print(f"{'='*70}")
    from fetch_prices import fetch_and_update_ticker

    # Get all tickers from database
    all_tickers = db.get_all_tickers()
    all_ticker_symbols = all_tickers if all_tickers else tickers

    for symbol in all_ticker_symbols:
        fetch_and_update_ticker(symbol, timeframe=timeframe)

    results = []
    total_time = time.time()

    # Run optimizations in parallel using joblib
    results = Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(_optimize_with_ticker_label)(symbol, timeframe, param_grid)
        for symbol in tickers
    )

    # Filter out failed optimizations and save results to database
    results = [r for r in results if r is not None]
    for result in results:
        db.save_best_params(result['symbol'], result['params'], result['metrics'])
        db.save_backtest_trades(result['symbol'], result['trades'])
        db.save_equity_curve(result['symbol'], result.get('metrics', {}), result.get('equity_curve', []), result.get('equity_dates', []))
        db.log_optimization_run(
            result['symbol'],
            result['metrics'],
            result['combos'],
            int(result['runtime'])
        )

    total_time = time.time() - total_time

    print(f"\n{'='*70}")
    print(f"NIGHTLY OPTIMIZATION COMPLETE")
    print(f"{'='*70}")
    print(f"Total tickers: {len(results)}/{len(tickers)}")
    print(f"Total runtime: {total_time:.1f}s\n")

    for result in results:
        print(f"{result['symbol']}:")
        print(f"  Params: MACD({result['params']['macd_fast']},{result['params']['macd_slow']}) "
              f"SMA({result['params']['sma_short']},{result['params']['sma_long']})")
        print(f"  Sharpe: {result['metrics']['sharpe_ratio']:.2f} | "
              f"Return: {result['metrics']['total_return']*100:.2f}%")

    print(f"\n{'='*70}")
    print("DATABASE SUMMARY")
    print(f"{'='*70}\n")

    for symbol in tickers:
        params = db.get_best_params(symbol)
        if params:
            print(f"{symbol} (updated {params['updated_at']}):")
            print(f"  {params}")

    db.close()
    return results


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Nightly parameter optimizer')
        parser.add_argument(
            '--timeframe',
            default=os.getenv('TRADING_TIMEFRAME', '1Hour'),
            help='Bar timeframe: 1Hour, 1Day, 30Min, etc. (default: TRADING_TIMEFRAME env or 1Hour)'
        )
        parser.add_argument(
            '--tickers',
            nargs='+',
            default=['SPY', 'QQQ', 'IWM'],
            help='Symbols to optimize (default: SPY QQQ IWM)'
        )
        args = parser.parse_args()

        run_nightly_optimization(tickers=args.tickers, timeframe=args.timeframe)
        sys.exit(0)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
