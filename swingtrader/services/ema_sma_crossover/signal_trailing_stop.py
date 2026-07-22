#!/usr/bin/env python3
"""Show live signals for EMA/SMA + Trailing Stop 2ATR strategy.
Uses Alpaca historical bars API for real-time hourly data (QQQ/VTI/VTV use EMAC 30m candles).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
import numpy as np
import pandas as pd
import config
import db as db_module
import psycopg2
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
WARMUP = config.SMA_PERIOD + 15
EMA_PERIOD = config.EMA_PERIOD
SMA_PERIOD = config.SMA_PERIOD

# Alpaca data API
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


def _get_alpaca_client():
    return StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)


def compute_atr(high, low, close, period=14):
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = np.full(len(close), np.nan)
    if len(tr) >= period:
        atr[period] = tr[:period].mean()
        for i in range(period + 1, len(close)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    return atr


def _get_daily_regime(conn, symbol):
    """Check daily EMA(10) vs SMA(40) regime from scanner daily table."""
    cur = conn.cursor()
    cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
    row = cur.fetchone()
    if not row:
        return False
    tid = row[0]

    cur.execute(
        'SELECT close FROM tbl_scanner_tickers_daily '
        'WHERE ticker_id = %s ORDER BY date DESC LIMIT %s', (tid, SMA_PERIOD + 10))
    daily_rows = cur.fetchall()
    if len(daily_rows) >= SMA_PERIOD:
        dc = np.array([float(r[0]) for r in reversed(daily_rows)])
        ds = pd.Series(dc)
        d_ema = ds.ewm(span=EMA_PERIOD, adjust=False).mean().values
        d_sma = ds.rolling(window=SMA_PERIOD).mean().values
        return bool(d_ema[-1] > d_sma[-1])
    return False


def _get_hourly_bars_alpaca(symbol, limit=WARMUP + 200):
    """Fetch hourly bars from Alpaca API (real-time via IEX feed, free tier)."""
    client = _get_alpaca_client()
    end = datetime.now(NY)
    start = end - timedelta(days=90)
    # Request max bars to ensure we get the most recent data
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
        limit=10000,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    if symbol not in bars.data or not bars.data[symbol]:
        return None

    rows = bars.data[symbol][-limit:]
    ts_arr = [str(b.timestamp) for b in rows]
    o = np.array([float(b.open) for b in rows])
    h = np.array([float(b.high) for b in rows])
    l = np.array([float(b.low) for b in rows])
    c = np.array([float(b.close) for b in rows])
    return ts_arr, o, h, l, c


def _show(symbol, ts_arr, o, h, l, c, daily_bullish, source):
    i = len(c) - 1
    series = pd.Series(c)
    ema = series.ewm(span=EMA_PERIOD, adjust=False).mean().values
    sma = series.rolling(window=SMA_PERIOD).mean().values
    atr = compute_atr(h, l, c)
    tf = '30m' if 'emac' in source.lower() else '1hr'

    # Check staleness
    last_ts = ts_arr[i]
    try:
        last_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))
        now_et = datetime.now(NY)
        last_et = last_dt.astimezone(NY)
        is_stale = (now_et.date() > last_et.date() and now_et.hour < 17)
    except:
        is_stale = False

    print(f'\n{"="*60}')
    print(f'  {symbol} — {tf} EMA/SMA + Trailing Stop 2ATR ({source})')
    print(f'{"="*60}')
    if is_stale:
        print(f'  ⚠ Data as of {last_et.strftime("%b %d %H:%M ET")} — today\'s bars not yet available')
    print(f'  Last bar:  {last_ts}')
    print(f'  Close:     ${c[i]:.2f}')
    print(f'  EMA(10):   ${ema[i]:.2f}')
    print(f'  SMA(40):   ${sma[i]:.2f}')
    print(f'  ATR(14):   ${atr[i]:.2f}' if not np.isnan(atr[i]) else '  ATR(14):   N/A')
    print(f'  Daily regime: {"BULLISH" if daily_bullish else "BEARISH"}')

    ema_gt = ema[i] > sma[i]
    prev_ema_ge = ema[i - 1] >= sma[i - 1] if not np.isnan(ema[i - 1]) else False
    fresh_cross = ema_gt and not prev_ema_ge

    print()
    if daily_bullish and fresh_cross:
        print(f'  >>> FRESH BUY SIGNAL: EMA just crossed above SMA, daily bullish')
    elif fresh_cross:
        print(f'  >>> FRESH CROSS but BLOCKED: daily regime is BEARISH')
    elif ema_gt and daily_bullish:
        print(f'  Signal: EMA > SMA (uptrend, daily bullish) — hold or wait for fresh cross')
    elif ema_gt:
        print(f'  Signal: EMA > SMA but daily BEARISH — no entry')
    else:
        print(f'  Signal: EMA < SMA (no entry)')

    if not np.isnan(atr[i]) and atr[i] > 0:
        stop = c[i] - 2.0 * atr[i]
        print(f'  Trailing stop (2x ATR): ${stop:.2f} ({(c[i] - stop) / c[i] * 100:.1f}% below)')

    print(f'{"="*60}\n')


def show_signal_emac(symbol):
    """Read from EMAC 30-min candle tables (QQQ/VTI/VTV)."""
    conn = db_module.get_conn()
    try:
        tid = db_module.get_ticker_id(conn, symbol)
        if not tid:
            return False

        daily_bullish = _get_daily_regime(conn, symbol)

        rows = db_module.get_candles(conn, tid, limit=WARMUP + 200)
        if len(rows) < WARMUP:
            return False

        ts_arr = [str(r[0]) for r in rows]
        o = np.array([float(r[1]) for r in rows])
        h = np.array([float(r[2]) for r in rows])
        l = np.array([float(r[3]) for r in rows])
        c = np.array([float(r[4]) for r in rows])

        _show(symbol, ts_arr, o, h, l, c, daily_bullish, 'EMAC candles')
        return True
    finally:
        conn.close()


def show_signal_alpaca(symbol):
    """Fetch real-time hourly bars from Alpaca API."""
    conn = db_module.get_conn()
    try:
        daily_bullish = _get_daily_regime(conn, symbol)
    finally:
        conn.close()

    result = _get_hourly_bars_alpaca(symbol)
    if not result:
        print(f'{symbol}: no Alpaca hourly data')
        return

    ts_arr, o, h, l, c = result
    if len(ts_arr) < WARMUP:
        print(f'{symbol}: only {len(ts_arr)} hourly bars (need {WARMUP})')
        return

    _show(symbol, ts_arr, o, h, l, c, daily_bullish, 'Alpaca API')


def show_signal_scanner(symbol):
    """Fallback: read from scanner hourly table."""
    conn = db_module.get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
        row = cur.fetchone()
        if not row:
            print(f'{symbol}: not found in tbl_stock_tickers')
            return
        tid = row[0]

        daily_bullish = _get_daily_regime(conn, symbol)

        cur.execute(
            'SELECT date, open, high, low, close FROM tbl_scanner_tickers_1hour '
            'WHERE ticker_id = %s ORDER BY date DESC LIMIT %s', (tid, WARMUP + 200))
        rows = cur.fetchall()
        if len(rows) < WARMUP:
            print(f'{symbol}: only {len(rows)} scanner hourly bars (need {WARMUP})')
            return

        rows.reverse()
        ts_arr = [str(r[0]) for r in rows]
        o = np.array([float(r[1]) for r in rows])
        h = np.array([float(r[2]) for r in rows])
        l = np.array([float(r[3]) for r in rows])
        c = np.array([float(r[4]) for r in rows])

        _show(symbol, ts_arr, o, h, l, c, daily_bullish, 'scanner hourly (stale)')
    finally:
        conn.close()


def show_signal(symbol):
    """Try EMAC candles first, then Alpaca API, then scanner hourly."""
    if show_signal_emac(symbol):
        return
    try:
        show_signal_alpaca(symbol)
    except Exception as e:
        print(f'{symbol}: Alpaca API failed ({e}), falling back to scanner...')
        show_signal_scanner(symbol)


def _compute_signal(symbol):
    """Return dict with signal data or None."""
    conn = db_module.get_conn()
    try:
        daily_bullish = _get_daily_regime(conn, symbol)
    finally:
        conn.close()

    # Try Alpaca first, fall back to scanner
    result = None
    source = 'Alpaca API'
    try:
        result = _get_hourly_bars_alpaca(symbol)
    except:
        pass

    if not result:
        source = 'scanner hourly'
        conn = db_module.get_conn()
        try:
            cur = conn.cursor()
            cur.execute('SELECT id FROM tbl_stock_tickers WHERE symbol = %s', (symbol,))
            row = cur.fetchone()
            if not row:
                return None
            tid = row[0]
            cur.execute(
                'SELECT date, open, high, low, close FROM tbl_scanner_tickers_1hour '
                'WHERE ticker_id = %s ORDER BY date DESC LIMIT %s', (tid, WARMUP + 200))
            rows = cur.fetchall()
            if len(rows) < WARMUP:
                return None
            rows.reverse()
            result = (
                [str(r[0]) for r in rows],
                np.array([float(r[1]) for r in rows]),
                np.array([float(r[2]) for r in rows]),
                np.array([float(r[3]) for r in rows]),
                np.array([float(r[4]) for r in rows]),
            )
        finally:
            conn.close()

    ts_arr, o, h, l, c = result
    series = pd.Series(c)
    ema = series.ewm(span=EMA_PERIOD, adjust=False).mean().values
    sma = series.rolling(window=SMA_PERIOD).mean().values
    atr = compute_atr(h, l, c)

    i = len(c) - 1
    ema_gt = ema[i] > sma[i]
    prev_ema_ge = ema[i - 1] >= sma[i - 1] if not np.isnan(ema[i - 1]) else False
    fresh_cross = ema_gt and not prev_ema_ge
    atr_val = atr[i] if not np.isnan(atr[i]) else 0.0
    stop = c[i] - 2.0 * atr_val if atr_val > 0 else 0.0

    if daily_bullish and fresh_cross:
        signal = 'BUY'
    elif fresh_cross:
        signal = 'CROSS-BEAR'
    elif ema_gt and daily_bullish:
        signal = 'HOLD'
    elif ema_gt:
        signal = 'EMA-BEAR'
    else:
        signal = '---'

    last_bar = ts_arr[i]
    try:
        last_dt = datetime.fromisoformat(last_bar.replace('Z', '+00:00'))
        now_et = datetime.now(NY)
        last_et = last_dt.astimezone(NY)
        stale = now_et.date() > last_et.date() and now_et.hour < 17
    except:
        stale = False

    return {
        'symbol': symbol, 'close': c[i], 'ema': ema[i], 'sma': sma[i],
        'atr': atr_val, 'stop': stop, 'pct_below': (c[i] - stop) / c[i] * 100 if stop else 0,
        'daily': 'BULL' if daily_bullish else 'BEAR', 'signal': signal,
        'last_bar': last_bar, 'stale': stale, 'source': source,
    }


def show_all_etfs():
    """Show tabular summary for all ETF tickers."""
    conn = db_module.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT symbol FROM tbl_stock_tickers WHERE is_etf = true AND enabled = true "
            "ORDER BY symbol")
        etfs = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    rows = []
    for sym in etfs:
        d = _compute_signal(sym)
        if d:
            rows.append(d)

    rows.sort(key=lambda x: x['close'] - x['ema'], reverse=True)

    # Colors
    G = '\033[92m'  # green
    Y = '\033[93m'  # yellow
    R = '\033[91m'  # red
    M = '\033[95m'  # magenta
    D = '\033[90m'  # dim
    B = '\033[1m'   # bold
    X = '\033[0m'   # reset

    sig_color = {'BUY': f'{B}{G}', 'HOLD': Y, 'EMA-BEAR': R, 'CROSS-BEAR': M, '---': D}
    daily_color = {'BULL': f'{B}{G}', 'BEAR': R}

    hdr = f'{"Sym":>6}  {"Close":>9}  {"EMA10":>9}  {"SMA40":>9}  {"ATR14":>8}  {"Stop":>9}  {"%":>5}  {"Daily":>5}  {"Signal":<10}'
    print(f'\n{"="*95}')
    print('  All ETFs — EMA/SMA + Trailing Stop 2ATR (real-time via Alpaca)')
    print(f'{"="*95}')
    print(f'  {hdr}')
    print(f'  {"-"*93}')
    for r in rows:
        sc = sig_color.get(r['signal'], '')
        dc = daily_color.get(r['daily'], '')
        stale_mark = f'{D}*{X}' if r['stale'] else ' '
        print(f'  {r["symbol"]:>6}  {r["close"]:>9.2f}  {r["ema"]:>9.2f}  {r["sma"]:>9.2f}  '
              f'{r["atr"]:>8.2f}  {r["stop"]:>9.2f}  {r["pct_below"]:>5.1f}  '
              f'{dc}{r["daily"]:>5}{X}  {sc}{r["signal"]:<10}{X}{stale_mark}')
    print(f'{"="*95}')
    print(f'  * = data from previous day (today\'s bars not yet available)')
    print()


def show_all_stocks():
    """Show tabular summary for all stock tickers."""
    conn = db_module.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT symbol FROM tbl_stock_tickers WHERE is_etf = false AND enabled = true "
            "ORDER BY symbol")
        stocks = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    rows = []
    for sym in stocks:
        d = _compute_signal(sym)
        if d:
            rows.append(d)

    rows.sort(key=lambda x: x['close'] - x['ema'], reverse=True)

    G = '\033[92m'; Y = '\033[93m'; R = '\033[91m'; M = '\033[95m'
    D = '\033[90m'; B = '\033[1m'; X = '\033[0m'
    sig_color = {'BUY': f'{B}{G}', 'HOLD': Y, 'EMA-BEAR': R, 'CROSS-BEAR': M, '---': D}
    daily_color = {'BULL': f'{B}{G}', 'BEAR': R}
    hdr = f'{"Sym":>6}  {"Close":>9}  {"EMA10":>9}  {"SMA40":>9}  {"ATR14":>8}  {"Stop":>9}  {"%":>5}  {"Daily":>5}  {"Signal":<10}'
    print(f'\n{"="*95}')
    print('  All Stocks — EMA/SMA + Trailing Stop 2ATR (real-time via Alpaca)')
    print(f'{"="*95}')
    print(f'  {hdr}')
    print(f'  {"-"*93}')
    for r in rows:
        sc = sig_color.get(r['signal'], '')
        dc = daily_color.get(r['daily'], '')
        stale_mark = f'{D}*{X}' if r['stale'] else ' '
        print(f'  {r["symbol"]:>6}  {r["close"]:>9.2f}  {r["ema"]:>9.2f}  {r["sma"]:>9.2f}  '
              f'{r["atr"]:>8.2f}  {r["stop"]:>9.2f}  {r["pct_below"]:>5.1f}  '
              f'{dc}{r["daily"]:>5}{X}  {sc}{r["signal"]:<10}{X}{stale_mark}')
    print(f'{"="*95}')
    print(f'  * = data from previous day (today\'s bars not yet available)')
    print()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('symbols', nargs='*', default=['QQQ'])
    parser.add_argument('--all-etfs', action='store_true', help='Show all ETFs in tabular form')
    parser.add_argument('--all-stocks', action='store_true', help='Show all stocks in tabular form')
    args = parser.parse_args()
    if args.all_etfs:
        show_all_etfs()
    elif args.all_stocks:
        show_all_stocks()
    else:
        for sym in args.symbols:
            show_signal(sym.upper())
