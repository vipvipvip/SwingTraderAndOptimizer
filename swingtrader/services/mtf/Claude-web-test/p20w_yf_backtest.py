#!/usr/bin/env python3
"""CoreEW P20w on Yahoo ADJUSTED closes, 2004 -> today, plus crash-window tests.

Place in swingtrader/services/mtf/ (next to backtest_trio_ew.py) and run with any
venv that has yfinance + pandas + numpy (e.g. portfolio-backtest/venv):

    python3 p20w_yf_backtest.py                 # download (cached) + all tests
    python3 p20w_yf_backtest.py --refresh       # force a fresh Yahoo download
    python3 p20w_yf_backtest.py --span 10,20,30 # neighbouring spans too
    python3 p20w_yf_backtest.py --start 2016-01-04 --outdir p20w_yf_parity
                                                # EMA seeded 2016 like the DB: should land
                                                # near the DB result (+362.8%, MaxDD 19.2%)

Parity with live / the repo harness
-----------------------------------
* Prices: Yahoo 'Adj Close' (split + dividend adjusted), requested explicitly with
  auto_adjust=False — the same convention as the DB's Alpaca adjustment='all'.
* Weekly bars: Monday-dated, close = last trading day's close of that week. Checked
  against the DB export: identical to Alpaca's native weekly bars on every settled week.
* Signal: port of PHP replayLegEmaSeries() — per leg, settled weeks only
  (week + 7 <= today), ewm(span, adjust=False) seeded at the first weekly close,
  long while close > EMA. A week-W state is actionable from the next Monday.
* Sim, flag alignment, rebalance mask: run_sim / settled_weekly_ref / pos_of are
  loaded VERBATIM from backtest_trio_ew.py (not re-typed): decision Monday, fill at
  the next session's close, 5 bp/side, OFF legs in cash at 0%, ON legs to equal
  weight every week.

Window tests use the signal computed on the FULL history (EMA warmed since 2004),
i.e. "the strategy was already running on that date"; capital starts in cash on the
window's first day and is deployed per the live state on the next session.
"""
import argparse
import ast
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

SYMS = ['QQQ', 'VTI', 'VTV']
COST = 0.0005
CAPITAL = 100000.0
HERE = os.path.dirname(os.path.abspath(__file__))

# Start shortly BEFORE each peak, so the window includes the whole fall.
CRASH_WINDOWS = [
    ('GFC (pre-peak)',       '2007-10-01'),
    ('GFC (pre-Lehman)',     '2008-09-02'),
    ('2010 flash crash',     '2010-04-15'),
    ('2011 US downgrade',    '2011-07-01'),
    ('2015-16 selloff',      '2015-07-15'),
    ('2018 Q4',              '2018-09-20'),
    ('COVID',                '2020-02-14'),
    ('2022 bear',            '2021-12-27'),
    ('2025 tariffs',         '2025-02-14'),
]
# Out-of-sample split: P20w was selected on 2016+, so 2004-2015 is genuinely unseen.
REGIMES = [
    ('2004-2015 (out-of-sample)', '2004-01-01', '2015-12-31'),
    ('2016-today (selection window)', '2016-01-04', None),
    ('2004-today (full)', '2004-01-01', None),
]


def load_harness(path):
    """Pull run_sim/settled_weekly_ref/pos_of verbatim from the repo harness."""
    if not os.path.exists(path):
        sys.exit(f'harness not found: {path} (use --harness)')
    tree = ast.parse(open(path).read())
    ns = {'np': np, 'date': date, 'timedelta': timedelta, 'CAPITAL': CAPITAL}
    want = {'run_sim', 'settled_weekly_ref', 'pos_of'}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in want:
            exec(compile(ast.Module([n], []), path, 'exec'), ns)
    missing = want - ns.keys()
    if missing:
        sys.exit(f'harness is missing {missing}')
    return ns


def load_prices(cache, start, refresh):
    if os.path.exists(cache) and not refresh:
        adj = pd.read_csv(cache, index_col=0, parse_dates=True)
        print(f'Loaded cached Adj Close: {cache}')
    else:
        try:
            import yfinance as yf
        except ImportError:
            sys.exit('pip install yfinance  (or use a venv that has it)')
        print(f'Downloading {SYMS} Adj Close from Yahoo since {start} ...')
        df = yf.download(SYMS, start=start, end=(date.today() + timedelta(days=1)).isoformat(),
                         auto_adjust=False, actions=False, progress=False,
                         group_by='column', threads=False)
        if df is None or df.empty:
            sys.exit('Yahoo returned no data')
        if isinstance(df.columns, pd.MultiIndex):
            if 'Adj Close' not in df.columns.get_level_values(0):
                sys.exit(f'No Adj Close column in Yahoo response: {sorted(set(df.columns.get_level_values(0)))}')
            adj = df['Adj Close']
        else:
            sys.exit('Unexpected single-level columns from yfinance')
        adj = adj[SYMS]
        adj.index = pd.to_datetime(adj.index).tz_localize(None)
        adj.to_csv(cache)
        print(f'Saved {cache}')
    adj = adj[SYMS].astype(float)
    adj = adj.loc[pd.Timestamp(start):]           # --start also slices a cached file
    first_common = adj.dropna().index[0]
    adj = adj.loc[first_common:]
    gaps = adj.isna().sum()
    if gaps.any():
        print(f'WARNING: dropping {int(adj.isna().any(axis=1).sum())} sessions with a missing leg: {gaps.to_dict()}')
        adj = adj.dropna()
    return adj


