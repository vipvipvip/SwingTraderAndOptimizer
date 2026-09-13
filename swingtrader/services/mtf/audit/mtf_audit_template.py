"""Strategy-agnostic audit report generator for any MTF-family backtest.

One entry point, one output contract: every strategy emits the SAME six
audit artifacts, so an auditor/investor reviews any strategy with the same
checklist.

USAGE
-----
  python mtf_audit_template.py [--out DIR] [--label NAME] [--quiet] [-- <backtest args...>]

  Everything after `--` (or any unrecognised tokens) is passed verbatim to
  backtest_topn_multitf.backtest(), so ANY strategy configuration the engine
  supports is auditable:
    --top-n, --score mtf|early|near|emasma, --rebalance, --exit, --tickers,
    --etf, --above, --min-score, --infancy, --hourly-ema-gate, --start,
    --stop-loss, --ppo-filter, --near-gap-k, --near-atr-k, ...

EXAMPLE
  python mtf_audit_template.py --out sector_etf_audit --label etf_top3 -- \
      --etf --score emasma --top-n 3 \
      --tickers XLB,XLE,XLF,XLRE,XLV,XLI,XLK,XLP,XLU,XLY,XLC

OUTPUT (in --out DIR, prefix = --label or derived from the backtest args)
  {label}_trades.csv        per-side ledger (signal snapshot + execution)
  {label}_roundtrips.csv    closed-trade pairs — the audit P/L ledger
  {label}_performance.csv   headline / risk / distribution metrics + benchmarks
  {label}_monthly.csv       year x month return matrix + annual
  {label}_by_symbol.csv     per-symbol activity & P/L
  {label}_equity.csv        NAV / date / positions daily series

INTEGRITY CONTRACT
  - No look-ahead: engine fills settle at the NEXT trading day's OPEN; each
    trade row carries a signal snapshot reconstructed from the bars on the
    decision day immediately before that fill, so every row ties to the exact
    bars that triggered it.
  - The ledger reconciles to the end-of-sample equity within display rounding:
    sum(net_pnl) + CAPITAL == final equity. Buy fee is embedded in share
    sizing ((alloc/bp)*(1-COST)); round-trip net P/L = gross - sell fee.
  - Canonical arithmetic (signals, fills, equity) comes from
    backtest_topn_multitf.backtest(); this module only reports it.
"""
import sys
import os
import csv
import argparse

import numpy as np
import pandas as pd

CUR = os.path.dirname(os.path.abspath(__file__))
MTF_DIR = os.path.dirname(CUR)
if MTF_DIR not in sys.path:
    sys.path.insert(0, MTF_DIR)

import db as db_module
import backtest_topn_multitf as bt
from backtest_topn_multitf import _last_idx_before, CAPITAL, COST, EMA, SMA, WARMUP

DEFAULT_OUT = os.path.join(CUR, 'outputs')

ENGINE_FLAGS = {'--top-n', '--rebalance', '--detail', '--etf', '--score',
                '--tickers', '--above', '--min-score', '--infancy',
                '--stop-loss', '--top-trades', '--ppo-filter',
                '--hourly-ema-gate', '--hourly-daily-gap', '--exit',
                '--ratchet-atr-src', '--start', '--near-gap-k', '--near-atr-k',
                '--equal-weight', '--cost'}

EXIT_REASONS = {'SELL': 'rotation (out of top-N)', 'SELL-STOP': 'stop-loss',
                'SELL-H-EMA': 'hourly-EMA exit', 'SELL-RATC': 'ratchet-ATR exit',
                'SELL-D-EMA': 'daily-EMA exit',
                'SELL-TRIM': 'equal-weight sizing trim'}


def parse_cli():
    argv = sys.argv[1:]
    if '--' in argv:
        head, tail = argv[:argv.index('--')], argv[argv.index('--') + 1:]
    else:
        head, tail = argv, None
    p = argparse.ArgumentParser(
        description='MTF audit template', add_help=True)
    p.add_argument('--out', help='output directory (default audit/outputs/<label>)')
    p.add_argument('--label', help='filename prefix (default derived from args)')
    p.add_argument('--quiet', action='store_true',
                   help='suppress the console report')
    cli = p.parse_args(head)
    if tail is None:
        _, tail = p.parse_known_args(head)
    return cli, tail


