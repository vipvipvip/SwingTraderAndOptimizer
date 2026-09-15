import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

SCHEMA_SQL = ""


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
        if SCHEMA_SQL.strip():
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()
        print('[DB] ready')
    finally:
        conn.close()