def weekly_settled(adj, today):
    wk = adj.index - pd.to_timedelta(adj.index.dayofweek, unit='D')
    W = adj.groupby(wk).last()
    W.index.name = 'week'
    return W[[(d.date() + timedelta(days=7)) <= today for d in W.index]]


def leg_states(W, span):
    alpha = 2.0 / (span + 1.0)
    out = {}
    for s in SYMS:
        c = W[s].to_numpy()
        ema = np.empty_like(c)
        ema[0] = c[0]
        for i in range(1, len(c)):
            ema[i] = alpha * c[i] + (1 - alpha) * ema[i - 1]
        out[s] = c > ema
    return out


def daily_flags(H, daily_dates, wdates, states):
    pos = H['settled_weekly_ref'](daily_dates, wdates)
    return {s: np.array([bool(states[s][j]) if j >= 0 else False for j in pos]) for s in SYMS}


def reb_mask(H, daily_dates, wdates):
    w0 = H['pos_of'](daily_dates, wdates)
    reb = np.zeros(len(daily_dates), dtype=bool)
    reb[0] = True
    reb[1:] = w0[1:] != w0[:-1]
    return reb


def run_window(H, dates, closes, flags, reb, i0, i1, tag='P20w'):
    sl = slice(i0, i1 + 1)
    d = dates[sl]
    c = {s: closes[s][sl] for s in SYMS}
    r = reb[sl].copy()
    r[0] = True
    allon = {s: np.ones(len(d), dtype=bool) for s in SYMS}
    out = {}
    eq, ed, b, s_ = H['run_sim'](d, c, {s: flags[s][sl] for s in SYMS}, r, COST)
    out[tag] = (np.r_[CAPITAL, eq], [d[0]] + ed, b + s_)
    eq, ed, b, s_ = H['run_sim'](d, c, allon, r, COST)
    out['A: EW weekly'] = (np.r_[CAPITAL, eq], [d[0]] + ed, b + s_)
    bh = np.array([sum(CAPITAL / 3 * c[s][k] / c[s][0] for s in SYMS) for k in range(len(d))])
    out['C: EW buy&hold'] = (bh, list(d), 0)
    return out