def default_label(a):
    u = 'etf' if a.etf else 'stk'
    t = 'sym' if not a.tickers else a.tickers.replace(',', '_')
    return f'top{a.top_n}_{a.score}_{u}_{t}'


def csv_write(path, rows):
    """Widen rows to a union of keys so dict rows with missing fields are safe."""
    keys = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(path, 'w', newline='') as f:
        if rows and isinstance(rows[0], dict):
            w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                w.writerow(dict((k, r.get(k, '')) for k in keys))
        else:
            w = csv.writer(f)
            for r in rows:
                w.writerow(r)


def bh_benchmark(conn, sym, w0, w1):
    cur = conn.cursor()
    cur.execute("""
        SELECT d.date, d.close FROM tbl_scanner_tickers_daily d
        JOIN tbl_stock_tickers s ON s.id = d.ticker_id
        WHERE s.symbol = %s AND s.is_etf = true ORDER BY d.date ASC""", (sym,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return None
    p0 = next((float(c) for dt, c in rows if dt >= w0), None)
    if p0 is None or p0 <= 0:
        return None
    pn = float(rows[-1][1])
    days = (w1 - w0).days
    return {'ret': (pn / p0 - 1) * 100,
            'cagr': ((pn / p0) ** (365.0 / days) - 1) * 100}


def main():
    global COST
    cli, bt_argv = parse_cli()
    res = bt.backtest(bt_argv)
    if res is None:
        print('backtest returned no results (empty sample).')
        return 1
    COST = res['COST']  # engine-effected COST (--cost override); keep ledger reconcilable
    a = res['args']
    label = cli.label or default_label(a)
    out = cli.out or os.path.join(DEFAULT_OUT, label)
    os.makedirs(out, exist_ok=True)

    eq = np.asarray(res['equity'])
    eq_dates = res['equity_dates']
    trades = res['trades']
    all_dates = res['all_dates']
    pc = res['pos_counts']
    date_idx = {d: i for i, d in enumerate(all_dates)}
    window_days = (all_dates[-1] - all_dates[0]).days
    sym_order = a.tickers.split(',') if a.tickers else None

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        # ---- bars for signal snapshots + benchmarks ----
        _, weekly = bt.load_bars(conn, 'tbl_scanner_tickers', 'date',
                                 bool(a.etf), sym_order)
        _, daily = bt.load_bars(conn, 'tbl_scanner_tickers_daily', 'date',
                                bool(a.etf), sym_order)
        _, hourly = bt.load_bars(conn, 'tbl_scanner_tickers_1hour', None,
                                 bool(a.etf), sym_order)
        for tid in weekly:
            wc_ = pd.Series(weekly[tid]['close'])
            weekly[tid]['ema'] = wc_.ewm(span=EMA, adjust=False).mean().to_numpy()
            weekly[tid]['sma'] = wc_.rolling(window=SMA).mean().to_numpy()
            dc_ser = pd.Series(daily[tid]['close'])
            daily[tid]['ema'] = dc_ser.ewm(span=EMA, adjust=False).mean().to_numpy()
            daily[tid]['sma'] = dc_ser.rolling(window=SMA).mean().to_numpy()
        sym_of = {}
        for tid, d_ in weekly.items():
            sym_of[d_['symbol']] = tid
        widx = {tid: {dt: i for i, dt in enumerate(weekly[tid]['dates'])}
                for tid in weekly}
        didx = {tid: {dt: i for i, dt in enumerate(daily[tid]['dates'])}
                for tid in daily}
        hidx = {tid: {dt: i for i, dt in enumerate(hourly[tid]['dates'])}
                for tid in hourly}

        def snap(tid, sig_date):
            """Reconstruct decision-time bars + all four scores for (tid, sig_date).

            Hourly data only exists from 2023-06-30, so pre-2023 snapshots carry
            blanks for hourly-based fields (atr_dist, mtf/near scores) rather than
            fabricating values the engine could not have seen.
            """
            if sig_date is None:
                return None
            wi = _last_idx_before(widx[tid], weekly[tid]['dates'], sig_date)
            di = _last_idx_before(didx[tid], daily[tid]['dates'], sig_date)
            if wi is None or wi < WARMUP or di is None:
                return None
            w = weekly[tid]
            sc, se, ss = w['close'][wi], w['ema'][wi], w['sma'][wi]
            d_ = daily[tid]
            dc, de, ds = d_['close'][di], d_['ema'][di], d_['sma'][di]
            if any(np.isnan(v) for v in (sc, se, ss, dc, de, ds)):
                return None
            hi = _last_idx_before(hidx[tid], hourly[tid]['dates'], sig_date) if tid in hourly else None
            hc = ha = float('nan')
            if hi is not None:
                hc = hourly[tid]['close'][hi]
                ha = hourly[tid]['atr_stop'][hi]
            have_hourly = bool(hc == hc) and bool(ha == ha)
            gap_w = (sc - ss) / ss * 100
            if have_hourly and hc > 0:
                atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0.0
            else:
                atr_dist = None
            days = 999
            for j in range(wi, 0, -1):
                e0, s0 = w['ema'][j], w['sma'][j]
                e1, s1 = w['ema'][j - 1], w['sma'][j - 1]
                if not any(np.isnan(v) for v in (e0, s0, e1, s1)):
                    if e0 > s0 and e1 <= s1:
                        days = (sig_date - w['dates'][j]).days
                        break
            gap_pts = min(gap_w / 20, 3)
            atr_pts = min(atr_dist / 1.5, 3) if atr_dist is not None else None
            fresh_pts = max(0, 2 - days / 60)
            signal_cnt = 2 + (1 if days < 60 else 0)
            return {
                'sig_date': sig_date,
                'sig_w_close': round(float(sc), 2),
                'sig_w_ema': round(float(se), 2), 'sig_w_sma': round(float(ss), 2),
                'sig_d_close': round(float(dc), 2),
                'sig_d_ema': round(float(de), 2), 'sig_d_sma': round(float(ds), 2),
                'sig_h_close': round(float(hc), 2) if have_hourly else None,
                'sig_h_atr': round(float(ha), 2) if have_hourly else None,
                'gap_w': round(gap_w, 2), 'atr_dist': round(atr_dist, 2) if atr_dist is not None else None,
                'freshness_days': days,
                'emasma_score': round(min(gap_w / 5, 5), 2),
                'mtf_score': round(gap_pts + atr_pts + fresh_pts, 1) if atr_pts is not None else None,
                'early_score': round(signal_cnt + fresh_pts - gap_pts, 1),
                'near_score': round(max(0.0, 3 - gap_w / (a.near_gap_k or 10))
                                    + max(0.0, 3 - atr_dist / (a.near_atr_k or 1.5))
                                    + fresh_pts, 1) if atr_dist is not None else None,
            }

        def sig_before(date):
            i = date_idx[date]
            return all_dates[i - 1] if i > 0 else None

        # ---- replay: pair buys/sells into round trips, engine-exact cash ----
        # Account-based (avg-cost-basis): equal-weight runs emit partial
        # SELL-TRIM / BUY-ADD legs that resize an existing open position rather
        # than open/close it. A single BUY opens (assigns trade_id); adds reuse
        # the same trade_id; sells consume avg basis.
        sell_by_date, buy_by_date = {}, {}
        for t in trades:
            sid = t[2]
            if sid in EXIT_REASONS:
                sell_by_date.setdefault(t[0], []).append(t)
            else:  # BUY / BUY-ADD
                buy_by_date.setdefault(t[0], []).append(t)

        ev = []
        rep_cash = CAPITAL
        open_pos = {}
        buy_tid = 0
        for d in all_dates:
            for t in sell_by_date.get(d, []):
                sym, sh, sp = t[1], t[3], t[4]
                pr = open_pos.get(sym)
                if pr is None or pr['sh'] <= 0:
                    continue
                avg_px = pr['basis'] / pr['sh']
                rel_basis = sh * avg_px
                sf = sh * sp * COST
                gross = sh * sp - rel_basis
                net = gross - sf
                rep_cash += sh * sp * (1 - COST)
                pr['sh'] -= sh
                pr['basis'] -= rel_basis
                if pr['sh'] <= 1e-9:
                    del open_pos[sym]
                s_date = sig_before(d)
                s_snap = snap(sym_of.get(sym), s_date)
                ev.append(dict(kind='SELL', trade_id=pr['tid'], symbol=sym,
                               exec_date=d, exec_price=round(sp, 2),
                               shares=round(sh, 2),
                               buy_date=pr['d'], buy_price=round(avg_px, 2),
                               buy_fee=round(rel_basis * COST, 2),
                               sell_fee=round(sf, 2),
                               gross_pnl=round(gross, 2), net_pnl=round(net, 2),
                               net_return_pct=round(net / rel_basis * 100, 2) if rel_basis else None,
                               hold_days=date_idx[d] - date_idx[pr['d']],
                               exit_reason=EXIT_REASONS[t[2]] if t[2] in EXIT_REASONS else t[2],
                               snap=s_snap))
            for t in buy_by_date.get(d, []):
                sym, sh, bp_ = t[1], t[3], t[4]
                if sym in open_pos:
                    pr = open_pos[sym]
                    pr['sh'] += sh
                    pr['basis'] += sh * bp_
                    rep_cash -= sh * bp_
                    ev.append(dict(kind='BUY', trade_id=pr['tid'], symbol=sym,
                                   exec_date=d, exec_price=round(bp_, 2),
                                   shares=round(sh, 2), buy_date=None, buy_price=None,
                                   buy_fee=round(sh * bp_ * COST, 2), sell_fee=None,
                                   gross_pnl=None, net_pnl=None, net_return_pct=None,
                                   hold_days=None, exit_reason=None,
                                   snap=snap(sym_of.get(sym), sig_before(d))))
                else:
                    buy_tid += 1
                    rep_cash -= sh * bp_
                    open_pos[sym] = dict(sh=sh, basis=sh * bp_, d=d, tid=buy_tid)
                    ev.append(dict(kind='BUY', trade_id=buy_tid, symbol=sym,
                                   exec_date=d, exec_price=round(bp_, 2),
                                   shares=round(sh, 2), buy_date=None, buy_price=None,
                                   buy_fee=round(sh * bp_ * COST, 2), sell_fee=None,
                                   gross_pnl=None, net_pnl=None, net_return_pct=None,
                                   hold_days=None, exit_reason=None,
                                   snap=snap(sym_of.get(sym), sig_before(d))))

        # end-of-sample marks for still-open positions (reporting only)
        last = all_dates[-1]
        for sym, pr in list(open_pos.items()):
            sh, entry_basis = pr['sh'], pr['basis']
            xi = _last_idx_before(didx[sym_of[sym]], daily[sym_of[sym]]['dates'], last)
            if xi is None:
                continue
            sp = float(daily[sym_of[sym]]['close'][xi])
            net = sh * sp - entry_basis   # no exit cost on open marks (engine MTMs at close)
            rep_cash += sh * sp
            ev.append(dict(kind='SELL', trade_id=pr['tid'], symbol=sym,
                           exec_date=last, exec_price=round(sp, 2),
                           shares=round(sh, 2),
                           buy_date=pr['d'], buy_price=round(entry_basis / sh, 2),
                           buy_fee=round(entry_basis * COST, 2),
                           sell_fee=None,
                           gross_pnl=round(net, 2), net_pnl=round(net, 2),
                           net_return_pct=round(net / entry_basis * 100, 2) if entry_basis else None,
                           hold_days=date_idx[last] - date_idx[pr['d']],
                           exit_reason='end-of-sample mark-to-market', snap=None))

        roundtrips = [e for e in ev if e['kind'] == 'SELL']
        strat_rt = [r for r in roundtrips
                    if r['exit_reason'] != 'end-of-sample mark-to-market']
        open_rt = [r for r in roundtrips
                   if r['exit_reason'] == 'end-of-sample mark-to-market']

        # ---- metrics ----
        rets = pd.Series(eq).pct_change().dropna().to_numpy()
        final = float(eq[-1])
        cagr = (final / CAPITAL) ** (365.0 / window_days) - 1
        sd = np.std(rets, ddof=1)
        vol = sd * np.sqrt(252)
        sharpe = float(np.mean(rets) / sd * np.sqrt(252)) if sd else float('nan')
        neg = rets[rets < 0]
        down = float(np.sqrt(np.mean(neg ** 2)) * np.sqrt(252)) if len(neg) else float('nan')
        sortino = float(np.mean(rets) * 252 / down) if down else float('nan')
        dd_ser = eq / np.maximum.accumulate(eq) - 1
        maxdd = float(dd_ser.min())
        calmar = cagr / abs(maxdd) if maxdd < 0 else float('nan')

        nets = np.array([r['net_pnl'] for r in strat_rt])
        pcts = np.array([r['net_return_pct'] for r in strat_rt])
        wins = nets[nets > 0]
        losses = nets[nets < 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else float('nan')
        hol = np.array([r['hold_days'] for r in strat_rt])
        streak = cur = 0
        for n in nets:
            cur = cur + 1 if n < 0 else 0
            streak = max(streak, cur)
        costs = float(sum(r['buy_fee'] + r['sell_fee'] for r in strat_rt))
        exposure = sum(1 for c in pc if c > 0) / len(pc) * 100

        # Auditor gate: the ledger (every SELL incl. open marks) + initial
        # capital must equal the engine's final equity. Any real gap (drift in
        # the engine's equity labeling, missing fees, etc.) FAILS the audit.
        ledger_sum = CAPITAL + float(np.sum([r['net_pnl'] for r in roundtrips]))
        ledger_delta = float(final - ledger_sum)
        RECON_TOL = 1.0  # USD; residual is float/display rounding only
        recon_ok = abs(ledger_delta) <= RECON_TOL

        # benchmarks
        bench = {}
        for s in ('SPY', 'VTI'):
            b = bh_benchmark(conn, s, all_dates[0], all_dates[-1])
            if b:
                bench[s] = b
        eqw = []
        for tid in daily:
            dts = daily[tid]['dates']
            i0 = next((i for i, dt in enumerate(dts) if dt >= all_dates[0]), None)
            if i0 is None or not dts:
                continue
            eqw.append((float(daily[tid]['close'][-1]) / float(daily[tid]['close'][i0]) - 1) * 100)
        if eqw:
            m = float(np.mean(eqw))
            bench['EQW-universe'] = {'ret': m,
                                     'cagr': ((1 + m / 100) ** (365.0 / window_days) - 1) * 100}

        # ---- write artifacts ----
        out_trades = []
        for e in sorted(ev, key=lambda x: (x['exec_date'], x['kind'], x['symbol'])):
            r = dict(kind=e['kind'], trade_id=e['trade_id'], symbol=e['symbol'],
                     exec_date=e['exec_date'], exec_price=e['exec_price'],
                     shares=e['shares'], buy_date=e['buy_date'],
                     buy_price=e['buy_price'], buy_fee=e['buy_fee'],
                     sell_fee=e['sell_fee'], gross_pnl=e['gross_pnl'],
                     net_pnl=e['net_pnl'], net_return_pct=e['net_return_pct'],
                     hold_days=e['hold_days'], exit_reason=e['exit_reason'])
            r.update({('sig_' + k): v for k, v in (e['snap'] or {}).items()})
            out_trades.append(r)
        csv_write(os.path.join(out, f'{label}_trades.csv'), out_trades)

        for r in roundtrips:
            bs = next((e['snap'] for e in ev
                       if e['kind'] == 'BUY' and e['trade_id'] == r['trade_id']),
                      None) or {}
            ss = r.pop('snap', None) or {}
            for prefix, snap in (('sig_buy_', bs), ('sig_sell_', ss)):
                r.update({(prefix + k): snap.get(k)
                          for k in ('sig_date', 'sig_w_close', 'mtf_score',
                                    'emasma_score', 'early_score', 'near_score',
                                    'gap_w', 'atr_dist', 'freshness_days')})
        csv_write(os.path.join(out, f'{label}_roundtrips.csv'),
                  sorted(roundtrips, key=lambda r: r['trade_id']))

        pf_rows = [
            ('window_start', all_dates[0]), ('window_end', all_dates[-1]),
            ('trading_days', len(all_dates)), ('calendar_days', window_days),
            ('top_n', a.top_n), ('score', a.score), ('exit', a.exit),
            ('universe_is_etf', bool(a.etf)), ('tickers', a.tickers),
            ('initial_capital_usd', CAPITAL),
            ('final_equity_usd', round(final, 2)),
            ('total_return_pct', round((final / CAPITAL - 1) * 100, 2)),
            ('cagr_pct', round(cagr * 100, 2)),
            ('annualized_vol_pct', round(vol * 100, 2)),
            ('sharpe_ratio', round(sharpe, 2)),
            ('sortino_ratio', round(sortino, 2)),
            ('max_drawdown_pct', round(maxdd * 100, 2)),
            ('calmar_ratio', round(calmar, 2)),
            ('closed_trades', len(strat_rt)),
            ('open_at_sample_end', len(open_rt)),
            ('total_trades', len(roundtrips)),
            ('total_cost_usd', round(costs, 2)),
            ('win_rate_pct', round(len(wins) / len(nets) * 100, 2) if len(nets) else 'n/a'),
            ('profit_factor', round(pf, 2) if pf == pf else 'n/a'),
            ('avg_win_usd', round(float(wins.mean()), 2) if len(wins) else 'n/a'),
            ('avg_loss_usd', round(float(losses.mean()), 2) if len(losses) else 'n/a'),
            ('expectancy_usd_per_trade', round(float(nets.mean()), 2) if len(nets) else 'n/a'),
            ('best_trade_usd', round(float(nets.max()), 2) if len(nets) else 'n/a'),
            ('worst_trade_usd', round(float(nets.min()), 2) if len(nets) else 'n/a'),
            ('best_trade_pct', round(float(pcts.max()), 2) if len(pcts) else 'n/a'),
            ('worst_trade_pct', round(float(pcts.min()), 2) if len(pcts) else 'n/a'),
            ('avg_hold_trading_days', round(float(hol.mean()), 2) if len(hol) else 'n/a'),
            ('max_losing_streak', streak),
            ('days_invested_pct', round(exposure, 2)),
            ('avg_positions', round(float(np.mean(pc)), 2) if pc else 'n/a'),
            ('cost_per_side_bps', COST * 10000),
            ('ledger_sum_usd', round(ledger_sum, 2)),
            ('ledger_delta_usd', round(ledger_delta, 2)),
            ('ledger_reconciliation', 'PASS' if recon_ok else 'FAIL'),
            ('note_open_marks', 'end-of-sample positions valued at last close; '
             'no exit cost applied (engine MTMs at close)'),
            ('note_hourly_fields', 'hourly-derived snapshot fields (atr_dist, '
             'mtf/near score) blank before 2023-06-30 -- hourly data starts then'),
        ]
        for k, v in bench.items():
            pf_rows += [('benchmark_%s_return_pct' % k.lower().replace('-', '_'), round(v['ret'], 2)),
                        ('benchmark_%s_cagr_pct' % k.lower().replace('-', '_'), round(v['cagr'], 2))]
        csv_write(os.path.join(out, f'{label}_performance.csv'),
                  [{'metric': k, 'value': v} for k, v in pf_rows])

        r = pd.Series(eq).pct_change().dropna()
        r.index = pd.to_datetime(eq_dates[1:])
        piv = {}
        for ts, v in r.items():
            piv.setdefault((ts.year, ts.month), 1.0)
            piv[(ts.year, ts.month)] *= (1 + v)
        rows = [['year'] + ['%02d' % m for m in range(1, 13)] + ['annual_%']]
        for yr in sorted(set(d.year for d in all_dates)):
            row = [yr]
            for m in range(1, 13):
                row.append(round((piv.get((yr, m), 1.0) - 1) * 100, 2))
            poly = r[r.index.year == yr]
            row.append(round((float(np.prod(1 + poly.values)) - 1) * 100, 2) if len(poly) else '')
            rows.append(row)
        with open(os.path.join(out, f'{label}_monthly.csv'), 'w', newline='') as f:
            csv.writer(f).writerows(rows)

        sym_stats = []
        for sym in sorted(set(x['symbol'] for x in strat_rt)):
            ss = [x for x in strat_rt if x['symbol'] == sym]
            n2 = np.array([x['net_pnl'] for x in ss])
            p2 = np.array([x['net_return_pct'] for x in ss])
            sym_stats.append(dict(symbol=sym, trades=len(ss),
                                  win_rate_pct=round((n2 > 0).mean() * 100, 1),
                                  net_pnl_usd=round(float(n2.sum()), 2),
                                  avg_net_pnl_usd=round(float(n2.mean()), 2),
                                  avg_return_pct=round(float(p2.mean()), 2),
                                  best_trade_pct=round(float(p2.max()), 2),
                                  worst_trade_pct=round(float(p2.min()), 2),
                                  avg_hold_days=round(float(np.mean([x['hold_days'] for x in ss])), 1)))
        csv_write(os.path.join(out, f'{label}_by_symbol.csv'), sym_stats)

        csv_write(os.path.join(out, f'{label}_equity.csv'),
                  [{'date': d, 'equity': round(float(e), 2), 'positions': int(c)}
                   for d, e, c in zip(eq_dates, eq, pc)])

        if not cli.quiet:
            report(label, out, all_dates, final, cagr, sharpe, sortino, vol,
                   maxdd, calmar, nets, hol, streak, costs, exposure, pc,
                   bench, strat_rt, open_rt, ledger_sum, ledger_delta, recon_ok)
        if not recon_ok:
            print(f'[AUDIT] ✗ FAIL: ledger {ledger_sum:,.2f} vs final equity '
                  f'{final:,.2f} (delta {ledger_delta:+,.2f}) — not reconcilable')
            return 1
        if not cli.quiet:
            print('[AUDIT] ✓ ledger reconciliation PASS')
        return 0
    finally:
        conn.close()


def report(label, out, all_dates, final, cagr, sharpe, sortino, vol, maxdd,
           calmar, nets, hol, streak, costs, exposure, pc, bench, strat_rt, open_rt,
           ledger_sum, ledger_delta, recon_ok):
    nets = np.asarray(nets)
    w = nets[nets > 0]
    ls = nets[nets < 0]
    print('\n' + '=' * 74)
    print(f'  AUDIT REPORT — {label}')
    print('=' * 74)
    print(f'  Window      {all_dates[0]} -> {all_dates[-1]}  ({len(all_dates)} trading days)')
    print(f'  Final eq    ${final:,.2f}   Return {(final/CAPITAL-1)*100:+.2f}%   CAGR {cagr*100:.2f}%')
    print(f'  Sharpe {sharpe:.2f}  Sortino {sortino:.2f}  Vol {vol*100:.1f}%  '
          f'MaxDD {maxdd*100:.1f}%  Calmar {calmar:.2f}')
    print(f'  Win rate {(nets>0).sum()}/{len(nets)} ({((nets>0).mean()*100):.1f}%)  '
          f'avg win ${w.mean():,.0f}  avg loss ${ls.mean():,.0f}  expect ${nets.mean():,.0f}')
    if len(hol):
        print(f'  Avg hold {hol.mean():.1f} td | max losing streak {streak} | costs ${costs:,.2f}')
    print(f'  Exposure {exposure:.1f}% days invested, avg {np.mean(pc):.1f} positions '
          f'({len(open_rt)} open at sample end, {len(strat_rt)} closed)')
    print(f'  Ledger     ${ledger_sum:,.2f} vs final ${final:,.2f} '
          f'(delta {ledger_delta:+,.2f}) — {"PASS" if recon_ok else "FAIL"}')
    print('  Benchmarks')
    for k, v in bench.items():
        print(f'    {k:<18} {v["ret"]:+8.1f}%   CAGR {v["cagr"]:+.1f}%')
    print('-' * 74)
    for f in sorted(os.listdir(out)):
        if f.startswith(label):
            print(f'  {out}/{f}')


if __name__ == '__main__':
    sys.exit(main())