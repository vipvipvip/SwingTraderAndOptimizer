import argparse
import csv
import json
import os
import pickle

import numpy as np

import sys
ROOT = '/home/dikesh/data/dev/SwingTraderAndOptimizer'
sys.path.insert(0, ROOT + '/swingtrader/services/mtf')
sys.path.insert(0, ROOT + '/.tmp_research')

import cmo_core
import db as db_module
import combined_universe_backtest as cub
import backtest_combined_mod as btmod

CACHE = ROOT + '/.tmp_research/combined_memberships.pkl'


def memberships():
    if os.path.exists(CACHE):
        with open(CACHE, 'rb') as f:
            return pickle.load(f)
    wp, dp = cub.load_panels()
    e10, s40, e40 = cub.weekly_indicators(wp)
    rs = cub.build_rs(wp, dp, e10, s40, e40)
    mtf = cub.build_mtf(wp['close'], e10, s40, e40)
    takeoff = cub.build_takeoff(wp)
    expl = cub.build_expl(wp['close'])
    dsignal = cub.build_daily_signal(wp, dp, e10, s40)
    weeks = sorted(set(rs) | set(mtf) | set(takeoff) | set(expl))
    all_dates = sorted(dp['close'].index)
    active = {}
    for day in all_dates:
        valid = [w for w in weeks if w + timedelta(days=7) <= day < w + timedelta(days=14)]
        s = dsignal.get(day, set())
        if valid:
            w = max(valid)
            for src in (rs, mtf, takeoff, expl):
                s |= src.get(w, set())
        active[day] = s
    with open(CACHE, 'wb') as f:
        pickle.dump({'active': active, 'all_dates': all_dates}, f)
    return {'active': active, 'all_dates': all_dates}


from datetime import timedelta

FAMILIES = {
    'bounce40': (-40, 30, -60),
    'bounce50': (-50, 20, -70),
    'dip50': (-50, 0, -70),
}


def custom_arr(ind, params):
    lo, exit_thr, hardstop = params
    arr = cmo_core.build_signal_arrays(ind, mode='cmo_bb', sell_mode='mirror')
    cmo = arr['cmo']
    valid = arr['valid']
    if lo < 0:
        buy = valid & cmo_core._cross_above_zero_event(cmo - lo)
    else:
        buy = valid & cmo_core._cross_below_zero_event(cmo - lo)
    sell = valid & (cmo_core._cross_above_zero_event(cmo - exit_thr) | (cmo < hardstop))
    arr['buy'] = buy
    arr['sell'] = sell
    arr['last_cmo_up'] = cmo_core._last_event_index(buy)
    return arr


def main():
    cache = memberships()
    active, all_dates = cache['active'], cache['all_dates']
    symbols = set().union(*active.values())
    conn = db_module.get_conn()
    try:
        data = cub.bt.load_universe(conn, symbols, 'day')
    finally:
        conn.close()
    data = {tid: d for tid, d in data.items() if d['symbol'] in symbols}
    inds = {tid: cmo_core.indicators(d, ma_type='wma') for tid, d in data.items()}

    filters = {
        'none': lambda s: True,
        'gap0': lambda s: np.isfinite(s.ema10) and np.isfinite(s.bb_mid) and s.ema10 > s.bb_mid,
        'gap1': lambda s: np.isfinite(s.ema10) and np.isfinite(s.bb_mid) and s.bb_mid > 0 and s.ema10 >= s.bb_mid * 1.01,
        'macd': lambda s: np.isfinite(s.macd_diff) and s.macd_diff > 0,
        'gap_neg1': lambda s: np.isfinite(s.ema10) and np.isfinite(s.bb_mid) and s.bb_mid > 0 and s.ema10 >= s.bb_mid * 0.99,
        'ema_bull': lambda s: np.isfinite(s.ema10) and np.isfinite(s.sma20) and s.ema10 > s.sma20,
        'macd_ema': lambda s: (np.isfinite(s.macd_diff) and s.macd_diff > 0
                               and np.isfinite(s.ema10) and np.isfinite(s.sma20)
                               and s.ema10 > s.sma20),
    }

    rows = []
    combos = []
    for fam, params in FAMILIES.items():
        for gate in ('none', 'any', 'majority', 'all'):
            for hwm in (5, 10, 15, 20):
                for fname in ('gap_neg1', 'gap0', 'macd', 'ema_bull', 'macd_ema', 'none'):
                    combos.append((fam, params, gate, hwm, fname, 1000))
    for fam, params, gate, hwm, fname, topn in combos:
        for tid, d in data.items():
            d['arr'] = custom_arr(inds[tid], params)
            d['date_to_i'] = {dt: i for i, dt in enumerate(d['dates'])}
        args = argparse.Namespace(
            top_n=topn, start=None, end=None, tickers=symbols,
            ma_type='wma', window=10, mode='cmo_bb', sell_mode='mirror',
            fill='open', cost=0.0005, rebalance_band=20.0, min_notional=500.0,
            no_event_study=True, market_filter='none', stop_loss=0.0,
            hwm_stop=hwm, cooldown=5, p20w_gate=gate, ew_by_target=True)
        res = btmod.run_sim(data, args, None,
                            active_universe=lambda day: active.get(day, set()),
                            entry_filter=filters[fname])
        m = btmod._metrics(res['equity'], res['dates'], res['exposure'], res['flows'], res['trades'], 252)
        rows.append({'family': fam, 'gate': gate, 'hwm': hwm, 'filter': fname,
                     'topn': topn, 'win': m['win'] * 100, 'dd': m['mdd'] * 100,
                     'ret': m['total'] * 100, 'sharpe': m['sharpe'],
                     'trades': m['trades'], 'expo': m['exposure'] * 100,
                     'score': m['win'] * 100 - 2 * abs(m['mdd'] * 100)})
    rows.sort(key=lambda r: (-r['score'], r['dd']))
    out = ROOT + '/.tmp_research/win_dd_search2.csv'
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('top by win-2|dd| score')
    for r in rows[:20]:
        print(r)
    print('\ntop by win (trades>=100)')
    for r in sorted((r for r in rows if r['trades'] >= 100), key=lambda r: (-r['win'], r['dd']))[:20]:
        print(r)
    feasible = [r for r in rows if r['trades'] >= 50 and r['dd'] > -33.8 and r['win'] >= 50]
    print('\nfeasible: trades>=50, dd>-33.8, win>=50')
    for r in sorted(feasible, key=lambda r: (-r['win'], r['dd']))[:30]:
        print(r)
    print('\nshallowest dd (trades>=50)')
    for r in sorted((r for r in rows if r['trades'] >= 50), key=lambda r: (-r['dd'], -r['win']))[:20]:
        print(r)


if __name__ == '__main__':
    main()
