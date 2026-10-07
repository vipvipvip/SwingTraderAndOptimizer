"""DB access for the weekly take-off scanner (reads weekly OHLCV only)."""

import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASS,
    )


def settled_week_cutoff(now=None):
    """Newest Monday-stamped weekly bar whose week has fully closed."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo('America/New_York'))
    monday = now.date() - timedelta(days=now.weekday())
    friday_done = (now.weekday() > 4 or
                   (now.weekday() == 4 and now.time() >= datetime.strptime('16:05', '%H:%M').time()))
    return monday if friday_done else monday - timedelta(days=7)


def load_weekly_all(conn):
    """Return a dict ticker_id -> (symbol, df[date, open, high, low, close, volume]).

    Only enabled non-ETF equity names with >= MIN_HISTORY_BARS weekly bars.
    Reads the canonical tbl_prices_weekly (the deprecated tbl_scanner_tickers is no
    longer fed). Weekly bars are Monday-anchored and the loader also stores the
    CURRENT, still-forming week, so unsettled weeks are excluded here: a bar counts
    only once its Friday session has closed (>= 16:05 ET) -- see settled_week_cutoff().
    """
    import pandas as pd
    from config import MIN_HISTORY_BARS
    with conn.cursor() as cur:
        cur.execute('''
            SELECT t.id, t.symbol, s.date,
                   s.open::float8, s.high::float8, s.low::float8,
                   s.close::float8, s.volume::float8
            FROM tbl_prices_weekly s
            JOIN tbl_stock_tickers t ON t.id = s.ticker_id
            WHERE t.enabled = true AND t.is_etf = false AND s.date <= %s
            ORDER BY t.symbol, s.date
        ''', (settled_week_cutoff(),))
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