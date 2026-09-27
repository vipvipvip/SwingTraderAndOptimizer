"""Idempotent, additive-only schema step for the OHLC slope experiment.

Adds slope_open/high/low/close as plain nullable NUMERIC columns to the
existing scanner tables (tbl_scanner_tickers_daily, tbl_scanner_tickers).
Never drops or alters an existing column -- safe to re-run, safe for the
live CoreEW/MTF readers of these tables.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acquire_ohlc import get_conn
import config

TABLES = list(config.TABLES.values())


def add_slope_columns(conn):
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"""
                ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS slope_open  NUMERIC,
                    ADD COLUMN IF NOT EXISTS slope_high  NUMERIC,
                    ADD COLUMN IF NOT EXISTS slope_low   NUMERIC,
                    ADD COLUMN IF NOT EXISTS slope_close NUMERIC
            """)
    conn.commit()


if __name__ == '__main__':
    conn = get_conn()
    try:
        add_slope_columns(conn)
        print('[schema] slope_open/high/low/close ensured on', ', '.join(TABLES))
    finally:
        conn.close()
