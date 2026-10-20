#!/usr/bin/env python3
"""Walk-forward detector: drawdown -> trough -> base -> imminent explosion.

Strictly causal: every quantity at bar i uses bars <= i only (EWMAs, trailing
windows shifted by one, a forward state machine). No fixed price/percent
thresholds -- everything is scaled by the stock's own volatility and judged
against its own trailing distribution or a random-walk null at a significance
level. The only knobs are time scales (FAST/SLOW/BASELINE) and ALPHA.

Stages (per stock, one episode at a time):
  1. Drawdown  : depth from running peak exceeds the random-walk expectation
                 sigma*sqrt(n) at significance ALPHA.
  2. Trough    : confirmed only once price has rebounded off the running low by
                 more than noise sigma*sqrt(m) (m = bars since low). The
                 confirmation date is therefore later than the low itself.
  3. Base      : after confirmation, volatility compresses (fast sigma < slow
                 sigma), price holds above the trough low, and the base range is
                 no wider than a random walk's expected range (2*sqrt(2/pi)).
  4. Imminent  : inside a base, jerk (3rd derivative of log price) is
                 significantly positive vs its own trailing distribution, with
                 acceleration > its norm and range-expansion acceleration > its norm.
"""
import argparse
import datetime as dt
import math
import os
from statistics import NormalDist

import numpy as np
import pandas as pd
import psycopg2

FAST, SLOW, BASELINE = 10, 60, 252   # time scales in trading days
SMOOTH = 5                            # derivative smoothing span
ALPHA = 0.05                          # one-sided significance level
Z_CRIT = NormalDist().inv_cdf(1 - ALPHA)
RW_RANGE = 2 * math.sqrt(2 / math.pi)  # E[range of Brownian motion] / (sigma*sqrt(n))


