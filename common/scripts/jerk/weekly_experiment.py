#!/usr/bin/env python3
"""Weekly "week-of" imminent-explosion experiment on stored tbl_prices_weekly bars.

Weekly bars are dated by their Monday; the last complete bar is the week of 2026-10-05
(ends 10-09). Variants are compared as A/B only: flagged weeks vs all weeks, success =
max weekly close over the next H weeks >= +GAIN over this week's close (evaluation only).
"""
import sys
import numpy as np
import pandas as pd
from statistics import NormalDist
from explosion import get_db

END = '2026-10-09'
REPORT_FROM = '2023-01-01'
GAIN = 0.20
Z = NormalDist().inv_cdf(0.95)
BASE_W = 52   # trailing weeks for the z-score baseline


def load(symbol):
    cur = get_db().cursor()
    cur.execute("""SELECT w.date, w.close, w.high, w.low FROM tbl_prices_weekly w
                   JOIN tbl_stock_tickers t ON t.id=w.ticker_id
                   WHERE t.symbol=%s AND w.date <= %s ORDER BY w.date""", (symbol, END))
    df = pd.DataFrame(cur.fetchall(), columns=['date', 'close', 'high', 'low'])
    return df.set_index(pd.to_datetime(df['date'])).drop(columns='date').astype(float)


ema = lambda s, n: s.ewm(span=n, adjust=False).mean()


def zs(x):
    m = x.rolling(BASE_W, min_periods=13).mean().shift(1)
    s = x.rolling(BASE_W, min_periods=13).std().shift(1)
    return (x - m) / s


def build(df):
    c = df['close']
    f = pd.DataFrame(index=df.index)
    f['c'] = c
    # ---- price-unit derivatives (as in the pasted rule / old prototype) ----
    v = ema(c.diff(4) / 4, 4)
    a = ema(v.diff(), 4)
    j = a.diff()
    ra = ema(df['high'] - df['low'], 4).diff().diff()
    f['v'], f['a'], f['j'], f['ra'] = v, a, j, ra
    # ---- scale-free: same chain on log price, z-scored vs own trailing weeks ----
    lc = np.log(c)
    lv = ema(lc.diff(), 3)
    la = ema(lv.diff(), 3)
    lj = la.diff()
    lra = ema(np.log(df['high'] / df['low']), 3).diff().ewm(span=2).mean().diff()
    f['jz'], f['az'], f['raz'] = zs(lj), zs(la), zs(lra)
    f['ema10'], f['ema20'] = ema(c, 10), ema(c, 20)
    return f


def variants(f):
    v, a, j, ra = f['v'], f['a'], f['j'], f['ra']
    pasted = (a > 0.01) & (j > 0.01) & (v > v.shift()) & (j > j.shift()) & (v < 0.6) & (v > -1.0)
    j2 = pasted & (j.shift() > j.shift(2))                       # jerk rising 2 consecutive weeks
    ema_f = pasted & (f['c'] > f['ema10']) & (ra > 0)            # + above 10w EMA, range accel > 0
    ema_f20 = pasted & (f['c'] > f['ema20']) & (ra > 0)
    z = (f['jz'] >= Z) & (f['az'] > 0) & (f['raz'] > 0)
    zj = f['jz'] >= Z
    z_ema = z & (f['c'] > f['ema10'])
    return {'pasted rule': pasted, 'pasted + jerk up 2wk': j2, 'pasted + >10wEMA + volA>0': ema_f,
            'pasted + >20wEMA + volA>0': ema_f20, 'z: jerk+accel+rangeacc': z, 'z: jerk only': zj,
            'z + >10wEMA': z_ema}


def fwd_gain(c, h):
    return pd.Series([c.iloc[i + 1:i + 1 + h].max() / c.iloc[i] - 1 if i + h < len(c) else np.nan
                      for i in range(len(c))], index=c.index)


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else 'MRNA'
    df = load(sym)
    f = build(df)
    print(f'{sym}: {len(df)} weekly bars, last {df.index[-1].date()}; report from {REPORT_FROM}')
    vs = variants(f)
    for h in (4, 8):
        g = fwd_gain(f['c'], h).loc[REPORT_FROM:].dropna()
        base = (g >= GAIN).mean()
        print(f'\n--- horizon {h}w, success = max close >= +{GAIN:.0%}   '
              f'(all weeks n={len(g)}, base rate {base:.0%}, median {g.median():+.0%}) ---')
        print(f'{"variant":30s} {"n":>3s} {"hit":>4s} {"rate":>5s} {"lift":>5s} {"median":>7s}')
        for name, m in vs.items():
            mm = m.loc[g.index].fillna(False)
            n, hit = int(mm.sum()), int((g[mm] >= GAIN).sum())
            rate = hit / n if n else float('nan')
            print(f'{name:30s} {n:3d} {hit:4d} {rate:5.0%} {rate / base if n else float("nan"):4.1f}x {g[mm].median() if n else float("nan"):+7.0%}')
    g4 = fwd_gain(f['c'], 4)
    print('\nFlagged weeks (week of Monday) -> next-4w max gain')
    for name in ('pasted rule', 'z: jerk+accel+rangeacc', 'pasted + >10wEMA + volA>0'):
        m = vs[name].loc[REPORT_FROM:].fillna(False)
        print(f'  [{name}]')
        print('   ' + '  '.join(f"{d.date()} c={f.c[d]:.0f} {g4[d]:+.0%}" if pd.notna(g4[d]) else f"{d.date()} c={f.c[d]:.0f} n/a"
                                 for d in m[m].index))


if __name__ == '__main__':
    main()
