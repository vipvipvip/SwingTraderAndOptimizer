from datetime import datetime, timezone

import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS emac_candles (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id),
    ts TIMESTAMP NOT NULL,
    open NUMERIC(12,4) NOT NULL,
    high NUMERIC(12,4) NOT NULL,
    low NUMERIC(12,4) NOT NULL,
    close NUMERIC(12,4) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_emac_candles_unique
ON emac_candles(ticker_id, ts);

CREATE TABLE IF NOT EXISTS emac_positions (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id) UNIQUE,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL DEFAULT 0,
    entry_price NUMERIC(12,4),
    entry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS emac_raw_trades (
    id BIGSERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id),
    ts TIMESTAMPTZ NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    size INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_emac_raw_trades_ticker_ts
ON emac_raw_trades(ticker_id, ts);

CREATE TABLE IF NOT EXISTS emac_trades (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_etf_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    signal_ts TIMESTAMP,
    pnl_dollar NUMERIC(14,4),
    pnl_pct NUMERIC(10,4),
    close_reason VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def get_ticker_id(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM tbl_etf_tickers WHERE symbol = %s', (symbol,))
        return (cur.fetchone() or [None])[0]


def ensure_ticker(conn, symbol):
    tid = get_ticker_id(conn, symbol)
    if tid:
        return tid
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO tbl_etf_tickers (symbol, enabled) VALUES (%s, true) '
            'ON CONFLICT DO NOTHING', (symbol,))
        conn.commit()
    return get_ticker_id(conn, symbol)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        print('[DB] emac_ tables ready')
    finally:
        conn.close()


# ── Raw Trades ──

def insert_raw_trades(conn, ticker_id, trades):
    """Bulk insert raw trade ticks. trades: list of {t, p, s}."""
    if not trades:
        return
    from psycopg2.extras import execute_values
    rows = []
    for t in trades:
        raw = t['t']
        if isinstance(raw, str):
            if raw.endswith('Z'):
                raw = raw[:-1]
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = raw
        rows.append((ticker_id, dt, float(t['p']), int(t['s'])))
    with conn.cursor() as cur:
        execute_values(cur,
            'INSERT INTO emac_raw_trades (ticker_id, ts, price, size) VALUES %s',
            rows)
    conn.commit()


def get_last_raw_trade_ts(conn, ticker_id):
    """Return the latest raw trade timestamp for a ticker, or None."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT ts FROM emac_raw_trades WHERE ticker_id = %s ORDER BY ts DESC LIMIT 1',
            (ticker_id,))
        row = cur.fetchone()
        return row[0] if row else None


# ── Candles ──

def insert_candle(conn, ticker_id, ts, o, h, l, c, v):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO emac_candles (ticker_id, ts, open, high, low, close, volume) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING',
            (ticker_id, ts, o, h, l, c, v),
        )
    conn.commit()


def get_last_candle_ts(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT ts FROM emac_candles WHERE ticker_id = %s ORDER BY ts DESC LIMIT 1',
            (ticker_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_candles(conn, ticker_id, limit=50):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT ts, open, high, low, close, volume FROM emac_candles '
            'WHERE ticker_id = %s ORDER BY ts DESC LIMIT %s',
            (ticker_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
        return rows


def candle_count(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT COUNT(*) FROM emac_candles WHERE ticker_id = %s', (ticker_id,))
        return cur.fetchone()[0]


# ── Positions ──

def get_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT symbol, quantity, entry_price, entry_at FROM emac_positions WHERE ticker_id = %s',
            (ticker_id,),
        )
        return cur.fetchone()


def upsert_position(conn, ticker_id, symbol, qty, entry_price, entry_at):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO emac_positions (ticker_id, symbol, quantity, entry_price, entry_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, NOW()) '
            'ON CONFLICT (ticker_id) DO UPDATE SET '
            'quantity = EXCLUDED.quantity, entry_price = EXCLUDED.entry_price, '
            'entry_at = EXCLUDED.entry_at, updated_at = NOW()',
            (ticker_id, symbol, qty, round(entry_price, 4), entry_at),
        )
    conn.commit()


def delete_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM emac_positions WHERE ticker_id = %s', (ticker_id,))
    conn.commit()


# ── Trades ──

def insert_trade(conn, ticker_id, symbol, side, quantity, price, executed_at,
                 signal_ts=None, pnl_dollar=None, pnl_pct=None, close_reason=None):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO emac_trades (ticker_id, symbol, side, quantity, price, executed_at, '
            'signal_ts, pnl_dollar, pnl_pct, close_reason) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (ticker_id, symbol, side, quantity, round(price, 4), executed_at,
             signal_ts,
             round(pnl_dollar, 4) if pnl_dollar is not None else None,
             round(pnl_pct, 4) if pnl_pct is not None else None,
             close_reason),
        )
    conn.commit()


def insert_candles_bulk(conn, rows):
    """Bulk insert candle rows: list of (ticker_id, ts, open, high, low, close, volume)"""
    if not rows:
        return
    from psycopg2.extras import execute_values
    with conn.cursor() as cur:
        execute_values(cur,
            'INSERT INTO emac_candles (ticker_id, ts, open, high, low, close, volume) '
            'VALUES %s ON CONFLICT DO NOTHING', rows)
    conn.commit()
