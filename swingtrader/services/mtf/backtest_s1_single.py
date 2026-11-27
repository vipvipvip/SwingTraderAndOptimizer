#!/usr/bin/env python3
"""A/B: fast daily EMA10/20 entry, slow settled-weekly EMA10/20 exit.

Entry = daily EMA10 crosses up through EMA20 (fill next open).
Exit  = weekly EMA10 crosses down through EMA20 on a SETTLED weekly bar
        (bar_date + 7 <= today), fill next daily open.
Baselines: daily-only EMA10/20 long/flat, and B&H. Same 5bp costs.
Usage: python3 spy_ema_daily_entry_weekly_exit.py [SYMBOL]
"""
import os
import sys

import numpy as np
import pandas as pd
import psycopg2

COST = 0.0005
CAPITAL = 100_000.0
DB = dict(host=os.getenv('DB_HOST', '127.0.0.1'),
          port=int(os.getenv('DB_PORT', '5432')),
          dbname=os.getenv('DB_DATABASE', 'swingtrader'),
          user=os.getenv('DB_USERNAME', 'swingtrader'),
          password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'))


def load(tf, symbol):
    table = 'tbl_prices_daily' if tf == 'day' else 'tbl_prices_weekly'
    conn = psycopg2.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT d.date, d.open, d.close FROM {table} d
            JOIN tbl_stock_tickers s ON s.id = d.ticker_id
            WHERE s.symbol = %s ORDER BY d.date ASC
        """, (symbol,))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['date', 'open', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ('open', 'close'):
        df[c] = df[c].astype(float)
    return df


def ema(v, span):
    return pd.Series(v, dtype=float).ewm(span=span, adjust=False,
                                          min_periods=span).mean().to_numpy()


def metrics(eq, dates):
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    peak = np.maximum.accumulate(eq)
    r = np.diff(eq) / eq[:-1]
    sd = r.std(ddof=0)
    return dict(total=eq[-1]/eq[0]-1, cagr=(eq[-1]/eq[0])**(1/years)-1,
                mdd=float((eq/peak-1).min()),
                sharpe=float(r.mean()/sd*np.sqrt(252)) if sd > 0 else 0.0,
                final=float(eq[-1]))


def show(label, m, expo, trades):
    print(f'  {label:<26} ret {m["total"]*100:>8.1f}%  CAGR {m["cagr"]*100:>6.2f}%  '
          f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}  '
          f'expo {expo*100:>3.0f}%  trades {trades:>3}  final ${m["final"]:>11,.0f}')


def sim(dates, opn, close, want):
    cash, shares = CAPITAL, 0.0
    eq, exposure, trades = [], [], 0
    for i in range(len(dates)):
        eq.append(cash + shares * close[i])
        exposure.append(shares * close[i] / eq[-1] if eq[-1] else 0.0)
        if i < len(dates) - 1:
            if want[i] and shares == 0 and cash > 0:
                shares = cash / (opn[i+1]*(1+COST)); cash = 0.0; trades += 1
            elif not want[i] and shares > 0:
                cash = shares * opn[i+1]*(1-COST); shares = 0.0
    return np.array(eq), np.array(exposure), trades


def main():
    symbol = (sys.argv[1] if len(sys.argv) > 1 else 'SPY').upper()
    d, w = load('day', symbol), load('week', symbol)
    d10, d20 = ema(d['close'], 10), ema(d['close'], 20)
    w10, w20 = ema(w['close'], 10), ema(w['close'], 20)
    wstate = np.where(np.isfinite(w10) & np.isfinite(w20), w10 > w20, False)
    settle = (w['date'] + pd.Timedelta(days=7)).to_numpy()
    wdates = w['date'].to_numpy()

    dd = d['date'].to_numpy()
    # latest settled weekly bar index as of each daily date (and prior day)
    ji = np.searchsorted(settle, dd, side='right') - 1
    jprev = np.searchsorted(settle, dd - np.timedelta64(1, 'D'), side='right') - 1

    valid_d = np.isfinite(d10) & np.isfinite(d20)
    cross_up = valid_d & (d10 > d20) & (np.roll(d10, 1) <= np.roll(d20, 1))
    cross_dn_w = np.zeros(len(d), dtype=bool)
    for i in range(len(d)):
        j = ji[i]
        if j >= 1 and j != jprev[i] and not wstate[j] and wstate[j-1]:
            cross_dn_w[i] = True

    dates = list(d['date'])
    opn, close = d['open'].to_numpy(), d['close'].to_numpy()
    n = len(d)

    # Strategy 1: enter on daily cross-up, exit on settled weekly cross-down.
    held = False
    want = np.zeros(n, dtype=bool)
    for i in range(n):
        if not held and cross_up[i]:
            held = True
        elif held and cross_dn_w[i]:
            held = False
        want[i] = held

    # Baseline: daily-only state (long while EMA10>EMA20).
    daily_state = valid_d & (d10 > d20)

    # B&H.
    bh = np.ones(n, dtype=bool)

    print(f'=== {symbol} ===')
    print(f'Window: {dates[0].date()} -> {dates[-1].date()} ({n} daily bars, '
          f'{len(w)} weekly bars)')
    print(f'Weekly bars settle at bar_date+7d; last weekly bar '
          f'{pd.Timestamp(wdates[-1]).date()} settles {pd.Timestamp(settle[-1]).date()}')
    print(f'Daily cross-ups: {cross_up.sum()}, weekly settled cross-downs: {cross_dn_w.sum()}\n')
    print(f'{"STRATEGY":<28}{"RET":>9}{"CAGR":>9}{"MDD":>9}{"SHARPE":>9}{"EXPO":>7}{"TRADES":>8}')
    for label, sig in (('S1 daily-in / weekly-out', want),
                       ('Daily-only EMA10/20', daily_state),
                       (f'{symbol} B&H', bh)):
        eq, expo, tr = sim(dates, opn, close, sig)
        show(label, metrics(eq, dates), expo.mean(), tr)

    # Show what the fast entry bought around the two crashes.
    e1, _, _ = sim(dates, opn, close, want)
    e2, _, _ = sim(dates, opn, close, daily_state)
    print('\nS1 round trips (entry fill -> exit fill, weekly bar that triggered exit):')
    held = False
    entry_i = None
    for i in range(n):
        if not held and cross_up[i]:
            held, entry_i = True, i
        elif held and cross_dn_w[i]:
            print(f'  {dates[entry_i+1].date()} -> {dates[i+1].date()}  '
                  f'({(dates[i+1]-dates[entry_i+1]).days} cal days)  '
                  f'weekly bar {pd.Timestamp(wdates[ji[i]]).date()}')
            held = False
    if held:
        print(f'  {dates[entry_i+1].date()} -> OPEN (still long)')

    print('\nEquity around key windows (S1 vs daily-only):')
    for dt in ('2020-03-23', '2020-12-31', '2025-04-09', '2025-12-31',
               str(dates[-1].date())):
        idx = np.searchsorted(dd, np.datetime64(dt), side='right') - 1
        if idx >= 0:
            print(f'  {dd[idx].astype("datetime64[D]")}: S1 ${e1[idx]:>11,.0f}  '
                  f'daily-only ${e2[idx]:>11,.0f}')


if __name__ == '__main__':
    main()
