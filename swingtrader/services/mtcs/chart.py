#!/usr/bin/env python3
"""Hilbert sine/lead chart — works for any ticker in tbl_stock_tickers."""
import sys
import os

# Auto-restart with optimizer venv if matplotlib isn't available
try:
    import matplotlib
except ImportError:
    _venv = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        '..', 'optimizer', 'venv', 'bin', 'python')
    _venv = os.path.normpath(_venv)
    if os.path.exists(_venv):
        os.execv(_venv, [_venv] + sys.argv)
    else:
        print(f'ERROR: venv not found at {_venv}', file=sys.stderr)
        print('Install dependencies: cd swingtrader/services/optimizer && python3 -m venv venv && venv/bin/pip install matplotlib numpy', file=sys.stderr)
        sys.exit(1)

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import psycopg2
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
import config
import spectral

NY = ZoneInfo('America/New_York')

DB_CFG = dict(
    host=config.DB_CONFIG['host'], port=config.DB_CONFIG['port'],
    dbname=config.DB_CONFIG['database'], user=config.DB_CONFIG['user'],
    password=config.DB_CONFIG['password'],
)


def _get_conn():
    return psycopg2.connect(**DB_CFG)


def _get_ticker_id(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol.upper(),))
        row = cur.fetchone()
        return row[0] if row else None


def _get_company_name(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('SELECT company_name FROM tbl_stock_tickers WHERE symbol = %s', (symbol.upper(),))
        row = cur.fetchone()
        return row[0] if row else symbol.upper()


def _get_daily_closes(conn, ticker_id):
    """Return (dates_list, closes_list) from scanner daily table, oldest first."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date, close::float8
            FROM tbl_scanner_tickers_daily
            WHERE ticker_id = %s
            ORDER BY date
        """, (ticker_id,))
        rows = cur.fetchall()
    if not rows:
        return [], []
    dates = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    return dates, closes


def _get_mtcs_position(conn, ticker_id):
    """Check MTCS position for signal overlay (optional, non-blocking)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT symbol, quantity, entry_price, entry_at '
                'FROM mtcs_positions WHERE ticker_id = %s', (ticker_id,))
            return cur.fetchone()
    except Exception:
        return None


def chart(symbol, save=None):
    import matplotlib
    if save or not os.environ.get('DISPLAY'):
        matplotlib.use('Agg')

    conn = _get_conn()
    tid = _get_ticker_id(conn, symbol)
    if not tid:
        print(f'Ticker {symbol} not found in tbl_stock_tickers')
        conn.close()
        return

    name = _get_company_name(conn, symbol)
    dates, closes = _get_daily_closes(conn, tid)
    conn.close()

    if len(closes) < config.WARMUP_BARS:
        print(f'{symbol}: only {len(closes)} daily bars, need {config.WARMUP_BARS}')
        return

    prices = np.array(closes)
    dc = spectral.dominant_cycle(prices)
    sine = dc['sine_smoothed']
    lead = dc['lead_smoothed']
    fft = dc.get('fft_cycles', [])
    cycles = ', '.join(f"{c['period']}d" for c in fft[:3]) if fft else '--'

    s0, s1 = sine[-2], sine[-1]
    l0, l1 = lead[-2], lead[-1]
    buy = s0 < l0 and s1 >= l1
    sell = s0 > l0 and s1 <= l1
    sig = 'BUY' if buy else ('SELL' if sell else 'NONE')

    cur = prices[-1]
    print(f'{symbol}: ${cur:.2f}  signal={sig}  cycles={cycles}')
    print(f'  Company: {name}  |  Daily bars: {len(closes)}')

    x = dates if dates and isinstance(dates[0], (datetime,)) else np.arange(len(prices))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f'{name} ({symbol}) — Hilbert Sine/Lead', fontsize=13, fontweight='bold')

    ax1.plot(x, prices, color='#e1e4e8', linewidth=1, label='Close')
    ax1.set_ylabel('Price')
    ax1.grid(True, alpha=0.15)
    ax1.legend(loc='upper left')

    ax2.axhline(0, color='#4a4d59', linewidth=0.5)
    ax2.plot(x, sine, color='#58a6ff', linewidth=1.2, label='Sine')
    ax2.plot(x, lead, color='#f85149', linewidth=1.2, label='Lead')
    ax2.set_ylabel('Cycle')
    ax2.grid(True, alpha=0.15)
    ax2.legend(loc='upper left')

    if buy:
        ax2.axvline(x=x[-1], color='#3fb950', linestyle='--', alpha=0.6, label='BUY')
    elif sell:
        ax2.axvline(x=x[-1], color='#f85149', linestyle='--', alpha=0.6, label='SELL')

    for ax in (ax1, ax2):
        ax.set_xlabel('')
        if dates and isinstance(dates[0], datetime):
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())

    info = f'Cycles: {cycles}  |  Signal: {sig}  |  Close: ${cur:.2f}  |  Bars: {len(closes)}'
    fig.text(0.5, 0.01, info, ha='center', fontsize=9, color='#8b949e')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    if save:
        path = os.path.join(os.path.dirname(__file__), save)
        fig.savefig(path, dpi=150, bbox_inches='tight')
        print(f'  Chart saved to {path}')
    else:
        plt.show()


if __name__ == '__main__':
    save_path = None
    symbols = []
    for a in sys.argv[1:]:
        if a.startswith('--save='):
            save_path = a.split('=', 1)[1]
        elif a == '--save' or a == '--chart':
            pass  # ignore bare flags
        else:
            symbols.append(a.upper())
    if not symbols:
        print('Usage: python chart.py SYMBOL [SYMBOL2 ...] [--save=path.png]')
        print('       python chart.py AAPL')
        print('       python chart.py AAPL MSFT NVDA')
        print('       python chart.py AAPL --save=/tmp/aapl.png')
        sys.exit(1)
    for sym in symbols:
        path = save_path
        if path and len(symbols) > 1:
            base, ext = os.path.splitext(path)
            path = f'{base}_{sym}{ext}'
        chart(sym, save=path)
        print()
