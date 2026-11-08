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
    python imminent_probability.py MRNA --trades --start 2025-06-01
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
ATR_WINDOW = 14
GAP_ATR = 2.0
EXT_ATR = 4.0
STOP_ATR = 2.5
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


def feature_panel(raw=None, with_labels=False):
    """Per-(symbol, date) weekly feature panel for the whole universe.

    This is the single data-prep path shared by scan, backtest and live.
    """
    if raw is None:
        raw = load_weekly()
    xs = []
    for tid, g in raw.groupby('ticker_id', sort=False):
        if len(g) < 80:
            continue
        g = g.reset_index(drop=True)
        f = features(g)
        jf = jerk_frame(g.set_index('date')['close'], 4, 3, 3e-4, 3e-4, 0.02)
        f['jerk_state'] = np.where(jf['imminent'].values, 'IMM',
                                   np.where(jf['firing'].values, 'FIRE', '-'))
        f['date'] = g['date'].values
        f['symbol'] = g['symbol'].iloc[0]
        f['close'] = g['close'].values
        f['dvol13'] = (g['close'] * g['volume']).rolling(
            13, min_periods=4).mean().values
        if with_labels:
            u, d = labels(g['close'])
            f['y_up'] = u
            f['y_dn'] = d
            f['y_expl'] = explosion_label(g['close'])
        xs.append(f)
    return pd.concat(xs, ignore_index=True)


def build_dataset(raw):
    out = feature_panel(raw, with_labels=True)
    return out.dropna(subset=FEATURES + ['y_up', 'y_dn', 'y_expl'])


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


def beta_vs_spy(symbol, asof=None, days=504):
    s = load_daily(symbol).set_index('date')['close']
    m = load_daily('SPY').set_index('date')['close']
    df = pd.concat([s, m], axis=1, keys=['s', 'm'], sort=True).dropna()
    if asof:
        df = df[df.index <= pd.Timestamp(asof)]
    df = df.tail(days)
    rs = df['s'].pct_change().dropna()
    rm = df['m'].pct_change().dropna()
    beta = float(np.cov(rs, rm)[0, 1] / np.var(rm, ddof=1))
    vol = float(rs.std() * np.sqrt(252))
    return {'ticker': symbol.upper(), 'as_of': str(df.index[-1].date()),
            'beta': round(beta, 2), 'vol': round(vol, 3),
            'class': 'high' if beta >= 1.2 else 'low'}


def atr_series(high, low, close, window=ATR_WINDOW):
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()],
                   axis=1).max(axis=1)
    return tr.rolling(window).mean()


def signal_frame(df, vspan, smooth, a_min, j_min, v_hi, obv_smooth, obv_span):
    c = df.set_index('date')['close']
    v = df.set_index('date')['volume']
    h = df.set_index('date')['high']
    l = df.set_index('date')['low']
    jf = jerk_frame(c, vspan, smooth, a_min, j_min, v_hi)
    ob = obv_frame(c, v, smooth=obv_smooth, span=obv_span)
    out = pd.DataFrame({'close': c}).join(jf).join(ob)
    out['state'] = np.where(out['imminent'], 'IMM',
                            np.where(out['firing'], 'FIRE', '-'))
    out['obv'] = [obv_state(s, u) for s, u in zip(out['obv_slope'], out['uvr'])]
    out['atr'] = atr_series(h, l, c)
    out['ema20'] = c.ewm(span=20, adjust=False).mean()
    out['gap_atr'] = (c - c.shift(1)) / out['atr']
    out['ext_atr'] = (c - out['ema20']) / out['atr']
    return out


