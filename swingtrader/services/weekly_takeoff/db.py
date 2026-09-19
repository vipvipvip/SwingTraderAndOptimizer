"""DB access for the weekly take-off scanner (reads weekly OHLCV only)."""

import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def load_weekly_all(conn):
    """Return a dict ticker_id -> (symbol, df[date, open, high, low, close, volume]).

    Only enabled non-ETF equity names with >= MIN_HISTORY_BARS weekly bars.
    Weekly bars are Monday-anchored, settled (scanner daily feeds this table).
    """
    import pandas as pd
    from config import MIN_HISTORY_BARS
    with conn.cursor() as cur:
        cur.execute('''
            SELECT t.id, t.symbol, s.date,
                   s.open::float8, s.high::float8, s.low::float8,
                   s.close::float8, s.volume::float8
            FROM tbl_scanner_tickers s
            JOIN tbl_stock_tickers t ON t.id = s.ticker_id
            WHERE t.enabled = true AND t.is_etf = false
            ORDER BY t.symbol, s.date
        ''')
        rows = cur.fetchall()
    if not rows:
        return {}
    data = {}
    for tid, sym, d, o, h, l, c, v in rows:
        if tid not in data:
            data[tid] = {'symbol': sym,
                         'date': [], 'open': [], 'high': [], 'low': [],
                         'close': [], 'volume': []}
        df = data[tid]
        df['date'].append(d)
        df['open'].append(o)
        df['high'].append(h)
        df['low'].append(l)
        df['close'].append(c)
        df['volume'].append(v)
    out = {}
    for tid, df in data.items():
        if len(df['date']) < MIN_HISTORY_BARS:
            continue
        out[tid] = {
            'symbol': df['symbol'],
            'df': pd.DataFrame({
                'date': pd.to_datetime(df['date']),
                'open': df['open'], 'high': df['high'],
                'low': df['low'], 'close': df['close'],
                'volume': df['volume'],
            }),
        }
    return out