"""Parallel parameter optimizer using multiprocessing - ready for Phase 1C"""
import itertools
import json
import pandas as pd
import numpy as np
from datetime import datetime
from multiprocessing import Pool, Manager
import os
from parameter_optimizer import ParameterOptimizer


def backtest_single_params(args):
    """
    Backtest a single parameter combination

    Args:
        args: tuple of (data_df, params, initial_capital)

    Returns:
        dict with params and metrics
    """
    data_df, params, initial_capital = args

    # Create optimizer instance just for this worker process
    optimizer = ParameterOptimizer(data_df, initial_capital)
    trades, metrics, equity_curve = optimizer._backtest_with_params(params)

    return {
        'params': params,
        'metrics': metrics,
        'trades_count': len(trades) if trades is not None else 0
    }


class ParallelParameterOptimizer(ParameterOptimizer):
    """Extended optimizer with multiprocessing support"""

    def optimize_parallel(self, param_grid, num_workers=None):
        """
        Run grid search with multiprocessing

        Args:
            param_grid: dict with lists of parameter values
            num_workers: number of CPU cores to use (None = auto-detect)

        Returns:
            List of results sorted by Sharpe ratio
        """

        # Auto-detect number of workers if not specified
        if num_workers is None:
            num_workers = os.cpu_count() - 1  # Leave 1 core free

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = [param_grid[name] for name in param_names]
        combinations = list(itertools.product(*param_values))

        print(f"\nTesting {len(combinations)} parameter combinations with {num_workers} workers...")
        print(f"Estimated speedup: ~{num_workers}x faster than serial\n")

        # Prepare arguments for each worker
        worker_args = [
            (self.data, dict(zip(param_names, combo)), self.initial_capital)
            for combo in combinations
        ]

        # Run backtests in parallel
        with Pool(num_workers) as pool:
            self.results = pool.map(backtest_single_params, worker_args)

        # Sort by Sharpe ratio (descending)
        self.results.sort(
            key=lambda x: x['metrics']['sharpe_ratio'],
            reverse=True
        )

        print(f"\n[OK] Optimization complete! Top 5 results:\n")
        self._print_top_results(5)

        return self.results


def run_parallel_optimization(symbol='SPY', num_workers=None):
    """Run parallel optimization for a ticker"""
    from data_fetcher import load_data

    print(f"\n{'='*80}")
    print(f"PARALLEL PARAMETER OPTIMIZATION: {symbol}")
    print(f"{'='*80}\n")

    # Load data
    df = load_data(symbol, '1Day')
    if df is None:
        print(f"No cached data for {symbol}")
        return

    # Parameter grid
    param_grid = {
        'macd_fast': [10, 12, 14],
        'macd_slow': [24, 26, 28],
        'macd_signal': [7, 9, 11],
        'sma_short': [40, 50, 60],
        'sma_long': [180, 200, 220],
        'bb_period': [18, 20, 22],
        'bb_std': [1.8, 2.0, 2.2]
    }

    # Run optimization
    optimizer = ParallelParameterOptimizer(df)
    results = optimizer.optimize_parallel(param_grid, num_workers=num_workers)

    # Save results
    if not os.path.exists('optimized_params'):
        os.makedirs('optimized_params')

    output_file = f"optimized_params/{symbol}_best_params_parallel.json"
    optimizer.save_best_params(output_file)

    return optimizer, results


if __name__ == '__main__':
    # Test parallel optimization
    # Uncomment to use:
    # optimizer, results = run_parallel_optimization(symbol='SPY', num_workers=4)
    print("Parallel optimizer ready for Phase 1C (multi-ticker nightly runs)")
    print("Usage: run_parallel_optimization('SPY', num_workers=4)")
