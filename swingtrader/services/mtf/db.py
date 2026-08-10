import psycopg2
import numpy as np
import pandas as pd
import json
from datetime import date, datetime
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, EMA_PERIOD, SMA_PERIOD, WARMUP_BARS, TS_START, SECTOR_ETFS

# Broad-market gate ETFs whose weekly EMA10>SMA40 state indicates market regime.
MARKET_GATE_ETFS = ['VTI', 'SPY', 'QQQ', 'VTV']

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mtf_positions (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_stock_tickers(id) UNIQUE,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL DEFAULT 0,
    entry_price NUMERIC(12,4),
    entry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mtf_trades (
    id SERIAL PRIMARY KEY,
    ticker_id INTEGER NOT NULL REFERENCES tbl_stock_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    pnl_dollar NUMERIC(14,4),
    pnl_pct NUMERIC(10,4),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mtf_pending (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(10) NOT NULL,
    top_symbols JSONB NOT NULL,
    score_detail JSONB NOT NULL,
    sig_date DATE NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mtf_pending_unconsumed
    ON mtf_pending(mode) WHERE consumed_at IS NULL;

CREATE TABLE IF NOT EXISTS mtf_runs (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(10) NOT NULL,
    sig_date DATE NOT NULL,
    action VARCHAR(10) NOT NULL,
    status VARCHAR(10) NOT NULL,
    detail TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mtf_runs_mode_time
    ON mtf_runs(mode, created_at DESC);
"""


def get_conn():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        print('[MTF DB] mtf_ tables ready')
    finally:
        conn.close()


def get_ticker_id_from_symbol(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
        return row[0] if row else None


def get_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT symbol, quantity, entry_price, entry_at FROM mtf_positions WHERE ticker_id = %s',
            (ticker_id,))
        return cur.fetchone()


def get_all_positions(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT ticker_id, symbol, quantity, entry_price FROM mtf_positions')
        return {row[1]: {'ticker_id': row[0], 'symbol': row[1], 'quantity': float(row[2]), 'entry_price': float(row[3]) if row[3] else 0}
                for row in cur.fetchall()}


def upsert_position(conn, ticker_id, symbol, qty, entry_price, entry_at):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtf_positions (ticker_id, symbol, quantity, entry_price, entry_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, NOW()) '
            'ON CONFLICT (ticker_id) DO UPDATE SET '
            'quantity = EXCLUDED.quantity, entry_price = EXCLUDED.entry_price, '
            'entry_at = EXCLUDED.entry_at, updated_at = NOW()',
            (ticker_id, symbol, qty, round(entry_price, 4), entry_at))
    conn.commit()


def delete_position(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM mtf_positions WHERE ticker_id = %s', (ticker_id,))
    conn.commit()


def insert_trade(conn, ticker_id, symbol, side, quantity, price, executed_at,
                 pnl_dollar=None, pnl_pct=None):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtf_trades (ticker_id, symbol, side, quantity, price, executed_at, '
            'pnl_dollar, pnl_pct) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (ticker_id, symbol, side, quantity, round(price, 4), executed_at,
             round(pnl_dollar, 4) if pnl_dollar is not None else None,
             round(pnl_pct, 4) if pnl_pct is not None else None))
    conn.commit()


def get_all_tickers(conn, is_etf=False):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s ORDER BY symbol',
            (is_etf,))
        return cur.fetchall()


def save_pending(conn, mode, top_symbols, score_detail, sig_date):
    """Store the evening scorer's picks for the morning executor.
    Replaces any existing unconsumed pending for the same mode+sig_date (idempotency).
    Does NOT delete unconsumed pending with a different sig_date (preserves failed executions)."""
    with conn.cursor() as cur:
        cur.execute('DELETE FROM mtf_pending WHERE mode = %s AND sig_date = %s AND consumed_at IS NULL', 
                    (mode, sig_date))
        cur.execute(
            'INSERT INTO mtf_pending (mode, top_symbols, score_detail, sig_date) '
            'VALUES (%s, %s::jsonb, %s::jsonb, %s)',
            (mode, json.dumps(top_symbols), json.dumps(score_detail), sig_date))
    conn.commit()


def get_pending(conn, mode):
    """Return the unconsumed pending execution for a mode, or None."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT top_symbols::text, score_detail::text, sig_date, created_at '
            'FROM mtf_pending WHERE mode = %s AND consumed_at IS NULL '
            'ORDER BY id DESC LIMIT 1', (mode,))
        row = cur.fetchone()
    if not row:
        return None
    return {
        'top_symbols': json.loads(row[0]),
        'score_detail': json.loads(row[1]),
        'sig_date': row[2],
        'created_at': row[3],
    }


def clear_pending(conn, mode, sig_date=None):
    """Mark the pending as consumed. If sig_date is provided, only mark that specific pending;
    otherwise mark all unconsumed for the mode (backward-compat for older call sites)."""
    with conn.cursor() as cur:
        if sig_date:
            cur.execute(
                'UPDATE mtf_pending SET consumed_at = NOW() '
                'WHERE mode = %s AND sig_date = %s AND consumed_at IS NULL', 
                (mode, sig_date))
        else:
            cur.execute(
                'UPDATE mtf_pending SET consumed_at = NOW() '
                'WHERE mode = %s AND consumed_at IS NULL', (mode,))
    conn.commit()


def log_run(conn, mode, sig_date, action, status, detail=None):
    """Append a run entry to mtf_runs for staleness/ops tracking."""
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtf_runs (mode, sig_date, action, status, detail) '
            'VALUES (%s, %s, %s, %s, %s)',
            (mode, sig_date, action, status, detail))
    conn.commit()


def get_last_run(conn, mode, action):
    """Return the most recent mtf_runs row for (mode, action), or None."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT sig_date, status, detail, created_at FROM mtf_runs '
            'WHERE mode = %s AND action = %s ORDER BY created_at DESC LIMIT 1',
            (mode, action))
        row = cur.fetchone()
    if not row:
        return None
    return {'sig_date': row[0], 'status': row[1], 'detail': row[2], 'created_at': row[3]}


def get_sector_tickers(conn):
    """Enabled ticker IDs+symbols for the SECTOR_ETFS list (info-only scoring)."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND symbol = ANY(%s) ORDER BY symbol',
            (SECTOR_ETFS,))
        return cur.fetchall()


def get_market_gate_tickers(conn):
    """Ticker IDs+symbols for the 4 broad-market gate ETFs (VTI/SPY/QQQ/VTV)."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND symbol = ANY(%s) ORDER BY symbol',
            (MARKET_GATE_ETFS,))
        return cur.fetchall()


def get_etf_name(conn, ticker_id):
    with conn.cursor() as cur:
        cur.execute('''
            SELECT e.company_name FROM tbl_etf_tickers e
            JOIN tbl_stock_tickers s ON s.symbol = e.symbol
            WHERE s.id = %s
        ''', (ticker_id,))
        row = cur.fetchone()
        return row[0] if row else None


def load_weekly(conn, ticker_id):
    cur = conn.cursor()
    cur.execute(
        'SELECT date, close FROM tbl_scanner_tickers WHERE ticker_id = %s ORDER BY date ASC',
        (ticker_id,))
    rows = cur.fetchall()
    cur.close()
    if len(rows) < WARMUP_BARS:
        return None
    dates = [r[0] for r in rows]
    closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
    s = pd.Series(closes)
    ema = s.ewm(span=EMA_PERIOD, adjust=False).mean().to_numpy()
    sma = s.rolling(window=SMA_PERIOD).mean().to_numpy()
    return dict(dates=dates, close=closes, ema=ema, sma=sma)


def load_daily(conn, ticker_id):
    cur = conn.cursor()
    cur.execute(
        'SELECT date, open, close FROM tbl_scanner_tickers_daily WHERE ticker_id = %s ORDER BY date ASC',
        (ticker_id,))
    rows = cur.fetchall()
    cur.close()
    if len(rows) < 2:
        return None
    dates = [r[0] for r in rows]
    opens = np.array([float(r[1]) for r in rows], dtype=np.float64)
    closes = np.array([float(r[2]) for r in rows], dtype=np.float64)
    s = pd.Series(closes)
    ema = s.ewm(span=EMA_PERIOD, adjust=False).mean().to_numpy()
    sma = s.rolling(window=SMA_PERIOD).mean().to_numpy()
    return dict(dates=dates, open=opens, close=closes, ema=ema, sma=sma)


def load_hourly(conn, ticker_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT date::date AS bar_date, close, atr_stop FROM tbl_scanner_tickers_1hour "
        "WHERE ticker_id = %s AND date >= %s ORDER BY date ASC",
        (ticker_id, TS_START))
    rows = cur.fetchall()
    cur.close()
    if len(rows) < 2:
        return None
    seen = {}
    for r in rows:
        seen[r[0]] = (r[0], float(r[1]) if r[1] else 0.0, float(r[2]) if r[2] else 0.0)
    sorted_rows = sorted(seen.values(), key=lambda x: x[0])
    dates = [r[0] for r in sorted_rows]
    closes = np.array([r[1] for r in sorted_rows], dtype=np.float64)
    atr_stops = np.array([r[2] for r in sorted_rows], dtype=np.float64)
    return dict(dates=dates, close=closes, atr_stop=atr_stops)


def get_latest_daily_bar_date(conn):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT MAX(date) FROM tbl_scanner_tickers_daily')
        return cur.fetchone()[0]


def bulk_load_weekly(conn, ticker_ids=None):
    """Load weekly data in one query. If ticker_ids provided, only load those."""
    import pandas as pd
    cur = conn.cursor()
    if ticker_ids:
        cur.execute('SELECT ticker_id, date, close FROM tbl_scanner_tickers WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date',
                    (list(ticker_ids),))
    else:
        cur.execute('SELECT ticker_id, date, close FROM tbl_scanner_tickers ORDER BY ticker_id, date')
    rows = cur.fetchall()
    cur.close()
    data = {}
    for tid, dt, close in rows:
        if tid not in data:
            data[tid] = {'dates': [], 'close': []}
        data[tid]['dates'].append(dt)
        data[tid]['close'].append(float(close))
    for tid in data:
        s = pd.Series(data[tid]['close'])
        data[tid]['ema'] = s.ewm(span=EMA_PERIOD, adjust=False).mean().to_numpy()
        data[tid]['sma'] = s.rolling(window=SMA_PERIOD).mean().to_numpy()
    return data


def bulk_load_daily(conn, ticker_ids=None):
    """Load daily data in one query. If ticker_ids provided, only load those."""
    import pandas as pd
    cur = conn.cursor()
    if ticker_ids:
        cur.execute('SELECT ticker_id, date, open, close FROM tbl_scanner_tickers_daily WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date',
                    (list(ticker_ids),))
    else:
        cur.execute('SELECT ticker_id, date, open, close FROM tbl_scanner_tickers_daily ORDER BY ticker_id, date')
    rows = cur.fetchall()
    cur.close()
    data = {}
    for tid, dt, opn, close in rows:
        if tid not in data:
            data[tid] = {'dates': [], 'open': [], 'close': []}
        data[tid]['dates'].append(dt)
        data[tid]['open'].append(float(opn) if opn else 0)
        data[tid]['close'].append(float(close) if close else 0)
    for tid in data:
        s = pd.Series(data[tid]['close'])
        data[tid]['ema'] = s.ewm(span=EMA_PERIOD, adjust=False).mean().to_numpy()
        data[tid]['sma'] = s.rolling(window=SMA_PERIOD).mean().to_numpy()
    return data


def bulk_load_hourly(conn, ticker_ids=None):
    """Load hourly data in one query. If ticker_ids provided, only load those."""
    cur = conn.cursor()
    if ticker_ids:
        cur.execute(
            "SELECT ticker_id, date::date AS bar_date, close, atr_stop "
            "FROM tbl_scanner_tickers_1hour WHERE ticker_id = ANY(%s) AND date >= %s ORDER BY ticker_id, date",
            (list(ticker_ids), TS_START))
    else:
        cur.execute(
            "SELECT ticker_id, date::date AS bar_date, close, atr_stop "
            "FROM tbl_scanner_tickers_1hour WHERE date >= %s ORDER BY ticker_id, date",
            (TS_START,))
    rows = cur.fetchall()
    cur.close()
    data = {}
    seen = {}
    for tid, dt, close, atr_stop in rows:
        key = (tid, dt)
        if key not in seen:
            seen[key] = (tid, dt, float(close) if close else 0.0, float(atr_stop) if atr_stop else 0.0)
    for tid, dt, close, atr_stop in seen.values():
        if tid not in data:
            data[tid] = {'dates': [], 'close': [], 'atr_stop': []}
        data[tid]['dates'].append(dt)
        data[tid]['close'].append(close)
        data[tid]['atr_stop'].append(atr_stop)
    return data


def get_market_breadth(conn, is_etf=False):
    with conn.cursor() as cur:
        cur.execute('''
            WITH wk AS (
                SELECT ticker_id, close::float8 AS close,
                       AVG(close::float8) OVER (PARTITION BY ticker_id ORDER BY date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS sma40,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
                FROM tbl_scanner_tickers
            ),
            dy AS (
                SELECT ticker_id, close::float8 AS close,
                       AVG(close::float8) OVER (PARTITION BY ticker_id ORDER BY date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW) AS sma40,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY date DESC) AS rn
                FROM tbl_scanner_tickers_daily
            )
            SELECT COUNT(*) FILTER (WHERE wk.close > wk.sma40 AND dy.close > dy.sma40) AS uptrend,
                   COUNT(*) AS total
            FROM wk
            JOIN dy ON dy.ticker_id = wk.ticker_id
            JOIN tbl_stock_tickers s ON s.id = wk.ticker_id
            WHERE wk.rn = 1 AND dy.rn = 1 AND s.is_etf = %s
        ''', (is_etf,))
        row = cur.fetchone()
    if row and row[1] > 0:
        return row[0] / row[1] * 100
    return None


def compute_market_breadth_from_data(weekly_data, daily_data, is_etf=False):
    """Compute market breadth from already-loaded data (instant, no SQL)."""
    uptrend = 0
    total = 0
    for tid in weekly_data:
        w = weekly_data[tid]
        d = daily_data.get(tid)
        if not d or len(w['close']) < 40 or len(d['close']) < 40:
            continue
        # Check if this ticker matches the is_etf filter — we can't here,
        # so caller should pre-filter the data
        wc = w['close'][-1]
        ws = w['sma'][-1]
        dc = d['close'][-1]
        ds = d['sma'][-1]
        if np.isnan(wc) or np.isnan(ws) or np.isnan(dc) or np.isnan(ds):
            continue
        total += 1
        if wc > ws and dc > ds:
            uptrend += 1
    if total > 0:
        return uptrend / total * 100
    return None
