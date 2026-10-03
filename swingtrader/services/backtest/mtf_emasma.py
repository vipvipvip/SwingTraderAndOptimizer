"""MTF emasma backtest — LOOKAHEAD-FREE by construction.

Signal logic is NOT implemented here. Every pick comes from emasma_core, the
same module runner.py imports for live. This file only:
  1. replays each settled weekly bar as of its decision date,
  2. hands candidates to harness.Sim for execution,
  3. prints the sheet.

No-lookahead rule: for decision date D, the last weekly bar usable is the one
with bar_date <= D - 7 days (settled Friday close). emasma_core.settled_weekly_idx
enforces that. Fills land on the next daily date strictly after D.

Data: tbl_prices_daily / tbl_prices_weekly (validated refresh). The pre-2026-10-02
figures in config.py comments and docs came off the old tables and are stale.
"""
import argparse
import os
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # services/
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), 'mtf'))  # services/mtf -> config, db, emasma_core
sys.path.insert(0, _HERE)                    # services/backtest -> harness

import config
import db as db_module
from emasma_core import settled_weekly_idx, compute_emasma_score, rank_candidates
import harness


def build_price_fn(daily_by_tid, ticker_names):
    """price_fn(symbol, date) -> settled close or None."""
    by_symbol = {ticker_names[tid]: d for tid, d in daily_by_tid.items() if tid in ticker_names}

    def price_fn(symbol, d):
        dly = by_symbol.get(symbol)
        if not dly:
            return None
        for i in range(len(dly['dates']) - 1, -1, -1):
            if dly['dates'][i] <= d:
                return dly['close'][i]
        return None

    return price_fn


def run(is_etf, start=None, end=None, verbose=True):
    start = start or date.fromisoformat(config.TS_START)
    end = end or date.today()
    conn = db_module.get_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE is_etf AND enabled ORDER BY id'
                if is_etf else
                'SELECT id, symbol FROM tbl_stock_tickers WHERE NOT is_etf AND enabled ORDER BY id')
    tickers = cur.fetchall()
    ticker_names = {t[0]: t[1] for t in tickers}
    tids = [t[0] for t in tickers]
    cur.close()

    weekly = db_module.bulk_load_weekly(conn, tids)
    daily = db_module.bulk_load_daily(conn, tids)
    conn.close()

    # weekly maps must be date -> index for settled_weekly_idx
    wmaps, wdates_sorted = {}, {}
    for tid, w in weekly.items():
        order = sorted(range(len(w['dates'])), key=lambda k: w['dates'][k])
        wmaps[tid] = {w['dates'][k]: j for j, k in enumerate(order)}
        wdates_sorted[tid] = [w['dates'][k] for k in order]

    sim = harness.Sim(price_fn=build_price_fn(daily, ticker_names))

    # decision dates = settled weekly bars inside the window
    all_wdates = sorted({d for w in weekly.values() for d in w['dates'] if start <= d <= end})
    last_fill = max((d['dates'][-1] for d in daily.values()), default=end)

    for wdate in all_wdates:
        today = wdate + timedelta(days=7)          # week is only settled a week later
        if today > last_fill:
            break
        sig_date = wdate                            # settled Friday close decision

        candidates = []
        for tid, w in weekly.items():
            if tid not in wmaps:
                continue
            wi = settled_weekly_idx(wmaps[tid], wdates_sorted[tid], today)
            if wi is None:
                continue
            dc = None
            for i in range(len(daily[tid]['dates']) - 1, -1, -1):
                if daily[tid]['dates'][i] <= sig_date:
                    dc = daily[tid]['close'][i]
                    break
            if dc is None:
                continue
            r = compute_emasma_score(w, dc, wi, sig_date)
            if r:
                r['tid'] = tid
                r['symbol'] = ticker_names.get(tid)
                candidates.append(r)

        top = rank_candidates(candidates, is_etf)
        # fill next available trading day AFTER the decision (earliest such date)
        fill_date = None
        sample = next(iter(daily.values()))
        for d in sample['dates']:
            if d > sig_date:
                fill_date = d
                break
        if fill_date is None:
            continue
        sim.rebalance(fill_date, [t['symbol'] for t in top])
        if verbose:
            print(f"  {sig_date} -> fill {fill_date}: {len(top)} names "
                  f"{[t['symbol'] for t in top][:5]}")

    out = sim.finish()
    if verbose:
        print(f"\n  MTF emasma ({'ETF' if is_etf else 'STOCK'}) "
              f"{start} -> {end}  [emasma_core shared logic]")
        for k, v in out.items():
            print(f"    {k:22} {v}")
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--etf', action='store_true')
    ap.add_argument('--start')
    ap.add_argument('--end')
    a = ap.parse_args()
    run(a.etf, date.fromisoformat(a.start) if a.start else None,
        date.fromisoformat(a.end) if a.end else None)