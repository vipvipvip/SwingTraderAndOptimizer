"""Cross-slope gap: pure calc, zero I/O.

Unlike momentum_fade_calc (which compares a slope to ITS OWN past value --
inherently a lagging measure, since deceleration can only be measured after
it happens), this compares TWO DIFFERENT slopes at the SAME bar: does the
high series keep accelerating while the close series lags behind it (upper
wicks growing, selling into strength)? That's visible WHILE price is still
making new highs, not just after the fact -- a candidate for a genuinely
leading signal rather than a lagging confirmation.
"""
import numpy as np


def cross_slope_gap(slope_a, slope_b):
    """slope_a - slope_b, elementwise, as a numpy array.

    TOP warning: cross_slope_gap(slope_high, slope_close) -- widening gap =
    highs outrunning closes (upper-wick distribution, selling into strength).
    BOTTOM warning: cross_slope_gap(slope_close, slope_low) -- widening gap
    = closes lifting off lows (lower wicks growing, buying support / basing).
    """
    return np.array(slope_a, dtype=float) - np.array(slope_b, dtype=float)
