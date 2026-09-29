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
                           week. WARNING: B/B'/E read the CURRENT week's weekly row,
                           which in the DB already holds that week's FRIDAY close, so
                           Mon-Fri decisions peek ahead - the old '+98.3% / 7.1% DD'
                           headline is that lookahead. Live-parity is variant S
                           (--settled-friday); see common/docs/TRADING_STRATEGIES.md.
  C. B&H                : equal-weight buy, never rebalance.
  D. score-proportional : per-ticker CO score = weekly EMA10>SMA40 (1/0) plus
                           daily EMA10>SMA40 (1/0) -> 0, 1 or 2; target weight
                           = score / sum(scores), re-applied and rebalanced to
                           every settled daily bar; all-zero day -> 100% cash.
                           When all three are fully bullish (2,2,2) this is
                           equal thirds, i.e. D degenerates to A.
  M. index-SMA gate      : (--sma-gate N [--sma-band PCT]) ONE market switch for
                           the whole trio: the equal-weight index of the three
                           closes vs its N-day SMA; off below SMA*(1-band), back on
                           above SMA*(1+band); all three in/out together, cash when
                           off. Decide on a settled close, fill at the NEXT day's
                           close. Price-only. Research (2000-2026, mutual-fund
                           extended history): SMA200 +/-3% cut max DD -60% -> -22%
                           at ~1 signal change/yr; see TRADING_STRATEGIES.md.
  M2. index-SMA ramp     : (--sma-gate N --sma-band PCT --sma-exposure ramp
                           [--rebal-tol FRAC]) dead-zone study. Same index, same
                           SMA, same settled-bar rule as M, but exposure ramps
                           LINEARLY across the +/-band zone instead of flipping
                           binary: 0% at -band, 50% mid-zone, 100% at +band. The
                           dead zone is where M sits in cash for months at a
                           time, so M2 measures what that idle time costs/buys.
                           Cash pays 0% in BOTH variants.
  M3. index-SMA step     : (--sma-exposure step [--sma-zone-weight FRAC]) same
                           study, discrete version: 0% below -band,
                           --sma-zone-weight inside it, 100% above +band.
  M4. no re-entry band   : (--sma-nohyst) M's exits but the OFF state re-enters
                           at the SMA itself, not SMA*(1+band) — isolates the
                           re-entry premium, i.e. how much of M is just "wait
                           for +band confirmation before buying back".
                           2016+ result (scanner tables start 2016-01-04):
                           M +266% / DD 21.9% | M2 ramp +178% / 20.1% |
                           M3 step +175% / 17.9% | M4 +209% / 22.7%. Partial
                           exposure inside the zone costs ~90 pts at the SAME
                           average exposure, and the zone weight barely matters
                           (0.25/0.5/0.75 all ~+175%) — the dead zone is
                           effectively all-or-nothing, and M's cash there is
                           the edge. Research only; B (the live ratchet gate)
                           beat all of them: +523% / DD 21.0%.
NOTE: the scanner tables only carry daily bars from
                            2016-01-04, so the 2000-2026 M headline is NOT
                            reproducible here — every index-gate number from this
                            script is 2016+ only.
  P. per-leg EMA gate   : (--leg-ema N[,N...]) A's weekly-EW machinery + a PER-ETF
                            binary crossover: each ETF is long only while its OWN
                            price > its EMA(N) (pure crossover, no band). OFF legs
                            sit in cash, never redeployed; the ON legs stay
                            equal-weight and re-trim weekly exactly like A. The
                            weekly variant (P{N}w — the live candidate, e.g. P20w
                            EMA20) is decided by the LIVE code via
                            trades:coreew-leg-ema-series; only the daily variant
                            (research, a whipsaw dead end vs A) is computed here.

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
import json
import subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse
from datetime import datetime, timedelta, date
import numpy as np
import pandas as pd

import config
import db as db_module
import asof

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
    LOOKAHEAD WARNING: `wpos` comes from pos_of(), which maps a day to the CURRENT
    week's Monday-stamped row whose close is that week's Friday close (future data
    on Mon-Thu). Use settled_week_flags() for anything meant to match live.
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


def _leg_ema_over(closes, n):
    """EMA(n) over a close series (pandas ewm, same convention as the gates)."""
    return pd.Series(closes).ewm(span=n, adjust=False).mean().to_numpy()


