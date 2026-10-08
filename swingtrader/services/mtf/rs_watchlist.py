"""Relative-strength WATCHLIST (research, read-only) — not a trading signal.

Composite = 0.5*pct_rank(13w ret) + 0.3*pct_rank(26w ret) + 0.2*pct_rank(52w ret), ranked across the
liquid stock universe (close >= $10, 26w avg dollar volume >= $5M) on the last SETTLED weekly bar.
Back-tests (2026-10-07, survivor-biased, A/B only) showed the top decile has a higher hit rate than
average but NO edge versus volatility-matched peers, so this narrows ~1,400 names to a review list for
chart inspection; it does not predict. Never wire it to orders without user sign-off.

Flags: BASE = fresh cross to rank>=0.8 after a weak base (mean rank over t-13..t-2 < 0.5);
       FRESH = weekly EMA10 crossed above SMA40 within the last 8 weeks.

Usage: python3 rs_watchlist.py [--all] [--min-rank 0.8] [--csv out.csv]
Default shows only names with BOTH flags (PANW-style), freshest cross first; --all lists every name at rank >= min-rank.
"""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

import config


def load():
    c = psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                         user=config.DB_USER, password=config.DB_PASS)
    q = lambda s: pd.read_sql(s, c)
    names = q("select symbol, company_name, is_etf from tbl_stock_tickers where enabled")
    w = q("select k.symbol sym, p.date, p.high, p.low, p.close, p.volume from tbl_prices_weekly p "
          "join tbl_stock_tickers k on k.id=p.ticker_id where k.enabled and not k.is_etf order by 1,2")
    held = set(q("select symbol from mtf_positions where quantity>0").symbol)
    c.close()
    for col in ('high', 'low', 'close', 'volume'):
        w[col] = w[col].astype(float)
    w['date'] = pd.to_datetime(w['date'])
    return w, names.set_index('symbol').company_name.to_dict(), held


def daily_macd_hist(symbols):
    """Daily MACD(10/40/400) histogram on the last SETTLED daily bar (date < today), per symbol.
    hist = (EMA10-EMA40) - EMA400(EMA10-EMA40). Needs >= 440 daily bars to be seeded; else NaN."""
    c = psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                         user=config.DB_USER, password=config.DB_PASS)
    q = ("select k.symbol sym, p.date, p.close from tbl_prices_daily p join tbl_stock_tickers k on k.id=p.ticker_id "
         "where k.symbol = any(%s) and p.date <= %s order by 1,2")
    # settled daily bar: today's bar only counts once the session is over (>= 16:30 ET), else yesterday's
    now = datetime.now(ZoneInfo('America/New_York'))
    asof = now.date() if now.hour * 60 + now.minute >= 16 * 60 + 30 else now.date() - timedelta(days=1)
    d = pd.read_sql(q, c, params=(list(symbols), asof)); c.close()
    d['close'] = d.close.astype(float)
    out = {}
    for sym, g in d.groupby('sym'):
        if len(g) < 440:
            out[sym] = np.nan
            continue
        m = g.close.ewm(span=10, adjust=False).mean() - g.close.ewm(span=40, adjust=False).mean()
        out[sym] = (m - m.ewm(span=400, adjust=False).mean()).iloc[-1]
    return pd.Series(out)


