import psycopg2
from datetime import datetime

import config

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mtcs_positions (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id) UNIQUE,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL DEFAULT 1,
    entry_price NUMERIC(12,4),
    entry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mtcs_trades (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    signal_ts TIMESTAMP,
    executed_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def get_conn():
    return psycopg2.connect(**config.DB_CONFIG)


def get_ticker_id(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM tbl_etf_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
        return row[0] if row else None


def ensure_ticker(conn, symbol):
    tid = get_ticker_id(conn, symbol)
    if tid:
        return tid
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO tbl_etf_tickers (symbol, enabled) VALUES (%s, true) ON CONFLICT DO NOTHING',
            (symbol,))
        conn.commit()
    return get_ticker_id(conn, symbol)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        print('[MTCS DB] mtcs_ tables ready')
    finally:
        conn.close()


def get_daily_candles(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM tbl_etf_tickers_1hour
            WHERE ticker_id = %s
            ORDER BY timestamp
        """, (ticker_id,))
        rows = cur.fetchall()
    if not rows:
        return None, 0
    closes = [float(r[4]) for r in rows]
    dates = [r[0] for r in rows]
    return closes, len(closes)


def get_latest_candle_ts(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(timestamp) FROM tbl_etf_tickers_1hour WHERE ticker_id = %s
        """, (ticker_id,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT symbol, quantity, entry_price, entry_at FROM mtcs_positions WHERE ticker_id = %s',
            (ticker_id,))
        return cur.fetchone()


def upsert_position(conn, ticker_id, symbol, qty, entry_price, entry_at):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtcs_positions (ticker_id, symbol, quantity, entry_price, entry_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, NOW()) '
            'ON CONFLICT (ticker_id) DO UPDATE SET '
            'quantity = EXCLUDED.quantity, entry_price = EXCLUDED.entry_price, '
            'entry_at = EXCLUDED.entry_at, updated_at = NOW()',
            (ticker_id, symbol, qty, round(entry_price, 4), entry_at))
    conn.commit()


def delete_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM mtcs_positions WHERE ticker_id = %s', (ticker_id,))
    conn.commit()


def insert_trade(conn, ticker_id, symbol, side, price, signal_ts, executed_at):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtcs_trades (ticker_id, symbol, side, price, signal_ts, executed_at) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (ticker_id, symbol, side, round(price, 4), signal_ts, executed_at))
    conn.commit()