def leg_ema_daily_flags(conn, tickers, daily_dates, n):
    """Variant P (daily): per-ETF EMA(n) crossover on each leg's OWN settled
    daily close — state[i] = close[i] > EMA(n)[i], per leg, independently.

    RESEARCH-ONLY (the daily-close CO is a whipsaw machine and is NOT live).
    run_sim then fills the decision of day i at day i+1's close and re-trims
    to equal weight among the ON legs on every weekly boundary — the ONLY
    differences vs A are the per-leg on/off switch (OFF legs idle in cash,
    never redeployed) and the re-entry cadence. Returns {sym: flags} over the
    window (flags[i] = state decided at the close of day i).
    """
    full = {s: load_full(conn, s, TABLE_D, '2000-01-01') for s in tickers}
    today = datetime.now().date()
    keep = [i for i, d in enumerate(full[tickers[0]][0]) if d < today]
    dfull = [full[tickers[0]][0][i] for i in keep]
    for s in tickers:
        if [full[s][0][i] for i in keep] != dfull:
            raise SystemExit(f'date mismatch for {s} (P daily EMA gate)')
    off = dfull.index(daily_dates[0])
    # The window can end on TODAY's partial bar (the hourly sampler writes it
    # intraday), which `keep` excludes by construction — so compare and slice
    # only the settled prefix, then hold the last settled flag across the
    # trailing present-day row instead of failing the alignment outright.
    n_settled = sum(1 for d in daily_dates if d < today)
    if dfull[off:off + n_settled] != list(daily_dates[:n_settled]):
        raise SystemExit('P daily EMA history does not line up with the backtest window')
    flags = {}
    for s in tickers:
        c = np.array([full[s][1][i] for i in keep], dtype=np.float64)
        ema = _leg_ema_over(c, n)
        state = (c > ema) & ~np.isnan(ema)
        f = state[off:off + n_settled]
        if len(f) < len(daily_dates):
            f = np.concatenate([f, np.repeat(f[-1:], len(daily_dates) - len(f))])
        flags[s] = f
    return flags


def fetch_live_leg_ema_series(span, symbols):
    """P{span}w per-leg weekly EMA crossover decided by the LIVE code.

    Shells out to `php artisan trades:coreew-leg-ema-series`, which calls
    TradeExecutorService::legEmaTrail() -> replayLegEmaSeries() — the exact
    method a live P20w driver would run (settled weekly closes only, same
    ewm(span, adjust=False) recursion as the index gates). The backtest never
    re-implements the signal, aligning the returned per-week `long` states to
    daily days exactly like variant S. Read-only (~10 ms + Laravel boot).
    """
    backend = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'backend'))
    cmd = ['php', '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:coreew-leg-ema-series',
           f'--span={span}', '--symbols=' + ','.join(symbols)]
    proc = subprocess.run(cmd, cwd=backend, capture_output=True, text=True, timeout=300)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        raise RuntimeError(
            f'could not parse leg-EMA series from `{" ".join(cmd)}`\n'
            f'stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}')
    if payload.get('error') or not payload.get('series'):
        raise RuntimeError(
            f'leg-EMA series failed: {payload.get("error") or payload}\n'
            f'cmd: `{" ".join(cmd)}`')
    return payload


def flags_from_live_leg_ema_series(daily_dates, payload):
    """Align the live per-leg weekly EMA states onto trading days.

    Same settled-week rule as variant S: week W's decision (made on its settled
    Friday close, which the PHP series guarantees is fully formed) becomes
    actionable only from the first daily day d with week+7 <= d — the following
    Monday — held until the next decision. Flat before the first actionable
    week. This alignment is the only gate logic in this file; the states
    themselves come from PHP.
    """
    flags = {}
    for sym in payload['symbols']:
        pts = payload['series'][sym]
        wdates = [date.fromisoformat(p['week']) for p in pts]
        pos = settled_weekly_ref(daily_dates, wdates)
        f = np.array([bool(pts[j]['long']) if j >= 0 else False for j in pos])
        if len(f) != len(daily_dates):
            raise SystemExit(f'P{payload["span"]}w leg flags length mismatch for {sym}')
        flags[sym] = f
    return flags


def sma_gate_series(conn, tickers, n):
    """Shared index + SMA series behind every --sma-gate variant (M, M2, ...).

    The signal series is the equal-weight (daily-rebalanced) index built from the
    tickers' settled daily closes: the three DAILY RETURNS are averaged — never
    the prices, which live on different scales — and compounded into a
    dimensionless index starting at 1.0. Returns (dates, idx, sma) over the full
    settled history (pre-`daily_dates[0]` bars included so the SMA is warm).
    """
    full = {s: load_full(conn, s, TABLE_D, '2000-01-01') for s in tickers}
    today = datetime.now().date()
    keep = [i for i, d in enumerate(full[tickers[0]][0]) if d < today]   # settled bars only
    dfull = [full[tickers[0]][0][i] for i in keep]
    for s in tickers:
        if [full[s][0][i] for i in keep] != dfull:
            raise SystemExit(f'date mismatch for {s} (SMA gate history)')
    px = pd.DataFrame({s: full[s][1][keep] for s in tickers}, index=dfull)
    idx = (1 + px.pct_change().mean(axis=1).fillna(0.0)).cumprod().to_numpy()
    sma = pd.Series(idx).rolling(n).mean().to_numpy()
    return dfull, idx, sma


