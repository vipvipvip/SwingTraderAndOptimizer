"""Momentum-divergence calc: pure calc, zero I/O.

Classic technical-analysis divergence (as in MACD/RSI divergence trading)
applied directly to the OHLC slope columns instead of a derived oscillator:
price makes a new swing extreme but the SLOPE of that same price series does
not confirm it -- momentum already weakening even though price is still
pushing to a new high/low. Compares two consecutive same-kind swing pivots
of a single series (e.g. two 'TOP' pivots of the `high` series + their
slope_high values).
"""
from collections import namedtuple

Divergence = namedtuple('Divergence', [
    'prior_date', 'prior_price', 'prior_slope',
    'latest_date', 'latest_price', 'latest_slope',
    'diverges',
])


def check_divergence(prior, latest, kind):
    """prior/latest: (date, price, slope) tuples for two consecutive
    same-direction pivots of one price series (both swing highs of the
    `high` series, or both swing lows of the `low` series).

    kind: 'TOP'    -> bearish divergence = price makes a higher high but
                       slope is lower than at the prior high.
          'BOTTOM' -> bullish divergence = price makes a lower low but
                       slope is higher (less negative) than at the prior low.

    Returns a Divergence namedtuple. `diverges` is True/False, or None if
    price didn't even make a new extreme (divergence doesn't apply -- that's
    just a failed swing, not a momentum warning).
    """
    p_date, p_price, p_slope = prior
    l_date, l_price, l_slope = latest
    if kind == 'TOP':
        new_extreme = l_price > p_price
        diverges = bool(l_slope < p_slope) if new_extreme else None
    elif kind == 'BOTTOM':
        new_extreme = l_price < p_price
        diverges = bool(l_slope > p_slope) if new_extreme else None
    else:
        raise ValueError(f"kind must be 'TOP' or 'BOTTOM', got {kind!r}")
    return Divergence(p_date, p_price, p_slope, l_date, l_price, l_slope, diverges)
