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
# MACD (18/26/14), PPO (12/26), EMA10/SMA40, SMA50/200 are FIXED
# Only Bollinger Bands parameters are optimized
PARAM_GRIDS = {
    '1Day': {
        'bb_period':   [20],
        'bb_std':      [2.0],
    },
    '1Hour': {
        'bb_period':   [20],
        'bb_std':      [2.0],
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
        'optimizer': optimizer,
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
        # Save only the best candidate (base_case=0) from this run
        # Old candidates are cleaned up to prevent table bloat
        symbol = result['symbol']
        optimizer = result.get('optimizer')
        if optimizer and optimizer.results:
            ticker_id = db.get_ticker_id(symbol)
            if ticker_id:
                # Clean up old base_case=0 candidates for this ticker
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'DELETE FROM strategy_parameters WHERE ticker_id = %s AND base_case = false',
                    (ticker_id,)
                )
                conn.commit()

            # Save only the best candidate from this optimization run
            best_result = optimizer.results[0]
            db.save_best_params(symbol, best_result['params'], best_result['metrics'])
            print(f"✓ Saved best candidate for {symbol} (cleaned up old candidates)")

        # Save trades and equity curve for the BEST candidate ONLY
        # Other candidates will be evaluated via backtest.py --mode all
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
        print(f"  Params: BB(period={result['params']['bb_period']}, std={result['params']['bb_std']})")
        print(f"  Sharpe: {result['metrics']['sharpe_ratio']:.2f} | "
              f"Return: {result['metrics']['total_return']*100:.2f}%")

    print(f"\n{'='*70}")
    print("DATABASE SUMMARY")
    print(f"{'='*70}\n")

    for symbol in tickers:
        params = db.get_best_params(symbol)
        if params:
            print(f"{symbol}:")
            print(f"  Sharpe: {params['metrics']['sharpe_ratio']:.2f}, "
                  f"Return: {params['metrics']['total_return']*100:.2f}%, "
                  f"Win Rate: {params['metrics']['win_rate']*100:.1f}%")

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