def sma_gate_flags(conn, tickers, daily_dates, n, band, reentry='band'):
    """Variant M: one index-level SMA gate for the whole trio.

    State is decided at the close of day t and applied to day t+1, so
    run_settled_sim fills it at the NEXT day's close. Returns the per-day bool
    flags aligned to `daily_dates` (same for every ticker).

    `reentry` selects where the OFF state turns back on:
      'band' (default, M) : re-enter above SMA*(1+band) — the hysteresis that
                            defines the dead zone.
      'zero'  (M4)        : re-enter as soon as the index is back above the SMA
                            itself, i.e. the band applies ONLY to the exit side.
                            Same exits as M, no re-entry premium — isolates how
                            much of M's edge is the +band confirmation.
    """
    dfull, idx, sma = sma_gate_series(conn, tickers, n)

    state = np.zeros(len(idx), dtype=bool)
    st = None
    for i in range(len(idx)):
        if np.isnan(sma[i]):
            continue
        re_thresh = sma[i] * (1 + band) if reentry == 'band' else sma[i]
        if st is None:
            st = idx[i] > sma[i]
        elif st and idx[i] < sma[i] * (1 - band):
            st = False
        elif (not st) and idx[i] > re_thresh:
            st = True
        state[i] = st

    off = dfull.index(daily_dates[0])
    if dfull[off:off + len(daily_dates)] != list(daily_dates):
        raise SystemExit('SMA gate history does not line up with the backtest window')
    if off == 0 or np.isnan(sma[off - 1]):
        print(f'  M: WARNING SMA{n} not warm at window start ({daily_dates[0]}); '
              f'gate sits in cash until the SMA is valid — use a later --start')
    lagged = np.concatenate([[False], state[:-1]])   # decide at close t, hold from t+1
    return lagged[off:off + len(daily_dates)]


def sma_gate_exposure(conn, tickers, daily_dates, n, band, mode, zone_weight=0.5):
    """Dead-zone exposure variants of the index SMA gate (float, 0..1 of equity).

    Same index/SMA and the same settled-bar rule as M (decide at the close of
    day t, hold from t+1); only the mapping from "distance from the SMA" to
    "how much of the book is invested" changes, which is the whole point: M
    dumps the entire book to cash the moment the index touches SMA*(1-band) and
    stays flat until SMA*(1+band) — the dead zone — so every day spent inside it
    is a day of zero market exposure.

      mode 'ramp' (M2): exposure ramps LINEARLY across the zone,
              w = clip((idx/SMA - 1 + band) / (2*band), 0, 1)
          i.e. 0% at -band, 50% dead center, 100% at +band. Continuous, so it
          needs no hysteresis: whipsaw around a threshold is impossible by
          construction, but the target moves every day, which is a cost problem
          (see rebal_tol in run_exposure_sim).

      mode 'step' (M3): half size inside the zone, full size above it,
              w = 0 below -band, zone_weight within +/-band, 1 above +band
          Discrete, so it only ever needs 3 trades per cycle and cannot churn.

    Returns the per-day target weight aligned to `daily_dates` (same for every
    ticker). NaN SMA (warm-up) -> 0, matching M sitting in cash.
    """
    dfull, idx, sma = sma_gate_series(conn, tickers, n)

    with np.errstate(invalid='ignore', divide='ignore'):
        dist = idx / sma - 1.0
    if mode == 'ramp':
        w = np.clip((dist + band) / (2.0 * band), 0.0, 1.0)
    elif mode == 'step':
        w = np.where(dist < -band, 0.0, np.where(dist > band, 1.0, zone_weight))
    else:
        raise SystemExit(f'unknown --sma-exposure mode {mode}')
    w = np.where(np.isnan(sma), 0.0, w)
    if band <= 0:
        raise SystemExit('--sma-band must be > 0 for --sma-exposure')

    off = dfull.index(daily_dates[0])
    if dfull[off:off + len(daily_dates)] != list(daily_dates):
        raise SystemExit('SMA gate history does not line up with the backtest window')
    if off == 0 or np.isnan(sma[off - 1]):
        print(f'  M2: WARNING SMA{n} not warm at window start ({daily_dates[0]}) — '
              f'exposure starts at 0; use a later --start')
    lagged = np.concatenate([[0.0], w[:-1]])   # decide at close t, hold from t+1
    return lagged[off:off + len(daily_dates)]


def run_exposure_sim(daily_dates, closes, weights, cost, rebal_tol):
    """Float-exposure sim: equal-weight the trio to `weights[i]` of equity, rest cash.

    `weights[i]` is the target invested FRACTION of equity on day i (already
    lagged by the caller: decide at close t, hold from t+1). Sells first, then
    buys, so the cash sleeve never goes negative mid-rebalance. Cost is charged
    on traded notional, same COST_PER_TRADE convention as the bool sims.

    `rebal_tol` is the trade threshold in units of equity: the book is only
    moved when the CURRENT invested fraction is off target by more than tol, so
    a smooth daily ramp does not churn every session. rebal_tol=0 rebalances to
    target every day (upper bound on performance, lower bound on realism).

    Cash earns 0% — the same convention as every other variant in this file. A
    T-bill yield on the cash sleeve would flatter every partial-exposure variant,
    so it is left out deliberately; the ramp/step numbers are therefore a
    floor, not a ceiling.

    Returns (equity array, dates, trades, gross traded notional, invested
    fraction per day).
    """
    syms = sorted(closes)
    positions = {s: 0.0 for s in syms}
    cash = CAPITAL
    eq, w_actual, gross = [], [], 0.0
    trades = 0
    for i, _d in enumerate(daily_dates):
        px = {s: closes[s][i] for s in syms}
        val = sum(sh * px[s] for s, sh in positions.items())
        equity = cash + val
        tgt = float(np.clip(weights[i], 0.0, 1.0))
        cur_w = val / equity if equity > 0 else 0.0
        w_actual.append(cur_w)
        if equity > 0 and (tgt > 0.0 or val > 0.0) and abs(cur_w - tgt) >= rebal_tol:
            # 1) sell down to target
            val = sum(sh * px[s] for s, sh in positions.items())
            equity = cash + val
            target_val = tgt * equity
            if val > target_val:
                excess = val - target_val
                for s in syms:
                    if excess <= 1e-9:
                        break
                    sh = min(positions[s], excess / px[s])
                    if sh <= 0:
                        continue
                    cash += sh * px[s] * (1 - cost)
                    positions[s] -= sh
                    trades += 1
                    gross += sh * px[s]
                    excess -= sh * px[s]
            # 2) buy up to target, equal thirds, grossed up for cost
            val = sum(sh * px[s] for s, sh in positions.items())
            equity = cash + val
            target_val = tgt * equity
            if val < target_val:
                per = (target_val - val) / len(syms)
                for s in syms:
                    sh = per / px[s] * (1 - cost)
                    if sh <= 0:
                        continue
                    cash -= sh * px[s]
                    positions[s] += sh
                    trades += 1
                    gross += sh * px[s]
        val = sum(sh * px[s] for s, sh in positions.items())
        eq.append(cash + val)
    return np.array(eq), daily_dates, trades, gross, np.array(w_actual)


