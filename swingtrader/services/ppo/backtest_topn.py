#!/usr/bin/env python3
"""Top-N rotation backtest using TOS WeeklyAndDailyPPO as the selector.

Mirrors mtf/backtest_topn_multitf.py construction for an apples-to-apples
comparison:
  - Precompute WDPPO = WeeklyPPO + DailyPPO (both scaled by weekly 130 EMA)
  - Candidates: WDPPO > 0 on the signal date
  - Rank by WDPPO desc, hold top-N, equal weight
  - Rebalance daily at next-day open, sell non-top-N, buy new entrants

Usage:
    python backtest_topn.py [--top-n 10] [--detail]
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
from datetime import date as dt_date
import numpy as np
import pandas as pd

import config
import db

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
WARMUP = config.WARMUP
MIN_TICKERS = 400


def _last_idx_before(idx_map, dates, target):
    xi = idx_map.get(target)
    if xi is not None:
        return xi
    for i in range(len(dates) - 1, -1, -1):
        if dates[i] <= target:
            return i
    return None


def precompute(conn, tickers):
    """Compute daily-aligned WDPPO arrays for every ticker."""
    weekly = db.bulk_load_weekly(conn, [t[0] for t in tickers])
    daily = db.bulk_load_daily(conn, [t[0] for t in tickers])

    pre = {}
    for tid, sym in tickers:
        w = weekly.get(tid)
        d = daily.get(tid)
        if not w or not d or len(d['close']) < WARMUP + 10:
            continue
        wc = pd.Series(w['close'])
        wf = wc.ewm(span=config.WEEKLY_PPO_FAST, adjust=False).mean().to_numpy()
        ws = wc.ewm(span=config.WEEKLY_PPO_SLOW, adjust=False).mean().to_numpy()

        dc = pd.Series(d['close'])
        df = dc.ewm(span=config.DAILY_PPO_FAST, adjust=False).mean().to_numpy()
        ds = dc.ewm(span=config.DAILY_PPO_SLOW, adjust=False).mean().to_numpy()

        w_sorted = sorted(w['dates'])
        wpos = -1
        wdppo = np.full(len(d['dates']), np.nan)
        for i, dd in enumerate(d['dates']):
            while wpos + 1 < len(w_sorted) and w_sorted[wpos + 1] <= dd:
                wpos += 1
            if wpos >= 0 and not np.isnan(ws[wpos]):
                wdppo[i] = ((wf[wpos] - ws[wpos]) / ws[wpos] * 100
                            + (df[i] - ds[i]) / ws[wpos] * 100)

        pre[tid] = dict(
            symbol=sym,
            dates=d['dates'],
            open=np.array([float(x) for x in d['open']], dtype=np.float64),
            close=np.array(d['close'], dtype=np.float64),
            wdppo=wdppo,
        )
    return pre


def main():
    parser = argparse.ArgumentParser(description='Top-N WeeklyAndDailyPPO rotation backtest')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--detail', action='store_true')
    parser.add_argument('--min-tickers', type=int, default=MIN_TICKERS,
                        help='Min tickers with data to count a date (partial-date exclusion)')
    parser.add_argument('--start', type=str, default=None,
                        help='Start backtest on/after YYYY-MM-DD (positions start empty)')
    args = parser.parse_args()

    conn = db.get_conn()
    try:
        tickers = db.get_all_tickers(conn, is_etf=False)
        print(f'\n  Universe: {len(tickers)} stocks')
        pre = precompute(conn, tickers)
        print(f'  Precomputed: {len(pre)} tickers\n')

        # Per-ticker date->index maps
        idx_map = {tid: {dt: i for i, dt in enumerate(p['dates'])} for tid, p in pre.items()}
        date_sets = {tid: set(p['dates']) for tid, p in pre.items()}

        # Trading calendar: union of all daily dates, exclude partial days
        all_dates = sorted(set().union(*date_sets.values()))
        all_dates = [d for d in all_dates
                     if sum(1 for s in date_sets.values() if d in s) >= args.min_tickers]
        if not all_dates:
            print('  No valid dates.')
            return
        skip = 0
        for ri, d in enumerate(all_dates):
            if sum(1 for s in date_sets.values() if d in s) >= args.min_tickers:
                skip = ri
                break
        all_dates = all_dates[skip:]
        print(f'  Period: {all_dates[0]} to {all_dates[-1]} ({len(all_dates)} days)')

        # Warmup: require tickers with enough daily bars on a date
        for ri, d in enumerate(all_dates):
            cnt = 0
            for tid, p in pre.items():
                xi = idx_map[tid].get(d)
                if xi is not None and xi >= WARMUP:
                    cnt += 1
            if cnt >= args.min_tickers:
                all_dates = all_dates[ri:]
                break
        print(f'  Warmup from {all_dates[0]}\n')

        if args.start:
            start = dt_date.fromisoformat(args.start)
            all_dates = [d for d in all_dates if d >= start]
            print(f'  Starting on/after {start}\n')

        positions = {}
        cash = CAPITAL
        equity_curve = []
        trade_log = []

        for ri in range(len(all_dates)):
            sig_date = all_dates[ri]

            candidates = []
            for tid, p in pre.items():
                di = idx_map[tid].get(sig_date)
                if di is None or di < 1:
                    continue
                v = p['wdppo'][di]
                if np.isnan(v) or v <= 0:
                    continue
                candidates.append((tid, v))

            if not candidates:
                pf_val = cash
                for tid in list(positions):
                    xi = _last_idx_before(idx_map[tid], pre[tid]['dates'], sig_date)
                    if xi is not None:
                        pf_val += positions[tid]['shares'] * pre[tid]['close'][xi]
                equity_curve.append(pf_val)
                continue

            candidates.sort(key=lambda x: -x[1])
            selected = {c[0] for c in candidates[:args.top_n]}

            exec_idx = ri + 1
            if exec_idx >= len(all_dates):
                break
            exec_date = all_dates[exec_idx]

            for tid in list(positions):
                if tid not in selected:
                    p = pre[tid]
                    xi = _last_idx_before(idx_map[tid], p['dates'], exec_date)
                    if xi is None or xi >= len(p['open']):
                        continue
                    sp = float(p['open'][xi])
                    pos = positions[tid]
                    cash += pos['shares'] * sp * (1 - COST)
                    ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                    trade_log.append((exec_date, pos['symbol'], 'SELL', pos['shares'], sp, ret))
                    if args.detail:
                        print(f'  {exec_date} SELL {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}')
                    del positions[tid]

            to_buy = [tid for tid in selected if tid not in positions]
            if to_buy:
                per_stock = cash / len(to_buy)
                for tid in to_buy:
                    p = pre[tid]
                    xi = _last_idx_before(idx_map[tid], p['dates'], exec_date)
                    if xi is None or xi >= len(p['open']):
                        continue
                    bp = float(p['open'][xi])
                    shares = (per_stock / bp) * (1 - COST)
                    cash -= shares * bp
                    positions[tid] = dict(shares=shares, entry_price=bp, symbol=p['symbol'])
                    trade_log.append((exec_date, p['symbol'], 'BUY', shares, bp, None))
                    if args.detail:
                        print(f'  {exec_date} BUY  {p["symbol"]} {shares:.2f} @ ${bp:.2f}')

            pf_val = cash
            for tid, pos in positions.items():
                p = pre[tid]
                xi = _last_idx_before(idx_map[tid], p['dates'], exec_date)
                if xi is not None:
                    pf_val += pos['shares'] * p['close'][xi]
            equity_curve.append(pf_val)

        if not equity_curve:
            print('  No trades.')
            return
        total_ret = (equity_curve[-1] - CAPITAL) / CAPITAL
        eq_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(eq_arr)
        dd = np.max((peak - eq_arr) / peak)

        all_sells = [t for t in trade_log if t[2] == 'SELL']
        all_buys = [t for t in trade_log if t[2] == 'BUY']
        winners = [t for t in all_sells if t[5] is not None and t[5] > 0]
        losers = [t for t in all_sells if t[5] is not None and t[5] <= 0]
        sells = len(all_sells)
        buys = len(all_buys)
        wr = len(winners) / sells * 100 if sells else 0

        print(f'\n{"="*80}')
        print(f'  TOP-{args.top_n} WEEKLY+DAILY PPO ROTATION')
        print(f'  Selector: WDPPO = WeeklyPPO + DailyPPO (EMA{config.WEEKLY_PPO_FAST}/{config.WEEKLY_PPO_SLOW} wk, '
              f'EMA{config.DAILY_PPO_FAST}/{config.DAILY_PPO_SLOW} dy, denom wk EMA{config.WEEKLY_PPO_SLOW})')
        print(f'  Period: {all_dates[0]} to {all_dates[-1]}')
        print(f'{"="*80}')
        print(f'  Initial: ${CAPITAL:,.0f}')
        print(f'  Final:   ${equity_curve[-1]:,.0f}')
        print(f'  Return:  {total_ret*100:+.2f}%')
        print(f'  Max DD:  {dd*100:.1f}%')
        print(f'  Trades:  {sells} sells / {buys} buys')
        print(f'  Win:     {len(winners)} ({wr:.0f}%)')
        print()

    finally:
        conn.close()


if __name__ == '__main__':
    main()
