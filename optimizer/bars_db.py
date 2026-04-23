"""SQLite database for storing historical bars"""
import sqlite3
from datetime import datetime
from pathlib import Path


class BarsDB:
    """SQLite database for historical OHLCV bars"""

    def __init__(self, db_path='optimized_params/strategy_params.db'):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Bars table: symbol, timestamp, OHLCV
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bars (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    source TEXT DEFAULT 'alpaca',
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, timestamp)
                )
            ''')

            # Index for fast queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_symbol_timestamp
                ON bars(symbol, timestamp DESC)
            ''')

            conn.commit()

    def insert_bars(self, symbol, bars_df):
        """Insert bars from DataFrame into database

        Args:
            symbol: Stock symbol
            bars_df: DataFrame with columns: open, high, low, close, volume
                    and index as timestamp
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            count = 0
            for timestamp, row in bars_df.iterrows():
                try:
                    cursor.execute('''
                        INSERT INTO bars (symbol, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        symbol,
                        timestamp.isoformat(),
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        int(row['volume'])
                    ))
                    count += 1
                except sqlite3.IntegrityError:
                    # Duplicate bar, skip
                    pass

            conn.commit()
            return count

    def get_latest_timestamp(self, symbol):
        """Get the most recent bar timestamp for a symbol

        Returns:
            datetime or None if no data exists
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT MAX(timestamp) FROM bars WHERE symbol = ?',
                (symbol,)
            )
            result = cursor.fetchone()[0]
            if result:
                return datetime.fromisoformat(result)
            return None

    def get_bars(self, symbol, start=None, end=None):
        """Retrieve bars for a symbol within date range

        Args:
            symbol: Stock symbol
            start: datetime or None
            end: datetime or None

        Returns:
            List of bar dicts
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if start and end:
                cursor.execute('''
                    SELECT * FROM bars
                    WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp
                ''', (symbol, start.isoformat(), end.isoformat()))
            elif start:
                cursor.execute('''
                    SELECT * FROM bars
                    WHERE symbol = ? AND timestamp >= ?
                    ORDER BY timestamp
                ''', (symbol, start.isoformat()))
            else:
                cursor.execute('''
                    SELECT * FROM bars
                    WHERE symbol = ?
                    ORDER BY timestamp
                ''', (symbol,))

            return [dict(row) for row in cursor.fetchall()]

    def bar_count(self, symbol):
        """Get total bar count for a symbol"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM bars WHERE symbol = ?', (symbol,))
            return cursor.fetchone()[0]

    def close(self):
        """Close database connection"""
        pass
