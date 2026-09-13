#!/usr/bin/env python3
"""Trio (QQQ/VTI/VTV) whole-market allocation comparison — the "what's CoreEW for?" test.

Three strategies on the same window, same cost, same weekly cadence, executed
at next-day close (settled bars only — in-progress day/week excluded):

  A. EW-weekly-rebalance : always equal-weight in all three, rebalance to EW
                           every week (trim overweights, top-up underweights).
                           Passive beta + periodic trim. No regime protection.
  B. EW-with-weekly-ratchet-gate : long an ETF only while its WEEKLY close is
                           above its peak-anchored ratchet stop (highest weekly
                           close since entry - mult x weekly ATR); flat -> cash
                           below. Equal-weight among passers, rebalanced every
                           week. This is the researched +98.3% / 7.1% DD rule.
  C. B&H                : equal-weight buy, never rebalance.

Win rate reported as the fraction of weekly intervals with positive portfolio
return — the honest metric for continuous-exposure strategies (no discrete
trades in A/C; the gate's discrete buys/sells are tallied too).

Usage:
  python backtest_trio_ew.py
  python backtest_trio_ew.py --mult 2.5
  python backtest_trio_ew.py --no-reset
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
TABLE_W = 'tbl_scanner_tickers'          # weekly
TABLE_D = 'tbl_scanner_tickers_daily'    # daily


def load(conn, sym, table):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT t.date::date, t.close, t.atr_stop FROM {table} t
        JOIN tbl_stock_tickers s ON s.id = t.ticker_id
        WHERE s.symbol=%s AND s.is_etf=true
          AND t.date::date >= '{TS_START}'
          AND t.date::date < CURRENT_DATE
        ORDER BY t.date::date ASC""", (sym,))
    rows = cur.fetchall()
    cur.close()
    dates = [r[0] for r in rows]
    close = np.array([float(r[1]) for r in rows], dtype=np.float64)
    atr = np.array([
        (float(r[1]) - float(r[2])) / 2.0 if r[2] and float(r[2]) > 0 else 0.0
        for r in rows], dtype=np.float64)
    return dates, close, atr


def pos_of(daily_dates, tf_dates):
    pos = np.full(len(daily_dates), -1, dtype=int)
    j = 0
    for i, d in enumerate(daily_dates):
        while j < len(tf_dates) - 1 and tf_dates[j + 1] <= d:
            j += 1
        if tf_dates[j] <= d:
            pos[i] = j
    return pos


def weekly_state(daily_dates, w_dates, w_close, w_atr, wpos, mult, reset):
    """Per-daily-day long flags for the weekly ratchet gate."""
    long_flags = np.zeros(len(daily_dates), dtype=bool)
    long = False
    entries = 0
    peak = stop = 0.0
    seen = -1
    for i, d in enumerate(daily_dates):
        wi = wpos[i]
        if wi < 0:
            long_flags[i] = long
            continue
        if wi != seen:
            seen = wi
            if long and w_atr[wi] > 0:
                peak = max(peak, w_close[wi])
                stop = max(stop, peak - mult * w_atr[wi])
        if not long and entries == 0 and w_atr[wi] > 0:
            long = True
            entries = 1
            peak = w_close[wi]
            stop = w_close[wi] - mult * w_atr[wi]
        elif long and w_atr[wi] > 0:
            if w_close[wi] <= stop:
                long = False
        elif not long and entries > 0 and w_atr[wi] > 0:
            if w_close[wi] > stop:
                long = True
                entries += 1
                peak = w_close[wi]
                if reset:
                    stop = w_close[wi] - mult * w_atr[wi]
        long_flags[i] = long
    return long_flags, entries


def run_sim(daily_dates, closes, passers, reb, cost):
    """Daily sim. passers[i] = symbols long that day (signal i, filled i+1);
    reb[i] = rebalance back to equal weight among passers on that signal day."""
    positions = {}
    cash = CAPITAL
    eq = []
    eq_dates = []
    buys = sells = 0
    for i in range(len(daily_dates)):
        if i + 1 >= len(daily_dates):
            break
        exec_date = daily_dates[i + 1]
        sig_pass = {s for s in passers if passers[s][i]}
        px = {s: closes[s][i + 1] for s in closes}

        for sym in list(positions):
            if sym not in sig_pass:
                cash += positions[sym] * px[sym] * (1 - cost)
                sells += 1
                del positions[sym]

        if reb[i] and sig_pass:
            total = cash + sum(positions.get(s, 0.0) * px[s] for s in sig_pass)
            per = total / len(sig_pass)
            for sym in sig_pass:
                held_val = positions.get(sym, 0.0) * px[sym]
                diff = per - held_val
                if diff > 0:
                    sh = diff / px[sym] * (1 - cost)
                    cash -= sh * px[sym]
                    positions[sym] = positions.get(sym, 0.0) + sh
                    buys += 1
                elif diff < 0:
                    sh = min(positions[sym], -diff / px[sym])
                    cash += sh * px[sym] * (1 - cost)
                    positions[sym] -= sh
                    sells += 1

        mark = cash + sum(sh * closes[s][i + 1] for s, sh in positions.items())
        eq.append(mark)
        eq_dates.append(exec_date)
    return np.array(eq), eq_dates, buys, sells


