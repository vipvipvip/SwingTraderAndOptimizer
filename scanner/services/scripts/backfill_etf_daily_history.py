#!/usr/bin/env python3
"""Quarterly dump-and-refresh of ETF daily/weekly OHLCV bars.

Source of truth: Alpaca StockHistoricalDataClient with adjustment='all'
(split + dividend adjusted). Daily and weekly are fetched SEPARATELY as
native intervals from Alpaca and stored in separate tables — never derived
from one another, so no aggregation drift.

Dump-and-refresh model: each symbol's rows are DELETEd and re-inserted from
a fresh query, so once a quarter you simply re-run this and pick up any
dividend re-adjustments yfinance/Alpaca retroactively apply.

Note: data is fetched from 2019 onward (Alpaca history for this account
starts 2016-01-04; 2019 gives ~40 warmup bars before the strategy window).

Usage:
    python backfill_etf_daily_history.py --timeframe day|week|both [--symbols A,B] [--source alpaca|yfinance]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_db_conn, API_KEY, SECRET_KEY

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from psycopg2.extras import execute_values

NY = ZoneInfo('America/New_York')

TABLES = {
    'day': 'tbl_scanner_tickers_daily',
    'week': 'tbl_scanner_tickers',
}

ALPACA_TF = {
    'day': TimeFrame.Day,
    'week': TimeFrame.Week,
}


def fetch_alpaca(symbol, tf_name, start_year=2019):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    start = datetime(start_year, 1, 1, tzinfo=NY)
    # SIP subscription blocks queries ending at "now"; end 1 day back is allowed
    end = datetime.now(NY) - timedelta(days=1)
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=ALPACA_TF[tf_name],
        start=start,
        end=end,
        adjustment='all',
        feed='sip',
    )
    all_bars = []
    page_token = None
    while True:
        if page_token:
            request.page_token = page_token
        response = client.get_stock_bars(request)
        if symbol in response.data:
            all_bars.extend(response.data[symbol])
        page_token = getattr(response, 'next_page_token', None)
        if not page_token:
            break
    rows = []
    for bar in all_bars:
        ts = bar.timestamp
        if ts.tzinfo is not None:
            ts = ts.astimezone(NY)
        rows.append((
            ts.date(),
            float(bar.open), float(bar.high), float(bar.low),
            float(bar.close), int(bar.volume),
        ))
    return rows


def fetch_yfinance(symbol, tf_name, start_year=2014):
    import yfinance as yf
    interval = '1wk' if tf_name == 'week' else '1d'
    start = datetime(start_year, 1, 1)
    df = yf.download(symbol, start=start, interval=interval, progress=False,
                     auto_adjust=True, threads=False)
    if df is None or df.empty:
        return []
    if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, 'levels'):
        df.columns = [c[1] if c[1] in ('Open', 'High', 'Low', 'Close', 'Volume')
                      else c[0] for c in df.columns]
    rows = []
    for ts, row in df.iterrows():
        ts_date = ts.date() if hasattr(ts, 'date') else ts
        if interval == '1wk':
            ts_date = ts_date - timedelta(days=ts_date.weekday())
        rows.append((ts_date,
                     float(row['Open']), float(row['High']), float(row['Low']),
                     float(row['Close']), int(row['Volume'])))
    return rows


def refresh(symbol, tf_name, source, start_year):
    if source == 'alpaca':
        rows = fetch_alpaca(symbol, tf_name, start_year)
    else:
        rows = fetch_yfinance(symbol, tf_name, start_year)
    if not rows:
        return 0, 'no data'
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol=%s', (symbol,))
            row = cur.fetchone()
            if not row:
                return 0, 'not in tbl_stock_tickers'
            tid = row[0]
            table = TABLES[tf_name]
            cur.execute(f'DELETE FROM {table} WHERE ticker_id=%s', (tid,))
            execute_values(
                cur,
                f'INSERT INTO {table} '
                '(ticker_id, date, open, high, low, close, volume) VALUES %s '
                'ON CONFLICT (ticker_id, date) DO NOTHING',
                [(tid, *r) for r in rows],
            )
        conn.commit()
        return len(rows), 'ok'
    except Exception as e:
        conn.rollback()
        return 0, str(e)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', default=None,
                        help='Comma-separated symbols (default: all enabled ETFs)')
    parser.add_argument('--start-year', type=int, default=None,
                        help='Fetch from this year (alpaca default 2019, yfinance default 2014)')
    parser.add_argument('--timeframe', choices=['day', 'week', 'both'], default='both')
    parser.add_argument('--source', choices=['alpaca', 'yfinance'], default='alpaca')
    args = parser.parse_args()

    tfs = ['day', 'week'] if args.timeframe == 'both' else [args.timeframe]
    start_year = args.start_year or (2019 if args.source == 'alpaca' else 2014)
    label = {args.timeframe} if args.timeframe != 'both' else {'daily', 'weekly'}

    conn = get_db_conn()
    try:
        if args.symbols:
            syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
        else:
            with conn.cursor() as cur:
                cur.execute('SELECT symbol FROM tbl_stock_tickers '
                            'WHERE enabled AND is_etf ORDER BY symbol')
                syms = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    for tf in tfs:
        total = 0
        failed = []
        print(f'--- {tf} ({label}) source={args.source} from {start_year} ---')
        for sym in syms:
            n, status = refresh(sym, tf, args.source, start_year)
            if status == 'ok':
                total += n
                print(f'  {sym}: {n} {tf} bars')
            else:
                failed.append((sym, status))
                print(f'  {sym}: ERROR {status}')
        print(f'  Done: {total} {tf} bars for {len(syms)} symbols.')
        if failed:
            print(f'  Failed: {len(failed)} -> {failed[:5]}')

    print('\nRefresh complete.')


if __name__ == '__main__':
    main()
