#!/usr/bin/env python3
"""Trio (QQQ/VTI/VTV) whole-market allocation comparison — the "what's CoreEW for?" test.

Strategies on the same window, same cost, same cadence, executed at next-day
close (settled bars only — in-progress day/week excluded):

  A. EW-weekly-rebalance : always equal-weight in all three, rebalance to EW
                           every week (trim overweights, top-up underweights).
                           Passive beta + periodic trim. No regime protection.
  B. EW-with-weekly-ratchet-gate : long an ETF only while its WEEKLY close is
                           above its peak-anchored ratchet stop (highest weekly
                           close since entry - mult x weekly ATR); flat -> cash
                           below. Equal-weight among passers, rebalanced every
                           week. This is the researched +98.3% / 7.1% DD rule.
  C. B&H                : equal-weight buy, never rebalance.
  D. score-proportional : per-ticker CO score = weekly EMA10>SMA40 (1/0) plus
                           daily EMA10>SMA40 (1/0) -> 0, 1 or 2; target weight
                           = score / sum(scores), re-applied and rebalanced to
                           every settled daily bar; all-zero day -> 100% cash.
                           When all three are fully bullish (2,2,2) this is
                           equal thirds, i.e. D degenerates to A.

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
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

import config
import db as db_module

CORE = ['QQQ', 'VTI', 'VTV']
MULT = config.RATCHET_ATR_MULT
COST = config.COST_PER_TRADE
CAPITAL = config.INITIAL_CAPITAL
TS_START = '2023-06-30'
WARMUP_DAYS = 520  # ~74 weekly bars (>> EMA10/SMA40 warmup) before TS_START for variant D
TABLE_W = 'tbl_scanner_tickers'          # weekly
TABLE_D = 'tbl_scanner_tickers_daily'    # daily


def load_full(conn, sym, table, start):
    """Load date,close from `start` (no trailing-end cutoff) for warmup needs."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT t.date::date, t.close FROM {table} t
        JOIN tbl_stock_tickers s ON s.id = t.ticker_id
        WHERE s.symbol=%s AND s.is_etf=true
          AND t.date::date >= %s
        ORDER BY t.date::date ASC""", (sym, start))
    rows = cur.fetchall()
    cur.close()
    dates = [r[0] for r in rows]
    close = np.array([float(r[1]) for r in rows], dtype=np.float64)
    return dates, close


def ema_sma(closes):
    s = pd.Series(closes)
    return (s.ewm(span=config.EMA_PERIOD, adjust=False).mean().to_numpy(),
            s.rolling(window=config.SMA_PERIOD).mean().to_numpy())


def load(conn, sym, table, ts_start):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT t.date::date, t.close, t.atr_stop FROM {table} t
        JOIN tbl_stock_tickers s ON s.id = t.ticker_id
        WHERE s.symbol=%s AND s.is_etf=true
          AND t.date::date >= '{ts_start}'
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
    """Per-daily-day long flags for the weekly ratchet gate.
    Also returns the ratchet-stop level in force each day (the trailing stop
    while long; the re-entry threshold while flat; NaN before the first gauge)."""
    long_flags = np.zeros(len(daily_dates), dtype=bool)
    stops = np.full(len(daily_dates), np.nan)
    long = False
    entries = 0
    peak = stop = 0.0
    seen = -1
    for i, d in enumerate(daily_dates):
        wi = wpos[i]
        if wi < 0:
            stops[i] = stop if seen >= 0 else np.nan
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
        stops[i] = stop
    return long_flags, entries, stops


def weekly_state_daily_reentry(daily_dates, d_close, w_dates, w_close, w_atr, wpos, mult, reset=True):
    """Variant E: B's weekly ratchet gate, but re-entry is confirmed on a DAILY
    close crossing back above the ratchet stop instead of waiting for a weekly
    settled close > stop. Exit logic identical to B (weekly close <= stop).
    Mid-week re-entry gets a fresh peak/stop anchored at the re-entry daily
    close when reset=True (mirroring B's reset); reset=False keeps the prior
    peak/stop so only a recovery toward the pre-crash peak re-enters."""
    long_flags = np.zeros(len(daily_dates), dtype=bool)
    stops = np.full(len(daily_dates), np.nan)
    long = False
    entries = 0
    peak = stop = 0.0
    seen = -1
    for i, d in enumerate(daily_dates):
        wi = wpos[i]
        if wi < 0:
            stops[i] = stop if seen >= 0 else np.nan
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
            if d_close[i] > stop:
                long = True
                entries += 1
                if reset:
                    peak = d_close[i]
                    stop = d_close[i] - mult * w_atr[wi]
        long_flags[i] = long
        stops[i] = stop
    return long_flags, entries, stops


def run_sim(daily_dates, closes, passers, reb, cost, entry_daily=False,
            fill_signal_close=False):
    """Daily sim. passers[i] = symbols long that day (signal i, filled i+1);
    reb[i] = rebalance back to equal weight among passers on that signal day.
    entry_daily: buy a newly-signalled passer the day after the signal (mid-week
    re-entries), independent of the weekly rebalance cadence.
    fill_signal_close: fill at the signal day's OWN close instead of the next
    day's close — matches the live gate, which decides Monday from the settled
    Friday bar and trades at Monday's price."""
    positions = {}
    cash = CAPITAL
    eq = []
    eq_dates = []
    buys = sells = 0
    last = len(daily_dates) if fill_signal_close else len(daily_dates) - 1
    for i in range(last):
        exec_date = daily_dates[i]
        px = {s: closes[s][i] for s in closes}
        if not fill_signal_close:
            exec_date = daily_dates[i + 1]
            px = {s: closes[s][i + 1] for s in closes}
        sig_pass = {s for s in passers if passers[s][i]}

        for sym in list(positions):
            if sym not in sig_pass:
                cash += positions[sym] * px[sym] * (1 - cost)
                sells += 1
                del positions[sym]

        if entry_daily and sig_pass:
            total_now = cash + sum(positions.get(s, 0.0) * px[s] for s in sig_pass)
            per = total_now / len(sig_pass)
            for sym in sig_pass:
                if sym not in positions and per > 0:
                    sh = per / px[sym] * (1 - cost)
                    cash -= sh * px[sym]
                    positions[sym] = sh
                    buys += 1

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

        mark = cash + sum(sh * px[s] for s, sh in positions.items())
        eq.append(mark)
        eq_dates.append(exec_date)
    return np.array(eq), eq_dates, buys, sells


def run_score_sim(dates, closes, scores, start, cost):
    """Variant D: score-proportional allocation.

    scores[s][i] = weekly CO state (1/0) + daily CO state (1/0) on settled bar
    i, so ∈ {0, 1, 2}. Target weight per ticker = score / sum(scores); when the
    day's sum is 0 the portfolio is 100% cash. Targets are re-applied and
    rebalanced to on every settled daily bar (fills at next-day close).
    """
    positions = {}
    cash = CAPITAL
    eq = []
    eq_dates = []
    buys = sells = 0
    for i in range(start, len(dates) - 1):
        exec_date = dates[i + 1]
        tot = float(sum(scores[s][i] for s in scores))
        targets = {s: (scores[s][i] / tot if tot > 0 else 0.0) for s in scores}
        px = {s: closes[s][i + 1] for s in scores}

        for sym in list(positions):
            if targets[sym] <= 0:
                cash += positions[sym] * px[sym] * (1 - cost)
                sells += 1
                del positions[sym]

        if tot > 0:
            total = cash + sum(positions.get(s, 0.0) * px[s] for s in targets if targets[s] > 0)
            for sym in targets:
                if targets[sym] <= 0:
                    continue
                diff = total * targets[sym] - positions.get(sym, 0.0) * px[sym]
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


def settled_weekly_ref(daily_dates, w_dates):
    """Index of the last SETTLED weekly bar per daily day — a weekly bar is
    settled only once bar_date + 7 <= day (its Friday close is in the past).

    Unlike pos_of (which points at the in-progress Monday row whose close
    keeps moving through the week), this lags one full week: the decision
    made on any day of week W uses week W-1's settled Friday close, with no
    knowledge of the current week's price action."""
    pos = np.full(len(daily_dates), -1, dtype=int)
    j = -1
    for i, d in enumerate(daily_dates):
        while j + 1 < len(w_dates) and (w_dates[j + 1] + timedelta(days=7)) <= d:
            j += 1
        pos[i] = j
    return pos


def settled_week_flags(daily_dates, w_dates, w_close, w_atr, mult, reset):
    """Weekly ratchet-gate long flags driven by the SETTLED weekly bars only.

    Same monotone gate logic as weekly_state, but the weekly series is lagged
    one full week (settled_weekly_ref): any decision on a day in week W uses
    week W-1's settled Friday close, with no knowledge of the current week's
    price action.

    Flag transitions (flips) therefore land on the first trading day after a
    New settled week becomes available — the following Monday — so executing
    at that day's close = decide on previous Friday, fill on Monday."""
    flags = np.zeros(len(daily_dates), dtype=bool)
    long = False
    peak = stop = 0.0
    seen = -1
    sref = settled_weekly_ref(daily_dates, w_dates)
    for i, d in enumerate(daily_dates):
        wi = sref[i]
        if wi < 0:
            continue
        if wi != seen:
            if seen < 0:
                long = True
                peak = w_close[wi]
                stop = w_close[wi] - mult * (w_atr[wi] if w_atr[wi] > 0 else 0.0)
            else:
                if long:
                    peak = max(peak, w_close[wi])
                    stop = max(stop, peak - mult * (w_atr[wi] if w_atr[wi] > 0 else 0.0))
                if w_close[wi] <= stop:
                    long = False
                elif not long and w_close[wi] > stop:
                    long = True
                    peak = w_close[wi]
                    if reset:
                        stop = w_close[wi] - mult * (w_atr[wi] if w_atr[wi] > 0 else 0.0)
            seen = wi
        flags[i] = long
    return flags


def run_settled_sim(daily_dates, closes, flags, cost):
    """Weekly sim driven by the SETTLED weekly bars only.

    flags[s][i] = whether symbol s is long on day i. Transitions happen only
    on the Monday a new settled week becomes available, and — unlike run_sim —
    the book is rebalanced to equal weight among passers AT THAT SAME DAY'S
    CLOSE (the Monday close). There is no +1-day fill here: decide on the
    previous Friday, fill on Monday."""
    positions = {}
    cash = CAPITAL
    eq = []
    eq_dates = []
    buys = sells = 0
    last_set = None
    for i, exec_date in enumerate(daily_dates):
        sig = {s for s in flags if flags[s][i]}
        px = {s: closes[s][i] for s in closes}
        if sig != last_set:
            for sym in list(positions):
                if sym not in sig:
                    cash += positions[sym] * px[sym] * (1 - cost)
                    sells += 1
                    del positions[sym]
            if sig:
                total = cash + sum(positions.get(s, 0.0) * px[s] for s in sig)
                per = total / len(sig)
                for sym in sig:
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
            last_set = sig
        mark = cash + sum(sh * closes[s][i] for s, sh in positions.items())
        eq.append(mark)
        eq_dates.append(exec_date)
    return np.array(eq), eq_dates, buys, sells


def prev_friday_close(dates, closes, sym, i):
    """Close of the most recent settled Friday on or just before day i — the
    settled weekly close that should have driven the decision (the previous
    Friday relative to the Monday fill)."""
    for k in range(i, -1, -1):
        if dates[k].isoweekday() == 5:
            return float(closes[sym][k])
    return float(closes[sym][i])


def write_settled_roundtrip_csvs(dates, closes, flags, syms, outdir, variant):
    """Pair settled-week entry/exit flips into one round-trip row per trade.

    Each row carries the previous-FRIDAY available close (the settled weekly
    close that drove the decision) and the MONDAY actual close (the execution
    price) for both entry and exit — so "fill == Monday close" is visible and
    verifiable per trade instead of asserted permanently."""
    os.makedirs(outdir, exist_ok=True)
    for sym in syms:
        trips = []
        open_dt = open_px = open_fri = None
        for i in range(len(dates)):
            cur = bool(flags[sym][i])
            prev = bool(flags[sym][i - 1]) if i > 0 else False
            monday_px = closes[sym][i]
            friday_px = prev_friday_close(dates, closes, sym, i)
            if cur and not prev:
                open_dt, open_px, open_fri = dates[i], monday_px, friday_px
            elif (not cur and prev) and open_dt is not None:
                exit_dt, exit_px, exit_fri = dates[i], monday_px, friday_px
                pct = (exit_px / open_px - 1.0) * 100 if open_px else 0.0
                days = (exit_dt - open_dt).days
                trips.append((open_dt, open_px, open_fri, exit_dt, exit_px,
                              exit_fri, pct, days, 'WIN' if pct >= 0 else 'LOSS'))
                open_dt = open_px = open_fri = None
        if open_dt is not None:
            last_px = closes[sym][-1]
            last_fri = prev_friday_close(dates, closes, sym, len(dates) - 1)
            pct = (last_px / open_px - 1.0) * 100 if open_px else 0.0
            trips.append((open_dt, open_px, open_fri, dates[-1], last_px,
                          last_fri, pct, (dates[-1] - open_dt).days, 'OPEN'))
        n_win = sum(1 for t in trips if t[8] == 'WIN')
        path = os.path.join(outdir, f'{variant}_settled_roundtrips_{sym}.csv')
        with open(path, 'w') as f:
            f.write('entry_date,entry_price,entry_prev_friday,'
                    'exit_date,exit_price,exit_prev_friday,pct_change,days_held,result\n')
            for dt, px, fri, xd, xpx, xfri, pct, days, res in trips:
                f.write(f'{dt},{px:.4f},{fri:.4f},{xd},{xpx:.4f},{xfri:.4f},'
                        f'{pct:+.2f},{days},{res}\n')
        print(f'  wrote settled round-trip CSV {path} ({len(trips)} trips, '
              f'{n_win} win)')
        trips_win = sum(1 for t in trips if t[8] == 'WIN')
        print(f'        {sym}: {len(trips)} trips, win {trips_win} '
              f'({100*trips_win/max(1,len(trips)):.0f}%)')


def prev_friday_close_week(dates, closes, sym, i):
    """Previous-Friday close pair lookup for the roundtrip CSV writer."""
    return prev_friday_close(dates, closes, sym, i)


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


def write_trade_csvs(dates, closes, flags, stops, syms, outdir, variant,
                     fill_signal_close=False):
    """Per-ticker gate entry/exit trades as CSVs for chart-walking.

    Fill = day after the signal, at next-day close (matches run_sim), unless
    fill_signal_close — then the fill is the signal day's own close.
    stop_signal = the ratchet-stop level in force at signal time."""
    os.makedirs(outdir, exist_ok=True)
    for sym in syms:
        rows = []
        prev = False
        for i in range(len(dates)):
            cur = bool(flags[sym][i])
            if cur != prev:
                act = 'BUY' if cur else 'SELL'
                st = stops[sym][i]
                j = i if fill_signal_close else min(i + 1, len(dates) - 1)
                rows.append((dates[j], act, closes[sym][j],
                             f'{st:.4f}' if not np.isnan(st) else ''))
            prev = cur
        path = os.path.join(outdir, f'{variant}_{sym}.csv')
        with open(path, 'w') as f:
            f.write('date,symbol,action,price,stop_signal\n')
            for d, act, px, st in rows:
                f.write(f'{d},{sym},{act},{px:.4f},{st}\n')
        print(f'  wrote {path} ({len(rows)} trades)')

    n_long = np.array([sum(1 for s in syms if flags[s][i]) for i in range(len(dates))])
    path = os.path.join(outdir, f'{variant}_exposure.csv')
    with open(path, 'w') as f:
        f.write('date,n_long,exposure_pct\n')
        for i in range(len(dates)):
            f.write(f'{dates[i]},{int(n_long[i])},{100*n_long[i]/max(1,len(syms)):.1f}\n')
    print(f'  wrote {path}')


def write_roundtrip_csvs(dates, closes, flags, syms, outdir, variant):
    """Pair the gate's entry/exit flips into one round-trip row per trade
    (entry date/px -> exit date/px, gross %, days held, WIN/LOSS), so each
    trip can be walked on a chart in isolation. Last trip stays 'OPEN' if it
    has not exited by the end of the window."""
    os.makedirs(outdir, exist_ok=True)
    for sym in syms:
        trips = []
        open_dt = open_px = None
        for i in range(1, len(dates) - 1):
            cur, prev = bool(flags[sym][i]), bool(flags[sym][i - 1])
            if cur and not prev:
                open_dt, open_px = dates[i + 1], closes[sym][i + 1]
            elif not cur and prev and open_dt is not None:
                exit_dt, exit_px = dates[i + 1], closes[sym][i + 1]
                pct = (exit_px / open_px - 1.0) * 100 if open_px else 0.0
                days = (exit_dt - open_dt).days
                trips.append((open_dt, open_px, exit_dt, exit_px, pct, days,
                              'WIN' if pct >= 0 else 'LOSS'))
                open_dt = open_px = None
        if open_dt is not None:
            last_px = closes[sym][-1]
            pct = (last_px / open_px - 1.0) * 100 if open_px else 0.0
            trips.append((open_dt, open_px, dates[-1], last_px, pct,
                          (dates[-1] - open_dt).days, 'OPEN'))
        n_win = sum(1 for t in trips if t[6] == 'WIN')
        path = os.path.join(outdir, f'{variant}_roundtrips_{sym}.csv')
        with open(path, 'w') as f:
            f.write('entry_date,entry_price,exit_date,exit_price,pct_change,days_held,result\n')
            for dt, px, xd, xpx, pct, days, res in trips:
                f.write(f'{dt},{px:.4f},{xd},{xpx:.4f},{pct:+.2f},{days},{res}\n')
        print(f'  wrote {path} ({len(trips)} trips, {n_win} win)')

    print('  Round-trip win rate by symbol:')
    for sym in syms:
        trips = []
        open_dt = open_px = None
        for i in range(1, len(dates) - 1):
            cur, prev = bool(flags[sym][i]), bool(flags[sym][i - 1])
            if cur and not prev:
                open_dt, open_px = dates[i + 1], closes[sym][i + 1]
            elif not cur and prev and open_dt is not None:
                exit_px = closes[sym][i + 1]
                trips.append(exit_px / open_px - 1.0)
                open_dt = None
        if open_dt is not None:
            trips.append(closes[sym][-1] / open_px - 1.0)
        wr = 100 * sum(1 for r in trips if r >= 0) / max(1, len(trips))
        avg = 100 * np.mean(trips) if trips else 0.0
        print(f'    {sym:<5} {len(trips):>2} trips  win {wr:>5.1f}%  avg per-trip {avg:>+6.2f}%')


def annual_exposure(dates, flags, syms):
    """Avg % long per calendar year + count of fully-cash / fully-long days."""
    n_long = np.array([sum(1 for s in syms if flags[s][i]) for i in range(len(dates))])
    years = {}
    for i, d in enumerate(dates):
        years.setdefault(d.year, []).append(n_long[i])
    print('  Exposure by year (avg % long, days fully-cash / fully-long):')
    for y in sorted(years):
        v = years[y]
        avg = 100 * np.mean(v) / len(syms)
        full_cash = sum(1 for x in v if x == 0)
        full_long = sum(1 for x in v if x == len(syms))
        print(f'    {y}: avg {avg:5.1f}%  cash {full_cash:>3}d  '
              f'full-long {full_long:>3}d / {len(v)}d')


def main():
    ap = argparse.ArgumentParser(description='Trio EW allocation comparison')
    ap.add_argument('--mult', type=float, default=MULT,
                    help=f'ATR multiplier for the gate (default {MULT})')
    ap.add_argument('--no-reset', action='store_true',
                    help='pure monotone gate (no ratchet reset on re-entry)')
    ap.add_argument('--fill-signal-close', action='store_true',
                    help="B': fill at the signal day's own close (Monday) "
                         'instead of next-day close — matches the live gate, '
                         'which decides Monday from the settled Friday bar')
    ap.add_argument('--tickers', default=','.join(CORE))
    ap.add_argument('--start', default=TS_START,
                    help=f'first backtest date (default {TS_START})')
    ap.add_argument('--no-score-alloc', action='store_true',
                    help='skip variant D (score-proportional)')
    ap.add_argument('--reentry-daily', action='store_true',
                    help='variant E: same ratchet exit as B, but daily close re-entry')
    ap.add_argument('--settled-friday', action='store_true',
                    help='variant S: same ratchet gate as B but driven ONLY by '
                         'settled (previous-Friday) weekly bars; decide on the '
                         'previous settled Friday, fill at the following Monday '
                         'close (no mid-week knowledge). Emits one round-trip '
                         'row per trade with prev-Friday + Monday-close both '
                         f'shown, so fill == Monday close is verifiable.')
    ap.add_argument('--csv-trades', action='store_true',
                    help='write per-ticker gate trade CSVs + exposure timeline to --csv-dir')
    ap.add_argument('--csv-dir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      'trio_trades'),
                    help='output dir for --csv-trades')
    args = ap.parse_args()
    tickers = [s.strip().upper() for s in args.tickers.split(',') if s.strip()]
    if not tickers:
        raise SystemExit('--tickers empty')

    conn = db_module.get_conn()
    try:
        ts_start = args.start
        daily = {s: load(conn, s, TABLE_D, ts_start) for s in tickers}
        weekly = {s: load(conn, s, TABLE_W, ts_start) for s in tickers}
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
        flagsB, entriesB, stopsB = {}, {}, {}
        for s in tickers:
            d, c, a = weekly[s]
            f, e, st = weekly_state(daily_dates, d, c, a, wpos[s], args.mult, not args.no_reset)
            flagsB[s], entriesB[s], stopsB[s] = f, e, st
        eqB, dB, bB, sB = run_sim(daily_dates, closes, flagsB, reb, COST)

        # B': the same monotone gate as B but filled at the signal day's OWN
        # close (Monday) instead of the next day's close (Tuesday) — mirrors
        # the live gate, which decides Monday on the settled Friday bar and
        # trades at Monday's price. reb is also applied at the Monday close.
        eqBp = dBp = None
        if args.fill_signal_close:
            eqBp, dBp, bBp, sBp = run_sim(daily_dates, closes, flagsB, reb, COST,
                                          fill_signal_close=True)

        # E: B with daily re-entry (only when requested)
        eqE = dE = bE = sE = None
        flagsE = entriesE = stopsE = None
        if args.reentry_daily:
            flagsE, entriesE, stopsE = {}, {}, {}
            for s in tickers:
                d, c, a = weekly[s]
                f, e, st = weekly_state_daily_reentry(daily_dates, closes[s], d, c, a,
                                                      wpos[s], args.mult, not args.no_reset)
                flagsE[s], entriesE[s], stopsE[s] = f, e, st
            eqE, dE, bE, sE = run_sim(daily_dates, closes, flagsE, reb, COST,
                                      entry_daily=True)

        # S: settled-Friday variant — the same ratchet gate as B, but driven
        # ONLY by SETTLED weekly bars: a decision on any day of week W uses
        # week W-1's settled Friday close (settled lag), never the current
        # week's price action.btn; filled at the next Monday close. Additive.
        eqS = dS = bS = sS = None
        flagsS = None
        if args.settled_friday:
            flagsS = {}
            for s in tickers:
                d, c, a = weekly[s]
                flagsS[s] = settled_week_flags(daily_dates, d, c, a,
                                               args.mult, not args.no_reset)
            eqS, dS, bS, sS = run_settled_sim(daily_dates, closes, flagsS, COST)

        # D: score-proportional (weekly CO + daily CO, re-applied daily).
        # Warm-up data pulled from before ts_start so EMA10/SMA40 are non-NaN
        # at the first signal day; skipped if no pre-start history is available.
        eqD = dD = bD = sD = cash_days = None
        if not args.no_score_alloc:
            warm_start = (datetime.fromisoformat(ts_start) - timedelta(days=WARMUP_DAYS)).date()
            dwarm = {s: load_full(conn, s, TABLE_D, warm_start) for s in tickers}
            wwarm = {s: load_full(conn, s, TABLE_W, warm_start) for s in tickers}
            d0 = dwarm[tickers[0]][0]
            if len(d0) < config.SMA_PERIOD + 5:
                print('  D: skipped (no pre-start warm-up data for EMA10/SMA40)')
            else:
                for s in tickers:
                    if list(dwarm[s][0]) != list(d0):
                        raise SystemExit(f'warm date mismatch for {s}')
                sim0 = next(i for i, d in enumerate(d0) if d >= datetime.fromisoformat(ts_start).date())
                if list(d0[sim0:]) != list(daily_dates):
                    raise SystemExit('warm window start mismatch')

                dema, dsma = {}, {}
                wema, wsma = {}, {}
                for s in tickers:
                    dema[s], dsma[s] = ema_sma(dwarm[s][1])
                    wema[s], wsma[s] = ema_sma(wwarm[s][1])
                wposD = {s: pos_of(d0, wwarm[s][0]) for s in tickers}

                scoresD = {}
                for s in tickers:
                    dsc = np.array([1.0 if (not np.isnan(dema[s][i]) and not np.isnan(dsma[s][i])
                                            and dema[s][i] > dsma[s][i]) else 0.0
                                    for i in range(len(d0))])
                    wsc = np.array([1.0 if (wposD[s][i] >= 0 and wema[s][wposD[s][i]] > wsma[s][wposD[s][i]]) else 0.0
                                    for i in range(len(d0))])
                    scoresD[s] = dsc + wsc

                closesD = {s: dwarm[s][1] for s in tickers}
                eqD, dD, bD, sD = run_score_sim(d0, closesD, scoresD, sim0, COST)
                cash_days = sum(1 for i in range(sim0, len(d0))
                                if sum(scoresD[s][i] for s in tickers) == 0)

        print('\n' + '=' * 74)
        print(f'  TRIO WHOLE-MARKET COMPARISON  {" / ".join(tickers)}')
        print(f'  window {daily_dates[0]} -> {daily_dates[-1]} '
              f'({len(daily_dates)} days), cost {COST*100:.2f}%, '
              f'gate mult {args.mult:.1f}x, reset={not args.no_reset}')
        print('=' * 74)
        stats(bh_eq, daily_dates, 'C. B&H (equal-weight)')
        stats(eqA, dA, 'A. EW weekly-rebalance')
        stats(eqB, dB, 'B. EW + weekly-ratchet gate')
        if eqBp is not None:
            stats(eqBp, dBp, "B'. B, Mon-close fill (live-like)")

        daily_long = sum(1 for i in range(len(daily_dates))
                         if sum(flagsB[s][i] for s in tickers) > 0)
        print(f'\n  Gate: {bB} buys / {sB} sells | '
              f'{100*daily_long/max(1,len(daily_dates)):.0f}% of days some ETF long '
              f'(entries per ETF: {", ".join(f"{s}={entriesB[s]}" for s in tickers)})')
        print(f'  A:    {bA} buys / {sA} sells (weekly trims)')

        if eqE is not None:
            stats(eqE, dE, 'E. ratchet gate, daily re-entry')
            e_long = sum(1 for i in range(len(daily_dates))
                         if sum(flagsE[s][i] for s in tickers) > 0)
            print(f'  E:    {bE} buys / {sE} sells | '
                  f'{100*e_long/max(1,len(daily_dates)):.0f}% of days some ETF long '
                  f'(entries per ETF: {", ".join(f"{s}={entriesE[s]}" for s in tickers)})')

        # S: settled-week ratchet gate. Decisions use ONLY the previous settled
        # Friday's close (settled_week_flags — not the current week's price
        # action), so the first trading day a new settled week becomes
        # available (Monday) is where fills land — at the Monday close.
        if eqS is not None:
            stats(eqS, dS, 'S. settled-week ratchet gate (prev Fri -> Mon close)')
            s_long = sum(1 for i in range(len(daily_dates))
                         if sum(flagsS[s][i] for s in tickers) > 0)
            print(f'  S:    {bS} buys / {sS} sells | '
                  f'{100*s_long/max(1,len(daily_dates)):.0f}% of days some ETF long')

        if eqD is not None:
            stats(eqD, dD, 'D. score-proportional (W+D CO, daily)')
            print(f'  D:    {bD} buys / {sD} sells | '
                  f'{100*cash_days/max(1, len(d0)-sim0):.0f}% of days fully in cash')
            for s in tickers:
                ups = int(np.sum(scoresD[s][sim0:] > 0)) if scoresD[s][sim0:].size else 0
                tot_days = int(len(d0) - sim0)
                print(f'        score>0 days {s}: {ups}/{tot_days} '
                      f'({100*ups/max(1,tot_days):.0f}%)')

        if args.csv_trades:
            annual_exposure(daily_dates, flagsB, tickers)
            write_trade_csvs(daily_dates, closes, flagsB, stopsB, tickers,
                             args.csv_dir, 'B',
                             fill_signal_close=args.fill_signal_close)
            write_roundtrip_csvs(daily_dates, closes, flagsB, tickers,
                                 args.csv_dir, 'B')
            if eqE is not None:
                write_trade_csvs(daily_dates, closes, flagsE, stopsE, tickers,
                                 args.csv_dir, 'E')
            if eqS is not None:
                write_settled_roundtrip_csvs(daily_dates, closes, flagsS,
                                             tickers, args.csv_dir, 'S')
    finally:
        conn.close()


if __name__ == '__main__':
    main()