"""EMA/SMA crossover calc: pure calc, zero I/O.

Mirrors the live convention used by swingtrader/services/mtf (EMA10 vs
SMA40, ewm(span=N, adjust=False) / rolling mean -- see
backtest_single_ticker.py:_cross_events) so results are directly
comparable to the live emasma scoring. No DB/env dependency, just
pandas/numpy in, structured events out.
"""
from collections import namedtuple

import numpy as np
import pandas as pd

CrossEvent = namedtuple('CrossEvent', ['index', 'date', 'direction'])


def compute_ema_sma(closes, ema_period=10, sma_period=40):
    """Return (ema, sma) numpy arrays for a close-price series.

    ema = pandas ewm(span=ema_period, adjust=False).mean()
    sma = rolling mean over sma_period (NaN for the first sma_period-1 bars)
    """
    s = pd.Series(closes, dtype=float)
    ema = s.ewm(span=ema_period, adjust=False).mean().to_numpy()
    sma = s.rolling(window=sma_period).mean().to_numpy()
    return ema, sma


def detect_crossovers(dates, ema, sma):
    """Return list[CrossEvent] where EMA crosses SMA.

    direction is 'bull' (EMA crosses above SMA, bear->bull) or 'bear'
    (EMA crosses below SMA, bull->bear). Bars where SMA is still NaN
    (warmup) are skipped, matching the live crossover-detection convention.
    """
    if len(dates) != len(ema) or len(dates) != len(sma):
        raise ValueError('dates, ema, sma must be the same length')

    bull = ema > sma
    events = []
    for i in range(1, len(dates)):
        if np.isnan(sma[i]) or np.isnan(sma[i - 1]):
            continue
        if bull[i] and not bull[i - 1]:
            events.append(CrossEvent(i, dates[i], 'bull'))
        elif not bull[i] and bull[i - 1]:
            events.append(CrossEvent(i, dates[i], 'bear'))
    return events
