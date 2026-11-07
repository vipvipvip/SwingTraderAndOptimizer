#!/usr/bin/env python3
"""Calibrated P(breakout) / P(breakdown) over the next H weeks from weekly
price+volume structure (drawdown, base, velocity/accel/jerk, volume dry-up,
up/down volume, OBV). Trains one cross-sectional model over the whole DB
universe, so scores are comparable across stocks and ETFs.

Usage:
    python imminent_probability.py --train
    python imminent_probability.py MRNA
    python imminent_probability.py MRNA --asof 2026-06-08
    python imminent_probability.py CAT QQQ --asof 2026-08-12
"""
import os
import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, brier_score_loss

HORIZON = 8
UP_THR = 0.15
DOWN_THR = 0.15
EXPL_HORIZON = 13
EXPL_THR = 0.30
START = '2017-01-01'
SPLIT = '2024-01-01'
MODEL_PATH = Path(__file__).resolve().parent / 'models' / 'imminent_probability.joblib'

DB = dict(
    host=os.getenv('DB_HOST', '127.0.0.1'),
    port=int(os.getenv('DB_PORT', '5432')),
    dbname=os.getenv('DB_DATABASE', 'swingtrader'),
    user=os.getenv('DB_USERNAME', 'swingtrader'),
    password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'),
)

FEATURES = [
    'dd_52w', 'wks_since_hi', 'base_range_12', 'dist_base_hi', 'ema20_dist',
    'ret_4w', 'ret_13w', 'vel', 'accel', 'jerk',
    'rv', 'rv_dryup', 'uvr13', 'obv_slope', 'vol_exp', 'atr_pct', 'is_etf',
]


def connect():
    return psycopg2.connect(**DB)


