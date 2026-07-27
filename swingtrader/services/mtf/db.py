import psycopg2
import numpy as np
import pandas as pd
from datetime import date
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, EMA_PERIOD, SMA_PERIOD, WARMUP_BARS, TS_START, SECTOR_ETFS


def get_conn():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS)


def init_db():
    conn = get_conn()
    conn.close()
    print('[MTF DB] Scanner tables available')


def get_all_tickers(conn, is_etf=False):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s ORDER BY symbol',
            (is_etf,))
        return cur.fetchall()


def get_sector_tickers(conn):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND symbol = ANY(%s) ORDER BY symbol',
            (SECTOR_ETFS,))
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
