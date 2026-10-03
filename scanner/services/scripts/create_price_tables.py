#!/usr/bin/env python3
"""Create the clean price tables that will replace tbl_scanner_tickers_daily
and tbl_scanner_tickers.

This is a BLUE/GREEN step. It only creates empty tables; it never reads,
writes, or alters the existing scanner tables. Nothing downstream changes
until the repoint, and the repoint is a separate step.

Schema notes:
  - column order and types mirror the current tables so the eventual repoint
    is a table-name swap with no query changes
  - slope_open/high/low/close are intentionally NOT carried over. They were a
    failed VWAP experiment; compute_indicators.INDICATOR_COLUMNS is
    ['atr_stop'] only and nothing reads them.
  - atr_stop IS carried over and is load-bearing: live MTF recovers ATR as
    ATR = (close - atr_stop) / 2, and data_readiness.py refuses to run when
    the latest bar has a NULL atr_stop. compute_indicators.py must populate
    it before the repoint.
  - provenance columns (source/feed/adjustment/fetched_at) are new. The
    current tables record nothing about which feed or adjustment basis a row
    came from, which is why the existing basis could not be identified.
  - date stays DATE (not timestamptz) to match the current tables exactly.

Usage:
    python create_price_tables.py --dry-run     # print DDL, write nothing
    python create_price_tables.py               # create if absent
    python create_price_tables.py --drop        # destroy and recreate
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn

PRICE_COLUMNS = """
    id          bigserial   PRIMARY KEY,
    ticker_id   bigint      NOT NULL REFERENCES tbl_stock_tickers(id),
    date        date        NOT NULL,
    open        numeric     NOT NULL,
    high        numeric     NOT NULL,
    low         numeric     NOT NULL,
    close       numeric     NOT NULL,
    volume      bigint      NOT NULL,
    atr_stop    numeric,
    source      text        NOT NULL DEFAULT 'alpaca',
    feed        text        NOT NULL DEFAULT 'sip',
    adjustment  text        NOT NULL DEFAULT 'all',
    fetched_at  timestamptz,
    created_at  timestamp   DEFAULT now(),
    updated_at  timestamp   DEFAULT now()
"""

INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS {t}_ticker_id_date_unique
    ON {t} (ticker_id, date);
CREATE INDEX IF NOT EXISTS {t}_date_index
    ON {t} (date);
CREATE INDEX IF NOT EXISTS {t}_ticker_id_index
    ON {t} (ticker_id);
CREATE INDEX IF NOT EXISTS {t}_ticker_id_date_index
    ON {t} (ticker_id, date);
CREATE INDEX IF NOT EXISTS {idx}
    ON {t} (ticker_id, date) INCLUDE (close);
"""


def ddl_for(table, idx):
    return (
        f'CREATE TABLE IF NOT EXISTS {table} ({PRICE_COLUMNS});'
        + INDEX_SQL.format(t=table, idx=idx)
    )


TARGETS = [
    ('tbl_prices_daily', 'idx_prices_daily_tid_date_close'),
    ('tbl_prices_weekly', 'idx_prices_weekly_tid_date_close'),
]


def table_exists(cur, table):
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return cur.fetchone() is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='Print the DDL without executing anything')
    ap.add_argument('--drop', action='store_true',
                    help='DROP the target tables first (destroys loaded data)')
    args = ap.parse_args()

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            if args.drop:
                for table, _ in TARGETS:
                    print(f'DROP TABLE IF EXISTS {table} CASCADE;')
                    if not args.dry_run:
                        cur.execute(f'DROP TABLE IF EXISTS {table} CASCADE')

            for table, idx in TARGETS:
                exists = table_exists(cur, table)
                if exists and not args.dry_run:
                    cur.execute(f'SELECT count(*) FROM {table}')
                    n = cur.fetchone()[0]
                    print(f'{table}: EXISTS with {n} rows, leaving untouched.')
                    continue
                print(f'--- {table} ---')
                print(ddl_for(table, idx))
                if not args.dry_run:
                    cur.execute(ddl_for(table, idx))
                    print(f'{table}: created.')

            if not args.dry_run:
                conn.commit()
                print('\nVerifying:')
                for table, _ in TARGETS:
                    cur.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name=%s ORDER BY ordinal_position",
                        (table,),
                    )
                    cols = cur.fetchall()
                    cur.execute(
                        "SELECT count(*) FROM pg_indexes WHERE tablename=%s", (table,))
                    print(f'  {table}: {len(cols)} cols, {cur.fetchone()[0]} indexes')
                    print('    ' + ', '.join(f'{c}:{t}' for c, t in cols))
        if args.dry_run:
            print('\nDry run: nothing executed.')
    except Exception as e:
        conn.rollback()
        print(f'ERROR: {e}')
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()