def metrics(eq, dts):
    eq = np.asarray(eq, float)
    yrs = max((dts[-1] - dts[0]).days / 365.25, 1e-9)
    r = eq[1:] / eq[:-1] - 1
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    k = int(dd.argmax())
    pk = int(eq[:k + 1].argmax())
    rec = next((j for j in range(k, len(eq)) if eq[j] >= eq[pk]), None)
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1
    return dict(ret=eq[-1] / eq[0] - 1, cagr=cagr, dd=dd.max(),
                sharpe=(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
                calmar=cagr / dd.max() if dd.max() > 0 else np.nan,
                dd_peak=dts[pk], dd_trough=dts[k],
                recov_days=(dts[rec] - dts[pk]).days if rec is not None else None)


def fmt_row(name, m, extra=''):
    rec = f"{m['recov_days']}d" if m['recov_days'] is not None else 'not yet'
    return (f"  {name:<17}{m['ret']*100:>9.1f}%{m['cagr']*100:>7.1f}%{m['dd']*100:>7.1f}%"
            f"{m['sharpe']:>7.2f}{m['calmar']:>7.2f}  {str(m['dd_trough']):<11}{rec:>9}{extra}")


HDR = (f"  {'':<17}{'Return':>10}{'CAGR':>7}{'MaxDD':>7}{'Sharpe':>7}{'Calmar':>7}"
       f"  {'DD trough':<11}{'recovery':>9}")


def idx_at_or_after(dates, d):
    for i, x in enumerate(dates):
        if x >= d:
            return i
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--start', default='2004-01-01')
    ap.add_argument('--span', default='20', help='comma list of EMA spans (live = 20)')
    ap.add_argument('--cache', default=os.path.join(HERE, 'trio_yf_adjclose.csv'))
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--harness', default=os.path.join(HERE, 'backtest_trio_ew.py'))
    ap.add_argument('--outdir', default=os.path.join(HERE, 'p20w_yf_out'))
    ap.add_argument('--today', default=None, help='override "today" for the settled-week rule (YYYY-MM-DD)')
    args = ap.parse_args()

    H = load_harness(args.harness)
    today = date.fromisoformat(args.today) if args.today else date.today()
    adj = load_prices(args.cache, args.start, args.refresh)
    dates = [d.date() for d in adj.index]
    closes = {s: adj[s].to_numpy() for s in SYMS}
    W = weekly_settled(adj, today)
    wdates = [d.date() for d in W.index]
    reb = reb_mask(H, dates, wdates)
    os.makedirs(args.outdir, exist_ok=True)

    print(f'\nData: {dates[0]} -> {dates[-1]}  ({len(dates)} sessions, {len(W)} settled weeks, '
          f'EMA seeded {wdates[0]})')
    print(f'Cost {COST*1e4:.0f} bp/side, cash at 0%, fill = next session close after Monday decision\n')

    summary = []
    for span in [int(x) for x in args.span.split(',') if x.strip()]:
        states = leg_states(W, span)
        flags = daily_flags(H, dates, wdates, states)
        tag = f'P{span}w'
        print('=' * 104)
        print(f'{tag}  — flips: ' + ', '.join(f'{s}={int((np.diff(flags[s].astype(int)) != 0).sum())}' for s in SYMS)
              + f"  | avg legs long {np.mean(sum(flags[s] for s in SYMS)):.2f}/3"
              + ' | current state: ' + ', '.join(s + '=' + ('ON' if states[s][-1] else 'off') for s in SYMS))

        # ---- regimes: out-of-sample vs selection window vs full
        for label, a, b in REGIMES:
            i0 = idx_at_or_after(dates, date.fromisoformat(a))
            ends = [i for i, x in enumerate(dates) if b is None or x <= date.fromisoformat(b)]
            if i0 is None or not ends or ends[-1] - i0 < 20:
                print(f'\n {label}: not covered by the data, skipped')
                continue
            i1 = ends[-1]
            if (dates[i0] - date.fromisoformat(a)).days > 10:
                print(f'\n NOTE: {label} starts {dates[i0]} (first available), not {a}')
            res = run_window(H, dates, closes, flags, reb, i0, i1, tag)
            print(f'\n {label}: {dates[i0]} -> {dates[i1]}')
            print(HDR)
            for k, (eq, dts, fills) in res.items():
                m = metrics(eq, dts)
                print(fmt_row(k, m))
                summary.append(dict(span=span, test=label, strategy=k, start=dates[i0], end=dates[i1], **m))
            if b is None and a == '2004-01-01':
                pd.DataFrame({k: pd.Series(v[0], index=pd.to_datetime(v[1])) for k, v in res.items()}) \
                  .to_csv(os.path.join(args.outdir, f'equity_full_{tag}.csv'))

        # ---- crash windows: 1y / 2y / to-today from just before each peak
        print(f'\n Crash windows ({tag}) — start just before the peak; strategy already running (warm EMA)')
        print(f"  {'window':<20}{'start':<12}{'strategy':<17}{'1y ret':>8}{'1y DD':>7}"
              f"{'2y ret':>8}{'2y DD':>7}{'to-today':>10}{'DD':>7}")
        for name, start in CRASH_WINDOWS:
            i0 = idx_at_or_after(dates, date.fromisoformat(start))
            if i0 is None or i0 >= len(dates) - 5 or (dates[i0] - date.fromisoformat(start)).days > 10:
                print(f'  {name:<20}{start:<12}not covered by the data, skipped')
                continue
            row = {}
            for horizon in ('1y', '2y', 'today'):
                if horizon == 'today':
                    i1 = len(dates) - 1
                else:
                    end = dates[i0] + timedelta(days=365 * int(horizon[0]))
                    i1 = max(i for i, x in enumerate(dates) if x <= end)
                res = run_window(H, dates, closes, flags, reb, i0, i1, tag)
                for k, (eq, dts, _) in res.items():
                    m = metrics(eq, dts)
                    row.setdefault(k, {})[horizon] = m
                    summary.append(dict(span=span, test=f'{name} [{horizon}]', strategy=k,
                                        start=dates[i0], end=dates[i1], **m))
            for j, (k, h) in enumerate(row.items()):
                print(f"  {name if j == 0 else '':<20}{str(dates[i0]) if j == 0 else '':<12}{k:<17}"
                      f"{h['1y']['ret']*100:>7.1f}%{h['1y']['dd']*100:>6.1f}%"
                      f"{h['2y']['ret']*100:>7.1f}%{h['2y']['dd']*100:>6.1f}%"
                      f"{h['today']['ret']*100:>9.0f}%{h['today']['dd']*100:>6.1f}%")
            print()

        # ---- calendar years (full history)
        fp = os.path.join(args.outdir, f'equity_full_{tag}.csv')
        if not os.path.exists(fp):
            continue
        eqP = pd.read_csv(fp, index_col=0, parse_dates=True)
        ye = eqP.groupby(eqP.index.year).last()
        yr = ye / ye.shift(1).fillna(CAPITAL) - 1
        yr.to_csv(os.path.join(args.outdir, f'calendar_years_{tag}.csv'))
        print(f' Calendar-year returns, %  ({tag}, full history)')
        print((yr * 100).round(1).to_string())
        print()

    pd.DataFrame(summary).to_csv(os.path.join(args.outdir, 'summary.csv'), index=False)
    print(f'Wrote {args.outdir}/summary.csv, equity_full_*.csv, calendar_years_*.csv')


if __name__ == '__main__':
    main()
