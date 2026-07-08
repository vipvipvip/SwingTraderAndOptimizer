import psycopg2
import numpy as np
import pandas as pd
from datetime import date
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS, EMA_PERIOD, SMA_PERIOD, WARMUP_BARS, TS_START


def get_conn():
    return psycopg2.connect(host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS)


def get_all_tickers(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true ORDER BY symbol')
        return cur.fetchall()


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


def get_market_breadth(conn):
    with conn.cursor() as cur:
        cur.execute('''
            SELECT COUNT(*) FILTER (WHERE we.ema10 > we.sma40 AND de.ema10 > de.sma40) AS uptrend,
                   COUNT(*) AS total
            FROM tbl_scanner_tickers we
            JOIN tbl_scanner_tickers_daily de ON de.ticker_id = we.ticker_id
                AND de.date = (SELECT MAX(date) FROM tbl_scanner_tickers_daily)
            WHERE we.date = (SELECT MAX(date) FROM tbl_scanner_tickers)
        ''')
        row = cur.fetchone()
    if row and row[1] > 0:
        return row[0] / row[1] * 100
    return None
