import argparse
import csv
import json
import math
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import psycopg2

ROOT = '/home/dikesh/data/dev/SwingTraderAndOptimizer'
MTF = ROOT + '/swingtrader/services/mtf'
sys.path.insert(0, MTF)
sys.path.insert(0, ROOT + '/common/scripts')
import config
import cmo_core
import db as db_module
import backtest_cmo as bt
import imminent_probability as ip

SRC = open(bt.__file__).read()
SRC = SRC.replace('def run_sim(data, args, bench_rows=None):',
                  'def run_sim(data, args, bench_rows=None, active_universe=None, entry_filter=None):')
SRC = SRC.replace('target_val = equity_dec / args.top_n',
                  'target_val = equity_dec / (max(1, len(target)) if getattr(args, "ew_by_target", False) else args.top_n)')
SRC = SRC.replace('''        states = {}
        for sym in held:''',
                  '''        active = active_universe(day) if active_universe is not None else None
        states = {}
        for sym in held:''')
OLD = '''            for tid, d in data.items():
                sym = d['symbol']
                if sym in positions:
                    continue
                i = last_i[tid]
                if i >= 1 and bool(d['arr']['buy'][i]):
                    states[sym] = cmo_core.signal_at(d['arr'], i)'''
NEW = '''            for tid, d in data.items():
                sym = d['symbol']
                if sym in positions:
                    continue
                if active is not None and sym not in active:
                    continue
                i = last_i[tid]
                if i >= 1 and bool(d['arr']['buy'][i]):
                    sig0 = cmo_core.signal_at(d['arr'], i)
                    if entry_filter is not None and not entry_filter(sig0):
                        continue
                    states[sym] = sig0'''
assert OLD in SRC
SRC = SRC.replace(OLD, NEW)
MOD = ROOT + '/.tmp_research/backtest_combined_mod.py'
open(MOD, 'w').write(SRC)
sys.path.insert(0, ROOT + '/.tmp_research')
import backtest_combined_mod as btmod

TAKEOFF_W = {'std20': 1.7, 'maxrange8': 1.65, 'low52': 1.65, 'atr': 1.65,
             'expcount': 1.6, 'dip8': 1.5, 'rng_c': 1.5, 'c2s': 1.3, 'ret20': 1.1}


def ewm(s, span):
    return s.ewm(span=span, adjust=False).mean()


def connect():
    return psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT, dbname=config.DB_NAME,
                            user=config.DB_USER, password=config.DB_PASS)


def load_panels():
    conn = connect()
    try:
        q = lambda s: pd.read_sql(s, conn)
        w = q("select k.symbol sym, p.date, p.open, p.high, p.low, p.close, p.volume "
              "from tbl_prices_weekly p join tbl_stock_tickers k on k.id=p.ticker_id "
              "where k.enabled and not k.is_etf order by 1,2")
        d = q("select k.symbol sym, p.date, p.close, p.atr_stop "
              "from tbl_prices_daily p join tbl_stock_tickers k on k.id=p.ticker_id "
              "where k.enabled and not k.is_etf order by 1,2")
    finally:
        conn.close()
    for col in ('open', 'high', 'low', 'close', 'volume'):
        w[col] = w[col].astype(float)
    for col in ('close', 'atr_stop'):
        d[col] = d[col].astype(float)
    w['date'] = pd.to_datetime(w['date']).dt.date
    d['date'] = pd.to_datetime(d['date']).dt.date
    wp = {c: w.pivot(index='date', columns='sym', values=c) for c in ('close', 'high', 'low', 'volume')}
    dp = {c: d.pivot(index='date', columns='sym', values=c) for c in ('close', 'atr_stop')}
    return wp, dp


def weekly_indicators(wp):
    px = wp['close']
    ema10 = px.apply(lambda s: ewm(s, 10))
    sma40 = px.rolling(40).mean()
    ema40 = px.apply(lambda s: ewm(s, 40))
    return ema10, sma40, ema40


