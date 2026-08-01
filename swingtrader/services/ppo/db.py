import psycopg2
import pandas as pd

import config


def get_conn():
    return psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT,
                            database=config.DB_NAME, user=config.DB_USER,
                            password=config.DB_PASS)


def get_all_tickers(conn, is_etf=True, limit=0, randomize=False):
    """Enabled tickers. For stocks with limit>0, take top-N by weekly bar count,
    or a random N-sample when randomize=True."""
    with conn.cursor() as cur:
        if is_etf or limit <= 0:
            cur.execute(
                'SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=%s ORDER BY symbol',
                (is_etf,))
            return cur.fetchall()
        if randomize:
            cur.execute('''
                SELECT id, symbol FROM tbl_stock_tickers
                WHERE enabled = true AND is_etf = false
                ORDER BY RANDOM()
                LIMIT %s
            ''', (limit,))
            return cur.fetchall()
        cur.execute('''
            SELECT s.id, s.symbol
            FROM tbl_stock_tickers s
            LEFT JOIN tbl_scanner_tickers t ON t.ticker_id = s.id
            WHERE s.enabled = true AND s.is_etf = false
            GROUP BY s.id, s.symbol
            ORDER BY COUNT(t.id) DESC, s.symbol
            LIMIT %s
        ''', (limit,))
        return cur.fetchall()


def bulk_load_weekly(conn, ticker_ids):
    """Load weekly closes grouped by ticker, no indicator computation."""
    cur = conn.cursor()
    cur.execute('SELECT ticker_id, date, close FROM tbl_scanner_tickers '
                'WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date',
                (list(ticker_ids),))
    rows = cur.fetchall()
    cur.close()
    data = {}
    for tid, dt, close in rows:
        if tid not in data:
            data[tid] = {'dates': [], 'close': []}
        data[tid]['dates'].append(dt)
        data[tid]['close'].append(float(close))
    return data


def bulk_load_daily(conn, ticker_ids):
    """Load daily open/close grouped by ticker, no indicator computation."""
    cur = conn.cursor()
    cur.execute('SELECT ticker_id, date, open, close FROM tbl_scanner_tickers_daily '
                'WHERE ticker_id = ANY(%s) ORDER BY ticker_id, date',
                (list(ticker_ids),))
    rows = cur.fetchall()
    cur.close()
    data = {}
    for tid, dt, opn, close in rows:
        if tid not in data:
            data[tid] = {'dates': [], 'open': [], 'close': []}
        data[tid]['dates'].append(dt)
        data[tid]['open'].append(float(opn) if opn else 0.0)
        data[tid]['close'].append(float(close) if close else 0.0)
    return data
