"""SQLite database for storing historical bars"""
import sqlite3
from datetime import datetime
from pathlib import Path


class BarsDB:
    """SQLite database for historical OHLCV bars"""

    def __init__(self, db_path='optimized_params/strategy_params.db', ticker_id=None):
        self.db_path = db_path
        self.ticker_id = ticker_id
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


    def insert_bars(self, ticker_id, bars_df, symbol=None):
        """Insert bars from DataFrame into database

        Args:
            ticker_id: Ticker ID from tickers table
            bars_df: DataFrame with columns: open, high, low, close, volume
                    and index as timestamp
            symbol: Stock symbol (optional, for logging)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            count = 0
            for timestamp, row in bars_df.iterrows():
                try:
                    cursor.execute('''
                        INSERT INTO bars (ticker_id, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        ticker_id,
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

    def get_latest_timestamp(self, ticker_id):
        """Get the most recent bar timestamp for a ticker

        Returns:
            datetime or None if no data exists
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT MAX(timestamp) FROM bars WHERE ticker_id = ?',
                (ticker_id,)
            )
            result = cursor.fetchone()[0]
            if result:
                return datetime.fromisoformat(result)
            return None

    def get_bars(self, ticker_id, start=None, end=None):
        """Retrieve bars for a ticker within date range

        Args:
            ticker_id: Ticker ID from tickers table
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
                    WHERE ticker_id = ? AND timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp
                ''', (ticker_id, start.isoformat(), end.isoformat()))
            elif start:
                cursor.execute('''
                    SELECT * FROM bars
                    WHERE ticker_id = ? AND timestamp >= ?
                    ORDER BY timestamp
                ''', (ticker_id, start.isoformat()))
            else:
                cursor.execute('''
                    SELECT * FROM bars
                    WHERE ticker_id = ?
                    ORDER BY timestamp
                ''', (ticker_id,))

            return [dict(row) for row in cursor.fetchall()]

    def bar_count(self, ticker_id):
        """Get total bar count for a ticker"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM bars WHERE ticker_id = ?', (ticker_id,))
            return cursor.fetchone()[0]

    def close(self):
        """Close database connection"""
        pass
