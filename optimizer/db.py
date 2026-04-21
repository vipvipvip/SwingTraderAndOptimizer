"""SQLite database management for strategy parameters"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path


class StrategyDB:
    """SQLite database for storing optimized strategy parameters"""

    def __init__(self, db_path='optimized_params/strategy_params.db'):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.init_db()

    def init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Tickers table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tickers (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT UNIQUE NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    enabled BOOLEAN DEFAULT 1
                )
            ''')

            # Strategy parameters table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_parameters (
                    id INTEGER PRIMARY KEY,
                    ticker_id INTEGER NOT NULL,
                    macd_fast INTEGER NOT NULL,
                    macd_slow INTEGER NOT NULL,
                    macd_signal INTEGER NOT NULL,
                    sma_short INTEGER NOT NULL,
                    sma_long INTEGER NOT NULL,
                    bb_period INTEGER NOT NULL,
                    bb_std REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    sharpe_ratio REAL NOT NULL,
                    total_return REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
                )
            ''')

            # Optimization history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS optimization_history (
                    id INTEGER PRIMARY KEY,
                    ticker_id INTEGER NOT NULL,
                    run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    best_sharpe REAL NOT NULL,
                    best_win_rate REAL NOT NULL,
                    best_return REAL NOT NULL,
                    total_combinations INTEGER NOT NULL,
                    runtime_seconds INTEGER NOT NULL,
                    FOREIGN KEY (ticker_id) REFERENCES tickers(id)
                )
            ''')

            conn.commit()

    def get_connection(self):
        """Get database connection"""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def add_ticker(self, symbol):
        """Add a ticker to monitor"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO tickers (symbol) VALUES (?)', (symbol,))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return self.get_ticker_id(symbol)

    def get_ticker_id(self, symbol):
        """Get ticker ID by symbol"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM tickers WHERE symbol = ?', (symbol,))
        row = cursor.fetchone()
        return row[0] if row else None

    def save_best_params(self, symbol, params, metrics):
        """Save best parameters for a ticker (one row per ticker — deletes old before inserting)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.add_ticker(symbol)

        # Keep exactly one row per ticker so both Python and Laravel always see the latest params.
        cursor.execute('DELETE FROM strategy_parameters WHERE ticker_id = ?', (ticker_id,))
        cursor.execute('''
            INSERT INTO strategy_parameters
            (ticker_id, macd_fast, macd_slow, macd_signal, sma_short, sma_long,
             bb_period, bb_std, win_rate, sharpe_ratio, total_return, total_trades)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                   total_trades, updated_at
            FROM strategy_parameters
            WHERE ticker_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
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
            },
            'updated_at': row[11]
        }

    def log_optimization_run(self, symbol, best_metrics, total_combinations, runtime_seconds):
        """Log an optimization run"""
        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            return

        cursor.execute('''
            INSERT INTO optimization_history
            (ticker_id, best_sharpe, best_win_rate, best_return, total_combinations, runtime_seconds)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            ticker_id,
            float(best_metrics['sharpe_ratio']),
            float(best_metrics['win_rate']),
            float(best_metrics['total_return']),
            total_combinations,
            runtime_seconds
        ))

        conn.commit()

    def get_all_tickers(self):
        """Get all enabled tickers"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT symbol FROM tickers WHERE enabled = 1')
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
            WHERE ticker_id = ?
            ORDER BY run_date DESC
            LIMIT ?
        ''', (ticker_id, limit))

        return [dict(row) for row in cursor.fetchall()]

    def save_backtest_trades(self, symbol, trades, optimization_run=None):
        """Save backtest trades for a ticker"""
        if not trades:
            return

        conn = self.get_connection()
        cursor = conn.cursor()

        ticker_id = self.get_ticker_id(symbol)
        if not ticker_id:
            return

        # Clear previous backtest trades for this ticker
        cursor.execute('DELETE FROM backtest_trades WHERE symbol = ?', (symbol,))

        # Insert new trades
        for trade in trades:
            cursor.execute('''
                INSERT INTO backtest_trades
                (ticker_id, symbol, entry_price, exit_price, entry_at, exit_at, pnl_dollar, pnl_pct, optimization_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ticker_id,
                symbol,
                float(trade['entry_price']),
                float(trade['exit_price']),
                trade['entry_at'],
                trade['exit_at'],
                float(trade['pnl_dollar']),
                float(trade['pnl_pct']),
                optimization_run or datetime.now().isoformat()
            ))

        conn.commit()

    def get_laravel_allocation_weight(self, symbol, default=10):
        """Fetch allocation_weight for a symbol from Laravel database (default 10% if not found)"""
        try:
            laravel_db_path = Path(__file__).parent.parent / 'backend' / 'database' / 'database.sqlite'
            if not laravel_db_path.exists():
                return default

            with sqlite3.connect(str(laravel_db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT allocation_weight FROM tickers WHERE symbol = ?', (symbol,))
                row = cursor.fetchone()
                if row and row[0] is not None:
                    return float(row[0])
        except Exception:
            pass

        return default

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