def translate_trades(o, max_wait, gap_atr=GAP_ATR, ext_atr=EXT_ATR,
                     stop_atr=STOP_ATR):
    pos = entry_i = entry_px = entry_atr = None
    fired = False
    trades = []
    for i, (dt, r) in enumerate(o.iterrows()):
        st, px = r['state'], r['close']
        if pos is None:
            ok = st in ('IMM', 'FIRE')
            if ok and pd.notna(r['gap_atr']) and r['gap_atr'] > gap_atr:
                ok = False
            if ok and pd.notna(r['ext_atr']) and r['ext_atr'] > ext_atr:
                ok = False
            if ok:
                pos, entry_i, entry_px = dt, i, px
                entry_atr, fired = r['atr'], st == 'FIRE'
        else:
            if st == 'FIRE':
                fired = True
            reason = None
            if stop_atr and pd.notna(entry_atr) and px <= entry_px - stop_atr * entry_atr:
                reason = 'stop'
            elif fired and st != 'FIRE':
                reason = 'fire-off'
            elif not fired and i - entry_i >= max_wait:
                reason = 'hook-fail'
            if reason:
                trades.append((pos, entry_px, dt, px, reason))
                pos, fired = None, False
    if pos is not None:
        trades.append((pos, entry_px, o.index[-1], o['close'].iloc[-1], 'open'))
    return trades


def trade_log(symbol, timeframe='daily', asof=None, start='2023-01-01',
              gap_atr=GAP_ATR, ext_atr=EXT_ATR, stop_atr=STOP_ATR):
    if timeframe == 'weekly':
        raw = load_weekly(symbol)
        if raw.empty:
            print(f'{symbol.upper()}: no weekly data')
            return
        g = raw[raw['symbol'] == symbol.upper()].reset_index(drop=True)
        o = signal_frame(g, 4, 3, 3e-4, 3e-4, 0.02, 13, 4)
        max_wait = 4
    else:
        g = load_daily(symbol)
        if g.empty:
            print(f'{symbol.upper()}: no daily data')
            return
        o = signal_frame(g, 5, 3, 2e-4, 2e-4, 0.02, 10, 5)
        max_wait = 10
    o = o[o.index >= pd.Timestamp(start)]
    if asof:
        o = o[o.index <= pd.Timestamp(asof)]
    if o.empty:
        print(f'{symbol.upper()}: no settled bars in range')
        return
    trades = translate_trades(o, max_wait, gap_atr, ext_atr, stop_atr)
    print(f'*{symbol.upper()} {timeframe.title()} trades — '
          f'ATR{gap_atr:g} gap / {ext_atr:g} ext / {stop_atr:g} stop*')
    print(f"{'Buy':<12}{'@':>8}  {'Sell':<12}{'@':>8}  {'Move':>8}  Reason")
    print('-' * 62)
    eq, wins, losses = 1.0, 0, 0
    for b, ep, s, sp, why in trades:
        r = sp / ep - 1.0
        eq *= 1.0 + r
        if r > 0:
            wins += 1
        else:
            losses += 1
        print(f"{str(pd.Timestamp(b).date()):<12}{ep:>8.2f}  "
              f"{str(pd.Timestamp(s).date()):<12}{sp:>8.2f}  "
              f"{r * 100:>+7.1f}%  {why}")
    print('-' * 62)
    print(f'Total {((eq - 1) * 100):+.1f}%  n={len(trades)}  '
          f'W/L={wins}/{losses}')


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


def last_settled(panel, today=None):
    """Most recent settled weekly bar: bar_date + 7 <= today.

    Weekly bars are stamped the ISO-week Monday, so `date < today` would accept
    the current week's running aggregate from Tuesday onward. This matches
    `emasma_core.settled_weekly_idx` and the repo's settled-weekly rule.
    """
    today = pd.Timestamp(today) if today else pd.Timestamp.today().normalize()
    d = panel.loc[panel['date'] + pd.Timedelta(days=7) <= today, 'date']
    return d.max() if not d.empty else None


