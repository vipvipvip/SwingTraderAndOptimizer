"""Swing top/bottom detection: pure calc, zero I/O.

Meant to be imported directly by backtests, live analysis, or other scripts
-- no DB/env dependency, just plain Python lists/floats in, structured
pivots out. Mirrors the separation used by ../slope_calc.py.
"""
from collections import namedtuple

Pivot = namedtuple('Pivot', ['index', 'date', 'price', 'kind', 'pct_from_prior'])


def find_swings(dates, prices, threshold=0.15):
    """Percentage-threshold zigzag over a price series.

    A new pivot is registered once price reverses by `threshold` (fractional,
    e.g. 0.15 = 15%) from the running extreme since the last confirmed pivot.
    This flags major swing points and ignores noise below the threshold.

    Args:
        dates: sequence of date-like labels, same length as `prices`.
        prices: sequence of float prices (e.g. weekly closes).
        threshold: fractional reversal required to confirm a pivot.

    Returns:
        list[Pivot] in chronological order. `kind` is 'TOP' or 'BOTTOM',
        with the final pivot suffixed ' (ongoing)' if the series ended
        mid-trend without a confirming reversal. `pct_from_prior` is the
        % change in price from the previous pivot (or the series start for
        the first pivot).
    """
    if len(dates) != len(prices):
        raise ValueError('dates and prices must be the same length')
    if len(prices) < 2:
        return []

    pivots = []
    trend = None
    anchor_idx = 0
    anchor_price = prices[0]

    for i in range(1, len(prices)):
        if trend is None:
            change = (prices[i] - anchor_price) / anchor_price
            if change >= threshold:
                trend = 'up'
                anchor_idx, anchor_price = i, prices[i]
            elif change <= -threshold:
                trend = 'down'
                anchor_idx, anchor_price = i, prices[i]
        elif trend == 'up':
            if prices[i] >= anchor_price:
                anchor_idx, anchor_price = i, prices[i]
            elif (prices[i] - anchor_price) / anchor_price <= -threshold:
                pivots.append((anchor_idx, anchor_price, 'TOP'))
                trend = 'down'
                anchor_idx, anchor_price = i, prices[i]
        else:  # trend == 'down'
            if prices[i] <= anchor_price:
                anchor_idx, anchor_price = i, prices[i]
            elif (prices[i] - anchor_price) / anchor_price >= threshold:
                pivots.append((anchor_idx, anchor_price, 'BOTTOM'))
                trend = 'up'
                anchor_idx, anchor_price = i, prices[i]

    kind = 'TOP' if trend == 'up' else ('BOTTOM' if trend == 'down' else None)
    if kind and (not pivots or pivots[-1][0] != anchor_idx):
        pivots.append((anchor_idx, anchor_price, kind + ' (ongoing)'))

    result = []
    prev_price = prices[0]
    for idx, price, kind in pivots:
        pct = (price - prev_price) / prev_price * 100
        result.append(Pivot(idx, dates[idx], price, kind, pct))
        prev_price = price
    return result


def pinpoint_extreme(dates, highs, lows, kind):
    """Find the single bar of the actual extreme within a window, at
    whatever resolution `dates`/`highs`/`lows` are sampled -- e.g. pass a
    week's worth of daily bars to find which day the top/bottom actually
    printed on, rather than the coarser weekly bar's date-stamp.

    Args:
        dates, highs, lows: equal-length sequences for the window to search.
        kind: 'TOP' (finds the max high) or 'BOTTOM' (finds the min low).
              Any ' (ongoing)' suffix from a Pivot.kind is ignored.

    Returns:
        (index, date, price) of the extreme bar within the window.
    """
    kind = kind.replace(' (ongoing)', '')
    if kind == 'TOP':
        idx = max(range(len(highs)), key=lambda i: highs[i])
        return idx, dates[idx], highs[idx]
    elif kind == 'BOTTOM':
        idx = min(range(len(lows)), key=lambda i: lows[i])
        return idx, dates[idx], lows[idx]
    else:
        raise ValueError(f"kind must be 'TOP' or 'BOTTOM', got {kind!r}")
