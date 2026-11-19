import argparse
import csv
import json
from datetime import date

import numpy as np

import sys
sys.path.insert(0, '/home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf')
sys.path.insert(0, '/home/dikesh/data/dev/SwingTraderAndOptimizer/.tmp_research')

import cmo_core
import db as db_module
import combined_universe_backtest as cub
import backtest_combined_mod as btmod
from win_dd_search import memberships, custom_arr, ROOT

CONFIGS = [
    ('bounce40_hwm15', (-40, 30, -60), 'majority', 15),
    ('bounce40_hwm20', (-40, 30, -60), 'majority', 20),
]


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
    gap_neg1 = lambda s: np.isfinite(s.ema10) and np.isfinite(s.bb_mid) and s.bb_mid > 0 and s.ema10 >= s.bb_mid * 0.99
    bconn = db_module.get_conn()
    try:
        for name, params, gate, hwm in CONFIGS:
            for tid, d in data.items():
                d['arr'] = custom_arr(inds[tid], params)
                d['date_to_i'] = {dt: i for i, dt in enumerate(d['dates'])}
            args = argparse.Namespace(
                top_n=1000, start=None, end=None, tickers=symbols,
                ma_type='wma', window=10, mode='cmo_bb', sell_mode='mirror',
                fill='open', cost=0.0005, rebalance_band=20.0, min_notional=500.0,
                no_event_study=True, market_filter='none', stop_loss=0.0,
                hwm_stop=hwm, cooldown=5, p20w_gate=gate, ew_by_target=True)
            res = btmod.run_sim(data, args, None,
                                active_universe=lambda day: active.get(day, set()),
                                entry_filter=gap_neg1)
            m = btmod._metrics(res['equity'], res['dates'], res['exposure'], res['flows'], res['trades'], 252)
            spy = cub.bt._benchmark(bconn, 'SPY', res['dates'], 'day', 252)
            mi = (res['dates'], res['equity'], res['exposure'], res['flows'], res['trades'])
            sub = {}
            for label, s0, s1 in [('2017-2020', date(2017, 1, 1), date(2020, 12, 31)),
                                  ('2021-2023', date(2021, 1, 1), date(2023, 12, 31)),
                                  ('2024-now', date(2024, 1, 1), all_dates[-1])]:
                sm = btmod._slice(mi, s0, s1, 252)
                sub[label] = None if not sm else {'win': sm['win'] * 100, 'dd': sm['mdd'] * 100, 'ret': sm['total'] * 100}
            print(name, json.dumps({'win': m['win'] * 100, 'dd': m['mdd'] * 100,
                                    'ret': m['total'] * 100, 'sharpe': m['sharpe'],
                                    'trades': m['trades'], 'expo': m['exposure'] * 100,
                                    'spy_ret': spy['total'] * 100, 'spy_dd': spy['mdd'] * 100,
                                    'sub': sub}, indent=2))
            allrows = res['trades'] + res['open_positions']
            out = ROOT + f'/common/docs/trade_books/{name}_trades.csv'
            with open(out, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['symbol', 'qty', 'entry_signal_date', 'entry_date',
                                                  'exit_signal_date', 'exit_date', 'entry_px', 'exit_px',
                                                  'pnl', 'ret', 'reason'])
                w.writeheader()
                w.writerows(allrows)
            print('wrote', out, len(allrows))
            years = {}
            for t in res['trades']:
                y = str(t['exit_date'])[:4]
                years.setdefault(y, []).append(t['ret'])
            print('by exit year', {y: (len(v), round(sum(v) / len(v) * 100, 1)) for y, v in sorted(years.items())})
    finally:
        bconn.close()


if __name__ == '__main__':
    main()
