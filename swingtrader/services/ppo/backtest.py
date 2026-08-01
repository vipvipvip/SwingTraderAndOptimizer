#!/usr/bin/env python3
"""Backtest the TOS WeeklyAndDailyPPO strategy (Vitaly Apirine).

WeeklyAndDailyPPO computed exactly like ThinkOrSwim's study:
    Weekly PPO = (EMA60_wk - EMA130_wk) / EMA130_wk * 100
    Daily  PPO = (EMA12_dy - EMA26_dy) / EMA130_wk * 100   (denom = weekly 130 EMA)
    WeeklyAndDailyPPO = Weekly PPO + Daily PPO

Signal (state machine, long-only, next-day-open fills):
    LONG  when WeeklyAndDailyPPO > 0
    EXIT  when WeeklyAndDailyPPO <= 0
Edit `daily_signal()` to change entry/exit logic.

Usage:
    python backtest.py [--universe etf|stocks] [--limit N] [--random]
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
import numpy as np
import pandas as pd

import config
import db

COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL


def daily_signal(wdppo):
    """State-machine signal on a single daily bar.

    wdppo: WeeklyAndDailyPPO value (NaN until weekly 130-EMA warmup done)

    Returns 'long', 'out', or None (not enough data yet).
    """
    if np.isnan(wdppo):
        return None
    if wdppo > 0:
        return 'long'
    return 'out'


def run_ticker_bt(sym, wdata, ddata):
    """Run the state machine on one ticker. Returns a result dict or None."""
    wk = pd.Series(wdata['close'])
    w_ema_fast = wk.ewm(span=config.WEEKLY_PPO_FAST, adjust=False).mean().to_numpy()
    w_ema_slow = wk.ewm(span=config.WEEKLY_PPO_SLOW, adjust=False).mean().to_numpy()

    dy = pd.Series(ddata['close'])
    d_ema_fast = dy.ewm(span=config.DAILY_PPO_FAST, adjust=False).mean().to_numpy()
    d_ema_slow = dy.ewm(span=config.DAILY_PPO_SLOW, adjust=False).mean().to_numpy()

    w_dates = wdata['dates']
    w_sorted_dates = sorted(w_dates)
    w_idx = {d: i for i, d in enumerate(w_dates)}

    n = len(ddata['dates'])
    position = False
    entry_price = None
    shares = 0.0
    capital = CAPITAL          # equity value in dollars (cash when flat)
    equity = []                # portfolio value in dollars after each bar
    dates_out = []
    trades = []                # (date, action, price)
    start_close_idx = None     # first daily bar with a valid signal

    for i in range(n):
        d = ddata['dates'][i]
        close = float(ddata['close'][i])

        wi = w_idx.get(d)
        if wi is None:
            for j in range(len(w_sorted_dates) - 1, -1, -1):
                if w_sorted_dates[j] <= d:
                    wi = w_idx[w_sorted_dates[j]]
                    break

        if wi is not None and not np.isnan(w_ema_slow[wi]):
            weekly_ppo = (w_ema_fast[wi] - w_ema_slow[wi]) / w_ema_slow[wi] * 100
            daily_ppo = (d_ema_fast[i] - d_ema_slow[i]) / w_ema_slow[wi] * 100
            wdppo = weekly_ppo + daily_ppo
        else:
            wdppo = np.nan

        sig = daily_signal(wdppo)
        if sig is None:
            continue

        if start_close_idx is None:
            start_close_idx = i

        if sig == 'long' and not position:
            if i + 1 >= n:
                break
            op = float(ddata['open'][i + 1])
            if op <= 0 or np.isnan(op):
                continue
            position = True
            entry_price = op
            shares = capital / op
            capital = shares * op
            trades.append((ddata['dates'][i + 1], 'BUY', op))
            equity.append(capital)
            dates_out.append(ddata['dates'][i + 1])
            continue

        if sig == 'out' and position:
            if i + 1 >= n:
                break
            op = float(ddata['open'][i + 1])
            if op <= 0 or np.isnan(op):
                continue
            position = False
            capital = shares * op * (1 - COST)
            shares = 0.0
            trades.append((ddata['dates'][i + 1], 'SELL', op))
            equity.append(capital)
            dates_out.append(ddata['dates'][i + 1])
            continue

        equity.append(shares * close if position else capital)
        dates_out.append(d)

    # Close any open position at last close for a clean comparison
    if position:
        ret = (close - entry_price) / entry_price - COST
        capital = shares * close * (1 - COST)
        shares = 0.0
        trades.append((d, 'SELL', close))

    # Buy & hold benchmark aligned to the SAME window the strategy traded:
    # invest CAPITAL at the first valid-signal close, hold to the last bar.
    bh_equity = None
    if start_close_idx is not None and len(equity) > 0:
        closes_arr = np.array(ddata['close'], dtype=np.float64)
        end_idx = min(start_close_idx + len(equity), len(closes_arr))
        if end_idx > start_close_idx and closes_arr[start_close_idx] > 0:
            bh_equity = CAPITAL * closes_arr[start_close_idx:end_idx] / closes_arr[start_close_idx]

    eq = np.array(equity, dtype=np.float64)
    if len(eq) < 2:
        return None

    total_ret = (eq[-1] - CAPITAL) / CAPITAL
    peak = np.maximum.accumulate(eq)
    dd = float(np.max((peak - eq) / peak)) if peak.max() > 0 else 0.0

    buys = [t for t in trades if t[1] == 'BUY']
    sells = [t for t in trades if t[1] == 'SELL']

    return dict(
        symbol=sym,
        equity=eq,
        bh_equity=bh_equity,
        dates=dates_out,
        closes=np.array(ddata['close'], dtype=np.float64),
        total_ret=total_ret,
        max_dd=dd,
        sells=sells,
        buys=buys,
        start=ddata['dates'][0],
        end=ddata['dates'][-1],
    )


def main():
    parser = argparse.ArgumentParser(description='TOS WeeklyAndDailyPPO backtest')
    parser.add_argument('--universe', choices=['etf', 'stocks'], default='etf',
                        help='Which ticker universe to run on (default: etf)')
    parser.add_argument('--limit', type=int, default=0,
                        help='Stocks only: use N tickers (0 = all)')
    parser.add_argument('--random', action='store_true',
                        help='Stocks only: pick the --limit sample at random instead of top-N by history')
    parser.add_argument('--detail', action='store_true', help='Print per-ticker detail')
    parser.add_argument('--symbols', type=str, default=None,
                        help='Comma-separated symbol filter, e.g. SPY,VTI,QQQ')
    args = parser.parse_args()

    conn = db.get_conn()
    try:
        is_etf = args.universe == 'etf'
        if is_etf:
            tickers = db.get_all_tickers(conn, is_etf=True)
        else:
            tickers = db.get_all_tickers(conn, is_etf=False, limit=args.limit, randomize=args.random)
        if args.symbols:
            want = {s.strip().upper() for s in args.symbols.split(',')}
            tickers = [t for t in tickers if t[1] in want]
        label = f'{len(tickers)} {"ETFs" if is_etf else "stocks"}'
        print(f'\n  Universe: {label}\n')

        weekly = db.bulk_load_weekly(conn, [t[0] for t in tickers])
        daily = db.bulk_load_daily(conn, [t[0] for t in tickers])

        results = []
        for tid, sym in tickers:
            wdata = weekly.get(tid)
            ddata = daily.get(tid)
            if not wdata or not ddata:
                continue
            if len(ddata['close']) < config.WARMUP + 10:
                continue
            r = run_ticker_bt(sym, wdata, ddata)
            if r:
                results.append(r)

        if not results:
            print('  No results.')
            return

        uni = 'ETF' if is_etf else 'STOCK'
        print(f'  {"Ticker":<8} {"Return":>9} {"MaxDD":>7} {"Trades":>7}  Period')
        print('  ' + '-' * 64)
        for r in sorted(results, key=lambda x: -x['total_ret']):
            print(f'  {r["symbol"]:<8} {r["total_ret"]*100:>+8.2f}% {r["max_dd"]*100:>6.1f}% '
                  f'{len(r["sells"]):>7}  {r["start"]} -> {r["end"]}')

        # Aggregate: equal-weight average of per-ticker equity curves (truncate to common length)
        n = min(len(r['equity']) for r in results)
        agg = np.mean([r['equity'][:n] for r in results], axis=0)
        agg_ret = (agg[-1] - CAPITAL) / CAPITAL
        peak = np.maximum.accumulate(agg)
        agg_dd = np.max((peak - agg) / peak)

        # Buy & hold: same per-ticker windows as the strategy, equal weight
        bh_avail = [r for r in results if r['bh_equity'] is not None]
        bh_n = min(len(r['bh_equity']) for r in bh_avail)
        bh = np.mean([r['bh_equity'][:bh_n] for r in bh_avail], axis=0)
        bh_ret = (bh[-1] - CAPITAL) / CAPITAL

        n_etfs = len(results)
        print(f'\n{"="*70}')
        print(f'  TOS WEEKLY+DAILY PPO BACKTEST  ({n_etfs} {uni}s)')
        print(f'  Weekly PPO: EMA{config.WEEKLY_PPO_FAST}/{config.WEEKLY_PPO_SLOW}   '
              f'Daily PPO: EMA{config.DAILY_PPO_FAST}/{config.DAILY_PPO_SLOW}   '
              f'denom = weekly {config.WEEKLY_PPO_SLOW} EMA')
        print(f'{"="*70}')
        print(f'  Signal: long when WeeklyPPO+DailyPPO > 0; out when <= 0')
        print(f'  Strategy (equal weight, $100k):')
        print(f'    Final:   ${agg[-1]:,.0f}')
        print(f'    Return:  {agg_ret*100:+.2f}%')
        print(f'    Max DD:  {agg_dd*100:.1f}%')
        print(f'  Buy & Hold (equal weight):')
        print(f'    Return:  {bh_ret*100:+.2f}%')

        total_sells = sum(len(r['sells']) for r in results)
        total_buys = sum(len(r['buys']) for r in results)
        print(f'  Trades:  {total_sells} round-trips across {n_etfs} {uni}s')

        print()

    finally:
        conn.close()


if __name__ == '__main__':
    main()
