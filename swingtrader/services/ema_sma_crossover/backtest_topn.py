#!/usr/bin/env python3
"""Top-N scanner backtest: rebalance into top N stocks by Long scanner score.

Score (matches ScannerController::indexLong):
  score = (macdCross ? 5 : 0) + (ppoCross ? 5 : 0) + min(5, max(0, int(stop_dist_pct)))
  Sorted: rule ASC, score DESC, macd_hist DESC
  Filter: close > atr_stop AND at least one MACD/PPO zero-line cross

Rebalance: sell non-top-N, buy new entrants at next-day open, equal weight.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np
from datetime import datetime
from collections import OrderedDict

import config
import db as db_module

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
WARMUP = 50


def load_ticker_data(conn, table):
    with conn.cursor() as cur:
        cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled=true ORDER BY symbol')
        tickers = cur.fetchall()
    print(f'Loading {len(tickers)} tickers from {table}...')

    data = {}
    count = 0
    for tid, sym in tickers:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT date, open, close, macd_histogram, ppo_histogram, atr_stop '
                f'FROM {table} WHERE ticker_id = %s ORDER BY date ASC', (tid,))
            rows = cur.fetchall()
        if len(rows) < WARMUP:
            continue
        dates = [r[0] for r in rows]
        opened = np.array([float(r[1]) for r in rows], dtype=np.float64)
        closed = np.array([float(r[2]) for r in rows], dtype=np.float64)
        macd = np.array([float(r[3]) if r[3] is not None else np.nan for r in rows], dtype=np.float64)
        ppo = np.array([float(r[4]) if r[4] is not None else np.nan for r in rows], dtype=np.float64)
        atr = np.array([float(r[5]) if r[5] is not None else 0.0 for r in rows], dtype=np.float64)
        data[tid] = dict(symbol=sym, dates=dates, open=opened, close=closed,
                         macd_hist=macd, ppo_hist=ppo, atr_stop=atr)
        count += 1
    print(f'  {count} tickers loaded')
    return tickers, data


def compute_score(d, i):
    if i < 1 or i >= len(d['close']):
        return None
    c, m, pm, p, pp, a = (d['close'][i], d['macd_hist'][i], d['macd_hist'][i - 1],
                          d['ppo_hist'][i], d['ppo_hist'][i - 1], d['atr_stop'][i])
    if any(np.isnan(x) for x in (c, m, pm, p, pp, a)):
        return None
    if c <= a or c <= 0:
        return None
    mc = m > 0 and pm <= 0
    pc = p > 0 and pp <= 0
    if not mc and not pc:
        return None
    sd = min(5, max(0, int((c - a) / c * 100)))
    score = (5 if mc else 0) + (5 if pc else 0) + sd
    rule = 1 if (mc and pc) else (2 if mc else 3)
    return (score, rule, float(m))


def main():
    parser = argparse.ArgumentParser(description='Top-N scanner backtest')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--rebalance', choices=['daily', 'weekly'], default='daily')
    parser.add_argument('--timeframe', choices=['daily', 'weekly'], default='daily')
    parser.add_argument('--detail', action='store_true', help='Show per-ticker log')
    args = parser.parse_args()

    table = {'daily': 'tbl_scanner_tickers_daily', 'weekly': 'tbl_scanner_tickers'}[args.timeframe]

    db_module.init_db()
    conn = db_module.get_conn()
    try:
        tickers, data = load_ticker_data(conn, table)

        # Build date index maps
        date_idx = {}
        for tid, d in data.items():
            date_idx[tid] = {dt: i for i, dt in enumerate(d['dates'])}

        # All dates sorted, skip warmup
        all_dates = sorted(set().union(*[set(d['dates']) for d in data.values()]))
        trading_dates = all_dates[WARMUP:]

        step = 5 if args.rebalance == 'weekly' else 1
        period_label = f'{args.rebalance} (every {step} trading day{"s" if step > 1 else ""})'

        print(f'  Date range: {all_dates[0]} to {all_dates[-1]} ({len(trading_dates)} raw dates)')
        # Find first date where enough tickers have data (avoid sparse early years)
        MIN_TICKERS = 400
        skip = 0
        for ri, d in enumerate(trading_dates):
            cnt = sum(1 for td in data.values() if d in td['dates'])
            if cnt >= MIN_TICKERS:
                skip = ri
                break
        trading_dates = trading_dates[skip:]
        print(f'  Data coverage: {MIN_TICKERS}+ tickers from {trading_dates[0]}')
        print(f'  Running: top {args.top_n}, rebalance {period_label}...\n')

        # Portfolio state
        positions = {}  # tid -> {'shares': float, 'entry_price': float, 'symbol': str}
        cash = CAPITAL
        equity_curve = []
        trade_log = []  # (date, symbol, side, shares, price, return)

        for ri in range(0, len(trading_dates), step):
            sig_date = trading_dates[ri]

            # --- 1. Compute scores for all tickers at sig_date ---
            candidates = []
            for tid, d in data.items():
                i = date_idx[tid].get(sig_date)
                if i is None:
                    continue
                r = compute_score(d, i)
                if r is None:
                    continue
                score, rule, macd_h = r
                candidates.append((tid, d['symbol'], score, rule, macd_h))
            if not candidates:
                # If no candidates, still mtm equity
                cur_val = cash + sum(
                    positions[tid]['shares'] * float(data[tid]['close'][date_idx[tid].get(sig_date, -1)])
                    for tid in list(positions) if date_idx[tid].get(sig_date) is not None
                )
                equity_curve.append(cur_val)
                continue

            # Sort by rule ASC, score DESC, macd_hist DESC
            candidates.sort(key=lambda x: (x[3], -x[2], -x[4]))
            selected = {(c[0], c[1]) for c in candidates[:args.top_n]}
            selected_ids = {c[0] for c in selected}

            # --- 2. Find next trading day for execution ---
            exec_idx = ri + 1
            if exec_idx >= len(trading_dates):
                break
            exec_date = trading_dates[exec_idx]

            # mtm portfolio before rebalance (at sig_date)
            pf_val = cash
            for tid in list(positions):
                p = date_idx[tid].get(sig_date)
                if p is not None:
                    pf_val += positions[tid]['shares'] * float(data[tid]['close'][p])

            # --- 3. SELL positions not in top N ---
            to_sell = [tid for tid in positions if tid not in selected_ids]
            for tid in to_sell:
                d = data.get(tid)
                if d is None:
                    continue
                xi = date_idx[tid].get(exec_date)
                if xi is None or xi >= len(d['open']):
                    continue
                sp = float(d['open'][xi])
                pos = positions[tid]
                proceeds = pos['shares'] * sp * (1 - COST)
                ret = (sp - pos['entry_price']) / pos['entry_price'] - COST
                cash += proceeds
                trade_log.append((exec_date, pos['symbol'], 'SELL', pos['shares'], sp, ret))
                if args.detail:
                    print(f'  {exec_date} SELL {pos["symbol"]} {pos["shares"]:.2f} @ ${sp:.2f}  ret={ret*100:+.2f}%')
                del positions[tid]

            # --- 4. BUY new top N entries ---
            existing = set(positions.keys())
            to_buy = [(tid, sym) for tid, sym in selected if tid not in existing]
            if to_buy:
                per_stock = cash / len(to_buy)
                for tid, sym in to_buy:
                    d = data.get(tid)
                    if d is None:
                        continue
                    xi = date_idx[tid].get(exec_date)
                    if xi is None or xi >= len(d['open']):
                        continue
                    bp = float(d['open'][xi])
                    shares = (per_stock / bp) * (1 - COST)
                    cost = shares * bp
                    cash -= cost
                    positions[tid] = dict(shares=shares, entry_price=bp, symbol=sym)
                    trade_log.append((exec_date, sym, 'BUY', shares, bp, None))
                    if args.detail:
                        print(f'  {exec_date} BUY  {sym} {shares:.2f} @ ${bp:.2f}')

            # --- 5. Record equity at exec_date close ---
            pf_val = cash
            for tid, pos in positions.items():
                d = data.get(tid)
                if d is None:
                    continue
                xi = date_idx[tid].get(exec_date)
                if xi is not None and xi < len(d['close']):
                    pf_val += pos['shares'] * float(d['close'][xi])
            equity_curve.append(pf_val)

        # --- RESULTS ---
        if not equity_curve:
            print('No trades.')
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

        avg_win = np.mean([t[5] for t in winners]) * 100 if winners else 0
        avg_loss = np.mean([t[5] for t in losers]) * 100 if losers else 0
        wr = len(winners) / sells * 100 if sells else 0
        lr = len(losers) / sells * 100 if sells else 0

        print(f'\n{"="*80}')
        print(f'  TOP-{args.top_n} SCANNER BACKTEST  ({period_label})')
        print(f'  Timeframe: {args.timeframe}  |  Period: {trading_dates[0]} to {trading_dates[-1]}')
        print(f'{"="*80}')
        print(f'  Initial capital: ${CAPITAL:,.0f}')
        print(f'  Final equity:    ${equity_curve[-1]:,.0f}')
        print(f'  Total return:    {total_ret*100:+.2f}%')
        print(f'  Max drawdown:    {dd*100:.1f}%')
        print(f'  Trades:          {sells} sells / {buys} buys')
        print(f'  Winners:         {len(winners)} ({wr:.0f}%)  avg +{avg_win:+.2f}%')
        print(f'  Losers:          {len(losers)} ({lr:.0f}%)  avg {avg_loss:+.2f}%')
        print(f'  Avg holding period:  {len(trading_dates) / max(1, sells) * step:.0f} days')
        print()

        # Monthly returns
        monthly = {}
        for i, v in enumerate(equity_curve):
            if i == 0:
                continue
            if isinstance(trading_dates[i * 1 if step == 1 else min(i * step, len(trading_dates) - 1)], datetime):
                d = trading_dates[i * 1 if step == 1 else min(i * step, len(trading_dates) - 1)]
            else:
                d = trading_dates[min(i * step if i * step < len(trading_dates) else len(trading_dates) - 1, len(trading_dates) - 1)]
            m_key = f'{d.year}-{d.month:02d}'
            monthly.setdefault(m_key, []).append((i, v))

        if monthly:
            print(f'\n  Monthly returns:')
            prev_idx = 0
            prev_val = CAPITAL
            for m_key in sorted(monthly):
                entries = monthly[m_key]
                last_idx, last_val = entries[-1]
                m_ret = (last_val - prev_val) / prev_val
                print(f'    {m_key}: {m_ret*100:+7.2f}%  (${prev_val:,.0f} → ${last_val:,.0f})')
                prev_val = last_val
                prev_idx = last_idx

    finally:
        conn.close()


if __name__ == '__main__':
    main()