def regime_series(bench='QQQ', daily_span=20, weekly_span=20):
    """Daily and weekly regime flags for `bench` (close > EMA)."""
    d = load_daily(bench).set_index('date')['close']
    daily_on = d > d.ewm(span=daily_span, adjust=False).mean()
    w = load_weekly(bench)
    w = w[w['symbol'] == bench.upper()].set_index('date')['close']
    weekly_on = w > w.ewm(span=weekly_span, adjust=False).mean()
    return {'daily': daily_on, 'weekly': weekly_on}


def regime_at(reg, asof):
    """Regime known at the signal week's Friday close (asof + 4 days)."""
    asof = pd.Timestamp(asof)
    d = reg['daily'][reg['daily'].index <= asof + pd.Timedelta(days=4)]
    w = reg['weekly'][reg['weekly'].index <= asof]
    daily_on = bool(d.iloc[-1]) if not d.empty else False
    weekly_on = bool(w.iloc[-1]) if not w.empty else False
    return {'daily': daily_on, 'weekly': weekly_on, 'ok': daily_on and weekly_on}


def select(panel, asof, bundle=None, top_n=20, min_dvol=0.0, min_p_expl=0.0,
           max_age_days=14):
    """Rank the universe at `asof` and return the top-N candidates.

    THE single selection path: scan, backtest and live all call this.
    Uses each symbol's latest settled weekly bar at/before `asof` (no lookahead).
    """
    if bundle is None:
        bundle = load_model()
    asof = pd.Timestamp(asof)
    p = panel[(panel['date'] <= asof) &
              (panel['date'] >= asof - pd.Timedelta(days=max_age_days))]
    p = p.dropna(subset=bundle['meta']['features'])
    if p.empty:
        return p
    p = p.sort_values(['symbol', 'date']).groupby('symbol', as_index=False).tail(1)
    if min_dvol:
        p = p[p['dvol13'].fillna(0) >= min_dvol]
    if p.empty:
        return p
    X = p[bundle['meta']['features']].astype(float)
    p = p.copy()
    p['p_expl'] = bundle['models']['expl'].predict_proba(X)[:, 1]
    p['p_up'] = bundle['models']['up'].predict_proba(X)[:, 1]
    p['p_dn'] = bundle['models']['down'].predict_proba(X)[:, 1]
    p = p[p['p_expl'] >= min_p_expl]
    p = p.sort_values('p_expl', ascending=False).head(top_n)
    cols = ['symbol', 'date', 'close', 'p_expl', 'p_up', 'p_dn',
            'dvol13', 'jerk_state']
    return p[cols].reset_index(drop=True)


def scan(asof=None, top_n=20, min_dvol=0.0, min_p_expl=0.0, panel=None,
         bundle=None):
    """Print the current cross-sectional explosion candidates (point-in-time)."""
    if panel is None:
        panel = feature_panel()
    asof = last_settled(panel, today=asof)
    if asof is None:
        print('scan: no settled weekly bars')
        return pd.DataFrame()
    picks = select(panel, asof, bundle=bundle, top_n=top_n,
                   min_dvol=min_dvol, min_p_expl=min_p_expl)
    reg = regime_at(regime_series(), asof)
    print(f"*Explosion scan — asof {pd.Timestamp(asof).date()} "
          f"(top {top_n}, min_dvol ${min_dvol / 1e6:.0f}M/wk)*")
    print(f"  regime: daily={'ON' if reg['daily'] else 'OFF'} "
          f"weekly={'ON' if reg['weekly'] else 'OFF'} -> "
          f"{'ALLOW' if reg['ok'] else 'BLOCK new entries'}")
    if picks.empty:
        print('  no candidates')
        return picks
    print(f"{'#':>3} {'Symbol':<7}{'Close':>9}{'P_expl':>8}{'P_up':>7}"
          f"{'P_dn':>7}{'DVol/wk':>11}  Jerk")
    print('-' * 66)
    for i, r in picks.iterrows():
        print(f"{i + 1:>3} {r['symbol']:<7}{r['close']:>9.2f}"
              f"{r['p_expl']:>8.3f}{r['p_up']:>7.2f}{r['p_dn']:>7.2f}"
              f"{r['dvol13'] / 1e6:>10.1f}M  {r['jerk_state']}")
    return picks


