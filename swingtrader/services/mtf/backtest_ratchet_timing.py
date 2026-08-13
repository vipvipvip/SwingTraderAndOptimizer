#!/usr/bin/env python3
"""Ratchet-stop timing backtest on the core ETFs (QQQ / VTI / VTV).

Rule: be long an ETF only while its close is above the peak-anchored ratchet
stop (highest close since entry - 2xATR) on ALL THREE timeframes — weekly,
daily, and hourly. Any timeframe breaking its stop -> flat (100% cash for that
name). Re-enter when all three close back above their stops; on re-entry the
peak/ratchet reset to the new entry prices (matches the live ratchet, whose
peak is 'since entry').

Portfolio: equal-weight the ETFs that pass on each decision day; 100% cash
when none pass. Executes at next-day open. Benchmark: equal-weight buy &
hold of the trio over the same window.

Run `--no-reset` for the pure monotone ratchet (peak/stop never reset on
re-entry, so a crashed name must recover near its pre-crash high before it can
re-enter).

Usage:
  python backtest_ratchet_timing.py
  python backtest_ratchet_timing.py --no-reset
  python backtest_ratchet_timing.py --detail
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np

import config
import db as db_module

CORE = ['QQQ', 'VTI', 'VTV']
MULT = config.RATCHET_ATR_MULT
COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
TS_START = '2023-06-30'
TFS = ('weekly', 'daily', 'hourly')
TABLE = {'weekly': 'tbl_scanner_tickers',
         'daily': 'tbl_scanner_tickers_daily',
         'hourly': 'tbl_scanner_tickers_1hour'}


def load(conn, sym, tf):
    table = TABLE[tf]
    date_expr = 't.date' if tf == 'hourly' else 't.date::date'
    cur = conn.cursor()
    cur.execute(f"""
        SELECT {date_expr}, t.close, t.atr_stop FROM {table} t
        JOIN tbl_stock_tickers s ON s.id = t.ticker_id
        WHERE s.symbol=%s AND s.is_etf=true AND t.date >= '{TS_START}'
        ORDER BY t.date ASC""", (sym,))
    rows = cur.fetchall()
    cur.close()
    dates = [r[0].date() if hasattr(r[0], 'date') else r[0] for r in rows]
    close = np.array([float(r[1]) for r in rows], dtype=np.float64)
    atr = np.array([
        (float(r[1]) - float(r[2])) / 2.0 if r[2] and float(r[2]) > 0 else 0.0
        for r in rows], dtype=np.float64)
    return dates, close, atr


def tf_positions(daily_dates, tf_dates):
    """For each daily date, the index of the last tf bar on/before it."""
    pos = np.full(len(daily_dates), -1, dtype=int)
    j = 0
    for i, d in enumerate(daily_dates):
        while j < len(tf_dates) - 1 and tf_dates[j + 1] <= d:
            j += 1
        if tf_dates[j] <= d:
            pos[i] = j
    return pos


def print_stats(equity, dates, n_pos, label, detail=False):
    total = (equity[-1] - CAPITAL) / CAPITAL
    arr = np.array(equity)
    peak = np.maximum.accumulate(arr)
    dd = np.max((peak - arr) / peak)
    invested = sum(1 for c in n_pos if c > 0)
    print(f'\n  {label}')
    print(f'  {"Final":>14} ${equity[-1]:>12,.0f}')
    print(f'  {"Return":>14} {total*100:>+11.2f}%')
    print(f'  {"Max DD":>14} {dd*100:>11.1f}%')
    print(f'  {"Exposure":>14} {100*invested/max(1,len(n_pos)):>11.0f}%  '
          f'({invested}/{len(n_pos)} days invested)')
    if detail:
        by_year = {}
        prev = CAPITAL
        last_y = None
        for i, d in enumerate(dates):
            if last_y is not None and d.year != last_y:
                by_year[last_y] = (arr[i - 1] - prev) / prev
                prev = arr[i - 1]
            last_y = d.year
        if last_y is not None:
            by_year[last_y] = (arr[-1] - prev) / prev
        for y in sorted(by_year):
            print(f'  {y:>6} return: {by_year[y]*100:+8.2f}%')
    return total, dd


def main():
    ap = argparse.ArgumentParser(description='Ratchet-stop timing backtest on core ETFs')
    ap.add_argument('--no-reset', action='store_true',
                    help='pure monotone ratchet: peak/stop never reset on re-entry')
    ap.add_argument('--tfs', default='weekly,daily,hourly',
                    help='comma-separated timeframes required (default weekly,daily,hourly)')
    ap.add_argument('--mult', type=float, default=MULT,
                    help=f'ATR multiplier for the ratchet stop (default {MULT})')
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()
    tfs = tuple(t.strip() for t in args.tfs.split(',') if t.strip())
    for t in tfs:
        if t not in TFS:
            raise SystemExit(f'unknown timeframe {t!r} — choose from {", ".join(TFS)}')

    conn = db_module.get_conn()
    try:
        bars = {}
        for sym in CORE:
            bars[sym] = {tf: load(conn, sym, tf) for tf in TFS}

        daily_dates = bars['QQQ']['daily'][0]
        print(f'  Window: {daily_dates[0]} -> {daily_dates[-1]} '
              f'({len(daily_dates)} trading days), mult={args.mult}, reset={not args.no_reset}, '
              f'tfs={tfs}')

        for sym in CORE:
            for tf in tfs:
                dates, close, atr = bars[sym][tf]
                n_bad = int(np.sum(atr <= 0))
                if n_bad:
                    print(f'  WARN {sym} {tf}: {n_bad} bars without ATR')

        tfpos = {sym: {tf: tf_positions(daily_dates, bars[sym][tf][0]) for tf in TFS}
                 for sym in CORE}

        state = {}
        for sym in CORE:
            state[sym] = {'long': False, 'peak': {tf: 0.0 for tf in tfs},
                          'ratchet': {tf: 0.0 for tf in tfs},
                          'tfseen': {tf: -1 for tf in tfs},
                          'entries': 0, 'flats': 0, 'long_days': 0,
                          'break_tf': {tf: 0 for tf in tfs}}
        long_hist = {sym: np.zeros(len(daily_dates), dtype=bool) for sym in CORE}

        first_valid = None
        for i, d in enumerate(daily_dates):
            valid = {}
            for sym in CORE:
                if all(tfpos[sym][tf][i] >= 0 for tf in tfs):
                    cs = {tf: float(bars[sym][tf][1][tfpos[sym][tf][i]]) for tf in tfs}
                    at = {tf: float(bars[sym][tf][2][tfpos[sym][tf][i]]) for tf in tfs}
                    if all(at[tf] > 0 for tf in tfs):
                        valid[sym] = (cs, at)
            if first_valid is None:
                if valid:
                    first_valid = i
                else:
                    continue
            for sym, (cs, at) in valid.items():
                st = state[sym]
                if not st['long'] and st['entries'] == 0:
                    st['long'] = True
                    st['entries'] = 1
                    for tf in tfs:
                        st['peak'][tf] = cs[tf]
                        st['ratchet'][tf] = cs[tf] - args.mult * at[tf]
                        st['tfseen'][tf] = tfpos[sym][tf][i]
            for sym, (cs, at) in valid.items():
                st = state[sym]
                if not st['long']:
                    continue
                for tf in tfs:
                    if tfpos[sym][tf][i] != st['tfseen'][tf]:
                        st['tfseen'][tf] = tfpos[sym][tf][i]
                        st['peak'][tf] = max(st['peak'][tf], cs[tf])
                        st['ratchet'][tf] = max(st['ratchet'][tf],
                                                 st["peak"][tf] - args.mult * at[tf])
                broken = [tf for tf in tfs if cs[tf] <= st['ratchet'][tf]]
                if broken:
                    st['long'] = False
                    st['flats'] += 1
                    st['break_tf'][broken[0]] += 1
                else:
                    st['long_days'] += 1
            for sym, (cs, at) in valid.items():
                st = state[sym]
                if st['long'] or st['entries'] == 0:
                    continue
                if all(st['ratchet'][tf] > 0 and cs[tf] > st['ratchet'][tf]
                       for tf in tfs):
                    st['long'] = True
                    st['entries'] += 1
                    for tf in tfs:
                        st['peak'][tf] = cs[tf]
                        if not args.no_reset:
                            st['ratchet'][tf] = cs[tf] - args.mult * at[tf]
                        st['tfseen'][tf] = tfpos[sym][tf][i]
            for sym in CORE:
                long_hist[sym][i] = state[sym]['long']

        # -- portfolio loop --
        positions = {}
        cash = CAPITAL
        equity_curve = []
        equity_dates = []
        pos_counts = []
        trade_log = []

        start = first_valid if first_valid is not None else 0
        for i in range(start, len(daily_dates)):
            sig_date = daily_dates[i]
            passers = {sym for sym in CORE if long_hist[sym][i]}

            exec_idx = i + 1
            if exec_idx >= len(daily_dates):
                break
            exec_date = daily_dates[exec_idx]

            for sym in list(positions):
                if sym in passers:
                    continue
                b = bars[sym]['daily']
                xi = tfpos[sym]['daily'][exec_idx]
                if xi < 0:
                    continue
                sp = float(b[1][xi])
                sh = positions[sym]
                cash += sh * sp * (1 - COST)
                trade_log.append((exec_date, sym, 'SELL', sh, sp))
                del positions[sym]

            to_buy = [sym for sym in passers if sym not in positions]
            if to_buy:
                per = cash / len(to_buy)
                for sym in to_buy:
                    b = bars[sym]['daily']
                    xi = tfpos[sym]['daily'][exec_idx]
                    if xi < 0:
                        continue
                    bp = float(b[1][xi])
                    shares = (per / bp) * (1 - COST)
                    cash -= shares * bp
                    positions[sym] = shares
                    trade_log.append((exec_date, sym, 'BUY', shares, bp))

            pf_val = cash
            for sym, sh in positions.items():
                b = bars[sym]['daily']
                xi = tfpos[sym]['daily'][exec_idx]
                if xi >= 0:
                    pf_val += sh * float(b[1][xi])
            equity_curve.append(pf_val)
            equity_dates.append(exec_date)
            pos_counts.append(len(positions))

        bh_close = {}
        for sym in CORE:
            bh_close[sym] = [float(bars[sym]['daily'][1][tfpos[sym]['daily'][i]])
                             for i in range(start, len(daily_dates))]
        bh_equity = []
        bh_dates = daily_dates[start:]
        base = np.array([bh_close[s][0] for s in CORE])
        base_idx = {s: k for k, s in enumerate(CORE)}
        for j in range(len(bh_dates)):
            bh_equity.append(sum(CAPITAL / 3.0 * bh_close[s][j] / base[base_idx[s]]
                                 for s in CORE))

        print('\n' + '=' * 70)
        print(f'  RATCHET-ALL-3 TIMING on {", ".join(CORE)}')
        print(f'  Rule: long iff close > peak-{args.mult}xATR stop on all three timeframes')
        print(f'        reset-on-re-entry: {not args.no_reset} | cost {COST*100:.2f}%')
        print('=' * 70)

        strat_ret, strat_dd = print_stats(equity_curve, equity_dates, pos_counts,
                                          'STRATEGY (ratchet all-3)', args.detail)
        bh_ret, bh_dd = print_stats(bh_equity, bh_dates, [3] * len(bh_dates),
                                    'BENCHMARK (equal-weight buy & hold)', args.detail)

        print('\n  PER-ETF')
        print(f'  {"ETF":<6}{"entries":>8}{"flats":>8}{"days long":>12}'
              f'{"% time":>8}  break source')
        for sym in CORE:
            st = state[sym]
            pct = 100 * st['long_days'] / max(1, len(bh_dates))
            bt = ', '.join(f'{tf}:{st["break_tf"][tf]}' for tf in tfs
                           if st['break_tf'][tf] > 0) or 'none'
            print(f'  {sym:<6}{st["entries"]:>8}{st["flats"]:>8}{st["long_days"]:>12}'
                  f'{pct:>7.0f}%  {bt}')

        sells = [t for t in trade_log if t[2] == 'SELL']
        buys = [t for t in trade_log if t[2] == 'BUY']
        print(f'\n  Trades: {len(buys)} buys / {len(sells)} sells')
        print(f'  Cash stretches: '
              f'{sum(1 for c in pos_counts if c == 0)}/{len(pos_counts)} days 100% cash')

        # Regression vs B&H
        end = min(len(equity_curve), len(bh_equity))
        arr_s = np.array(equity_curve[:end])
        arr_b = np.array(bh_equity[:end])
        print(f'\n  vs B&H: strategy {strat_ret*100:+.1f}% (DD {strat_dd*100:.1f}%) vs '
              f'B&H {bh_ret*100:+.1f}% (DD {bh_dd*100:.1f}%)')
        print(f'  CAGR: strategy {((equity_curve[-1]/CAPITAL)**(252/end)-1)*100:+.1f}% vs '
              f'B&H {((bh_equity[-1]/CAPITAL)**(252/end)-1)*100:+.1f}%')

    finally:
        conn.close()


if __name__ == '__main__':
    main()
