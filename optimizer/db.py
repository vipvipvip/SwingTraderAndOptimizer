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
            cursor.execute('INSERT INTO tickers (symbol, enabled) VALUES (%s, true)', (symbol,))
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
        cursor.execute('SELECT id FROM tickers WHERE symbol = %s', (symbol,))
        row = cursor.fetchone()
        return row[0] if row else None

    def save_best_params(self, symbol, params, metrics):
        """Save best parameters for a ticker (one row per ticker — deletes old before inserting)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.add_ticker(symbol)

        try:
            # Update or insert strategy parameters
            cursor.execute('''
                INSERT INTO strategy_parameters
                (ticker_id, macd_fast, macd_slow, macd_signal, sma_short, sma_long,
                 bb_period, bb_std, win_rate, sharpe_ratio, total_return, total_trades)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker_id) DO UPDATE SET
                    macd_fast = EXCLUDED.macd_fast,
                    macd_slow = EXCLUDED.macd_slow,
                    macd_signal = EXCLUDED.macd_signal,
                    sma_short = EXCLUDED.sma_short,
                    sma_long = EXCLUDED.sma_long,
                    bb_period = EXCLUDED.bb_period,
                    bb_std = EXCLUDED.bb_std,
                    win_rate = EXCLUDED.win_rate,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    total_return = EXCLUDED.total_return,
                    total_trades = EXCLUDED.total_trades
            ''', (
                ticker_id,
                int(params['macd_fast']),
                int(params['macd_slow']),
                int(params['macd_signal']),
                int(params['sma_short']),
                int(params['sma_long']),
                int(params['bb_period']),
                float(params['bb_std']),
                float(metrics['win_rate']),
                float(metrics['sharpe_ratio']),
                float(metrics['total_return']),
                int(metrics['total_trades'])
            ))

            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error saving parameters: {e}")

    def get_best_params(self, symbol):
        """Get best parameters for a ticker"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            return None

        cursor.execute('''
            SELECT macd_fast, macd_slow, macd_signal, sma_short, sma_long,
                   bb_period, bb_std, win_rate, sharpe_ratio, total_return,
                   total_trades
            FROM strategy_parameters
            WHERE ticker_id = %s
        ''', (ticker_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return {
            'macd_fast': row[0],
            'macd_slow': row[1],
            'macd_signal': row[2],
            'sma_short': row[3],
            'sma_long': row[4],
            'bb_period': row[5],
            'bb_std': row[6],
            'metrics': {
                'win_rate': row[7],
                'sharpe_ratio': row[8],
                'total_return': row[9],
                'total_trades': row[10]
            }
        }

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
        cursor.execute('SELECT symbol FROM tickers WHERE enabled = true')
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
            saved_count = 0
            for trade in trades:
                cursor.execute('''
                    INSERT INTO backtest_trades
                    (ticker_id, symbol, entry_price, exit_price, entry_at, exit_at, pnl_pct, pnl_dollar)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    ticker_id,
                    symbol,
                    float(trade.get('entry_price', 0)),
                    float(trade.get('exit_price', 0)),
                    trade.get('entry_at'),
                    trade.get('exit_at'),
                    float(trade.get('return', 0)),
                    float(trade.get('pnl_dollar', 0))
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
                'SELECT allocation_weight FROM tickers WHERE symbol = %s',
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
        print(f"[DEBUG] save_equity_curve for {symbol}: ticker_id={ticker_id}, equity_curve len={len(equity_curve) if equity_curve else 0}, equity_dates len={len(equity_dates) if equity_dates else 0}")
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

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