def build_rs(wp, dp, ema10, sma40, ema40):
    px, hi, lo, vol = wp['close'], wp['high'], wp['low'], wp['volume']
    dv = (px * vol).rolling(26).mean()
    liq = (px >= 10) & (dv >= 5e6)
    rk = lambda r: r.where(liq).rank(axis=1, pct=True)
    rank = (0.5 * rk(px.pct_change(13)) + 0.3 * rk(px.pct_change(26)) + 0.2 * rk(px.pct_change(52))).rank(axis=1, pct=True)
    base = rank.shift(2).rolling(12).mean()
    base_ev = (rank >= .8) & (rank.shift(1) < .8) & (base < .5)
    up = (ema10 > sma40) & sma40.notna()
    cross = up & ~up.shift(1, fill_value=False) & sma40.shift(1).notna()
    pos = pd.DataFrame(np.where(cross, np.arange(len(px))[:, None], np.nan), index=px.index, columns=px.columns).ffill()
    age = pd.DataFrame(np.arange(len(px))[:, None] - pos.values, index=px.index, columns=px.columns).where(up)
    bpos = pd.DataFrame(np.where(base_ev, np.arange(len(px))[:, None], np.nan), index=px.index, columns=px.columns).ffill()
    bage = pd.DataFrame(np.arange(len(px))[:, None] - bpos.values, index=px.index, columns=px.columns)
    base_flag = bage <= 8
    macd = ema10 - ema40
    dclose = dp['close']
    de10 = dclose.apply(lambda s: ewm(s, 10))
    de40 = dclose.apply(lambda s: ewm(s, 40))
    dm = de10 - de40
    dhist = (dm - dm.ewm(span=400, adjust=False).mean()).where(dclose.notna().cumsum() >= 440)
    ddates = np.array(dclose.index, dtype=object)
    out = {}
    for k, wk in enumerate(px.index):
        asof = wk + timedelta(days=4)
        j = np.searchsorted(ddates, asof, side='right') - 1
        if j < 0:
            out[wk] = set()
            continue
        row = dhist.iloc[j].reindex(px.columns)
        mask = (rank.iloc[k] >= .8) & (age.iloc[k] <= 8) & base_flag.iloc[k] & (row > 0)
        out[wk] = set(px.columns[mask.values])
    return out


def build_mtf(px, ema10, sma40, ema40):
    n, m = px.shape
    elig = np.zeros((n, m), dtype=bool)
    cols = px.columns
    dates = np.array(px.index, dtype=object)
    for ci, sym in enumerate(cols):
        e = ema10[sym].to_numpy(dtype=float)
        s = sma40[sym].to_numpy(dtype=float)
        e40 = ema40[sym].to_numpy(dtype=float)
        co = np.where((e > s) & (np.r_[False, e[:-1] <= s[:-1]]))[0]
        md = e - e40
        mup = np.where((md > 0) & (np.r_[False, md[:-1] <= 0]))[0]
        for k in range(n):
            if not np.isfinite(e[k]) or not np.isfinite(s[k]) or k < 60 or e[k] <= s[k]:
                continue
            prev = co[co <= k]
            if len(prev) == 0:
                continue
            c = prev[-1]
            if np.any((mup >= c - 5) & (mup <= c + 5)):
                elig[k, ci] = True
    out = {}
    for k, wk in enumerate(px.index):
        gap = (px.iloc[k].to_numpy(dtype=float) - sma40.iloc[k].to_numpy(dtype=float)) / sma40.iloc[k].to_numpy(dtype=float) * 100
        score = np.minimum(gap / 5.0, 5.0)
        valid = elig[k] & np.isfinite(score)
        idx = np.where(valid)[0]
        idx = sorted(idx, key=lambda i: (-score[i], cols[i]))[:25]
        out[wk] = {cols[i] for i in idx}
    return out


def build_takeoff(wp):
    px, hi, lo = wp['close'], wp['high'], wp['low']
    dates = np.array(px.index, dtype=object)
    scores = np.full(px.shape, np.nan)
    for ci, sym in enumerate(px.columns):
        c = px[sym].astype(float)
        h = hi[sym].astype(float)
        l = lo[sym].astype(float)
        e10 = ewm(c, 10)
        s40 = c.rolling(40).mean()
        r = c.pct_change()
        co = np.where((e10 >= s40) & (e10.shift(1) < s40.shift(1)))[0]
        for k in range(45, len(c)):
            if not np.isfinite(s40.iloc[k]) or not np.isfinite(e10.iloc[k]) or e10.iloc[k] < s40.iloc[k]:
                continue
            prev = co[co <= k]
            if len(prev) == 0:
                continue
            cw = prev[-1]
            since = (dates[k] - dates[cw]).days / 7.0
            if since > 12:
                continue
            pre = slice(max(0, k - 8), k - 1)
            rs = r.iloc[max(0, k - 20):k - 1]
            feat = {
                'std20': rs.std() * 100,
                'maxrange8': (h.iloc[pre] / l.iloc[pre]).max(),
                'expcount': int(((h.iloc[max(0, k - 5):k - 1] / l.iloc[max(0, k - 5):k - 1]) >= 1.10).sum()),
                'atr': (h.iloc[max(0, k - 20):k].sub(l.iloc[max(0, k - 20):k])).mean() / c.iloc[k] * 100,
                'dip8': (1 - l.iloc[pre].min() / c.iloc[k]) * 100,
                'rng_c': h.iloc[k] / l.iloc[k],
                'c2s': c.iloc[k] / s40.iloc[k],
                'ret20': (c.iloc[k] / c.iloc[max(0, k - 20)] - 1) * 100,
                'low52': c.iloc[k] / c.iloc[max(0, k - 52):k - 1].min(),
            }
            if any(not np.isfinite(v) for v in feat.values()):
                continue
            scores[k, ci] = sum(TAKEOFF_W[f] * feat[f] for f in TAKEOFF_W)
    out = {}
    for k, wk in enumerate(px.index):
        row = scores[k]
        idx = np.where(np.isfinite(row))[0]
        idx = sorted(idx, key=lambda i: (-row[i], px.columns[i]))[:25]
        out[wk] = {px.columns[i] for i in idx}
    return out


