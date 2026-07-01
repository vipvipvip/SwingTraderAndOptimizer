import psycopg2
import psycopg2.extras
import pandas as pd
from datetime import datetime

import config

def get_conn():
    return psycopg2.connect(**config.DB_CONFIG)

def load_daily(symbol):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT t1.timestamp, t1.open, t1.high, t1.low, t1.close, t1.volume
        FROM tbl_etf_tickers_1hour t1
        JOIN tbl_etf_tickers t ON t.id = t1.ticker_id
        WHERE t.symbol = %s
        ORDER BY t1.timestamp
    """, (symbol,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df

def load_weekly(symbol):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, open, high, low, close, volume
        FROM tbl_scanner_tickers s
        JOIN tbl_etf_tickers t ON t.id = s.ticker_id
        WHERE t.symbol = %s AND s.date >= '2020-07-27'
        ORDER BY s.date
    """, (symbol,))
    rows = cur.fetchall()
    conn.close()
    if rows:
        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        for c in ['open','high','low','close','volume']:
            df[c] = df[c].astype(float)
        return df
    return None
