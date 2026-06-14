"""PostgreSQL database management for strategy parameters"""
import psycopg2
import json
from datetime import datetime
from zoneinfo import ZoneInfo


class StrategyDB:
    """PostgreSQL database for storing optimized strategy parameters"""

    def __init__(self, db_path=None):
        self.conn = None
        self.connect()

    def connect(self):
        """Connect to PostgreSQL"""
        try:
            self.conn = psycopg2.connect(
                host='127.0.0.1',
                port=5432,
                database='swingtrader',
                user='swingtrader',
                password='swingtrader_dev_password'
            )
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            raise

    def get_connection(self):
        """Get database connection"""
        if self.conn is None:
            self.connect()
        return self.conn

    def add_ticker(self, symbol):
        """Add a ticker to monitor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO tbl_etf_tickers (symbol, enabled) VALUES (%s, true)', (symbol,))
            conn.commit()
            ticker_id = self.get_ticker_id(symbol)
            return ticker_id
        except psycopg2.IntegrityError:
            conn.rollback()
            return self.get_ticker_id(symbol)
        except Exception as e:
            conn.rollback()
            print(f"Error adding ticker: {e}")
            return None

    def get_ticker_id(self, symbol):
        """Get ticker ID by symbol"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM tbl_etf_tickers WHERE symbol = %s', (symbol,))
        row = cursor.fetchone()
        return row[0] if row else None

    def save_best_params(self, symbol, params, metrics):
        """Insert new optimization result with base_case=0 (never updates base_case=1 rows)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.add_ticker(symbol)

        try:
            # Insert new optimization candidate row (base_case=0)
            # Does NOT touch existing base_case=1 rows
            period = int(params.get('chandelier_period', 18))
            mult = float(params.get('chandelier_mult', 3.0))
            entry_mult = float(params.get('chandelier_entry_mult', 1.5))
            reg_window = params.get('reg_slope_window')
            reg_threshold = params.get('reg_slope_threshold')
            reg_type = params.get('reg_slope_type')
            cursor.execute('''
                INSERT INTO strategy_parameters
                (ticker_id, chandelier_period, atr_period, chandelier_mult, chandelier_entry_mult,
                 reg_slope_window, reg_slope_threshold, reg_slope_type,
                 win_rate, sharpe_ratio, total_return, total_trades, max_drawdown, base_case, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, NOW(), NOW())
            ''', (
                ticker_id,
                period,  # chandelier_period
                period,  # atr_period (same as chandelier_period)
                mult,    # chandelier_mult
                entry_mult,  # chandelier_entry_mult
                reg_window,
                reg_threshold,
                reg_type,
                float(metrics['win_rate']),
                float(metrics['sharpe_ratio']),
                float(metrics['total_return']),
                int(metrics['total_trades']),
                float(metrics.get('max_drawdown', 0))
            ))

            conn.commit()
            print(f"✓ Saved optimization candidate for {symbol} (base_case=0)")
        except Exception as e:
            conn.rollback()
            print(f"Error saving parameters: {e}")

    def get_best_params(self, symbol):
        """Get best parameters for a ticker (base_case=true only)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            return None

        cursor.execute('''
            SELECT atr_period, chandelier_mult, chandelier_entry_mult,
                   reg_slope_window, reg_slope_threshold, reg_slope_type,
                   win_rate, sharpe_ratio, total_return, total_trades
            FROM strategy_parameters
            WHERE ticker_id = %s AND base_case = true
        ''', (ticker_id,))

        row = cursor.fetchone()
        if not row:
            return None

        result = {
            'atr_period': row[0],
            'chandelier_mult': row[1],
            'chandelier_entry_mult': float(row[2]) if row[2] is not None else None,
        }
        if row[3] is not None:
            result['reg_slope_window'] = int(row[3])
            result['reg_slope_threshold'] = float(row[4])
            result['reg_slope_type'] = row[5]
        result['metrics'] = {
            'win_rate': row[6],
            'sharpe_ratio': row[7],
            'total_return': row[8],
            'total_trades': row[9]
        }
        return result

    def log_optimization_run(self, symbol, best_metrics, total_combinations, runtime_seconds):
        """Log an optimization run"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            print(f"[DEBUG] Ticker {symbol} not found for logging")
            return

        try:
            cursor.execute('''
                INSERT INTO optimization_history
                (ticker_id, best_sharpe, best_win_rate, best_return, total_combinations, runtime_seconds)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                ticker_id,
                float(best_metrics['sharpe_ratio']),
                float(best_metrics['win_rate']),
                float(best_metrics['total_return']),
                total_combinations,
                int(runtime_seconds)
            ))

            conn.commit()
            print(f"✓ Logged optimization run for {symbol}: Sharpe={best_metrics['sharpe_ratio']}")
        except Exception as e:
            conn.rollback()
            print(f"✗ Error logging optimization run for {symbol}: {e}")
            import traceback
            traceback.print_exc()

    def get_all_tickers(self):
        """Get all enabled tickers"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT symbol FROM tbl_etf_tickers WHERE enabled = true')
        return [row[0] for row in cursor.fetchall()]

    def get_optimization_history(self, symbol, limit=10):
        """Get optimization history for a ticker"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            return []

        cursor.execute('''
            SELECT run_date, best_sharpe, best_win_rate, best_return, total_combinations, runtime_seconds
            FROM optimization_history
            WHERE ticker_id = %s
            ORDER BY run_date DESC
            LIMIT %s
        ''', (ticker_id, limit))

        return cursor.fetchall()

    def save_backtest_trades(self, symbol, trades, optimization_run=None):
        """Save backtest trades to PostgreSQL"""
        if not trades or len(trades) == 0:
            print(f"[DEBUG] No trades to save for {symbol}")
            return

        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            print(f"[DEBUG] Ticker {symbol} not found")
            return

        try:
            # Clear old backtest trades for this ticker (keep only latest optimization)
            cursor.execute('DELETE FROM backtest_trades WHERE ticker_id = %s', (ticker_id,))

            saved_count = 0
            for trade in trades:
                # Handle both 'entry_date'/'exit_date' and 'entry_at'/'exit_at' field names
                entry_ts = trade.get('entry_date') or trade.get('entry_at')
                exit_ts = trade.get('exit_date') or trade.get('exit_at')

                cursor.execute('''
                    INSERT INTO backtest_trades
                    (ticker_id, entry_at, entry_price, exit_at, exit_price, return, pnl_dollar, days_held, simulated_close, source_symbol, allocation_weight, exit_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    ticker_id,
                    entry_ts,
                    float(trade.get('entry_price', 0)),
                    exit_ts,
                    float(trade.get('exit_price', 0)),
                    float(trade.get('return', 0)),
                    float(trade.get('pnl_dollar', 0)),
                    float(trade.get('days_held', 0)),
                    bool(trade.get('simulated_close', False)),
                    str(trade.get('symbol', ''))[:10],
                    float(trade.get('allocation_pct', 0)),
                    str(trade.get('exit_type', 'chandelier'))[:20],
                ))
                saved_count += 1

            conn.commit()
            print(f"✓ Saved {saved_count} backtest trades for {symbol} to PostgreSQL")
        except Exception as e:
            conn.rollback()
            print(f"✗ Error saving backtest trades for {symbol}: {e}")
            import traceback
            traceback.print_exc()

    def get_laravel_allocation_weight(self, symbol, default=10):
        """Get allocation weight from Laravel tickers table"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'SELECT allocation_weight FROM tbl_etf_tickers WHERE symbol = %s',
                (symbol,)
            )
            row = cursor.fetchone()
            return float(row[0]) if row else default
        except Exception as e:
            print(f"Error getting allocation weight: {e}")
            return default

    def save_equity_curve(self, symbol, metrics, equity_curve, equity_dates=None):
        """Save equity curve snapshots to PostgreSQL"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id or not equity_curve or len(equity_curve) == 0:
            return

        try:
            # Clear old backtest snapshots for this ticker
            cursor.execute('DELETE FROM equity_snapshots WHERE ticker_id = %s AND snapshot_type = %s',
                          (ticker_id, 'backtest'))

            # Insert equity snapshot for each point in the equity curve
            saved_count = 0
            for i, equity_value in enumerate(equity_curve):
                snapshot_date = equity_dates[i] if equity_dates and i < len(equity_dates) else None
                if snapshot_date:
                    cursor.execute('''
                        INSERT INTO equity_snapshots
                        (ticker_id, snapshot_date, equity_value, snapshot_type, source)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (
                        ticker_id,
                        snapshot_date,
                        float(equity_value),
                        'backtest',
                        'optimizer'
                    ))
                    saved_count += 1

            conn.commit()
            print(f"✓ Saved {saved_count} equity snapshots for {symbol}")
        except Exception as e:
            conn.rollback()
            print(f"✗ Error saving equity curve for {symbol}: {e}")

    def update_strategy_metrics(self, symbol, metrics):
        """Update win_rate, sharpe_ratio, total_return, total_trades on base_case=true row"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE strategy_parameters
                SET win_rate = %s, sharpe_ratio = %s, total_return = %s, total_trades = %s, updated_at = NOW()
                WHERE ticker_id = (SELECT id FROM tbl_etf_tickers WHERE symbol = %s)
                AND base_case = true
            ''', (
                float(metrics['win_rate']),
                float(metrics['sharpe_ratio']),
                float(metrics['total_return']),
                int(metrics['total_trades']),
                symbol
            ))
            conn.commit()
            print(f"  ✓ Updated strategy_metrics for {symbol}")
        except Exception as e:
            conn.rollback()
            print(f"  ✗ Error updating strategy_metrics for {symbol}: {e}")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