def build_expl(px):
    panel = ip.feature_panel()
    panel = panel[panel['symbol'].isin(px.columns)]
    bundle = ip.load_model()
    out = {}
    for wk in px.index:
        try:
            picks = ip.select(panel, wk, bundle=bundle, top_n=10, min_dvol=50e6)
        except Exception:
            picks = pd.DataFrame()
        out[wk] = set(picks['symbol']) if not picks.empty else set()
    return out


def build_daily_signal(wp, dp, ema10w, sma40w):
    dc = dp['close']
    atr = dp['atr_stop']
    de10 = dc.apply(lambda s: ewm(s, 10))
    de40 = dc.apply(lambda s: ewm(s, 40))
    ddates = np.array(dc.index, dtype=object)
    wdates = np.array(wp['close'].index, dtype=object)
    wkpos = np.searchsorted(wdates, ddates - timedelta(days=7), side='right') - 1
    cands = [[] for _ in ddates]
    for sym in dc.columns:
        c = dc[sym].to_numpy(dtype=float)
        a = atr[sym].to_numpy(dtype=float)
        e = de10[sym].to_numpy(dtype=float)
        s = de40[sym].to_numpy(dtype=float)
        we = ema10w[sym].to_numpy(dtype=float)
        ws = sma40w[sym].to_numpy(dtype=float)
        wc = wp['close'][sym].to_numpy(dtype=float)
        co = np.where((we > ws) & (np.r_[False, we[:-1] <= ws[:-1]]))[0]
        last = np.full(len(we), np.nan)
        for k in co:
            last[k:] = k
        days = np.full(len(we), 999.0)
        for k in range(len(we)):
            if np.isfinite(last[k]):
                days[k] = (wdates[k] - wdates[int(last[k])]).days
        for j in range(len(ddates)):
            k = wkpos[j]
            if k < 0 or not np.isfinite(e[j]) or not np.isfinite(s[j]):
                continue
            if not np.isfinite(we[k]) or not np.isfinite(ws[k]) or we[k] <= ws[k] or e[j] <= s[j]:
                continue
            gap = (wc[k] - ws[k]) / ws[k] * 100
            ad = (c[j] - a[j]) / c[j] * 100 if np.isfinite(a[j]) and a[j] > 0 else 0.0
            score = min(gap / 20.0, 3.0) + min(ad / 1.5, 3.0) + max(0.0, 2.0 - days[k] / 60.0)
            cands[j].append((score, sym))
    out = {}
    for j, dt in enumerate(ddates):
        top = sorted(cands[j], key=lambda x: (-x[0], x[1]))[:25]
        out[dt] = {sym for _, sym in top}
    return out


