import numpy as np
import pandas as pd

import config
import db as db_module

WARMUP = max(config.SMA_PERIOD + 1, config.MACD_SIGNAL + 1)


def get_close_array(conn, ticker_id):
    rows = db_module.get_candles(conn, ticker_id, limit=WARMUP + 5)
    if len(rows) < WARMUP:
        return None
    return np.array([float(r[4]) for r in rows])


def macd_line(prices):
    series = pd.Series(prices)
    fast_ema = series.ewm(span=config.MACD_FAST, adjust=False).mean()
    slow_ema = series.ewm(span=config.MACD_SLOW, adjust=False).mean()
    return (fast_ema - slow_ema).values


def macd_signal(prices):
    ml = macd_line(prices)
    return pd.Series(ml).ewm(span=config.MACD_SIGNAL, adjust=False).mean().values


def check_signal(conn, ticker_id):
    closes = get_close_array(conn, ticker_id)
    if closes is None:
        return None

    close_series = pd.Series(closes)
    ema_fast = close_series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma_slow = close_series.rolling(window=config.SMA_PERIOD).mean().values
    ml = macd_line(closes)
    sl = macd_signal(closes)
    hist = ml - sl

    i = len(closes) - 1
    if any(np.isnan(x[i]) or np.isnan(x[i - 1])
           for x in (ema_fast, sma_slow, ml, sl, hist)):
        return None

    pos = db_module.get_position(conn, ticker_id)
    in_position = pos is not None and float(pos[1]) > 0

    if not in_position:
        entry_ok = ema_fast[i] > sma_slow[i] and hist[i] > 0
        prev_ok = ema_fast[i - 1] > sma_slow[i - 1] and hist[i - 1] > 0
        if entry_ok and not prev_ok:
            print(f'[STRATEGY] ticker_id={ticker_id} BUY (crossover + MACD hist>0)')
            return 'BUY'
    else:
        exit_ok = ema_fast[i] < sma_slow[i] and hist[i] < 0
        prev_ok = ema_fast[i - 1] < sma_slow[i - 1] and hist[i - 1] < 0
        if exit_ok and not prev_ok:
            print(f'[STRATEGY] ticker_id={ticker_id} SELL (crossover + MACD hist<0)')
            return 'SELL'

    return None