def train_bundle(panel, cutoff):
    """Fit up/ down/ expl models on panel rows strictly before `cutoff`."""
    tr = panel[panel['date'] < pd.Timestamp(cutoff)].dropna(
        subset=FEATURES + ['y_up', 'y_dn', 'y_expl'])
    models = {}
    for name, ycol in [('up', 'y_up'), ('down', 'y_dn'), ('expl', 'y_expl')]:
        models[name] = make_pipe().fit(tr[FEATURES], tr[ycol])
    return {'models': models, 'meta': {'features': FEATURES}}


def backtest(top_n=10, min_dvol=0.0, start='2024-01-01', horizon=13,
             target=0.30, stop=0.0, capital=100000.0, panel=None,
             bundle=None, verbose=True, use_regime=True):
    """Slot-based portfolio simulation driven by the shared `select()` path.

    Enters at the next weekly close after a signal, exits on +target, -stop,
    or after `horizon` weeks. Capital split equally across `top_n` slots.
    Trains its own model on data before `start` so there is no lookahead.
    """
    if panel is None:
        panel = feature_panel(with_labels=True)
    if bundle is None:
        bundle = train_bundle(
            panel, pd.Timestamp(start) - pd.Timedelta(weeks=EXPL_HORIZON))
    reg = regime_series() if use_regime else None
    px = {}
    for sym, g in panel.groupby('symbol'):
        g = g.sort_values('date')
        px[sym] = (g['date'].values, g['close'].values)

    dates = sorted(panel.loc[panel['date'] >= pd.Timestamp(start), 'date'].unique())
    slots = [None] * top_n
    pending = []
    trades = []
    equity = capital
    curve = []

    def bar(sym, d):
        di, ci = px[sym]
        j = np.searchsorted(di, np.datetime64(d), side='right') - 1
        return (j, ci[j]) if j >= 0 else (None, None)

    for d in dates:
        for sym, sigd in pending:
            free = next((i for i, s in enumerate(slots) if s is None), None)
            if free is None:
                continue
            j, c = bar(sym, d)
            if j is None or px[sym][0][j] < np.datetime64(
                    pd.Timestamp(d) - pd.Timedelta(days=14)):
                continue
            slots[free] = {'symbol': sym, 'entry_date': d, 'entry_px': c,
                           'signal_date': sigd, 'weeks': 0}
        pending = []

        for i, s in enumerate(slots):
            if s is None:
                continue
            j, c = bar(s['symbol'], d)
            if j is None:
                continue
            s['weeks'] += 1
            ret = c / s['entry_px'] - 1.0
            reason = None
            if ret >= target:
                reason = 'target'
            elif stop and ret <= -stop:
                reason = 'stop'
            elif s['weeks'] >= horizon:
                reason = 'time'
            if reason:
                trades.append({'symbol': s['symbol'],
                               'signal_date': s['signal_date'],
                               'entry_date': s['entry_date'], 'entry_px': s['entry_px'],
                               'exit_date': d, 'exit_px': c, 'ret': ret,
                               'weeks': s['weeks'], 'reason': reason})
                equity *= 1.0 + ret / top_n
                slots[i] = None

        if any(s is None for s in slots):
            if use_regime and not regime_at(reg, d)['ok']:
                pass
            else:
                held = {s['symbol'] for s in slots if s}
                picks = select(panel, d, bundle=bundle, top_n=top_n,
                               min_dvol=min_dvol)
                need = sum(1 for s in slots if s is None)
                for _, p in picks.iterrows():
                    if p['symbol'] in held:
                        continue
                    pending.append((p['symbol'], d))
                    if len(pending) >= need:
                        break
        curve.append((d, equity))

    tr = pd.DataFrame(trades)
    if tr.empty:
        print('backtest: no trades')
        return tr, pd.DataFrame(curve, columns=['date', 'equity'])
    tr['year'] = pd.to_datetime(tr['exit_date']).dt.year
    hit = (tr['ret'] >= target).mean()
    dd = (pd.Series([e for _, e in curve]) /
          pd.Series([e for _, e in curve]).cummax() - 1).min()
    if verbose:
        print(f"*Backtest — top{top_n} min_dvol ${min_dvol / 1e6:.0f}M/wk "
              f"{start}..{dates[-1]}*")
        print(f"  trades={len(tr)}  hit(>= {target:.0%})={hit:.3f}  "
              f"avg={tr['ret'].mean() * 100:+.1f}%  "
              f"median={tr['ret'].median() * 100:+.1f}%  "
              f"final=${equity:,.0f} ({equity / capital - 1:+.1%})  maxDD={dd:.1%}")
        for y, g in tr.groupby('year'):
            print(f"  {y}: n={len(g):>4} hit={(g['ret'] >= target).mean():.3f} "
                  f"avg={g['ret'].mean() * 100:+.1f}% "
                  f"med={g['ret'].median() * 100:+.1f}%")
    return tr, pd.DataFrame(curve, columns=['date', 'equity'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tickers', nargs='*')
    ap.add_argument('--train', action='store_true')
    ap.add_argument('--asof')
    ap.add_argument('--score', action='store_true',
                    help='compact one-line score instead of the by-date report')
    ap.add_argument('--scan', action='store_true',
                    help='rank the whole universe by P_expl at --asof')
    ap.add_argument('--backtest', action='store_true',
                    help='slot portfolio backtest driven by the same select() path')
    ap.add_argument('--top', type=int, default=20,
                    help='names to hold/scan (default 20)')
    ap.add_argument('--min-dvol', type=float, default=0.0,
                    help='min trailing 13w dollar volume in $/week (default 0)')
    ap.add_argument('--no-regime', action='store_true',
                    help='disable the QQQ daily+weekly regime gate')
    ap.add_argument('--beta', action='store_true',
                    help='beta vs SPY + realized vol classification')
    ap.add_argument('--trades', action='store_true',
                    help='ATR-filtered BUY/SELL trade log')
    ap.add_argument('--tf', choices=['weekly', 'daily', 'both'], default='both',
                    help='timeframe for --trades (default both)')
    ap.add_argument('--start', default='2023-01-01',
                    help='first bar for --trades (default 2023-01-01)')
    ap.add_argument('--gap-atr', type=float, default=GAP_ATR,
                    help=f'skip BUY if signal-bar gap > N ATR (default {GAP_ATR:g})')
    ap.add_argument('--ext-atr', type=float, default=EXT_ATR,
                    help=f'skip BUY if close > N ATR above EMA20 (default {EXT_ATR:g})')
    ap.add_argument('--stop-atr', type=float, default=STOP_ATR,
                    help=f'stop at entry - N ATR (default {STOP_ATR:g}; 0 disables)')
    args = ap.parse_args()
    if args.train:
        train()
        return
    if args.scan:
        scan(args.asof, args.top, args.min_dvol)
        return
    if args.backtest:
        backtest(top_n=args.top, min_dvol=args.min_dvol,
                 start=args.start, horizon=13,
                 use_regime=not args.no_regime)
        return
    if not args.tickers:
        ap.error('give a ticker, --train, --scan or --backtest')
    for t in args.tickers:
        if args.beta:
            r = beta_vs_spy(t, args.asof)
            print(f"{r['ticker']} as_of={r['as_of']} beta={r['beta']:.2f} "
                  f"vol={r['vol'] * 100:.1f}% class={r['class']}")
        elif args.trades:
            tfs = ['weekly', 'daily'] if args.tf == 'both' else [args.tf]
            for tf in tfs:
                trade_log(t, tf, args.asof, args.start,
                          args.gap_atr, args.ext_atr, args.stop_atr)
                print()
        elif args.score:
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