def get_db():
    return psycopg2.connect(host=os.getenv('DB_HOST', 'localhost'), port=5432, dbname='swingtrader',
                            user='swingtrader', password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'))


def get_daily(conn, symbol, start=None):
    q = """SELECT d.date, d.close, d.high, d.low FROM tbl_prices_daily d
           JOIN tbl_stock_tickers t ON t.id = d.ticker_id
           WHERE t.symbol=%s AND d.date < %s"""   # settled bars only
    params = [symbol.upper(), dt.date.today()]
    if start:
        q += " AND d.date >= %s"
        params.append(start)
    q += " ORDER BY d.date"
    cur = conn.cursor()
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close()
    df = pd.DataFrame(rows, columns=['date', 'close', 'high', 'low'])
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date').astype(float)


def _z(x):
    """z-score vs the feature's own trailing window, excluding the current bar."""
    m = x.rolling(BASELINE, min_periods=SLOW).mean().shift(1)
    s = x.rolling(BASELINE, min_periods=SLOW).std().shift(1)
    return (x - m) / s


def features(df):
    lc = np.log(df['close'])
    r = lc.diff()
    out = pd.DataFrame(index=df.index)
    out['lc'] = lc
    out['sig_slow'] = r.ewm(span=SLOW).std()
    out['sig_fast'] = r.ewm(span=FAST).std()
    v = r.ewm(span=SMOOTH).mean()               # velocity
    a = v.diff().ewm(span=SMOOTH).mean()        # acceleration
    j = a.diff()                                # jerk
    rs = np.log(df['high'] / df['low']).ewm(span=SMOOTH).mean()
    ra = rs.diff().ewm(span=3).mean().diff()    # range-expansion acceleration
    out['j_z'], out['a_z'], out['ra_z'] = _z(j), _z(a), _z(ra)
    return out


def detect(df):
    """Walk forward; return a list of event dicts (trough / base / fire)."""
    f = features(df)
    lc = f['lc'].values
    idx = df.index
    events = []
    peak_i = low_i = 0
    state = 'DECLINE'   # DECLINE (tracking peak/low) -> BASE -> FIRED
    trough_low = conf_i = None
    base_flagged = False
    for i in range(1, len(df)):
        sig = f['sig_slow'].iloc[i]
        if not np.isfinite(sig) or sig <= 0 or i < SLOW:
            peak_i = low_i = i
            continue
        if state == 'DECLINE':
            if lc[i] >= lc[peak_i]:
                peak_i = low_i = i
                continue
            if lc[i] <= lc[low_i]:
                low_i = i
            n = max(low_i - peak_i, 1)
            depth = lc[peak_i] - lc[low_i]
            m = i - low_i
            if m >= 1 and depth / (sig * math.sqrt(n)) >= Z_CRIT \
                    and (lc[i] - lc[low_i]) / (sig * math.sqrt(m)) >= Z_CRIT:
                state, trough_low, conf_i, base_flagged = 'BASE', lc[low_i], i, False
                events.append(dict(kind='trough', date=idx[i], low_date=idx[low_i], close=df['close'].iloc[i],
                                   low=df['close'].iloc[low_i], peak_date=idx[peak_i],
                                   dd_pct=(math.exp(-depth) - 1) * 100,
                                   dd_z=depth / (sig * math.sqrt(n))))
        else:  # BASE or FIRED
            if lc[i] < trough_low:                       # trough failed -> back to decline tracking
                state, low_i = 'DECLINE', i
                continue
            if lc[i] >= lc[peak_i]:                      # fully recovered
                state, peak_i, low_i = 'DECLINE', i, i
                continue
            if i - conf_i > BASELINE:                    # stale: memory window is BASELINE bars
                state = 'DECLINE'
                peak_i = i - BASELINE + int(np.argmax(lc[i - BASELINE:i + 1]))
                low_i = i
                continue
            if state == 'FIRED':
                continue
            # The base is judged on bars BEFORE the trigger bar (the trigger move itself
            # inflates fast vol), over a trailing window (not since confirmation, which
            # would count a post-trough rally against the base).
            nb = i - conf_i
            win = lc[max(conf_i, i - SLOW):i]
            sig_p = f['sig_slow'].iloc[i - 1]
            compressed = f['sig_fast'].iloc[i - 1] < sig_p
            tight = nb >= 2 and (win.max() - win.min()) / (sig_p * math.sqrt(len(win))) <= RW_RANGE
            if nb >= FAST and compressed and tight:
                if not base_flagged:
                    base_flagged = True
                    events.append(dict(kind='base', date=idx[i], close=df['close'].iloc[i], bars=nb))
                if f['j_z'].iloc[i] >= Z_CRIT and f['a_z'].iloc[i] > 0 and f['ra_z'].iloc[i] > 0:
                    state = 'FIRED'
                    events.append(dict(kind='fire', date=idx[i], close=df['close'].iloc[i], base_bars=nb,
                                       j_z=f['j_z'].iloc[i], a_z=f['a_z'].iloc[i], ra_z=f['ra_z'].iloc[i],
                                       depth_from_peak_pct=(math.exp(lc[i] - lc[peak_i]) - 1) * 100,
                                       off_trough_pct=(math.exp(lc[i] - trough_low) - 1) * 100))
    return events


def forward(df, date, n):
    """Evaluation only (uses future bars): max close gain over the next n bars."""
    i = df.index.get_loc(date)
    fut = df['close'].iloc[i + 1:i + 1 + n]
    if len(fut) < n:
        return None
    return (fut.max() / df['close'].iloc[i] - 1) * 100


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('tickers', nargs='+')
    ap.add_argument('--start', default=None)
    ap.add_argument('--fires-only', action='store_true')
    args = ap.parse_args()
    conn = get_db()
    for t in args.tickers:
        df = get_daily(conn, t, args.start)
        print(f'\n=== {t.upper()}  {df.index[0].date()} -> {df.index[-1].date()}  ({len(df)} daily bars) ===')
        for e in detect(df):
            d = e['date'].date()
            if e['kind'] == 'trough' and not args.fires_only:
                print(f"{d}  TROUGH confirmed  low {e['low_date'].date()} @{e['low']:.2f}  peak {e['peak_date'].date()}  "
                      f"dd {e['dd_pct']:.0f}% (z={e['dd_z']:.1f})  now {e['close']:.2f}")
            elif e['kind'] == 'base' and not args.fires_only:
                print(f"{d}  base qualified   {e['bars']} bars since confirmation  c={e['close']:.2f}")
            elif e['kind'] == 'fire':
                f20, f60 = forward(df, e['date'], 20), forward(df, e['date'], 60)
                fw = ' '.join(f'{k}={v:+.0f}%' for k, v in (('max20d', f20), ('max60d', f60)) if v is not None)
                print(f"{d}  *** IMMINENT ***  c={e['close']:.2f} base={e['base_bars']}b  jerk_z={e['j_z']:.1f} "
                      f"accel_z={e['a_z']:.1f} rangeacc_z={e['ra_z']:.1f}  off-trough {e['off_trough_pct']:+.0f}%  "
                      f"vs-peak {e['depth_from_peak_pct']:.0f}%   [eval only: {fw or 'n/a'}]")
    conn.close()


if __name__ == '__main__':
    main()
