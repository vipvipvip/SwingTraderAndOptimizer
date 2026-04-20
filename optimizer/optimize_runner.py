"""Run parameter optimization for a ticker"""
import os
import sys
from data_fetcher import load_data
from parameter_optimizer import ParameterOptimizer


def run_optimization(symbol='SPY', param_grid=None):
    """
    Run parameter grid search optimization

    Args:
        symbol: Stock symbol to optimize
        param_grid: Dict of parameter ranges to test
    """

    print(f"\n{'='*80}")
    print(f"PARAMETER OPTIMIZATION: {symbol}")
    print(f"{'='*80}\n")

    # Load historical data
    df = load_data(symbol, '1Day')
    if df is None:
        print(f"No cached data for {symbol}. Run backtest_runner.py first to fetch data.")
        return

    print(f"Data: {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}\n")

    # Default parameter grid if not provided
    if param_grid is None:
        param_grid = {
            'macd_fast': [10, 12, 14],
            'macd_slow': [24, 26, 28],
            'macd_signal': [7, 9, 11],
            'sma_short': [40, 50, 60],
            'sma_long': [180, 200, 220],
            'bb_period': [18, 20, 22],
            'bb_std': [1.8, 2.0, 2.2]
        }

    print("Parameter ranges to test:")
    for param, values in param_grid.items():
        print(f"  {param}: {values}")

    # Run optimization
    optimizer = ParameterOptimizer(df)
    results = optimizer.optimize(param_grid)

    # Save best parameters
    if not os.path.exists('optimized_params'):
        os.makedirs('optimized_params')

    output_file = f"optimized_params/{symbol}_best_params.json"
    optimizer.save_best_params(output_file)

    return optimizer, results


def get_best_params(symbol='SPY'):
    """Load best parameters for a symbol"""
    import json

    filepath = f"optimized_params/{symbol}_best_params.json"

    if not os.path.exists(filepath):
        print(f"No optimized parameters found for {symbol}")
        return None

    with open(filepath, 'r') as f:
        data = json.load(f)

    return data['best_params']


if __name__ == '__main__':
    # Run with default parameter grid
    optimizer, results = run_optimization(symbol='SPY')

    # Show how to use the best params
    print(f"\n{'='*80}")
    print("NEXT STEPS:")
    print(f"{'='*80}")
    print("\n1. Load best parameters:")
    print("   best_params = get_best_params('SPY')")
    print("\n2. Run backtest with these parameters:")
    print("   from backtest_runner import run_backtest")
    print("   trades, metrics, equity_curve, df = run_backtest('SPY')")
    print("\n3. For nightly optimization, add this to a cron job:")
    print("   python optimize_runner.py")
    print("\n")
