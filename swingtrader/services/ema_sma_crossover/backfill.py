#!/usr/bin/env python3
"""Pre-populate emac_candles with historical 30-min bars from Alpaca.

This lets the live runner start trading immediately instead of waiting
~2 trading days for the warmup period to accumulate 40+ candles.
"""
import config
import db as db_module
from price_collector import fetch_all_30min_bars


def backfill():
    db_module.init_db()
    conn = db_module.get_conn()

    try:
        for sym in config.TICKERS:
            tid = db_module.ensure_ticker(conn, sym)
            print(f'[{sym}] Fetching all historical 30-min bars...')
            bars = fetch_all_30min_bars(sym)

            if not bars:
                print(f'  ✗ No data')
                continue

            rows = []
            for b in bars:
                ts = b['t']
                if isinstance(ts, str):
                    from datetime import timezone as tz
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                rows.append((
                    tid, ts,
                    float(b['o']), float(b['h']), float(b['l']), float(b['c']),
                    int(b['v']),
                ))

            db_module.insert_candles_bulk(conn, rows)
            count = db_module.candle_count(conn, tid)
            print(f'  ✓ {count} candles stored for {sym}')

        print('\n[BACKFILL] Complete. Live runner can start trading immediately.')
    finally:
        conn.close()


if __name__ == '__main__':
    from datetime import datetime
    backfill()
