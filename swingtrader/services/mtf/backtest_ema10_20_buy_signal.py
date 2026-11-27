#!/usr/bin/env python3
"""A/B evaluation: daily EMA10/EMA20 buy-trigger variants.

Signal definition (from Slack "solid buy" table): daily EMA10/EMA20 bullish gap.
Table rows were post-cross snapshots (EMA10>EMA20, gap 0.5%-2.6%), not cross day.
We evaluate as BUY trigger variants with S1-style exit (settled weekly EMA10<EMA20).

Variants
- S1: cross-up day (EMA10>EMA20 and prev EMA10<=EMA20) - baseline
- S1+gap: cross-up day AND 0 < gap% <= max_gap
- S1+fresh: enter if within fresh_days of cross-up and EMA10>EMA20 and gap ok
- GapState: any day EMA10>EMA20 and 0 < gap% <= max_gap (state, not cross) - matches table
- DailyOnly: long while EMA10>EMA20
- B&H

All fills next open, cost 0.0005/side. Settled weekly exit: bar_date+7 <= day.
Backtest returns are NOT trustworthy; A/B relative only.
"""
import argparse, os
import numpy as np, pandas as pd, psycopg2

COST = 0.0005
CAPITAL = 100_000.0
DB = dict(host=os.getenv('DB_HOST', '127.0.0.1'), port=int(os.getenv('DB_PORT', '5432')),
          dbname=os.getenv('DB_DATABASE', 'swingtrader'),
          user=os.getenv('DB_USERNAME', 'swingtrader'),
          password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'))


def load(tf, symbols):
    table = 'tbl_prices_daily' if tf == 'day' else 'tbl_prices_weekly'
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.symbol, p.date, p.open, p.close FROM {table} p
                JOIN tbl_stock_tickers s ON s.id=p.ticker_id
                WHERE s.symbol = ANY(%s) ORDER BY p.date
            """, (symbols,))
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['symbol', 'date', 'open', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ('open', 'close'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    out = {}
    for c in ('open', 'close'):
        out[c] = df.pivot(index='date', columns='symbol', values=c).reindex(columns=symbols)
    return out


def ema_df(close, span):
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def weekly_settled_cross_down(dclose, wclose):
    w10, w20 = ema_df(wclose, 10), ema_df(wclose, 20)
    wstate = (w10 > w20).where(np.isfinite(w10) & np.isfinite(w20), False)
    settle = wclose.index + pd.Timedelta(days=7)
    cross_dn = pd.DataFrame(False, index=dclose.index, columns=dclose.columns)
    for sym in dclose.columns:
        changed = np.r_[True, settle.values[1:] != settle.values[:-1]]
        dn = (~wstate[sym]) & wstate[sym].shift(1).fillna(False) & changed
        for week in dn.index[dn.fillna(False)]:
            later = dclose.index[dclose.index >= week + pd.Timedelta(days=7)]
            if len(later):
                cross_dn.loc[later[0], sym] = True
    return cross_dn


def build_signals(dclose, wclose, max_gap=3.0, fresh_days=5):
    d10, d20 = ema_df(dclose, 10), ema_df(dclose, 20)
    valid = np.isfinite(d10) & np.isfinite(d20)
    gap = (d10 / d20 - 1) * 100
    cross_up = valid & (d10 > d20) & (d10.shift(1) <= d20.shift(1))
    gap_ok = valid & (d10 > d20) & (gap > 0) & (gap <= max_gap)
    cross_dn = weekly_settled_cross_down(dclose, wclose)

    # days since last cross-up per symbol
    since = pd.DataFrame(np.inf, index=dclose.index, columns=dclose.columns)
    for sym in dclose.columns:
        last = -999999
        arr = cross_up[sym].to_numpy()
        out = np.full(len(arr), np.inf)
        for i, v in enumerate(arr):
            if v:
                last = i
            if last >= 0:
                out[i] = i - last
        since[sym] = out

    variants = {}
    variants['S1_cross_up'] = cross_up.fillna(False)
    variants['S1_cross_up_gap'] = (cross_up & gap_ok).fillna(False)
    variants['S1_fresh_gap'] = (valid & (d10 > d20) & gap_ok & (since <= fresh_days)).fillna(False)
    variants['GapState_like_table'] = gap_ok.fillna(False)
    variants['DailyOnly_EMA10gt20'] = (valid & (d10 > d20)).fillna(False)
    variants['BH'] = pd.DataFrame(True, index=dclose.index, columns=dclose.columns)
    return variants, cross_dn


def sim_portfolio(dopen, dclose, entry_signal, exit_signal=None, hold_while=None):
    op, cl = dopen.to_numpy(float), dclose.to_numpy(float)
    ent = entry_signal.reindex(index=dclose.index, columns=dclose.columns).fillna(False).to_numpy(bool)
    if hold_while is not None:
        hold = hold_while.reindex(index=dclose.index, columns=dclose.columns).fillna(False).to_numpy(bool)
    else:
        ex = exit_signal.reindex(index=dclose.index, columns=dclose.columns).fillna(False).to_numpy(bool)
    cash = CAPITAL
    shares = np.zeros(cl.shape[1])
    eq = np.empty(len(cl)); expo = np.empty(len(cl)); trades = 0
    held = np.zeros(cl.shape[1], dtype=bool)
    for i in range(len(cl)):
        investable = np.isfinite(cl[i])
        invested = float(np.sum(shares[investable] * cl[i][investable]))
        equity = cash + invested
        eq[i] = equity
        expo[i] = invested / equity if equity > 0 else 0
        if i >= len(cl) - 1:
            break
        nxt = op[i + 1]
        ok = np.isfinite(nxt)
        if hold_while is not None:
            target = hold[i] & ok
        else:
            new_held = held.copy()
            new_held[ent[i] & ~held] = True
            new_held[ex[i] & held] = False
            held = new_held
            target = held & ok
        exit_idx = np.flatnonzero((shares > 0) & ~target & ok)
        for j in exit_idx:
            cash += shares[j] * nxt[j] * (1 - COST); shares[j] = 0; trades += 1
        entry_idx = np.flatnonzero(target & (shares == 0))
        if len(entry_idx):
            per = cash / len(entry_idx)
            for j in entry_idx:
                q = per / (nxt[j] * (1 + COST))
                if q > 0:
                    shares[j] = q; cash -= q * nxt[j] * (1 + COST); trades += 1
    return eq, expo, trades


def metrics(eq, dates):
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    peak = np.maximum.accumulate(eq)
    r = np.diff(eq) / eq[:-1]
    sd = r.std(ddof=0)
    return dict(total=eq[-1]/eq[0]-1, cagr=(eq[-1]/eq[0])**(1/years)-1,
                mdd=float((eq/peak-1).min()),
                sharpe=float(r.mean()/sd*np.sqrt(252)) if sd > 0 else 0.0,
                final=float(eq[-1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default='')
    ap.add_argument('--all-enabled', action='store_true')
    ap.add_argument('--max-gap', type=float, default=3.0)
    ap.add_argument('--fresh-days', type=int, default=5)
    ap.add_argument('--start', default='2016-01-01')
    args = ap.parse_args()

    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            if args.all_enabled:
                cur.execute("SELECT symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=false ORDER BY symbol")
                symbols = [r[0] for r in cur.fetchall()]
            elif args.symbols:
                symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
            else:
                symbols = ['EXR','CVCO','FCN','GXO','HMN','IDXX','INSM','KIM','MAS','MIDD','PG','PVH']
    finally:
        conn.close()

    d = load('day', symbols)
    w = load('week', symbols)
    dopen, dclose = d['open'], d['close']
    wclose = w['close']
    start = pd.to_datetime(args.start)
    dopen, dclose = dopen[dopen.index >= start], dclose[dclose.index >= start]
    wclose = wclose[wclose.index >= start - pd.Timedelta(days=400)]
    # align columns
    cols = [s for s in symbols if s in dclose.columns]
    dopen, dclose, wclose = dopen[cols], dclose[cols], wclose.reindex(columns=cols)

    variants, cross_dn = build_signals(dclose, wclose, args.max_gap, args.fresh_days)
    dates = list(dclose.index)
    print(f'Universe: {len(cols)} symbols, {dates[0].date()}..{dates[-1].date()}')
    print(f'Params: max_gap={args.max_gap}%, fresh_days={args.fresh_days}, cost={COST}')
    print(f'NOTE: A/B relative only; backtest returns not trustworthy.')
    print()
    hdr = f'{"VARIANT":<26} {"RET":>8} {"CAGR":>7} {"MDD":>8} {"SHARPE":>7} {"EXPO":>6} {"TRADES":>7} {"FINAL":>12}'
    print(hdr)
    for name, sig in variants.items():
        if name in ('DailyOnly_EMA10gt20', 'BH'):
            eq, expo, tr = sim_portfolio(dopen, dclose, sig, hold_while=sig)
        else:
            eq, expo, tr = sim_portfolio(dopen, dclose, sig, exit_signal=cross_dn)
        m = metrics(eq, dates)
        print(f'{name:<26} {m["total"]*100:>7.1f}% {m["cagr"]*100:>6.2f}% {m["mdd"]*100:>7.2f}% {m["sharpe"]:>7.2f} {expo.mean()*100:>5.0f}% {tr:>7} ${m["final"]:>11,.0f}')

    # Signal counts
    print('\nSignal counts (entry days, sum over symbols):')
    for name, sig in variants.items():
        if name in ('DailyOnly_EMA10gt20', 'BH'):
            continue
        c = int(sig.fillna(False).sum().sum())
        print(f'  {name:<26} {c}')


if __name__ == '__main__':
    main()
