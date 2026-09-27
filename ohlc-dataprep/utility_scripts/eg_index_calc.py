"""Synthetic EG100 index construction: pure calc, zero I/O.

Close series replicates TradeExecutorService::replayIndexEgGate() /
backtest_trio_ew.py's ema_gate_series() exactly (documented in AGENTS.md as
verified to 1e-6 parity between PHP and Python): the equal-weight,
daily-rebalanced index of the trio's settled daily closes, built by averaging
daily RETURNS (never raw prices -- QQQ/VTI/VTV trade on different scales) and
compounding from 1.0 (day-0 return = 0).

Extends that with synthetic Open/High/Low, which the live PHP gate has no
concept of (it only ever looks at closes) -- see run_eg_index_build.py for
why this part has no ground truth to verify against. Each leg's O/H/L is
expressed as a return relative to THAT LEG'S OWN PRIOR CLOSE (the same anchor
the close index already uses), averaged across legs, then applied to the
synthetic index's own prior close. Because every leg satisfies
high >= close >= low every day, high_ret >= close_ret >= low_ret holds
leg-by-leg, and survives averaging (a linear op) -- so
idx_high >= idx_close >= idx_low is guaranteed by construction, not just
usually true.
"""
import numpy as np
import pandas as pd


def build_eg_index(legs: dict) -> pd.DataFrame:
    """legs: {symbol: DataFrame(date, open, high, low, close, ...)}, one row
    per settled daily bar (e.g. from acquire_ohlc.load_daily). Returns a
    DataFrame (date, open, high, low, close) for the synthetic equal-weight
    index, restricted to dates present in EVERY leg (mirrors
    replayIndexEgGate's date-intersection), seeded at 1.0 on the first common
    date (day-0 return = 0, matching the live formula).
    """
    symbols = list(legs)
    if len(symbols) < 2:
        raise ValueError('need at least 2 legs to build an index')

    frames = {s: legs[s].set_index('date').sort_index() for s in symbols}
    common = frames[symbols[0]].index
    for s in symbols[1:]:
        common = common.intersection(frames[s].index)
    common = common.sort_values()
    if len(common) < 2:
        raise ValueError('fewer than 2 common dates across legs')
    frames = {s: frames[s].loc[common] for s in symbols}
    n = len(common)

    close_ret = np.zeros(n)
    open_ret = np.zeros(n)
    high_ret = np.zeros(n)
    low_ret = np.zeros(n)
    for s in symbols:
        c = frames[s]['close'].to_numpy(dtype=float)
        prior_c = np.concatenate([[np.nan], c[:-1]])
        close_ret += (c / prior_c - 1.0)
        open_ret += (frames[s]['open'].to_numpy(dtype=float) / prior_c - 1.0)
        high_ret += (frames[s]['high'].to_numpy(dtype=float) / prior_c - 1.0)
        low_ret += (frames[s]['low'].to_numpy(dtype=float) / prior_c - 1.0)
    close_ret /= len(symbols)
    open_ret /= len(symbols)
    high_ret /= len(symbols)
    low_ret /= len(symbols)
    close_ret[0] = 0.0  # day 0: no prior close, matches the live formula

    idx_close = np.empty(n)
    idx_close[0] = 1.0
    for i in range(1, n):
        idx_close[i] = idx_close[i - 1] * (1.0 + close_ret[i])

    prior_idx_close = np.concatenate([[np.nan], idx_close[:-1]])
    idx_open = prior_idx_close * (1.0 + open_ret)
    idx_high = prior_idx_close * (1.0 + high_ret)
    idx_low = prior_idx_close * (1.0 + low_ret)

    # Day 0 has no prior synthetic close to anchor to -- seed O/H/L instead
    # from each leg's own day-0 intraday ratio against ITS OWN day-0 close.
    idx_open[0] = 1.0 * (1.0 + np.mean([frames[s]['open'].iloc[0] / frames[s]['close'].iloc[0] - 1.0 for s in symbols]))
    idx_high[0] = 1.0 * (1.0 + np.mean([frames[s]['high'].iloc[0] / frames[s]['close'].iloc[0] - 1.0 for s in symbols]))
    idx_low[0] = 1.0 * (1.0 + np.mean([frames[s]['low'].iloc[0] / frames[s]['close'].iloc[0] - 1.0 for s in symbols]))

    return pd.DataFrame({
        'date': common, 'open': idx_open, 'high': idx_high,
        'low': idx_low, 'close': idx_close,
    }).reset_index(drop=True)


def ema(values, span):
    """ewm(span=span, adjust=False): alpha = 2/(span+1), seeded at the first
    value. Exact convention replayIndexEgGate and the live EMA10/SMA40
    crossover both use."""
    return pd.Series(values, dtype=float).ewm(span=span, adjust=False).mean().to_numpy()


def crossover_state(idx_close, ema_vals):
    """Pure crossover (no band) -- the EG100 convention: long while
    idx_close > ema, flip the instant it strictly crosses (equality holds the
    current state, mirroring replayIndexEgGate's `<`/`>` with bandFrac=0).
    Returns (state: bool array, flips: list of (i, to_bool)); state[0] is
    seeded by the first comparison, not counted as a flip.
    """
    n = len(idx_close)
    state = np.zeros(n, dtype=bool)
    flips = []
    st = None
    for i in range(n):
        if st is None:
            st = bool(idx_close[i] > ema_vals[i])
        elif st and idx_close[i] < ema_vals[i]:
            st = False
            flips.append((i, False))
        elif (not st) and idx_close[i] > ema_vals[i]:
            st = True
            flips.append((i, True))
        state[i] = st
    return state, flips
