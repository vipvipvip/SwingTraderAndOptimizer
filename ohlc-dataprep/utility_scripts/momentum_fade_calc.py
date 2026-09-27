"""Continuous momentum-fade score: pure calc, zero I/O.

Unlike divergence_calc's pivot-to-pivot binary check (which only fires at
specific zigzag-confirmed swing points), this scores EVERY bar on a
continuous scale: how close price is to its recent rolling extreme,
combined with how much the corresponding slope has decelerated recently.
Meant to support a graded "start lightening/adding exposure" signal instead
of a binary buy/sell trigger -- higher score = more warning, not a yes/no.
"""
import numpy as np
import pandas as pd


def fade_score(prices, slopes, direction, rolling_window=20, fade_lookback=4):
    """
    prices: the extreme-relevant price series (`high` for TOP, `low` for BOTTOM)
    slopes: the matching slope series (`slope_high`/`slope_low`)
    direction: 'TOP' -> warns of a distribution top (price near its rolling
               high, upward slope decelerating).
               'BOTTOM' -> warns of capitulation exhaustion (price near its
               rolling low, downward slope decelerating, i.e. less negative).
    rolling_window: bars used to define "near the recent extreme".
    fade_lookback: bars back used to measure slope deceleration.

    Returns (score, proximity, decel) as numpy arrays, same length as input,
    NaN during warmup (first `rolling_window + fade_lookback` bars).
    `proximity` in [0, 1] (1 = at the rolling extreme). `decel` >= 0 (0 = no
    deceleration or still accelerating). `score = proximity * decel` is a
    relative ranking tool, not a probability -- use its percentile within a
    series/universe to threshold it, not the raw magnitude (slope units
    differ by ticker/price level).
    """
    if direction not in ('TOP', 'BOTTOM'):
        raise ValueError(f"direction must be 'TOP' or 'BOTTOM', got {direction!r}")

    s_price = pd.Series(prices, dtype=float)
    s_slope = pd.Series(slopes, dtype=float)
    delta = s_slope - s_slope.shift(fade_lookback)

    if direction == 'TOP':
        rolling_extreme = s_price.rolling(rolling_window, min_periods=rolling_window).max()
        proximity = s_price / rolling_extreme
        decel = (-delta).clip(lower=0)  # slope falling = losing upward steam
    else:
        rolling_extreme = s_price.rolling(rolling_window, min_periods=rolling_window).min()
        proximity = rolling_extreme / s_price
        decel = delta.clip(lower=0)  # slope rising (less negative) = losing downward steam

    score = proximity * decel
    return score.to_numpy(), proximity.to_numpy(), decel.to_numpy()
