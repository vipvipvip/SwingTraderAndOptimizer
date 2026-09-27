"""Phase 1 driver: acquire -> compute slopes -> write back.

Kept separate from both acquire_ohlc.py (read-only DB access) and
slope_calc.py (pure math, zero I/O) by design, so slope_calc's functions stay
importable by future backtests/live trading without pulling in this script's
DB-write path.
"""
import argparse
import math
import os
import sys
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from acquire_ohlc import get_conn, get_ticker_id, load_daily, load_weekly
from slope_calc import add_ohlc_slopes
from schema import add_slope_columns

LOADERS = {'daily': load_daily, 'weekly': load_weekly}


def _bulk_write_slopes(conn, table, ticker_id, df):
    """COPY the computed slope columns into a temp table, then UPDATE the
    target table joined on (ticker_id, date) -- same pattern
    scanner/services/scripts/compute_indicators.py uses to write atr_stop."""
    buf = StringIO()
    for _, row in df.iterrows():
        vals = [str(ticker_id), row['date'].isoformat()]
        for col in config.SLOPE_COLUMNS:
            v = row[col]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                vals.append('\\N')
            else:
                vals.append(str(v))
        buf.write('\t'.join(vals) + '\n')
    buf.seek(0)

    with conn.cursor() as cur:
        cur.execute('DROP TABLE IF EXISTS tmp_ohlc_slopes')
        cur.execute("""
            CREATE TEMP TABLE tmp_ohlc_slopes (
                ticker_id bigint, date date,
                slope_open float8, slope_high float8,
                slope_low float8, slope_close float8
            ) ON COMMIT DROP
        """)
        cur.copy_expert(
            'COPY tmp_ohlc_slopes (ticker_id, date, slope_open, slope_high, '
            'slope_low, slope_close) FROM STDIN WITH (FORMAT text)',
            buf,
        )
        set_clause = ', '.join(f'{c} = tmp_ohlc_slopes.{c}' for c in config.SLOPE_COLUMNS)
        cur.execute(f"""
            UPDATE {table} t
            SET {set_clause}
            FROM tmp_ohlc_slopes
            WHERE t.ticker_id = tmp_ohlc_slopes.ticker_id
              AND t.date = tmp_ohlc_slopes.date
        """)
    conn.commit()


def run(conn, timeframe):
    table = config.TABLES[timeframe]
    window = config.SLOPE_WINDOW[timeframe]
    load = LOADERS[timeframe]
    for symbol in config.TICKERS:
        ticker_id = get_ticker_id(conn, symbol)
        df = load(conn, symbol)
        if df.empty:
            print(f'[{timeframe}] {symbol}: no rows, skipping')
            continue
        df = add_ohlc_slopes(df, window)
        _bulk_write_slopes(conn, table, ticker_id, df)
        print(f'[{timeframe}] {symbol}: wrote {len(df)} rows (window={window})')


def main():
    parser = argparse.ArgumentParser(
        description='Compute and store OHLC slopes for the phase-1 ETF universe.')
    parser.add_argument('--timeframe', choices=['daily', 'weekly', 'all'], default='all')
    args = parser.parse_args()

    timeframes = ['daily', 'weekly'] if args.timeframe == 'all' else [args.timeframe]

    conn = get_conn()
    try:
        add_slope_columns(conn)
        for tf in timeframes:
            run(conn, tf)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