def weekly_boundary_mask(daily_dates):
    """True on the first trading day of each ISO week.

    The settled-bar rebalance cadence: variant A resets to equal weight every
    Monday, so the gated variants have to as well or they win by accident through
    months of un-rebalanced drift rather than through the gate itself.
    """
    reb = np.zeros(len(daily_dates), dtype=bool)
    prev = None
    for i, d in enumerate(daily_dates):
        iso = d.isocalendar()[:2]
        if iso != prev:
            reb[i] = True
            prev = iso
    return reb


def run_settled_sim(daily_dates, closes, flags, cost, reb=None):
    """Weekly sim driven by the SETTLED weekly bars only.

    flags[s][i] = whether symbol s is long on day i. Transitions happen only
    on the Monday a new settled week becomes available, and — unlike run_sim —
    the book is rebalanced to equal weight among passers AT THAT SAME DAY'S
    CLOSE (the Monday close). There is no +1-day fill here: decide on the
    previous Friday, fill on Monday.

    `reb[i]` marks a new-settled-week boundary. The live gate rebalances the book
    to equity/N among gate-LONG legs on every settled week, whether or not the
    gate flipped, so a sim that only acted when the passer set changed would let
    positions drift for weeks at a time and stop modelling live. Passing `reb`
    restores the weekly cadence; omitting it keeps the old flip-only behaviour.
    """
    positions = {}
    cash = CAPITAL
    eq = []
    eq_dates = []
    buys = sells = 0
    last_set = None
    for i, exec_date in enumerate(daily_dates):
        sig = {s for s in flags if flags[s][i]}
        px = {s: closes[s][i] for s in closes}
        week_open = bool(reb[i]) if reb is not None else False
        if sig != last_set or week_open:
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


def fetch_live_gate_series(mult, symbols):
    """Per-week gate decisions produced by the LIVE gate code.

    Shells out to `php artisan trades:coreew-gate-series`, which calls
    TradeExecutorService::coreewGateSeries() — the exact method the live trade
    path runs. The backtest therefore never re-implements the ratchet rule, so
    the two cannot drift apart. This call is read-only (no Alpaca, no orders)
    and takes ~10 ms of gate work plus Laravel boot.

    Returns (series, meta) where series maps symbol -> list of weekly decision
    dicts [week, close, atr, long, peak, stop, entries], each being the state
    AFTER that week's settled bar was processed.
    """
    backend = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'backend'))
    cmd = ['php', '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:coreew-gate-series',
           f'--mult={mult}', '--symbols=' + ','.join(symbols)]
    proc = subprocess.run(cmd, cwd=backend, capture_output=True, text=True, timeout=300)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        raise RuntimeError(
            f'could not parse gate series from `{" ".join(cmd)}`\n'
            f'stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}')
    meta = {k: payload[k] for k in ('mult', 'cutoff', 'last_week', 'state')}
    return payload['series'], meta


def flags_from_live_gate(daily_dates, series):
    """Align the live gate's per-week decisions onto trading days.

    The ONLY thing this file is responsible for: a decision taken on week W's
    settled Friday close may only be acted on from W+7 onward (the following
    Monday), because that is when stream 1 could have published it. Everything
    before the first actionable week is flat.
    """
    ordinals = np.array([d.toordinal() for d in daily_dates], dtype=np.int64)
    flags = {}
    boundaries = set()
    for sym, trail in series.items():
        f = np.zeros(len(daily_dates), dtype=bool)
        for point in trail:
            # W is the Monday the bar is stamped on; its close is W+4 (Friday).
            # It is settled and publishable from W+7 (the next Monday).
            actionable = date.fromisoformat(point['week']) + timedelta(days=7)
            i = int(np.searchsorted(ordinals, actionable.toordinal(), side='left'))
            if i < len(f):
                f[i:] = bool(point['long'])
                boundaries.add(i)
        flags[sym] = f
    # One rebalance per activated settled week, even when the gate did not flip:
    # that is the live cadence. Weeks land on distinct Mondays, so the set of
    # activation indices is already the boundary mask.
    reb = np.zeros(len(daily_dates), dtype=bool)
    for i in boundaries:
        reb[i] = True
    return flags, reb


