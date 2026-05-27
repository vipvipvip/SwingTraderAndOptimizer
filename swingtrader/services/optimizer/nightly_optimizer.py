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
# Chandelier Exit: period (macd_fast) and multiplier (bb_std)
PARAM_GRIDS = {
    '1Day': {
        'macd_fast':   [14, 18, 22],
        'bb_std':      [2.5, 3.0, 3.5],
    },
    '1Hour': {
        'macd_fast':   [14, 18, 22],
        'bb_std':      [2.5, 3.0, 3.5],
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
        tickers = ['QQQ', 'VTI', 'VTV']
    if timeframe is None:
        timeframe = os.getenv('TRADING_TIMEFRAME', '1Day')
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
        if symbol == 'BLENDED':
            continue
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

            # Also update base_case=true with individual ticker metrics
            # (coordinate ascent later updates only the params, not metrics)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE strategy_parameters
                SET win_rate = %s, sharpe_ratio = %s, total_return = %s,
                    total_trades = %s, max_drawdown = %s, updated_at = NOW()
                WHERE ticker_id = %s AND base_case = true
            ''', (
                float(best_result['metrics']['win_rate']),
                float(best_result['metrics']['sharpe_ratio']),
                float(best_result['metrics']['total_return']),
                int(best_result['metrics']['total_trades']),
                float(best_result['metrics'].get('max_drawdown', 0)),
                ticker_id
            ))
            conn.commit()
            print(f"✓ Updated base_case=true metrics for {symbol}")

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

    # --- Step 3: Portfolio coordinate ascent ---
    # Uses coordinate ascent to find the per-ticker params that maximize BLENDED Sharpe
    print(f"\n{'='*70}")
    print("STEP 3: PORTFOLIO COORDINATE ASCENT")
    print(f"{'='*70}")
    from data_fetcher import load_data_from_db
    from parameter_optimizer import ParameterOptimizer

    # Build candidate pool per ticker: current active + top 5 from optimizer
    conn = db.get_connection()
    cursor = conn.cursor()
    ticker_candidates = {}
    for sym in tickers:
        candidates = []
        cursor.execute('''
            SELECT macd_fast, bb_std FROM strategy_parameters
            WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
            AND base_case = true LIMIT 1
        ''', (sym,))
        row = cursor.fetchone()
        if row:
            candidates.append({'macd_fast': int(row[0]), 'bb_std': float(row[1])})
        for result in results:
            if result['symbol'] == sym:
                opt = result.get('optimizer')
                if opt and opt.results:
                    for r in opt.results[:5]:
                        candidates.append(r['params'])
                break
        seen = set()
        ticker_candidates[sym] = []
        for c in candidates:
            k = (c['macd_fast'], c['bb_std'])
            if k not in seen:
                seen.add(k)
                ticker_candidates[sym].append(c)

    ticker_data = {}
    for sym in tickers:
        df = load_data_from_db(sym)
        if df is not None:
            ticker_data[sym] = df

    # Start from current active params
    current = {}
    for sym in tickers:
        cursor.execute('''
            SELECT macd_fast, bb_std FROM strategy_parameters
            WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
            AND base_case = true LIMIT 1
        ''', (sym,))
        row = cursor.fetchone()
        if row:
            current[sym] = {'macd_fast': int(row[0]), 'bb_std': float(row[1])}
        else:
            current[sym] = ticker_candidates[sym][0]

    ticker_symbols = list(tickers)
    for iteration in range(5):
        improved = False
        for sym in ticker_symbols:
            best_sharpe = -999
            best_params = current[sym]
            best_metrics = None
            best_trades = None
            best_equity = None
            for cand in ticker_candidates[sym]:
                test_params = dict(current)
                test_params[sym] = cand
                trades, metrics, eq_curve, eq_dates = ParameterOptimizer.backtest_portfolio(
                    ticker_data, test_params, initial_capital=100000
                )
                if metrics['sharpe_ratio'] > best_sharpe:
                    best_sharpe = metrics['sharpe_ratio']
                    best_params = cand
                    best_metrics = metrics
                    best_trades = trades
                    best_equity = (eq_curve, eq_dates)
            if best_params != current[sym]:
                current[sym] = best_params
                improved = True

        if not improved:
            break

    # Run final portfolio backtest with converged params
    ptrades, pmetrics, pequity, pequity_dates = ParameterOptimizer.backtest_portfolio(
        ticker_data, current, initial_capital=100000
    )
    print(f"  Converged after {iteration+1} iterations")
    print(f"  Portfolio return: {pmetrics['total_return']*100:.2f}%")
    print(f"  Sharpe: {pmetrics['sharpe_ratio']:.2f}")
    print(f"  Max DD: {pmetrics['max_drawdown']*100:.2f}%")
    print(f"  Trades: {pmetrics['total_trades']}")
    for sym in ticker_symbols:
        p = current[sym]
        print(f"  {sym}: CHAND({p['macd_fast']}, {p['bb_std']})")

    # Update base_case=true for each ticker with portfolio-optimized params only
    # (metrics are kept from individual optimization to show per-ticker performance)
    for sym in ticker_symbols:
        p = current[sym]
        cursor.execute('''
            UPDATE strategy_parameters
            SET macd_fast = %s, bb_std = %s, bb_period = %s, updated_at = NOW()
            WHERE ticker_id = (SELECT id FROM tickers WHERE symbol = %s)
            AND base_case = true
        ''', (
            p['macd_fast'], p['bb_std'], p['macd_fast'], sym
        ))
    conn.commit()

    # Save BLENDED results
    cursor.execute("SELECT id FROM tickers WHERE symbol = 'BLENDED'")
    blended_row = cursor.fetchone()
    if not blended_row:
        cursor.execute("INSERT INTO tickers (symbol, enabled) VALUES ('BLENDED', true)")
        conn.commit()
        cursor.execute("SELECT id FROM tickers WHERE symbol = 'BLENDED'")
        blended_id = cursor.fetchone()[0]
    else:
        blended_id = blended_row[0]

    cursor.execute('''
        SELECT id FROM strategy_parameters
        WHERE ticker_id = %s AND base_case = true LIMIT 1
    ''', (blended_id,))
    existing = cursor.fetchone()

    first = next(iter(current.values()))
    if existing:
        cursor.execute('''
            UPDATE strategy_parameters
            SET macd_fast = %s, bb_std = %s, win_rate = %s, sharpe_ratio = %s,
                total_return = %s, total_trades = %s, max_drawdown = %s, updated_at = NOW()
            WHERE id = %s
        ''', (
            first['macd_fast'], first['bb_std'],
            float(pmetrics['win_rate']), float(pmetrics['sharpe_ratio']),
            float(pmetrics['total_return']), int(pmetrics['total_trades']),
            float(pmetrics['max_drawdown']), existing[0]
        ))
    else:
        cursor.execute('''
            INSERT INTO strategy_parameters
            (ticker_id, macd_fast, bb_period, bb_std,
             win_rate, sharpe_ratio, total_return, total_trades, max_drawdown,
             base_case, created_at, updated_at)
            VALUES (%s, %s, %s, %s,
                    %s, %s, %s, %s, %s, true, NOW(), NOW())
        ''', (
            blended_id, first['macd_fast'], first['macd_fast'], first['bb_std'],
            float(pmetrics['win_rate']), float(pmetrics['sharpe_ratio']),
            float(pmetrics['total_return']), int(pmetrics['total_trades']),
            float(pmetrics['max_drawdown']),
        ))
    conn.commit()
    db.save_backtest_trades('BLENDED', ptrades)
    db.save_equity_curve('BLENDED', pmetrics, pequity, pequity_dates)
    print("  ✓ Saved BLENDED portfolio results")

    total_time = time.time() - total_time

    print(f"\n{'='*70}")
    print(f"NIGHTLY OPTIMIZATION COMPLETE")
    print(f"{'='*70}")
    print(f"Total tickers: {len(results)}/{len(tickers)}")
    print(f"Total runtime: {total_time:.1f}s\n")

    for result in results:
        print(f"{result['symbol']}:")
        print(f"  Params: CHAND(period={result['params']['macd_fast']}, mult={result['params']['bb_std']})")
        print(f"  Sharpe: {result['metrics']['sharpe_ratio']:.2f} | "
              f"Return: {result['metrics']['total_return']*100:.2f}%")

    print(f"\n{'='*70}")
    print("DATABASE SUMMARY")
    print(f"{'='*70}\n")

    for symbol in list(tickers) + ['BLENDED']:
        params = db.get_best_params(symbol)
        if params:
            label = f"{symbol} (PORTFOLIO)" if symbol == 'BLENDED' else symbol
            print(f"{label}:")
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
            default=os.getenv('TRADING_TIMEFRAME', '1Day'),
            help='Bar timeframe: 1Day, 1Hour, etc. (default: TRADING_TIMEFRAME env or 1Day)'
        )
        parser.add_argument(
            '--tickers',
            nargs='+',
            default=['QQQ', 'VTI', 'VTV'],
            help='Symbols to optimize (default: QQQ VTI VTV)'
        )
        args = parser.parse_args()

        run_nightly_optimization(tickers=args.tickers, timeframe=args.timeframe)
        sys.exit(0)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
