#!/usr/bin/env python3
"""Weekly EMA10/SMA40 take-off scanner.

On settled WEEKLY bars (tbl_scanner_tickers, Monday-anchored), find stock names
that had an EMA10>SMA40 bullish crossover within the last MAX_SINCE_CROSS_WEEKS
weeks and are still above, ranked by the take-off odds score (V-reversal +
expansion signature). Prints an alphabetized comma-delimited ticker list with
freshness (calendar days since the crossover week) and posts a Slack summary.

Ad-hoc:
    python3 weekly_takeoff.py            # full run (prints + Slack)
    python3 weekly_takeoff.py --no-slack # print only, no Slack

Output format (stdout):
    Line 1  comma list, alphabetical (paste into TOS Watchlist)
    Line 2.. alphabetical: SYMBOL days-since-cross
"""
import argparse
import sys
from datetime import date

import numpy as np
import pandas as pd
import requests

import config
import db as db_module

EMA = config.EMA_PERIOD
SMA = config.SMA_PERIOD
W = config.WEIGHTS

NY = None  # freshness uses calendar days; anchor date kept in data


def ewm(close, span):
    return close.ewm(span=span, adjust=False).mean()


def scoring(sym, g, last_date):
    """Compute take-off features at the LAST settled weekly bar and score."""
    g = g.copy().reset_index(drop=True)
    g['e10'] = ewm(g['close'], EMA)
    g['s40'] = g['close'].rolling(SMA).mean()
    n = len(g) - 1
    if pd.isna(g['s40'][n]) or pd.isna(g['e10'][n]):
        return None
    above = g['e10'][n] >= g['s40'][n]
    if not above:
        return None
    cross_idx = g.index[(g['e10'] >= g['s40']) & (g['e10'].shift(1) < g['s40'].shift(1))]
    if len(cross_idx) == 0:
        return None
    rc = g['date'][cross_idx[-1]].date()
    since_days = (last_date - rc).days
    since_weeks = since_days / 7.0
    if since_weeks > config.MAX_SINCE_CROSS_WEEKS:
        return None

    g['r'] = g['close'].pct_change()
    pre = g.loc[max(0, n - 8):n - 1]

    feat = {
        'std20': g['r'].loc[max(0, n - 20):n - 1].std() * 100,
        'maxrange8': float(pre['high'].div(pre['low']).max()),
        'expcount': int((pre.tail(4)['high'].div(pre.tail(4)['low']) >= 1.10).sum()),
        'atr': float(pre.tail(20)['high'].sub(pre.tail(20)['low']).mean() / g['close'][n] * 100),
        'dip8': (1 - pre['low'].min() / g['close'][n]) * 100,
        'rng_c': float(g['high'][n] / g['low'][n]),
        'c2s': float(g['close'][n] / g['s40'][n]),
        'ret20': (g['close'][n] / g['close'][max(0, n - 20)] - 1) * 100,
        'low52': float(g['close'][n] / g['close'].loc[max(0, n - 52):n - 1].min()),
    }
    score = sum(W[k] * feat[k] for k in W)
    return dict(sym=sym, close=float(g['close'][n]), score=score,
                since_days=int(since_days), since_weeks=round(since_weeks, 1),
                features=feat)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-slack', action='store_true', help='print only, skip Slack')
    parser.add_argument('--top', type=int, default=config.TOP_N, help='max names to report')
    args = parser.parse_args()

    conn = db_module.get_conn()
    try:
        data = db_module.load_weekly_all(conn)
    finally:
        conn.close()
    if not data:
        print('[weekly_takeoff] no weekly data loaded'); sys.exit(1)

    last_date = max(d['df']['date'].max() for d in data.values()).date()

    hits = []
    for d in data.values():
        r = scoring(d['symbol'], d['df'], last_date)
        if r is None:
            continue
        hits.append(r)

    hits.sort(key=lambda x: x['score'], reverse=True)
    top = hits[:args.top]
    top.sort(key=lambda x: x['sym'])  # alphabetical for output

    # stdout lines
    csl = ', '.join(r['sym'] for r in top)
    print(f"[weekly_takeoff] {last_date} last settled week; "
          f"{len(top)}/{len(hits)} candidates (weekly EMA10>SMA40 cross <= 12wk, still above)")
    print(csl)
    for r in top:
        print(f"  {r['sym']:<6} {r['since_days']:>4}d ago  (cross week {r['since_weeks']}w)  "
              f"dip8={r['features']['dip8']:.0f}%  close={r['close']:.2f}")

    if args.no_slack or not config.SLACK_WEBHOOK_URL:
        return 0

    lines = [f'*[WEEKLY-TAKEOFF]* {last_date} — top {len(top)} (EMA10>SMA40 cross '
             f'≤{config.MAX_SINCE_CROSS_WEEKS}wk, still above, settled weekly)']
    lines.append(f'{csl}')
    lines.append('```' + '\n'.join(
        f"{r['sym']:<6} {r['since_days']:>4}d since CO" for r in top) + '```')
    msg = '\n'.join(lines)
    try:
        rp = requests.post(config.SLACK_WEBHOOK_URL,
                           json={'text': msg}, timeout=30)
        rp.raise_for_status()
        print('[Slack] sent')
    except Exception as e:
        print(f'[Slack] error: {e}')
    return 0


if __name__ == '__main__':
    sys.exit(main())