def main():
    wp, dp = load_panels()
    ema10w, sma40w, ema40w = weekly_indicators(wp)
    print('building weekly lists', flush=True)
    rs = build_rs(wp, dp, ema10w, sma40w, ema40w)
    mtf = build_mtf(wp['close'], ema10w, sma40w, ema40w)
    takeoff = build_takeoff(wp)
    print('building EXPL list', flush=True)
    expl = build_expl(wp['close'])
    print('building Daily Signal list', flush=True)
    dsignal = build_daily_signal(wp, dp, ema10w, sma40w)

    weeks = sorted(set(rs) | set(mtf) | set(takeoff) | set(expl))
    all_dates = sorted(dp['close'].index)
    active_all = {}
    src_counts = {s: 0 for s in ('rs', 'mtf', 'takeoff', 'expl', 'dsignal')}
    for day in all_dates:
        valid = [w for w in weeks if w + timedelta(days=7) <= day < w + timedelta(days=14)]
        wset = set()
        if valid:
            w = max(valid)
            for src in (rs, mtf, takeoff, expl):
                wset |= src.get(w, set())
        dset = dsignal.get(day, set())
        wset |= dset
        active_all[day] = wset
        if wset:
            for name, s in (('rs', rs.get(max(valid), set()) if valid else set()),
                            ('mtf', mtf.get(max(valid), set()) if valid else set()),
                            ('takeoff', takeoff.get(max(valid), set()) if valid else set()),
                            ('expl', expl.get(max(valid), set()) if valid else set()),
                            ('dsignal', dset)):
                src_counts[name] += len(s)

    latest_w = max(weeks)
    latest_d = all_dates[-1]
    print('latest weekly', latest_w, 'rs', len(rs[latest_w]), 'mtf', len(mtf[latest_w]),
          'takeoff', len(takeoff[latest_w]), 'expl', len(expl[latest_w]))
    print('latest daily', latest_d, 'dsignal', len(dsignal[latest_d]))
    print('combined active latest', len(active_all[latest_d]))
    print('avg memberships', {k: round(v / max(1, len(all_dates)), 1) for k, v in src_counts.items()})

    symbols = set().union(*active_all.values())
    conn = db_module.get_conn()
    try:
        data = bt.load_universe(conn, symbols, 'day')
    finally:
        conn.close()
    data = {tid: d for tid, d in data.items() if d['symbol'] in symbols}

    gap1 = lambda s: (np.isfinite(s.ema10) and np.isfinite(s.bb_mid) and s.bb_mid > 0
                      and s.ema10 >= s.bb_mid * 1.01)
    rows = []
    bconn = db_module.get_conn()
    try:
        for mode in ('armed', 'cmo_bb'):
            for tid, d in data.items():
                ind = cmo_core.indicators(d, ma_type='wma')
                d['arr'] = cmo_core.build_signal_arrays(ind, window=10, mode=mode, sell_mode='mirror')
                d['date_to_i'] = {dt: i for i, dt in enumerate(d['dates'])}
            args = argparse.Namespace(
                top_n=1000, start=None, end=None, tickers=symbols,
                ma_type='wma', window=10, mode=mode, sell_mode='mirror',
                fill='open', cost=0.0005, rebalance_band=20.0, min_notional=500.0,
                no_event_study=True, market_filter='none', stop_loss=0.0,
                hwm_stop=15.0, cooldown=5, p20w_gate='majority', ew_by_target=True)
            res = btmod.run_sim(data, args, None,
                                active_universe=lambda day: active_all.get(day, set()),
                                entry_filter=gap1)
            m = btmod._metrics(res['equity'], res['dates'], res['exposure'], res['flows'], res['trades'], 252)
            spy = bt._benchmark(bconn, 'SPY', res['dates'], 'day', 252)
            mi = (res['dates'], res['equity'], res['exposure'], res['flows'], res['trades'])
            sub = {}
            for label, s0, s1 in [('2017-2020', date(2017, 1, 1), date(2020, 12, 31)),
                                  ('2021-2023', date(2021, 1, 1), date(2023, 12, 31)),
                                  ('2024-now', date(2024, 1, 1), all_dates[-1])]:
                sm = btmod._slice(mi, s0, s1, 252)
                sub[label] = None if not sm else {'win': sm['win'] * 100, 'mdd': sm['mdd'] * 100, 'ret': sm['total'] * 100}
            rows.append({'universe': 'combined', 'mode': mode, 'win': m['win'] * 100,
                         'mdd': m['mdd'] * 100, 'ret': m['total'] * 100,
                         'sharpe': m['sharpe'], 'trades': m['trades'],
                         'expo': m['exposure'] * 100, 'sub': json.dumps(sub)})
            rows.append({'universe': 'SPY', 'mode': 'buy-hold', 'win': None,
                         'mdd': spy['mdd'] * 100, 'ret': spy['total'] * 100,
                         'sharpe': spy['sharpe'], 'trades': None,
                         'expo': 100.0, 'sub': json.dumps({})})
            with open(f'{ROOT}/.tmp_research/combined_{mode}_trades.csv', 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['symbol', 'qty', 'entry_signal_date', 'entry_date',
                                                  'exit_signal_date', 'exit_date', 'entry_px', 'exit_px',
                                                  'pnl', 'ret', 'reason'])
                w.writeheader()
                w.writerows(res['trades'] + res['open_positions'])
            print('combined', mode, f"win={m['win']*100:.1f} dd={m['mdd']*100:.1f} ret={m['total']*100:.1f} n={m['trades']}")
            print('SPY', f"dd={spy['mdd']*100:.1f} ret={spy['total']*100:.1f}")
    finally:
        bconn.close()
    out = ROOT + '/.tmp_research/combined_vs_spy.csv'
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('wrote', out)
    for r in rows:
        print(r)


if __name__ == '__main__':
    main()