def build(w):
    # settled weeks only: bar_date + 7 <= today (same predicate as emasma_core.settled_weekly_idx)
    w = w[w.date <= pd.Timestamp(date.today() - timedelta(days=7))]
    px, hi, lo, vol = (w.pivot(index='date', columns='sym', values=c) for c in ('close', 'high', 'low', 'volume'))
    dv = (px * vol).rolling(26).mean()
    liq = (px >= 10) & (dv >= 5e6)
    rk = lambda r: r.where(liq).rank(axis=1, pct=True)
    rank = (0.5 * rk(px.pct_change(13)) + 0.3 * rk(px.pct_change(26)) + 0.2 * rk(px.pct_change(52))).rank(axis=1, pct=True)
    base = rank.shift(2).rolling(12).mean()
    base_ev = (rank >= .8) & (rank.shift(1) < .8) & (base < .5)
    ema = px.apply(lambda s: s.dropna().ewm(span=config.EMA_PERIOD, adjust=False).mean()).reindex(px.index)
    sma = px.rolling(config.SMA_PERIOD).mean()
    up = (ema > sma) & sma.notna()
    cross = up & ~up.shift(1, fill_value=False) & sma.shift(1).notna()
    pos = pd.DataFrame(np.where(cross, np.arange(len(px))[:, None], np.nan), index=px.index, columns=px.columns).ffill()
    age = pd.DataFrame(np.arange(len(px))[:, None] - pos.values, index=px.index, columns=px.columns).where(up)
    base_age = pd.DataFrame(np.where(base_ev, np.arange(len(px))[:, None], np.nan), index=px.index, columns=px.columns).ffill()
    base_age = pd.DataFrame(np.arange(len(px))[:, None] - base_age.values, index=px.index, columns=px.columns)
    last = px.index[-1]
    d = pd.DataFrame({
        'rank': rank.loc[last], 'prior_base': base.loc[last], 'wks_since_cross': age.loc[last],
        'wks_since_base_brk': base_age.loc[last],
        'close': px.loc[last], 'from_52w_hi%': (px.loc[last] / px.rolling(52).max().loc[last] - 1) * 100,
        'r13%': px.pct_change(13).loc[last] * 100, 'r26%': px.pct_change(26).loc[last] * 100,
        'r52%': px.pct_change(52).loc[last] * 100,
        'vol4/26': vol.rolling(4).mean().loc[last] / vol.rolling(26).mean().loc[last],
        'range13%': (hi.rolling(13).max().loc[last] / lo.rolling(13).min().loc[last] - 1) * 100,
    })
    d['FRESH'] = d.wks_since_cross <= 8
    d['BASE'] = d.wks_since_base_brk <= 8
    return d.dropna(subset=['rank']), last


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-rank', type=float, default=0.8)
    ap.add_argument('--csv')
    ap.add_argument('--no-daily-macd', action='store_true', help='do not require daily MACD(10/40/400) histogram > 0')
    ap.add_argument('--slack', action='store_true', help='post the BOTH-flags list to the Slack webhook (config.SLACK_WEBHOOK_URL)')
    ap.add_argument('--all', action='store_true', help='list every name at rank>=min-rank, not just FRESH & BASE')
    a = ap.parse_args()
    w, names, held = load()
    d, last = build(w)
    prev, _ = build(w[w.date < last])          # same rules, one settled week earlier (stateless)
    prev_set = set(prev.index[prev.FRESH & prev.BASE & (prev['rank'] >= a.min_rank)])
    d = d[d['rank'] >= a.min_rank]
    n_all, n_fresh, n_base = len(d), int(d.FRESH.sum()), int(d.BASE.sum())
    d = d.sort_values('rank', ascending=False)
    if not a.all:
        d = d[d.FRESH & d.BASE].sort_values(['wks_since_cross', 'rank'], ascending=[True, False])
    n_before = len(d)
    if not a.all and not a.no_daily_macd:
        dm = daily_macd_hist(d.index[d.FRESH & d.BASE])
        d['dMACD'] = dm.reindex(d.index)
        dropped = [t for t in d.index[d.FRESH & d.BASE] if not d.at[t, 'dMACD'] > 0]
        d = d.drop(index=dropped)
        print(f'daily MACD(10/40/400) hist > 0 required: kept {len(d)}, removed {len(dropped)}: ' + (', '.join(dropped) or 'none'))
    d['held'] = d.index.isin(held)
    d['name'] = [str(names.get(s) or '')[:24] for s in d.index]
    pd.set_option('display.width', 250)
    cols = ['name', 'rank', 'prior_base', 'wks_since_cross', 'close', 'from_52w_hi%', 'r13%', 'r26%', 'r52%', 'vol4/26', 'range13%', 'FRESH', 'BASE', 'held']
    if 'dMACD' in d: cols.insert(-3, 'dMACD')
    print(f'RS watchlist — settled week {last.date()} — rank>={a.min_rank}: {n_all} names '
          f'(FRESH {n_fresh}, BASE {n_base}); showing {len(d)}' + ('' if a.all else ' with BOTH flags, freshest cross first'))
    print('WATCHLIST ONLY — no predictive edge vs volatility-matched peers in backtests.')
    print(d[cols].round(2).to_string())
    if not a.all:
        new = [t for t in d.index if t not in prev_set]
        print(f'\nNEW since {_.date()} ({len(new)}): ' + (', '.join(new) if new else 'none'))
        print('\n' + ','.join(d.index))
        if a.slack:
            grp = lambda lo_, hi_: ', '.join(f"{t}{'*' if t in held else ''}" for t in d.index[(d.wks_since_cross >= lo_) & (d.wks_since_cross <= hi_)])
            txt = (f"*[RS-Watchlist]* settled week {last.date()} — _watchlist only; no proven edge vs volatility-matched peers; not a trade signal_\n"
                   f"Fresh weekly EMA10/SMA40 cross + weak-base breakout, rank ≥ {a.min_rank}, daily MACD(10/40/400) hist > 0: *{len(d)}* names  (* = held in MTF)\n"
                   f"• 0–3 wks: {grp(0, 3)}\n• 4–6 wks: {grp(4, 6)}\n• 7–8 wks: {grp(7, 8)}\n"
                   f"*NEW since {_.date()} ({len(new)}):* {', '.join(new) or 'none'}\n"
                   f"`{','.join(d.index)}`")
            r = requests.post(config.SLACK_WEBHOOK_URL, json={'text': txt}, timeout=30)
            print(f'\nSlack HTTP {r.status_code}')
    if a.csv:
        d[cols].round(3).to_csv(a.csv)
