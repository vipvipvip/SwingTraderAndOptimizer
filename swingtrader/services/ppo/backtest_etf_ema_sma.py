"""ETF basket backtest: per-ETF weekly EMA10/SMA40 long/flat, equal weight.

Unlike MTF Top-N, every ETF runs its own binary signal (long when weekly
EMA10 > SMA40, flat otherwise). Equal weight across the enabled basket.
Position is taken the trading day after the weekly bar closes.

Usage:
    python3 backtest_etf_ema_sma.py [--start 2020-07-27] [--cost 0.001]
"""
import argparse
import datetime
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import db

FAST = 10
SLOW = 40


def get_symbols(conn):
    cur = conn.cursor()
    cur.execute("SELECT s.id, s.symbol FROM tbl_stock_tickers s "
                "JOIN tbl_etf_tickers e ON e.symbol = s.symbol "
                "WHERE e.enabled ORDER BY e.symbol")
    rows = cur.fetchall()
    cur.close()
    sym_by_tid = {t: s for t, s in rows}
    return [sym_by_tid[t] for t in sorted(sym_by_tid)], sym_by_tid


def weekly_signal(wdates, wclose, signal):
    s = pd.Series(wclose)
    if signal == 'ema-sma':
        fast = s.ewm(span=FAST, adjust=False).mean().to_numpy()
        slow = s.rolling(SLOW).mean().to_numpy()
    elif signal == 'ppo126':
        e12 = s.ewm(span=12, adjust=False).mean().to_numpy()
        e26 = s.ewm(span=26, adjust=False).mean().to_numpy()
        fast = (e12 - e26) / e26 * 100
        slow = np.zeros(len(wdates))
    else:
        raise ValueError(signal)
    pos = np.zeros(len(wdates), dtype=int)
    for i in range(len(wdates)):
        if signal == 'ppo126' or not np.isnan(slow[i]):
            pos[i] = 1 if fast[i] > slow[i] else 0
    return pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2020-07-27')
    ap.add_argument('--cost', type=float, default=0.001)
    ap.add_argument('--signal', default='ema-sma', choices=['ema-sma', 'ppo126'])
    ap.add_argument('--symbols', default=None,
                    help='comma-separated subset, e.g. SPY,QQQ,VTI,VTV')
    args = ap.parse_args()
    start = datetime.date.fromisoformat(args.start)

    conn = db.get_conn()
    symbols, sym_by_tid = get_symbols(conn)
    tids = list(sym_by_tid.keys())

    if args.symbols:
        keep = {s.strip().upper() for s in args.symbols.split(',')}
        tids = [t for t in tids if sym_by_tid[t] in keep]

    wdata = db.bulk_load_weekly(conn, tids)
    ddata = db.bulk_load_daily(conn, tids)

    # Skip symbols lacking either weekly or daily data.
    usable = [t for t in tids
              if t in wdata and len(wdata[t]['dates']) > SLOW
              and t in ddata and ddata[t]['dates']]
    usable_syms = [sym_by_tid[t] for t in usable]
    n = len(usable_syms)
    print(f'ETF basket: {n} symbols  window {start} -> today')

    # Weekly signal per ticker.
    sig = {t: weekly_signal(wdata[t]['dates'], wdata[t]['close'], args.signal) for t in usable}

    # Build daily calendar across all usable tickers.
    all_dates = sorted(set().union(*[set(ddata[t]['dates']) for t in usable]))
    dates = [d for d in all_dates if d >= start]
    di = {d: i for i, d in enumerate(all_dates)}

    # Position for each ticker on each day: signal acts on the Monday of the
    # crossing week (matches TOS live-paint + Alpaca Monday-labeled weekly bars).
    day_pos = {}
    for t in usable:
        wd = wdata[t]['dates']
        sig_w = sig[t]
        idx_by_mon = {}
        for i, dt in enumerate(ddata[t]['dates']):
            mon = dt - datetime.timedelta(days=dt.weekday())
            idx_by_mon.setdefault(mon, []).append(i)
        arr = np.full(len(all_dates), -1, dtype=int)
        cur_p = 0
        for wlabel, p in zip(wd, sig_w):
            if wlabel in idx_by_mon:
                cur_p = p
                for i in idx_by_mon[wlabel]:
                    arr[i] = p
        # fill forward: carry last signal across all remaining days
        last = 0
        for i in range(len(all_dates)):
            arr[i] = arr[i] if arr[i] >= 0 else last
            last = arr[i]
        day_pos[t] = arr

    closes = {t: dict(zip(ddata[t]['dates'], ddata[t]['close'])) for t in usable}
    dc = {t: {d: i for i, d in enumerate(ddata[t]['dates'])} for t in usable}

    equity = 1.0
    peak = 1.0
    maxdd = 0.0
    invested_days = 0
    buys = 0
    prev_pos = {t: 0 for t in usable}

    for i, d in enumerate(dates):
        gi = di[d]
        rets_today = []
        flips = 0
        for t in usable:
            c = closes[t]
            idx = dc[t].get(d)
            if idx is None or idx == 0:
                continue
            r = c[d] / ddata[t]['close'][idx - 1] - 1.0
            p = day_pos[t][gi]
            if p != prev_pos[t]:
                flips += 1
                if p:
                    buys += 1
            prev_pos[t] = p
            if p:
                rets_today.append(r)
        if rets_today:
            invested_days += 1
            cost = args.cost * flips / n
            equity *= (1.0 + np.mean(rets_today) - cost)
        peak = max(peak, equity)
        maxdd = max(maxdd, (peak - equity) / peak)

    print(f'Equity: $100,000 -> ${100000*equity:,.0f}  ({(equity-1)*100:+.1f}%)')
    print(f'Max drawdown: {maxdd*100:.1f}%   invested days: {invested_days}/{len(dates)}')

    # Buy & hold equal weight comparison.
    bheq = 1.0
    bhedd = 0.0
    bhepeak = 1.0
    for i, d in enumerate(dates):
        rr = []
        for t in usable:
            c = closes[t]
            idx = dc[t].get(d)
            if idx is None or idx == 0:
                continue
            rr.append(c[d] / ddata[t]['close'][idx - 1] - 1.0)
        if rr:
            bheq *= (1.0 + np.mean(rr))
        bhepeak = max(bhepeak, bheq)
        bhedd = max(bhedd, (bhepeak - bheq) / bhepeak)
    print(f'Buy&hold eq-weight:  ${100000*bheq:,.0f}  ({(bheq-1)*100:+.1f}%)  maxDD {bhedd*100:.1f}%')

    # Per-ETF: strategy vs buy&hold of that ETF alone.
    print()
    print(f'{"sym":>6} {"strat%":>8} {"b&h%":>8} {"DD%":>7} {"b&hDD%":>7}  verdict')
    for t in usable:
        sym = sym_by_tid[t]
        c = closes[t]
        ds = [d for d in dates if d in c]
        seg = 1.0
        segdd = 0.0
        segpeak = 1.0
        tr = 0.0
        bh = 1.0
        bhpeak = 1.0
        bhdd = 0.0
        n_long = 0
        n_days = 0
        for i, d in enumerate(ds):
            gi = di[d]
            idx = dc[t].get(d)
            if idx is None or idx == 0:
                continue
            r = c[d] / ddata[t]['close'][idx - 1] - 1.0
            bh *= (1 + r)
            bhpeak = max(bhpeak, bh)
            bhdd = max(bhdd, (bhpeak - bh) / bhpeak)
            n_days += 1
            if day_pos[t][gi]:
                n_long += 1
                seg *= (1 + r)
                tr += 1
                segpeak = max(segpeak, seg)
                segdd = max(segdd, (segpeak - seg) / segpeak)
        invest = n_long / n_days if n_days else 0
        verdict = 'beats B&H' if seg > bh else 'loses to B&H'
        print(f'{sym:>6} {100*(seg-1):8.1f} {100*(bh-1):8.1f} '
              f'{100*segdd:7.1f} {100*bhdd:7.1f}  {verdict} (long {100*invest:.0f}%)')


if __name__ == '__main__':
    main()
