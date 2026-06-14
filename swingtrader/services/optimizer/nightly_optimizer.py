"""Nightly optimizer - runs parameter optimization for all tickers"""
import argparse
import itertools
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
        'chandelier_period':       [14, 18, 22],
        'chandelier_mult':         [2.5, 3.0, 3.5],
        'chandelier_entry_mult':   [1.0, 1.5, 2.0],
    },
}

# Regression exit grid (tested after chandelier-only grid, using best chandelier params)
REG_PARAM_GRID = {
    'reg_slope_window':   [3, 5, 8, 10],
    'reg_slope_threshold': [-2.0, -1.0, -0.5, -0.3],
    'reg_slope_type':     ['slope_atr', 'slope_pct'],
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

    Two-pass search:
    1. Chandelier-only: grid search period/mult/entry_mult
    2. Chandelier + regression: fix best chandelier params, grid search regression window/threshold/type
    Keeps whichever gives better Sharpe.

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

    df = load_data_from_db(symbol)
    if df is None or len(df) == 0:
        print(f"Failed to load data for {symbol}")
        return None

    # ── Pass 1: Chandelier-only ──
    combos = 3 ** len(param_grid)
    print(f"PASS 1: Testing {combos} chandelier-only combinations...")
    optimizer = ParameterOptimizer(df, symbol=symbol, allocation_weight=allocation_weight)
    results = optimizer.optimize(param_grid)
    chand_best = results[0]
    chand_metrics = chand_best['metrics']

    # ── Pass 2: Chandelier + regression ──
    print(f"\nPASS 2: Testing {len(REG_PARAM_GRID['reg_slope_window']) * len(REG_PARAM_GRID['reg_slope_threshold']) * len(REG_PARAM_GRID['reg_slope_type'])} regression combinations"
          f" (fixed chandelier: period={chand_best['params']['chandelier_period']}, mult={chand_best['params']['chandelier_mult']}, entry={chand_best['params']['chandelier_entry_mult']})...")
    reg_params_list = list(itertools.product(
        REG_PARAM_GRID['reg_slope_window'],
        REG_PARAM_GRID['reg_slope_threshold'],
        REG_PARAM_GRID['reg_slope_type'],
    ))
    reg_results = []
    for w, th, rt in reg_params_list:
        p = dict(chand_best['params'])
        p.update({'reg_slope_window': w, 'reg_slope_threshold': th, 'reg_slope_type': rt})
        trades, metrics, eq, dates = optimizer._backtest_with_params(p, entry_mode='chandelier_entry')
        reg_results.append({'params': p, 'metrics': metrics, 'trades': trades,
                            'equity_curve': eq, 'equity_dates': dates})
    reg_results.sort(key=lambda r: r['metrics']['sharpe_ratio'], reverse=True)
    reg_best = reg_results[0] if reg_results else None

    # ── Compare and pick best ──
    reg_note = ''
    if reg_best and reg_best['metrics']['total_trades'] >= 3:
        chand_sharpe = chand_metrics['sharpe_ratio']
        reg_sharpe = reg_best['metrics']['sharpe_ratio']
        if reg_sharpe > chand_sharpe and reg_best['metrics']['total_return'] >= chand_metrics['total_return'] * 0.8:
            best_result = reg_best
            reg_note = f" (+ REG {reg_best['params']['reg_slope_type']} {reg_best['params']['reg_slope_window']}d th={reg_best['params']['reg_slope_threshold']})"
            print(f"  ✓ Regression exit wins: Sharpe {reg_sharpe:.2f} vs {chand_sharpe:.2f}")
            # Merge results for reporting
            results = reg_results + [chand_best] + results[1:]
            results.sort(key=lambda r: r['metrics']['sharpe_ratio'], reverse=True)
            optimizer.results = results
        else:
            best_result = chand_best
            print(f"  ✓ Chandelier-only wins: Sharpe {chand_sharpe:.2f} vs regression {reg_sharpe:.2f}")
    else:
        best_result = chand_best

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
        'combos': combos + len(reg_params_list),
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

            # Promote best params to base_case=true so the live system picks them up
            # (coordinate ascent may override later)
            p = best_result['params']
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE strategy_parameters
                SET chandelier_period = %s, chandelier_mult = %s,
                    chandelier_entry_mult = %s, atr_period = %s,
                    reg_slope_window = %s, reg_slope_threshold = %s, reg_slope_type = %s,
                    win_rate = %s, sharpe_ratio = %s, total_return = %s,
                    total_trades = %s, max_drawdown = %s, updated_at = NOW()
                WHERE ticker_id = %s AND base_case = true
            ''', (
                int(p['chandelier_period']), float(p['chandelier_mult']),
                float(p.get('chandelier_entry_mult', 1.5)), int(p['chandelier_period']),
                p.get('reg_slope_window'), p.get('reg_slope_threshold'), p.get('reg_slope_type'),
                float(best_result['metrics']['win_rate']),
                float(best_result['metrics']['sharpe_ratio']),
                float(best_result['metrics']['total_return']),
                int(best_result['metrics']['total_trades']),
                float(best_result['metrics'].get('max_drawdown', 0)),
                ticker_id
            ))
            conn.commit()
            print(f"✓ Updated base_case=true params + metrics for {symbol}")

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

    import json as _json

    # Build candidate pool per ticker: current active + top 5 from optimizer (chandelier + regression)
    conn = db.get_connection()
    cursor = conn.cursor()
    ticker_candidates = {}
    for sym in tickers:
        candidates = []
        cursor.execute('''
            SELECT chandelier_period, chandelier_mult, chandelier_entry_mult,
                   reg_slope_window, reg_slope_threshold, reg_slope_type
            FROM strategy_parameters
            WHERE ticker_id = (SELECT id FROM tbl_etf_tickers WHERE symbol = %s)
            AND base_case = true LIMIT 1
        ''', (sym,))
        row = cursor.fetchone()
        if row:
            c = {
                'chandelier_period': int(row[0]),
                'chandelier_mult': float(row[1]),
                'chandelier_entry_mult': float(row[2]) if row[2] is not None else 1.5,
            }
            if row[3] is not None:
                c['reg_slope_window'] = int(row[3])
                c['reg_slope_threshold'] = float(row[4])
                c['reg_slope_type'] = row[5]
            candidates.append(c)
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
            k = (c['chandelier_period'], c['chandelier_mult'], c.get('chandelier_entry_mult', 1.5),
                 c.get('reg_slope_window'), c.get('reg_slope_threshold'), c.get('reg_slope_type'))
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
            SELECT chandelier_period, chandelier_mult, chandelier_entry_mult,
                   reg_slope_window, reg_slope_threshold, reg_slope_type
            FROM strategy_parameters
            WHERE ticker_id = (SELECT id FROM tbl_etf_tickers WHERE symbol = %s)
            AND base_case = true LIMIT 1
        ''', (sym,))
        row = cursor.fetchone()
        if row:
            c = {
                'chandelier_period': int(row[0]),
                'chandelier_mult': float(row[1]),
                'chandelier_entry_mult': float(row[2]) if row[2] is not None else 1.5,
            }
            if row[3] is not None:
                c['reg_slope_window'] = int(row[3])
                c['reg_slope_threshold'] = float(row[4])
                c['reg_slope_type'] = row[5]
            current[sym] = c
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

    # Promotion gate: best-ever promoted Sharpe for this exact ticker combination
    tickers_key = ','.join(sorted(ticker_symbols))
    cursor.execute('''
        SELECT MAX(oh.best_sharpe) FROM optimization_history oh
        JOIN tbl_etf_tickers t ON oh.ticker_id = t.id
        WHERE t.symbol = 'BLENDED'
        AND oh.promoted = true
        AND oh.params::text LIKE %s
    ''', (f'%{tickers_key.split(",")[0]}%',))
    row = cursor.fetchone()
    # Fallback: filter by checking each promoted row's params keys match current tickers
    cursor.execute('''
        SELECT best_sharpe, params FROM optimization_history oh
        JOIN tbl_etf_tickers t ON oh.ticker_id = t.id
        WHERE t.symbol = 'BLENDED' AND oh.promoted = true
        ORDER BY oh.best_sharpe DESC LIMIT 20
    ''')
    best_ever_sharpe = 0.0
    for r in cursor.fetchall():
        try:
            params_dict = _json.loads(r[1]) if r[1] else None
        except (TypeError, _json.JSONDecodeError):
            params_dict = None
        if params_dict and set(params_dict.keys()) == set(ticker_symbols):
            best_ever_sharpe = max(best_ever_sharpe, float(r[0]))
            break

    # Also measure current baseline for reference
    _, baseline_pmetrics, _, _ = ParameterOptimizer.backtest_portfolio(
        ticker_data, {sym: ticker_candidates[sym][0] for sym in ticker_symbols}, initial_capital=100000
    )
    baseline_sharpe = max(baseline_pmetrics['sharpe_ratio'], best_ever_sharpe)
    print(f"  Promotion gate: {baseline_sharpe:.4f} (best ever: {best_ever_sharpe:.4f}, current: {baseline_pmetrics['sharpe_ratio']:.4f})")

    # Run final portfolio backtest with converged params
    ptrades, pmetrics, pequity, pequity_dates = ParameterOptimizer.backtest_portfolio(
        ticker_data, current, initial_capital=100000
    )
    print(f"  Converged after {iteration+1} iterations")
    print(f"  Portfolio return: {pmetrics['total_return']*100:.2f}%")
    print(f"  Sharpe: {pmetrics['sharpe_ratio']:.2f} (baseline: {baseline_sharpe:.2f})")
    print(f"  Max DD: {pmetrics['max_drawdown']*100:.2f}%")
    print(f"  Trades: {pmetrics['total_trades']}")
    for sym in ticker_symbols:
        p = current[sym]
        reg_str = ''
        if p.get('reg_slope_window') is not None:
            reg_str = f", REG({p['reg_slope_type']} {p['reg_slope_window']}d th={p['reg_slope_threshold']})"
        print(f"  {sym}: CHAND({p['chandelier_period']}, {p['chandelier_mult']}, entry_mult={p.get('chandelier_entry_mult',1.5)}){reg_str}")

    # Always save portfolio coord ascent result to optimization_history for auditing
    cursor.execute("SELECT id FROM tbl_etf_tickers WHERE symbol = 'BLENDED'")
    blended_id_row = cursor.fetchone()
    blended_ticker_id = blended_id_row[0] if blended_id_row else None
    promoted_flag = bool(pmetrics['sharpe_ratio'] > baseline_sharpe)
    if blended_ticker_id:
        cursor.execute('''
            INSERT INTO optimization_history
            (ticker_id, run_date, best_sharpe, best_win_rate, best_return,
             total_combinations, runtime_seconds, params, promoted)
            VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s)
        ''', (
            blended_ticker_id,
            float(pmetrics['sharpe_ratio']),
            float(pmetrics['win_rate']),
            float(pmetrics['total_return']),
            0,  # not a grid search
            0,
            _json.dumps({sym: {k: float(v) if isinstance(v, (int, float)) else v
                                for k, v in p.items()}
                          for sym, p in current.items()}),
            promoted_flag,
        ))
        conn.commit()

    # Only promote if new params beat best-ever Sharpe
    if not promoted_flag:
        print(f"  ✗ No improvement ({pmetrics['sharpe_ratio']:.4f} <= {baseline_sharpe:.4f}) — keeping current params")
    else:
        print(f"  ✓ Sharpe improved {baseline_sharpe:.4f} → {pmetrics['sharpe_ratio']:.4f} — promoting new params")

        for sym in ticker_symbols:
            p = current[sym]
            cursor.execute('''
                UPDATE strategy_parameters
                SET chandelier_period = %s, chandelier_mult = %s,
                    chandelier_entry_mult = %s, atr_period = %s,
                    reg_slope_window = %s, reg_slope_threshold = %s, reg_slope_type = %s,
                    updated_at = NOW()
                WHERE ticker_id = (SELECT id FROM tbl_etf_tickers WHERE symbol = %s)
                AND base_case = true
            ''', (
                p['chandelier_period'], p['chandelier_mult'],
                p.get('chandelier_entry_mult', 1.5), p['chandelier_period'],
                p.get('reg_slope_window'), p.get('reg_slope_threshold'), p.get('reg_slope_type'),
                sym
            ))
        conn.commit()

        # Save BLENDED results
        cursor.execute("SELECT id FROM tbl_etf_tickers WHERE symbol = 'BLENDED'")
        blended_row = cursor.fetchone()
        if not blended_row:
            cursor.execute("INSERT INTO tbl_etf_tickers (symbol, enabled) VALUES ('BLENDED', true)")
            conn.commit()
            cursor.execute("SELECT id FROM tbl_etf_tickers WHERE symbol = 'BLENDED'")
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
                SET chandelier_period = %s, chandelier_mult = %s, win_rate = %s, sharpe_ratio = %s,
                    total_return = %s, total_trades = %s, max_drawdown = %s, updated_at = NOW()
                WHERE id = %s
            ''', (
                first['chandelier_period'], first['chandelier_mult'],
                float(pmetrics['win_rate']), float(pmetrics['sharpe_ratio']),
                float(pmetrics['total_return']), int(pmetrics['total_trades']),
                float(pmetrics['max_drawdown']), existing[0]
            ))
        else:
            cursor.execute('''
                INSERT INTO strategy_parameters
                (ticker_id, chandelier_period, atr_period, chandelier_mult,
                 win_rate, sharpe_ratio, total_return, total_trades, max_drawdown,
                 base_case, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, NOW(), NOW())
            ''', (
                blended_id, first['chandelier_period'], first['chandelier_period'], first['chandelier_mult'],
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
        p = result['params']
        reg = ''
        if p.get('reg_slope_window') is not None:
            reg = f", REG({p['reg_slope_type']} {p['reg_slope_window']}d th={p['reg_slope_threshold']})"
        print(f"{result['symbol']}:")
        print(f"  Params: CHAND(period={p['chandelier_period']}, mult={p['chandelier_mult']}){reg}")
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
