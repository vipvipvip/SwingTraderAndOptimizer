"""Reusable slope calculations for OHLC price series.

Pure functions only -- no DB access, no file I/O. Meant to be imported
directly by backtests and live trading code, not just this experiment's prep
script. Generalizes the rolling linear-regression slope already used in
common/scripts/test_scripts/test_regression_train_test.py (there: close-only,
via np.linalg.lstsq) to any of the four OHLC price series independently, using
the closed-form simple-regression slope (mathematically identical to the
lstsq fit, just without re-solving a 2x2 system every window).
"""
import numpy as np
import pandas as pd

DEFAULT_COLUMNS = ('open', 'high', 'low', 'close')


def rolling_ols_slope(values, window):
    """Rolling ordinary-least-squares slope ($ per bar) over `window` bars.

    Element i is NaN for i < window - 1 (warmup) or if any of the window's
    values are NaN. Regressor is the plain bar index 0..window-1, so units
    are $/bar, not $/day.
    """
    if window < 2:
        raise ValueError('window must be >= 2')
    values = np.asarray(values, dtype=float)
    n = len(values)
    slope = np.full(n, np.nan)

    x = np.arange(window, dtype=float)
    x_centered = x - x.mean()
    denom = (x_centered ** 2).sum()

    for i in range(window - 1, n):
        y = values[i - window + 1: i + 1]
        if np.isnan(y).any():
            continue
        slope[i] = (x_centered * (y - y.mean())).sum() / denom
    return slope


def add_ohlc_slopes(df: pd.DataFrame, window: int,
                     columns=DEFAULT_COLUMNS) -> pd.DataFrame:
    """Return a copy of `df` with a `slope_<col>` column added for each of
    `columns` (default: open/high/low/close), via rolling_ols_slope."""
    out = df.copy()
    for col in columns:
        out[f'slope_{col}'] = rolling_ols_slope(out[col].values, window)
    return out
