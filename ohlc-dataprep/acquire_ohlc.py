"""Data acquisition: read-only OHLCV loads from the scanner DB.

No writes, no external API calls, no CSVs. The scanner tables already hold
the raw bars (existing ingestion pipeline in scanner/services/scripts/); this
module's only job is reading them into DataFrames for slope_calc to consume.
"""
import os
import sys

import psycopg2
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']


def get_conn():
    return psycopg2.connect(
        host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME,
        user=config.DB_USER, password=config.DB_PASS,
    )


def get_ticker_id(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f'unknown ticker symbol: {symbol}')
        return row[0]


def _load(conn, table, symbol, settled_only):
    query = f"""
        SELECT d.date, d.open, d.high, d.low, d.close, d.volume
        FROM {table} d
        JOIN tbl_stock_tickers t ON t.id = d.ticker_id
        WHERE t.symbol = %s
        {"AND d.date < CURRENT_DATE" if settled_only else ""}
        ORDER BY d.date
    """
    with conn.cursor() as cur:
        cur.execute(query, (symbol,))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=_COLUMNS)
    for c in ('open', 'high', 'low', 'close'):
        df[c] = df[c].astype(float)
    return df


def load_daily(conn, symbol):
    """Settled daily bars for `symbol`. Excludes today's still-forming bar
    (the daily pipeline runs a pre-close snapshot at 9 AM, so today's row, if
    present, is incomplete until the day is over)."""
    return _load(conn, config.TABLES['daily'], symbol, settled_only=True)


def load_weekly(conn, symbol):
    """All weekly bars for `symbol`. No settled-bar filter needed: weekly rows
    are only ever written Friday-after-close (backfilling the last 3-4 weeks
    in case any were missed) -- there is no intermediate/in-progress weekly
    row to guard against, unlike daily."""
    return _load(conn, config.TABLES['weekly'], symbol, settled_only=False)
