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


def get_daily_close_array(conn, ticker_id):
    rows = db_module.get_daily_candles(conn, ticker_id, limit=500)
    if len(rows) < 50:
        return None
    return np.array([float(r[4]) for r in rows])


def check_daily_bullish_regime(conn, ticker_id):
    """Check if the last daily EMA/SMA crossover was bullish (EMA > SMA).
    Only EMA/SMA on daily — no MACD filter.
    """
    closes = get_daily_close_array(conn, ticker_id)
    if closes is None:
        return False

    close_series = pd.Series(closes)
    ema = close_series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma = close_series.rolling(window=config.SMA_PERIOD).mean().values

    i = len(closes) - 1
    if np.isnan(ema[i]) or np.isnan(sma[i]):
        return False

    # Current day: is EMA > SMA? That means last crossover was bullish
    return bool(ema[i] > sma[i])


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

    ema_gt = ema_fast[i] > sma_slow[i]

    if not in_position:
        # ENTRY: EMA > SMA (no MACD condition)
        if ema_gt:
            # Daily filter: only enter if daily EMA/SMA regime is bullish
            if not check_daily_bullish_regime(conn, ticker_id):
                print(f'[STRATEGY] ticker_id={ticker_id} BUY blocked by daily regime')
                return None
            print(f'[STRATEGY] ticker_id={ticker_id} BUY')
            return 'BUY'
    else:
        # EXIT: EMA just crossed below SMA (MACD ignored)
        ema_lt = ema_fast[i] < sma_slow[i]
        prev_ema_ge = ema_fast[i - 1] >= sma_slow[i - 1]
        if ema_lt and prev_ema_ge:
            print(f'[STRATEGY] ticker_id={ticker_id} SELL')
            return 'SELL'

    return None
