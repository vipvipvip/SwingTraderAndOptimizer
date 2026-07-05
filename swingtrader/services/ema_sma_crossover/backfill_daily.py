#!/usr/bin/env python3
"""Backfill daily OHLC bars for EMAC tickers from Alpaca."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import db as db_module
from price_collector import fetch_daily_bars
from datetime import datetime


def main():
    db_module.init_db()
    conn = db_module.get_conn()

    try:
        for sym in config.TICKERS:
            tid = db_module.ensure_ticker(conn, sym)
            last = db_module.get_last_daily_ts(conn, tid)
            start = None if not last else f'{last}T00:00:00Z'

            if not last:
                print(f'[{sym}] No daily data — fetching all from 2020-01-01')
            else:
                print(f'[{sym}] Last daily: {last} — fetching since then')

            bars = fetch_daily_bars(sym, start=start or '2020-01-01T00:00:00Z')
            if not bars:
                print(f'  No bars returned')
                continue

            rows = []
            for b in bars:
                ts_str = b['t']
                if isinstance(ts_str, str) and 'T' in ts_str:
                    ts = datetime.fromisoformat(ts_str.split('T')[0]).date()
                else:
                    ts = datetime.fromisoformat(str(ts_str)[:10]).date()
                rows.append((
                    tid,
                    ts,
                    float(b['o']),
                    float(b['h']),
                    float(b['l']),
                    float(b['c']),
                    int(b['v']),
                ))

            db_module.insert_daily_candles_bulk(conn, rows)
            cnt = db_module.count_daily_candles(conn, tid)
            print(f'  Inserted {len(rows)} bars → total {cnt} daily candles')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
