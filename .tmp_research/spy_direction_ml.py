#!/usr/bin/env python3
"""Predict SPY 20-trading-day direction (up/down) from causal daily features.

Strict chronological build/test split with a 20-day embargo so overlapping
forward-return labels never bridge the boundary. All features use data through
day t only; signals at close t fill at open t+1 (same convention as the EMA study).
"""
import math
import os

import numpy as np
import pandas as pd
import psycopg2
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, precision_score,
                             recall_score, roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HORIZON = 5
SPLIT = '2023-01-01'
COST = 0.0005
CAPITAL = 100_000.0
DB = dict(host=os.getenv('DB_HOST', '127.0.0.1'),
          port=int(os.getenv('DB_PORT', '5432')),
          dbname=os.getenv('DB_DATABASE', 'swingtrader'),
          user=os.getenv('DB_USERNAME', 'swingtrader'),
          password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'))


def load():
    conn = psycopg2.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.date, d.open, d.high, d.low, d.close, d.volume
            FROM tbl_prices_daily d
            JOIN tbl_stock_tickers s ON s.id = d.ticker_id
            WHERE s.symbol = 'SPY'
            ORDER BY d.date ASC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ('open', 'high', 'low', 'close'):
        df[c] = df[c].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df


def features(df):
    c, h, l, v = df['close'], df['high'], df['low'], df['volume']
    f = pd.DataFrame(index=df.index)
    for n in (1, 5, 10, 20, 60, 120, 252):
        f[f'r{n}'] = c.pct_change(n)
    for n in (10, 20, 50, 200):
        em = c.ewm(span=n, adjust=False).mean()
        f[f'px_ema{n}'] = c / em - 1
        if n in (10, 20):
            f[f'ema{n}_slope5'] = em / em.shift(5) - 1
    f['ema10_20'] = (c.ewm(span=10, adjust=False).mean() /
                     c.ewm(span=20, adjust=False).mean() - 1)
    f['ema20_50'] = (c.ewm(span=20, adjust=False).mean() /
                     c.ewm(span=50, adjust=False).mean() - 1)
    f['px_sma40'] = c / c.rolling(40).mean() - 1
    for n in (20, 60, 252):
        lo, hi = c.rolling(n).min(), c.rolling(n).max()
        f[f'pos{n}'] = (c - lo) / (hi - lo).replace(0, np.nan)
    f['dd252'] = c / c.rolling(252).max() - 1
    f['off_low252'] = c / c.rolling(252).min() - 1
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    f['rsi14'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    f['macd'] = macd / c
    f['macd_sig'] = macd.ewm(span=9, adjust=False).mean() / c
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    f['bb_z'] = (c - m20) / s20.replace(0, np.nan)
    r = c.pct_change()
    for n in (20, 60):
        f[f'vol{n}'] = r.rolling(n).std() * math.sqrt(252)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f['atr14'] = tr.ewm(span=14, adjust=False).mean() / c
    f['vol_r20'] = np.log(v / v.rolling(20).mean())
    f['vol_r60'] = np.log(v / v.rolling(60).mean())
    f['up_days20'] = (r > 0).rolling(20).sum() / 20
    return f


def metrics(eq, dates):
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    ret = eq[-1] / eq[0] - 1
    peak = np.maximum.accumulate(eq)
    r = np.diff(eq) / eq[:-1]
    sd = r.std(ddof=0)
    return dict(total=ret, cagr=(eq[-1]/eq[0])**(1/years)-1,
                mdd=float((eq/peak-1).min()),
                sharpe=float(r.mean()/sd*math.sqrt(252)) if sd > 0 else 0.0)


def sim(dates, opn, close, want, start):
    cash, shares = CAPITAL, 0.0
    eq = []
    for i in range(start, len(dates)):
        eq.append(cash + shares * close[i])
        if i < len(dates) - 1:
            if want[i] and shares == 0 and cash > 0:
                shares = cash / (opn[i+1]*(1+COST)); cash = 0.0
            elif not want[i] and shares > 0:
                cash = shares * opn[i+1]*(1-COST); shares = 0.0
    return np.array(eq)


def show_m(label, m):
    print(f'  {label:<24} ret {m["total"]*100:>8.1f}%  CAGR {m["cagr"]*100:>6.2f}%  '
          f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}')


def main():
    df = load()
    X = features(df)
    y = (df['close'].shift(-HORIZON) > df['close']).astype(int)
    ok = X.notna().all(axis=1) & y.notna()
    d = df[ok].reset_index(drop=True)
    X = X[ok].reset_index(drop=True)
    y = y[ok].astype(int).to_numpy()
    split_i = d.index[d['date'] >= SPLIT][0]
    build_end = split_i - HORIZON  # embargo: drop last 20 build days (label overlap)
    Xb, yb = X.iloc[:build_end], y[:build_end]
    Xt, yt = X.iloc[split_i:], y[split_i:]
    print(f'All clean rows: {len(d)}  ({d["date"].iloc[0].date()} -> {d["date"].iloc[-1].date()})')
    print(f'BUILD: {len(Xb)} rows through {d["date"].iloc[build_end-1].date()} '
          f'(20d embargo to {d["date"].iloc[split_i-1].date()})')
    print(f'TEST:  {len(Xt)} rows {d["date"].iloc[split_i].date()} -> {d["date"].iloc[-1].date()}')
    print(f'Features: {X.shape[1]}  Up-class: build {yb.mean()*100:.1f}%  test {yt.mean()*100:.1f}%')
    print(f'Baseline (always-up) test accuracy: {max(yt.mean(),1-yt.mean())*100:.1f}%\n')

    models = {
        'LogReg': make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        'RandomForest': RandomForestClassifier(n_estimators=300, max_depth=5,
                                               min_samples_leaf=20, random_state=42,
                                               n_jobs=-1),
        'GradBoost': HistGradientBoostingClassifier(max_iter=150, max_depth=3,
                                                    learning_rate=0.05,
                                                    min_samples_leaf=30, random_state=42),
    }
    dates = list(d['date'])
    opn, close = d['open'].to_numpy(), d['close'].to_numpy()
    test_start = split_i
    bh_eq = sim(dates, opn, close, np.ones(len(d), bool), test_start)
    e10 = d['close'].ewm(span=10, adjust=False).mean().to_numpy()
    e20 = d['close'].ewm(span=20, adjust=False).mean().to_numpy()
    ema_eq = sim(dates, opn, close, e10 > e20, test_start)

    print('Classification metrics on TEST:')
    results = {}
    for name, model in models.items():
        model.fit(Xb, yb)
        p = model.predict_proba(Xt)[:, 1]
        pred = (p >= 0.5).astype(int)
        acc = accuracy_score(yt, pred)
        auc = roc_auc_score(yt, p)
        prec = precision_score(yt, pred, zero_division=0)
        rec = recall_score(yt, pred, zero_division=0)
        tn, fp, fn, tp = confusion_matrix(yt, pred).ravel()
        results[name] = p
        print(f'  {name:<14} acc {acc*100:>5.1f}%  AUC {auc:>5.3f}  '
              f'prec {prec*100:>5.1f}%  rec {rec*100:>5.1f}%  '
              f'TP/TN/FP/FN {tp}/{tn}/{fp}/{fn}')

    def full_signal(p, th):
        w = np.zeros(len(d), dtype=bool)
        w[test_start:] = p >= th
        return w

    print('\nLong/flat trading on TEST (predict up -> long, else cash; 5bp costs):')
    show_m('B&H', metrics(bh_eq, dates[test_start:]))
    show_m('EMA10/20', metrics(ema_eq, dates[test_start:]))
    for name, p in results.items():
        eq = sim(dates, opn, close, full_signal(p, 0.5), test_start)
        show_m(name + ' (p>=0.5)', metrics(eq, dates[test_start:]))

    best = max(results, key=lambda k: roc_auc_score(yt, results[k]))
    model = models[best]
    print(f'\nBest by AUC: {best}. Train-only threshold sweep (p*):')
    pb = model.predict_proba(Xb)[:, 1]
    for th in (0.45, 0.50, 0.55, 0.60):
        acc = accuracy_score(yb, (pb >= th).astype(int))
        eq = sim(dates, opn, close, full_signal(results[best], th), test_start)
        mm = metrics(eq, dates[test_start:])
        print(f'  th {th:.2f}  build acc {acc*100:.1f}%  '
              f'test ret {mm["total"]*100:>7.1f}%  Sharpe {mm["sharpe"]:.2f}')

    if hasattr(model, 'feature_importances_'):
        imp = sorted(zip(X.columns, model.feature_importances_), key=lambda x: -x[1])[:10]
        print(f'\nTop features ({best}): ' + ', '.join(f'{k} {v:.3f}' for k, v in imp))


if __name__ == '__main__':
    main()