def weekly_rets(eq, dates):
    """Portfolio return per ISO week boundary."""
    out = []
    prev_iso = None
    prev_val = eq[0]
    for i, d in enumerate(dates):
        iso = d.isocalendar()[:2]
        if iso != prev_iso and prev_iso is not None:
            out.append(eq[i] / prev_val - 1.0)
            prev_val = eq[i]
        prev_iso = iso
    return out


def stats(eq, dates, label):
    total = (eq[-1] - CAPITAL) / CAPITAL
    peak = np.maximum.accumulate(eq)
    dd = float(np.max((peak - eq) / peak))
    wr = 100 * sum(1 for r in weekly_rets(eq, dates) if r > 0) / max(1, len(weekly_rets(eq, dates)))
    cagr = ((eq[-1] / CAPITAL) ** (252.0 / max(1, len(eq))) - 1) * 100
    print(f'  {label:<33} return {total*100:>+10.2f}%  MaxDD {dd*100:>6.1f}%  '
          f'weekly-up {wr:>5.1f}%  CAGR {cagr:>+7.1f}%')
    return total, dd, wr


def main():
    ap = argparse.ArgumentParser(description='Trio EW allocation comparison')
    ap.add_argument('--mult', type=float, default=MULT,
                    help=f'ATR multiplier for the gate (default {MULT})')
    ap.add_argument('--no-reset', action='store_true',
                    help='pure monotone gate (no ratchet reset on re-entry)')
    ap.add_argument('--tickers', default=','.join(CORE))
    args = ap.parse_args()
    tickers = [s.strip().upper() for s in args.tickers.split(',') if s.strip()]
    if not tickers:
        raise SystemExit('--tickers empty')

    conn = db_module.get_conn()
    try:
        daily = {s: load(conn, s, TABLE_D) for s in tickers}
        weekly = {s: load(conn, s, TABLE_W) for s in tickers}
        daily_dates = daily[tickers[0]][0]
        for s in tickers:
            if list(daily[s][0]) != list(daily_dates):
                raise SystemExit(f'date mismatch for {s}')

        closes = {s: daily[s][1] for s in tickers}
        wpos = {s: pos_of(daily_dates, weekly[s][0]) for s in tickers}
        w0 = pos_of(daily_dates, weekly[tickers[0]][0])
        reb = np.zeros(len(daily_dates), dtype=bool)
        reb[0] = True
        for i in range(1, len(daily_dates)):
            if w0[i] != w0[i - 1]:
                reb[i] = True

        # C: B&H (never rebalance)
        base = {s: closes[s][0] for s in tickers}
        bh_eq = np.array([
            sum(CAPITAL / len(tickers) * closes[s][i] / base[s] for s in tickers)
            for i in range(len(daily_dates))])

        # A: always long all three, rebalance EW weekly
        passersA = {s: np.ones(len(daily_dates), dtype=bool) for s in tickers}
        eqA, dA, bA, sA = run_sim(daily_dates, closes, passersA, reb, COST)

        # B: weekly ratchet gate + weekly EW rebalance among passers
        flagsB, entriesB = {}, {}
        for s in tickers:
            d, c, a = weekly[s]
            f, e = weekly_state(daily_dates, d, c, a, wpos[s], args.mult, not args.no_reset)
            flagsB[s], entriesB[s] = f, e
        eqB, dB, bB, sB = run_sim(daily_dates, closes, flagsB, reb, COST)

        print('\n' + '=' * 74)
        print(f'  TRIO WHOLE-MARKET COMPARISON  {" / ".join(tickers)}')
        print(f'  window {daily_dates[0]} -> {daily_dates[-1]} '
              f'({len(daily_dates)} days), cost {COST*100:.2f}%, '
              f'gate mult {args.mult:.1f}x, reset={not args.no_reset}')
        print('=' * 74)
        stats(bh_eq, daily_dates, 'C. B&H (equal-weight)')
        stats(eqA, dA, 'A. EW weekly-rebalance')
        stats(eqB, dB, 'B. EW + weekly-ratchet gate')

        daily_long = sum(1 for i in range(len(daily_dates))
                         if sum(flagsB[s][i] for s in tickers) > 0)
        print(f'\n  Gate: {bB} buys / {sB} sells | '
              f'{100*daily_long/max(1,len(daily_dates)):.0f}% of days some ETF long '
              f'(entries per ETF: {", ".join(f"{s}={entriesB[s]}" for s in tickers)})')
        print(f'  A:    {bA} buys / {sA} sells (weekly trims)')
    finally:
        conn.close()


if __name__ == '__main__':
    main()