def fetch_live_eg_series(span, symbols, band=0.0):
    """EG index-EMA gate per-day decisions produced by the LIVE gate code.

    Shells out to `php artisan trades:coreew-eg-series`, which calls
    TradeExecutorService::indexEgTrail() -> replayIndexEgGate() — the exact
    method the live trade path runs. The backtest therefore never re-implements
    the index/EMA/crossover, so the two cannot drift apart. Read-only (no
    Alpaca, no orders), ~10 ms of gate work plus Laravel boot.
    """
    backend = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'backend'))
    cmd = ['php', '-d', 'xdebug.mode=off', '-d', 'display_errors=0',
           'artisan', 'trades:coreew-eg-series',
           f'--span={span}', f'--band={band:g}', '--symbols=' + ','.join(symbols)]
    proc = subprocess.run(cmd, cwd=backend, capture_output=True, text=True, timeout=300)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if payload is None:
        raise RuntimeError(
            f'could not parse EG gate series from `{" ".join(cmd)}`\n'
            f'stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}')
    if 'series' not in payload or payload.get('error'):
        raise RuntimeError(
            f'EG gate series failed: {payload.get("error") or payload}\n'
            f'cmd: `{" ".join(cmd)}`')
    return payload


def flags_from_live_eg_series(daily_dates, payload):
    """Align the live EG gate's per-day decisions onto trading days.

    The live gate decides on the close of SETTLED day t (state[t] in the PHP
    trail — the same tail `runEg100Gate` consumes) and may only be acted on
    from session t+1, so this returns hold-from-next-day flags:
    flags[i] = state at the close of day i-1; everything before the first
    settled bar is flat. This lag is the only gate logic in this file — the
    state itself comes from PHP.
    """
    sdates = [date.fromisoformat(d) for d in payload['series']['dates']]
    state = np.asarray(payload['series']['state'], dtype=bool)
    if len(sdates) != len(state):
        raise SystemExit(f'EG series len mismatch: dates {len(sdates)} vs state {len(state)}')
    if payload.get('bars') != len(sdates):
        raise SystemExit(f'EG series bars {payload.get("bars")} != dates {len(sdates)}')
    ordinals = np.array([d.toordinal() for d in sdates], dtype=np.int64)
    off = int(np.searchsorted(ordinals, daily_dates[0].toordinal(), side='left'))
    if sdates[off:off + len(daily_dates)] != list(daily_dates):
        raise SystemExit('EG live series does not line up with the backtest window')
    lagged = np.concatenate([[False], state[:-1]])
    return lagged[off:off + len(daily_dates)]


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
    ap.add_argument('--legacy-weekly', action='store_true',
                    help='run the B/B\'/E family and variant D. All of them read the '
                         'Monday-dated weekly row while that week is still forming, so the '
                         'as-of guard fails them; kept for A/B against the live-parity path '
                         'and off by default.')
    ap.add_argument('--allow-lookahead', action='store_true',
                    help='permit running the B/B\'/E family, which reads the Monday-dated '
                         'weekly row while that week is still forming (4 days of future '
                         'close). Off by default so B numbers cannot be quoted by accident.')
    ap.add_argument('--ema-gate', default='', metavar='LIST',
                    help='variant E-gate: comma-separated EMA spans on the synthetic '
                         'index (e.g. 25,50,75,100), pure crossover with no dead zone. '
                         'Decide on a settled close, hold from the next close.')
    ap.add_argument('--ema-band', type=float, default=0.0, metavar='PCT',
                    help='hysteresis band for --ema-gate, same semantics as --sma-band '
                         '(default 0 = pure crossover, no dead zone)')
    ap.add_argument('--leg-ema', default='', metavar='LIST',
                    help='variant P: comma-separated EMA spans for a PER-LEG crossover '
                         'on each ETF\'s OWN settled closes (e.g. 10), run on BOTH daily '
                         'closes and settled weekly closes. Off legs idle in cash; the ON '
                         'legs re-trim to equal weight weekly exactly like A.')
    ap.add_argument('--sma-gate', type=int, default=0, metavar='N',
                    help='variant M: one index-level N-day SMA gate for the whole trio '
                         '(e.g. 200); decide on a settled close, fill next-day close')
    ap.add_argument('--sma-band', type=float, default=3.0, metavar='PCT',
                    help='variant M hysteresis band in percent (default 3.0): off below '
                         'SMA*(1-b), back on above SMA*(1+b)')
    ap.add_argument('--sma-exposure', choices=['ramp', 'step'], default=None,
                    help='dead-zone variants: "ramp" (M2) ramps exposure linearly across '
                         'the +/-band zone (0%% at -band, 50%% mid, 100%% at +band); '
                         '"step" (M3) holds --sma-zone-weight inside the zone and full '
                         'size above it. Same index, same settled-bar rule as M')
    ap.add_argument('--sma-zone-weight', type=float, default=0.5, metavar='FRAC',
                    help='M3 only: exposure fraction held inside the dead zone '
                         '(default 0.5)')
    ap.add_argument('--sma-nohyst', action='store_true',
                    help='also run M4: identical to M but the OFF state re-enters at '
                         'the SMA itself instead of SMA*(1+band) — the band applies '
                         'only to the exit side, isolating the re-entry premium')
    ap.add_argument('--rebal-tol', type=float, default=0.10, metavar='FRAC',
                    help='M2 only: only rebalance when invested fraction is off target '
                         'by more than this fraction of equity (default 0.10). 0 = '
                         'rebalance to target every single day')
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

        # ---- As-of (no-lookahead) guard ------------------------------------
        # A hard precondition, not a report. A variant may only read a bar whose
        # CONTENT has already formed by the decision instant. The Monday-dated
        # weekly row is unreadable on its own Monday -- its close is that week's
        # Friday -- which is why the B family and D must opt in explicitly.
        weekly_mask = weekly_boundary_mask(daily_dates)
        w_dates = weekly[tickers[0]][0]
        settled_ref = asof.settled_weekly_ref(daily_dates, w_dates)
        s_audit = [asof.audit_weekly(daily_dates, w_dates, settled_ref,
                                     'S (last settled week)')]
        m_audit = [asof.audit_daily_close(daily_dates, 'M family (close-of-day)')]
        legacy_audit = []
        if args.legacy_weekly:
            legacy_audit = [
                asof.audit_weekly(daily_dates, weekly[s][0], wpos[s],
                                  f"B/B'/E {s} (in-progress week)") for s in tickers
            ] + [asof.audit_weekly(daily_dates, w_dates,
                                   asof.in_progress_weekly_ref(daily_dates, w_dates),
                                   'D (weekly CO leg)')]

        print('\n  AS-OF GUARD -- a bar is readable only once its content has formed')
        print(asof.render(legacy_audit + s_audit + m_audit))

        asof.enforce(s_audit + m_audit, 'live-parity variants (S, M)')
        if args.legacy_weekly and not args.allow_lookahead:
            bad = [r for r in legacy_audit if r.violations]
            if bad:
                raise SystemExit(
                    f"\nB/B'/E/D read the Monday-dated weekly row before that week's close "
                    f"exists (worst lead {max(r.worst_lead for r in bad)}d), so their returns "
                    "are inflated by construction.\n  Live-parity path: re-run with "
                    "--settled-friday.\n  To inspect B anyway, pass --allow-lookahead."
                )

        # C: B&H (never rebalance)
        base = {s: closes[s][0] for s in tickers}
        bh_eq = np.array([
            sum(CAPITAL / len(tickers) * closes[s][i] / base[s] for s in tickers)
            for i in range(len(daily_dates))])

        # A: always long all three, rebalance EW weekly
        passersA = {s: np.ones(len(daily_dates), dtype=bool) for s in tickers}
        eqA, dA, bA, sA = run_sim(daily_dates, closes, passersA, reb, COST)

        # B: weekly ratchet gate + weekly EW rebalance among passers. Lookahead
        # (reads the in-progress week), so opt-in via --legacy-weekly.
        flagsB = entriesB = stopsB = None
        eqB = dB = bB = sB = None
        if args.legacy_weekly:
            flagsB, entriesB, stopsB = {}, {}, {}
            for s in tickers:
                d, c, a = weekly[s]
                f, e, st = weekly_state(daily_dates, d, c, a, wpos[s], args.mult,
                                        not args.no_reset)
                flagsB[s], entriesB[s], stopsB[s] = f, e, st
            eqB, dB, bB, sB = run_sim(daily_dates, closes, flagsB, reb, COST)

        # B': the same monotone gate as B but filled at the signal day's OWN
        # close (Monday) instead of the next day's close (Tuesday) — mirrors
        # the live gate, which decides Monday on the settled Friday bar and
        # trades at Monday's price. reb is also applied at the Monday close.
        eqBp = dBp = None
        if args.fill_signal_close and args.legacy_weekly:
            eqBp, dBp, bBp, sBp = run_sim(daily_dates, closes, flagsB, reb, COST,
                                          fill_signal_close=True)

        # E: B with daily re-entry (only when requested)
        eqE = dE = bE = sE = None
        flagsE = entriesE = stopsE = None
        if args.reentry_daily and args.legacy_weekly:
            flagsE, entriesE, stopsE = {}, {}, {}
            for s in tickers:
                d, c, a = weekly[s]
                f, e, st = weekly_state_daily_reentry(daily_dates, closes[s], d, c, a,
                                                      wpos[s], args.mult, not args.no_reset)
                flagsE[s], entriesE[s], stopsE[s] = f, e, st
            eqE, dE, bE, sE = run_sim(daily_dates, closes, flagsE, reb, COST,
                                      entry_daily=True)

        # S: the LIVE-PARITY variant. The gate decisions are NOT computed here —
        # they come from TradeExecutorService::coreewGateSeries(), the same PHP
        # method the live trade path runs, via `trades:coreew-gate-series`. This
        # file only aligns each week-W decision to the first day it could have
        # been acted on (W+7, the following Monday) and fills at that close.
        # Decided on the previous settled Friday, filled Monday.
        eqS = dS = bS = sS = None
        flagsS = None
        gateMeta = None
        if args.settled_friday:
            liveSeries, gateMeta = fetch_live_gate_series(args.mult, tickers)
            flagsS, rebS = flags_from_live_gate(daily_dates, liveSeries)
            eqS, dS, bS, sS = run_settled_sim(daily_dates, closes, flagsS, COST, reb=rebS)

        # EG: pure EMA(n) crossover gate on the same synthetic index, decided by
        # the LIVE code (TradeExecutorService::replayIndexEgGate, via
        # `trades:coreew-eg-series`) — the backtest only aligns dates and fills.
        # Additive; comma-separated spans so one run sweeps them.
        eqEG = {}
        egFlags = {}
        if args.ema_gate:
            for n_ema in [int(x) for x in args.ema_gate.split(',') if x.strip()]:
                egSeries = fetch_live_eg_series(n_ema, tickers, args.ema_band)
                flagEG = flags_from_live_eg_series(daily_dates, egSeries)
                flagsEG = {s_: flagEG for s_ in tickers}
                egFlags[n_ema] = flagsEG
                eqEG[n_ema] = run_settled_sim(daily_dates, closes, flagsEG, COST,
                                              reb=weekly_mask)

        # P: per-leg EMA(n) crossover — A's weekly-EW machinery + a per-ETF
        # on/off switch off each ETF's OWN price vs its EMA(n) (settled closes).
        # OFF legs idle in cash; ON legs stay equal-weight and re-trim weekly,
        # exactly like A. The WEEKLY variant (P{n}w, the live candidate) is
        # decided by the LIVE code via `trades:coreew-leg-ema-series`; only the
        # daily variant (research, dead end) is computed here. Additive.
        legP = {}
        if args.leg_ema:
            for n_leg in [int(x) for x in args.leg_ema.split(',') if x.strip()]:
                fD = leg_ema_daily_flags(conn, tickers, daily_dates, n_leg)
                eqP, dP, bP, sP = run_sim(daily_dates, closes, fD, reb, COST,
                                          entry_daily=True)
                legSeries = fetch_live_leg_ema_series(n_leg, tickers)
                fW = flags_from_live_leg_ema_series(daily_dates, legSeries)
                eqPw, dPw, bPw, sPw = run_sim(daily_dates, closes, fW, reb, COST)
                legP[n_leg] = ((eqP, dP, bP, sP, fD), (eqPw, dPw, bPw, sPw, fW))

        # M: index-level SMA gate (additive; only with --sma-gate N). Same
        # settled-sim fill rule as S, but the flags come from ONE market signal.
        eqM = dM = bM = sM = flagsM = None
        if args.sma_gate:
            flagM = sma_gate_flags(conn, tickers, daily_dates, args.sma_gate,
                                   args.sma_band / 100.0)
            flagsM = {s: flagM for s in tickers}
            eqM, dM, bM, sM = run_settled_sim(daily_dates, closes, flagsM, COST,
                                                 reb=weekly_mask)

        # M2/M3: dead-zone exposure variants on the SAME index/SMA
        # (--sma-exposure ramp|step). Baselines are M and M4 below; the cash
        # sleeve pays 0% in every variant.
        eqM2 = dM2 = tM2 = None
        wM2 = None
        if args.sma_gate and args.sma_exposure:
            wM2 = sma_gate_exposure(conn, tickers, daily_dates, args.sma_gate,
                                    args.sma_band / 100.0, args.sma_exposure,
                                    args.sma_zone_weight)
            eqM2, dM2, tM2, gM2, w_act = run_exposure_sim(
                daily_dates, closes, wM2, COST, args.rebal_tol)

        # M4: M's exits, but re-entry at the SMA instead of SMA*(1+band).
        eqM4 = dM4 = bM4 = sM4 = flagsM4 = None
        if args.sma_gate and args.sma_nohyst:
            flagM4 = sma_gate_flags(conn, tickers, daily_dates, args.sma_gate,
                                    args.sma_band / 100.0, reentry='zero')
            flagsM4 = {s: flagM4 for s in tickers}
            eqM4, dM4, bM4, sM4 = run_settled_sim(daily_dates, closes, flagsM4, COST,
                                                     reb=weekly_mask)

        # D: score-proportional (weekly CO + daily CO, re-applied daily).
        # Warm-up data pulled from before ts_start so EMA10/SMA40 are non-NaN
        # at the first signal day; skipped if no pre-start history is available.
        eqD = dD = bD = sD = cash_days = None
        if not args.no_score_alloc and args.legacy_weekly:
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
        if eqB is not None:
            stats(eqB, dB, 'B. EW + weekly-ratchet gate [LOOKAHEAD]')
        if eqBp is not None:
            stats(eqBp, dBp, "B'. B, Mon-close fill (live-like)")

        if flagsB is not None:
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

        if eqEG:
            print()
            for n_ema, (eqEGv, dEGv, bEGv, sEGv) in eqEG.items():
                tag = 'crossover' if args.ema_band == 0 else f'+/-{args.ema_band:g}% band'
                stats(eqEGv, dEGv, f'EG{n_ema}. index EMA{n_ema} {tag}')
                fEG = egFlags[n_ema][tickers[0]]
                flips = int(np.sum(fEG[1:] != fEG[:-1]))
                print(f'  EG{n_ema}:  {bEGv} buys / {sEGv} sells | {flips} signal changes | '
                      f'{100*fEG.mean():.0f}% of days invested')

        if legP:
            dA_ret = (eqA[-1] - CAPITAL) / CAPITAL
            for n_leg, ((eqP, dP, bP, sP, fD), (eqPw, dPw, bPw, sPw, fW)) in legP.items():
                print()
                stats(eqP, dP, f'P{n_leg}. per-leg EMA{n_leg} CO (daily closes)')
                flipsD = {s: int(np.sum(fD[s][1:] != fD[s][:-1])) for s in tickers}
                print(f'  P{n_leg}:   {bP} buys / {sP} sells | per-leg flips '
                      f'{", ".join(f"{s}={flipsD[s]}" for s in tickers)} | '
                      f'avg {100*np.mean([fD[s].mean() for s in tickers]):.0f}% invested')
                stats(eqPw, dPw, f'P{n_leg}w. per-leg EMA{n_leg} CO (settled weekly)')
                flipsW = {s: int(np.sum(fW[s][1:] != fW[s][:-1])) for s in tickers}
                print(f'  P{n_leg}w:  {bPw} buys / {sPw} sells | per-leg flips '
                      f'{", ".join(f"{s}={flipsW[s]}" for s in tickers)} | '
                      f'avg {100*np.mean([fW[s].mean() for s in tickers]):.0f}% invested')
                dP_ret = (eqP[-1] - CAPITAL) / CAPITAL
                dPw_ret = (eqPw[-1] - CAPITAL) / CAPITAL
                print(f'  A/B:   A {dA_ret*100:+.2f}% vs daily {dP_ret*100:+.2f}% '
                      f'({(dP_ret-dA_ret)*100:+.2f} pts) vs weekly {dPw_ret*100:+.2f}% '
                      f'({(dPw_ret-dA_ret)*100:+.2f} pts)')

        if eqM is not None:
            stats(eqM, dM, f'M. index SMA{args.sma_gate} +/-{args.sma_band:g}% gate')
            m_long = int(np.sum(flagsM[tickers[0]]))
            m_flips = int(np.sum(flagsM[tickers[0]][1:] != flagsM[tickers[0]][:-1]))
            print(f'  M:    {bM} buys / {sM} sells | {m_flips} signal changes | '
                  f'{100*m_long/max(1,len(daily_dates)):.0f}% of days invested '
                  f'(all three ETFs together)')

        if eqM2 is not None:
            zone = np.abs(np.asarray(wM2) * 2.0 - 1.0) < 0.999  # 0 < w < 1 target
            tag = 'M2' if args.sma_exposure == 'ramp' else 'M3'
            print()
            stats(eqM2, dM2,
                  f'{tag}. SMA{args.sma_gate} dead-zone {args.sma_exposure.upper()} '
                  f'+/-{args.sma_band:g}%')
            print(f'  {tag}:   {tM2} trades (tol {args.rebal_tol:g} of equity) | '
                  f'avg invested {100*w_act.mean():.0f}% of days | '
                  f'target inside zone (<100%, >0%) {100*zone.mean():.0f}% of days | '
                  f'gross traded ${gM2/1000:.0f}k '
                  f'({gM2/(COST*CAPITAL*1000):.1f}x the cost of one full turnover)')
            if eqM is not None:
                dm = (eqM[-1] - CAPITAL) / CAPITAL
                d2 = (eqM2[-1] - CAPITAL) / CAPITAL
                print(f'  A/B:  M {dm*100:+.2f}% vs {tag} {d2*100:+.2f}% '
                      f'({(d2-dm)*100:+.2f} pts) at the SAME average exposure '
                      f'({100*w_act.mean():.0f}% vs '
                      f'{100*m_long/max(1,len(daily_dates)):.0f}%) — the gap is '
                      f'timing inside the zone, not time in the market')

        if eqM4 is not None:
            print()
            stats(eqM4, dM4,
                  f'M4. SMA{args.sma_gate} gate, re-entry at SMA (no +band wait)')
            m4_long = int(np.sum(flagsM4[tickers[0]]))
            m4_flips = int(np.sum(flagsM4[tickers[0]][1:] != flagsM4[tickers[0]][:-1]))
            print(f'  M4:   {bM4} buys / {sM4} sells | {m4_flips} signal changes | '
                  f'{100*m4_long/max(1,len(daily_dates)):.0f}% of days invested')
            if eqM is not None:
                dm = (eqM[-1] - CAPITAL) / CAPITAL
                d4 = (eqM4[-1] - CAPITAL) / CAPITAL
                print(f'  A/B:  M {dm*100:+.2f}% (re-enter at +{args.sma_band:g}%) vs '
                      f'M4 {d4*100:+.2f}% (re-enter at 0%) -> the +band re-entry '
                      f'premium is worth {(dm-d4)*100:+.2f} pts')

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