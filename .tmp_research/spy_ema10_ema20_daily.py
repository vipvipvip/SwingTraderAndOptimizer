#!/usr/bin/env python3
"""SPY daily EMA10/EMA20 crossover vs buy-and-hold, over all DB history.

Signal (close of day t): long while EMA10 > EMA20, flat otherwise.
Fill: next session's open (no lookahead). Costs: 5 bps per side.
"""
import math
import os

import numpy as np
import pandas as pd
import psycopg2

CAPITAL = 100_000.0
COST = 0.0005
FAST, SLOW = 10, 20

DB = dict(
    host=os.getenv('DB_HOST', '127.0.0.1'),
    port=int(os.getenv('DB_PORT', '5432')),
    dbname=os.getenv('DB_DATABASE', 'swingtrader'),
    user=os.getenv('DB_USERNAME', 'swingtrader'),
    password=os.getenv('DB_PASSWORD', 'swingtrader_dev_password'),
)


def load_spy(symbol='SPY'):
    conn = psycopg2.connect(**DB)
    try:
        q = """
            SELECT d.date, d.open, d.close
            FROM tbl_prices_daily d
            JOIN tbl_stock_tickers s ON s.id = d.ticker_id
            WHERE s.symbol = %s
            ORDER BY d.date ASC
        """
        cur = conn.cursor()
        cur.execute(q, (symbol.upper(),))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['date', 'open', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    for c in ('open', 'close'):
        df[c] = df[c].astype(float)
    df['open'] = np.where(df['open'] > 0, df['open'], df['close'])
    return df


def ema(values, span):
    return pd.Series(values, dtype=float).ewm(
        span=span, adjust=False, min_periods=span).mean().to_numpy()


def simulate(df):
    dates = df['date'].tolist()
    opn = df['open'].to_numpy()
    close = df['close'].to_numpy()
    e10, e20 = ema(close, FAST), ema(close, SLOW)
    n = len(df)

    cash, shares, entry_px, entry_i = CAPITAL, 0.0, 0.0, None
    equity, exposure, trades = [], [], []
    for i in range(n):
        equity.append(cash + shares * close[i])
        exposure.append(shares * close[i] / equity[-1] if equity[-1] else 0.0)
        if not (np.isfinite(e10[i]) and np.isfinite(e20[i])) or i >= n - 1:
            continue
        want_long = e10[i] > e20[i]
        fill = opn[i + 1]
        if want_long and shares == 0 and cash > 0:
            shares = cash / (fill * (1 + COST))
            cash = 0.0
            entry_px, entry_i = fill, i + 1
            trades.append([dates[i], dates[i + 1], fill, None, None, False])
        elif not want_long and shares > 0:
            proceeds = shares * fill * (1 - COST)
            t = trades[-1]
            t[3], t[4], t[5] = dates[i + 1], fill, True
            cash += proceeds
            shares = 0.0
    if shares > 0:
        t = trades[-1]
        t[3], t[4] = dates[-1], close[-1]
    return dates, np.array(equity), np.array(exposure), trades


def flat_periods(dates, trades):
    dates_idx = {d: i for i, d in enumerate(dates)}
    spans = []
    start = dates[0]
    for j, t in enumerate(trades):
        entry = t[1]
        if entry > start:
            spans.append((start, entry, 'warmup' if j == 0 else 'signal'))
        if not t[5]:
            break
        start = t[3]
    if start < dates[-1]:
        spans.append((start, dates[-1], 'signal'))
    return [(a, b, kind, dates_idx[b] - dates_idx[a])
            for a, b, kind in spans]


def buy_hold(df):
    close = df['close'].to_numpy()
    shares = CAPITAL / (close[0] * (1 + COST))
    return shares * close, shares * close


def metrics(dates, equity, exposure, trades):
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    rets = np.diff(equity) / equity[:-1]
    peak = np.maximum.accumulate(equity)
    sd = float(rets.std(ddof=0))
    closed = [t for t in trades if t[3] is not None]
    return dict(
        total=equity[-1] / CAPITAL - 1,
        cagr=(equity[-1] / CAPITAL) ** (1 / years) - 1,
        mdd=float((equity / peak - 1).min()),
        sharpe=float(rets.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
        trades=len(closed),
        win=sum(1 for t in closed if t[4] > t[2]) / len(closed) if closed else 0.0,
        expo=float(np.mean(exposure)),
        final=float(equity[-1]),
    )


def show(label, m):
    print(f'  {label:<22} ret {m["total"]*100:>9.1f}%  CAGR {m["cagr"]*100:>6.2f}%  '
          f'MDD {m["mdd"]*100:>7.2f}%  Sharpe {m["sharpe"]:>5.2f}  '
          f'trades {m["trades"]:>4}  win {m["win"]*100:>4.0f}%  '
          f'expo {m["expo"]*100:>3.0f}%  final ${m["final"]:>12,.0f}')


def main():
    df = load_spy()
    if df.empty:
        raise SystemExit('no SPY daily data in DB')
    dates, eq, expo, trades = simulate(df)
    bh_eq, _ = buy_hold(df)

    print(f'=== SPY EMA{FAST}/EMA{SLOW} daily crossover vs Buy & Hold ===')
    print(f'Window: {dates[0].date()} -> {dates[-1].date()}  '
          f'({len(df)} daily bars, all DB history)')
    print(f'Costs: {COST*100:.2f}% per side, fills at next open, '
          f'start capital ${CAPITAL:,.0f}')
    print()
    show('EMA10/20 long-flat', metrics(dates, eq, expo, trades))
    show('SPY Buy & Hold', metrics(dates, bh_eq, np.ones(len(df)), []))

    # Cash-equity curve comparison at a few horizons.
    print('\nEquity checkpoints (strategy vs B&H):')
    for dt in ('2016-12-30', '2020-03-23', '2020-12-31', '2022-12-30',
               '2024-12-31', str(dates[-1].date())):
        targets = df.index[df['date'] == pd.Timestamp(dt)]
        if len(targets) == 0:
            targets = df.index[df['date'] <= pd.Timestamp(dt)]
            if len(targets) == 0:
                continue
            i = targets[-1]
            dt = str(df['date'].iloc[i].date())
        else:
            i = targets[0]
        print(f'  {dt}:  ${eq[i]:>12,.0f}  vs  ${bh_eq[i]:>12,.0f}')

    print('\nCash (out-of-market) periods, exit fill -> next entry fill:')
    spans = flat_periods(dates, trades)
    total_days = 0
    for a, b, kind, sess in spans:
        total_days += (b - a).days
        print(f'  {a.date()} -> {b.date()}  '
              f'{(b-a).days:>3} cal days, {sess:>3} sessions  [{kind}]')
    print(f'  {len(spans)} stretches, {total_days} calendar days out '
          f'({total_days/(dates[-1]-dates[0]).days*100:.0f}% of window)')

    print('\nNOTE: research backtest only — idealized fills, no taxes/dividends. '
          'Use A/B comparison, not absolute return, per operating rules.')


if __name__ == '__main__':
    main()