def load_weekly(symbol=None):
    conn = connect()
    try:
        base = """
            SELECT w.ticker_id, s.symbol, s.is_etf, w.date,
                   w.close, w.high, w.low, w.volume
            FROM tbl_prices_weekly w
            JOIN tbl_stock_tickers s ON s.id = w.ticker_id
            WHERE w.date >= %s
        """
        params = [START]
        if symbol:
            base += " AND s.symbol = %s"
            params.append(symbol.upper())
        base += " ORDER BY w.ticker_id, w.date"
        cur = conn.cursor()
        cur.execute(base, params)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['ticker_id', 'symbol', 'is_etf', 'date',
                                     'close', 'high', 'low', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ['close', 'high', 'low', 'volume']:
        df[c] = df[c].astype(float)
    df['is_etf'] = df['is_etf'].astype(bool)
    return df


def load_daily(symbol):
    conn = connect()
    try:
        q = """
            SELECT s.symbol, d.date, d.close, d.high, d.low, d.volume
            FROM tbl_prices_daily d
            JOIN tbl_stock_tickers s ON s.id = d.ticker_id
            WHERE s.symbol = %s AND d.date >= %s
            ORDER BY d.date
        """
        cur = conn.cursor()
        cur.execute(q, (symbol.upper(), START))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['symbol', 'date', 'close', 'high', 'low', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ['close', 'high', 'low', 'volume']:
        df[c] = df[c].astype(float)
    return df


def features(g):
    c = g['close']
    v = g['volume']
    rng = g['high'] - g['low']
    f = pd.DataFrame(index=g.index)

    hi52 = c.rolling(52, min_periods=20).max()
    f['dd_52w'] = c / hi52 - 1.0
    f['wks_since_hi'] = c.rolling(52, min_periods=20).apply(
        lambda x: len(x) - 1 - int(np.argmax(x)), raw=True)

    b_hi = c.rolling(12, min_periods=8).max()
    b_lo = c.rolling(12, min_periods=8).min()
    f['base_range_12'] = (b_hi - b_lo) / b_lo
    f['dist_base_hi'] = c / b_hi - 1.0
    f['ema20_dist'] = c / c.ewm(span=20, adjust=False).mean() - 1.0

    f['ret_4w'] = c.pct_change(4)
    f['ret_13w'] = c.pct_change(13)

    vel = ((c - c.shift(4)) / 4.0) / c
    vel_s = vel.ewm(span=3, adjust=False).mean()
    acc = vel_s.diff()
    f['vel'] = vel_s
    f['accel'] = acc
    f['jerk'] = acc.diff()

    e13 = v.ewm(span=13, adjust=False).mean()
    e52 = v.ewm(span=52, adjust=False).mean()
    f['rv'] = e13 / e52
    f['rv_dryup'] = f['rv'] / f['rv'].rolling(12, min_periods=4).min()

    up_vol = v.where(c.diff() > 0, 0.0)
    f['uvr13'] = up_vol.rolling(13).sum() / v.rolling(13).sum()

    obv = (np.sign(c.diff()).fillna(0.0) * v).cumsum()
    f['obv_slope'] = (obv.ewm(span=13, adjust=False).mean().diff(4)
                      / (v.rolling(13).mean() * 13.0))

    f['vol_exp'] = v / v.rolling(13).mean()
    f['atr_pct'] = rng.rolling(4).mean() / c
    f['is_etf'] = float(g['is_etf'].iloc[0])
    return f


def labels(c, horizon=HORIZON, up_thr=UP_THR, down_thr=DOWN_THR):
    vals = c.to_numpy(dtype=float)
    n = len(vals)
    y_up = np.full(n, np.nan)
    y_dn = np.full(n, np.nan)
    for i in range(n - horizon):
        fut = vals[i + 1:i + 1 + horizon]
        base = vals[i]
        y_up[i] = 1.0 if fut.max() >= base * (1.0 + up_thr) else 0.0
        y_dn[i] = 1.0 if fut.min() <= base * (1.0 - down_thr) else 0.0
    return y_up, y_dn


def explosion_label(c, horizon=EXPL_HORIZON, thr=EXPL_THR):
    vals = c.to_numpy(dtype=float)
    n = len(vals)
    y = np.full(n, np.nan)
    for i in range(n - horizon):
        fut = vals[i + 1:i + 1 + horizon]
        y[i] = 1.0 if fut.max() >= vals[i] * (1.0 + thr) else 0.0
    return y


def build_dataset(raw):
    xs = []
    for tid, g in raw.groupby('ticker_id', sort=False):
        if len(g) < 80:
            continue
        g = g.reset_index(drop=True)
        f = features(g)
        u, d = labels(g['close'])
        f['y_up'] = u
        f['y_dn'] = d
        f['y_expl'] = explosion_label(g['close'])
        f['date'] = g['date'].values
        f['symbol'] = g['symbol'].iloc[0]
        xs.append(f)
    out = pd.concat(xs, ignore_index=True).dropna(
        subset=FEATURES + ['y_up', 'y_dn', 'y_expl'])
    return out


def make_pipe():
    lr = LogisticRegression(max_iter=1000, class_weight='balanced', C=0.5)
    pipe = Pipeline([('sc', StandardScaler()), ('lr', lr)])
    return CalibratedClassifierCV(pipe, method='sigmoid', cv=TimeSeriesSplit(n_splits=3))


def train(raw_path=None):
    raw = load_weekly()
    ds = build_dataset(raw)
    ds = ds.sort_values('date').reset_index(drop=True)
    print(f"dataset rows={len(ds)} tickers={ds['symbol'].nunique()} "
          f"span={ds['date'].min().date()}..{ds['date'].max().date()}")
    print(f"base rates: up={ds['y_up'].mean():.3f} down={ds['y_dn'].mean():.3f} "
          f"expl={ds['y_expl'].mean():.3f}")

    tr = ds[ds['date'] < SPLIT]
    te = ds[ds['date'] >= SPLIT]
    for name, ycol in [('UP', 'y_up'), ('DOWN', 'y_dn'), ('EXPL', 'y_expl')]:
        m = make_pipe().fit(tr[FEATURES], tr[ycol])
        p = m.predict_proba(te[FEATURES])[:, 1]
        print(f"  holdout {name}: n={len(te)} AUC={roc_auc_score(te[ycol], p):.3f} "
              f"Brier={brier_score_loss(te[ycol], p):.4f}")

    meta = {'features': FEATURES, 'horizon': HORIZON, 'up_thr': UP_THR,
            'down_thr': DOWN_THR, 'expl_horizon': EXPL_HORIZON,
            'expl_thr': EXPL_THR}
    models = {}
    for name, ycol in [('up', 'y_up'), ('down', 'y_dn'), ('expl', 'y_expl')]:
        models[name] = make_pipe().fit(ds[FEATURES], ds[ycol])
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({'models': models, 'meta': meta}, MODEL_PATH)
    print(f"saved -> {MODEL_PATH}")


def load_model():
    if not MODEL_PATH.exists():
        raise SystemExit(f"no model at {MODEL_PATH}; run --train first")
    return joblib.load(MODEL_PATH)


def score(symbol, asof=None):
    bundle = load_model()
    raw = load_weekly(symbol)
    if raw.empty:
        return {'ticker': symbol.upper(), 'error': 'no data'}
    g = raw[raw['symbol'] == symbol.upper()].reset_index(drop=True)
    if len(g) < 60:
        return {'ticker': symbol.upper(), 'error': 'insufficient history'}
    f = features(g)
    f['date'] = g['date'].values
    f['close'] = g['close'].values
    f = f.dropna(subset=bundle['meta']['features'])
    if asof:
        f = f[f['date'] <= pd.Timestamp(asof)]
    if f.empty:
        return {'ticker': symbol.upper(), 'error': 'no bar at/ before asof'}
    row = f.iloc[-1]
    X = row[bundle['meta']['features']].to_frame().T.astype(float)
    p_up = float(bundle['models']['up'].predict_proba(X)[:, 1][0])
    p_dn = float(bundle['models']['down'].predict_proba(X)[:, 1][0])
    p_expl = float(bundle['models']['expl'].predict_proba(X)[:, 1][0])
    return {
        'ticker': symbol.upper(),
        'as_of': str(pd.Timestamp(row['date']).date()),
        'close': float(row['close']),
        'p_up_15pct_8w': round(p_up, 4),
        'p_down_15pct_8w': round(p_dn, 4),
        'p_no_move_8w': round(max(0.0, 1.0 - p_up - p_dn), 4),
        'p_expl_30pct_13w': round(p_expl, 4),
        'features': {k: round(float(row[k]), 4) for k in bundle['meta']['features']},
    }


def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def jerk_frame(c, vspan, smooth, a_min, j_min, v_hi):
    vel = ((c - c.shift(vspan)) / float(vspan)) / c
    vs = ema(vel, smooth)
    a = ema(vs.diff(), smooth)
    j = a.diff()
    out = pd.DataFrame({'v': vs, 'a': a, 'j': j}, index=c.index)
    out['imminent'] = (
        (out['a'] > a_min) & (out['j'] > j_min) &
        (out['j'] > out['j'].shift(1)) &
        (out['a'] > out['a'].shift(1)) &
        (out['v'] > out['v'].shift(1)) &
        (out['v'] < v_hi)
    )
    out['firing'] = (out['v'] > v_hi) & (out['a'] > a_min)
    return out


def obv_frame(c, v, smooth=13, span=4):
    obv = (np.sign(c.diff()).fillna(0.0) * v).cumsum()
    obv_s = ema(obv, smooth)
    slope = (obv_s - obv_s.shift(span)) / (v.rolling(smooth).mean() * smooth)
    up = v.where(c.diff() > 0, 0.0).rolling(smooth).sum()
    uvr = up / v.rolling(smooth).sum()
    return pd.DataFrame({'obv_slope': slope, 'uvr': uvr}, index=c.index)


def obv_state(slope, uvr):
    if pd.isna(slope) or pd.isna(uvr):
        return '-'
    if slope > 0 and uvr >= 0.55:
        return 'ACCUM'
    if slope < 0 and uvr <= 0.45:
        return 'DIST'
    if slope > 0:
        return 'acc+'
    if slope < 0:
        return 'dist-'
    return 'flat'


def vol_state(rv, dryup):
    if pd.isna(rv):
        return '-'
    if rv >= 1.5:
        return 'EXPAND'
    if rv <= 0.85:
        return 'DRY'
    return 'normal'


def report(symbol, asof=None, n_weekly=4, n_daily=5):
    bundle = load_model()
    raw = load_weekly(symbol)
    if raw.empty:
        print(f'{symbol.upper()}: no weekly data')
        return None
    g = raw[raw['symbol'] == symbol.upper()].reset_index(drop=True)
    if len(g) < 60:
        print(f'{symbol.upper()}: insufficient history')
        return None

    f = features(g)
    f['date'] = g['date'].values
    f['close'] = g['close'].values
    f = f.dropna(subset=FEATURES)
    if asof:
        f = f[f['date'] <= pd.Timestamp(asof)]
    if f.empty:
        print(f'{symbol.upper()}: no settled bar at/before {asof}')
        return None

    p_expl, p_up, p_dn = [], [], []
    for _, row in f.iterrows():
        X = row[FEATURES].to_frame().T.astype(float)
        p_expl.append(float(bundle['models']['expl'].predict_proba(X)[:, 1][0]))
        p_up.append(float(bundle['models']['up'].predict_proba(X)[:, 1][0]))
        p_dn.append(float(bundle['models']['down'].predict_proba(X)[:, 1][0]))
    f['p_expl'] = p_expl
    f['p_up'] = p_up
    f['p_dn'] = p_dn

    wc = g.set_index('date')['close']
    wvvol = g.set_index('date')['volume']
    wj = jerk_frame(wc, 4, 3, 3e-4, 3e-4, 0.02)
    wo = obv_frame(wc, wvvol, smooth=13, span=4).rename(
        columns={'obv_slope': 'obv_slope_w', 'uvr': 'uvr_w'})
    wrv = wvvol.ewm(span=13, adjust=False).mean() / wvvol.ewm(span=52, adjust=False).mean()
    wk = pd.DataFrame({'close': wc})
    wk = wk.join(wj).join(wo)
    wk['rv'] = wrv
    wk['rv_dryup'] = wrv / wrv.rolling(12, min_periods=4).min()
    wk = wk.join(f.set_index('date')[['p_expl', 'p_up', 'p_dn']])
    wk = wk.dropna(subset=['p_expl', 'v', 'a', 'j']).tail(n_weekly)

    print(f'*{symbol.upper()} Weekly — {wk.index[-1].date()}*')
    print(f"{'Week':<12}{'Close':>9}{'P_expl':>8}{'P_up':>7}{'v':>9}{'a':>9}{'j':>9}  {'JERK':<6}{'OBV':<7}{'Vol'}")
    print('-' * 88)
    for d, r in wk.iterrows():
        jerk = 'IMM' if r['imminent'] else ('fire' if r['firing'] else '-')
        print(f"{str(d.date()):<12}{r['close']:>9.2f}{r['p_expl']:>8.2f}{r['p_up']:>7.2f}"
              f"{r['v']:>9.4f}{r['a']:>9.4f}{r['j']:>9.4f}  {jerk:<6}"
              f"{obv_state(r['obv_slope_w'], r['uvr_w']):<7}{vol_state(r['rv'], r['rv_dryup'])}")
    print()

    d = load_daily(symbol)
    if d.empty or len(d) < 60:
        print(f'  no daily data')
        return {'ticker': symbol.upper(), 'weekly': wk}
    dc = d.set_index('date')['close']
    dv = d.set_index('date')['volume']
    dj = jerk_frame(dc, 5, 3, 2e-4, 2e-4, 0.02)
    do = obv_frame(dc, dv, smooth=10, span=5)
    drv = dv.ewm(span=13, adjust=False).mean() / dv.ewm(span=52, adjust=False).mean()
    dd = pd.DataFrame({'close': dc}).join(dj).join(do)
    dd['rv'] = drv
    dd['rv_dryup'] = drv / drv.rolling(12, min_periods=4).min()
    if asof:
        dd = dd[dd.index <= pd.Timestamp(asof)]
    dd = dd.dropna(subset=['v', 'a', 'j']).tail(n_daily)

    print(f'*{symbol.upper()} Daily — {dd.index[-1].date()}*')
    print(f"{'Date':<12}{'Close':>9}{'v':>9}{'a':>9}{'j':>9}  {'JERK':<6}{'OBV':<7}{'Vol'}")
    print('-' * 74)
    for dt, r in dd.iterrows():
        jerk = 'IMM' if r['imminent'] else ('fire' if r['firing'] else '-')
        print(f"{str(dt.date()):<12}{r['close']:>9.2f}{r['v']:>9.4f}{r['a']:>9.4f}{r['j']:>9.4f}"
              f"  {jerk:<6}{obv_state(r['obv_slope'], r['uvr']):<7}{vol_state(r['rv'], r['rv_dryup'])}")
    print()
    print(f"Latest: P(expl>=30%,13w)={wk['p_expl'].iloc[-1]:.3f} "
          f"P(up>=15%,8w)={wk['p_up'].iloc[-1]:.3f} "
          f"P(down>=15%,8w)={wk['p_dn'].iloc[-1]:.3f} | "
          f"weekly_jerk={'IMM' if wk['imminent'].iloc[-1] else 'no'} "
          f"daily_jerk={'IMM' if dd['imminent'].iloc[-1] else 'no'}")
    return {'ticker': symbol.upper(), 'weekly': wk, 'daily': dd}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tickers', nargs='*')
    ap.add_argument('--train', action='store_true')
    ap.add_argument('--asof')
    ap.add_argument('--score', action='store_true',
                    help='compact one-line score instead of the by-date report')
    args = ap.parse_args()
    if args.train:
        train()
        return
    if not args.tickers:
        ap.error('give a ticker or --train')
    for t in args.tickers:
        if args.score:
            r = score(t, args.asof)
            if 'error' in r:
                print(f"{t}: {r['error']}")
            else:
                print(f"{r['ticker']} as_of={r['as_of']} close={r['close']:.2f} "
                      f"P(up>=15%,8w)={r['p_up_15pct_8w']:.3f} "
                      f"P(down>=15%,8w)={r['p_down_15pct_8w']:.3f} "
                      f"P(expl>=30%,13w)={r['p_expl_30pct_13w']:.3f}")
        else:
            report(t, args.asof)
            print()


if __name__ == '__main__':
    main()
