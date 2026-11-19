#!/usr/bin/env python3
"""CMO strategy backtest — Book A (stateful signal book), next-open fills.

Reads canonical Alpaca adjusted bars (`tbl_prices_daily` by default, or
`tbl_prices_weekly` with --timeframe week), computes the CMO signal in `cmo_core`,
and simulates:

  * decision on settled bar D close
  * execution at D+1 open (or close, `--fill close` for sensitivity)
  * capacity TOP_N, equal weight equity/TOP_N, trim-before-top-up with a band
  * a held name exits only on its own mirror sell window (no rank rotation)
  * 0.05% per side by default

It also runs a signal event study (forward 5/10/20/60-bar returns vs the
same-day equal-weight universe) and sub-window metrics, because a single pretty
equity curve is not evidence.

No DB writes, no orders. Research only.
"""
import argparse
import bisect
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cmo_core
import db as db_module
from backtest_trio_ew import (fetch_live_leg_ema_series,
                             flags_from_live_leg_ema_series)

INITIAL_CAPITAL = 100_000.0
MIN_TICKERS = 400
DEFAULT_COST = 0.0005
HORIZONS = (5, 10, 20, 60)


# ───────────────────────────────── loading ──────────────────────────────────

def load_universe(conn, symbols=None, timeframe='day'):
    if symbols:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, symbol FROM tbl_stock_tickers '
                'WHERE enabled=true AND symbol = ANY(%s) ORDER BY symbol',
                (list(symbols),))
            tickers = cur.fetchall()
    else:
        tickers = db_module.get_all_tickers(conn, is_etf=False)
    tids = [t[0] for t in tickers]
    loader = (db_module.bulk_load_weekly if timeframe == 'week'
              else db_module.bulk_load_daily)
    raw = loader(conn, tids)
    data = {}
    for tid, symbol in tickers:
        d = raw.get(tid)
        if not d or len(d['dates']) < cmo_core.WARMUP_BARS:
            continue
        close = np.asarray(d['close'], dtype=np.float64)
        if not np.isfinite(close).all() or (close <= 0).any():
            continue
        data[tid] = {
            'symbol': symbol,
            'dates': list(d['dates']),
            'open': np.asarray(d['open'], dtype=np.float64),
            'close': close,
        }
    return data


def load_benchmark(conn, symbol='SPY', timeframe='day'):
    table = 'tbl_prices_weekly' if timeframe == 'week' else 'tbl_prices_daily'
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT d.date, d.close FROM {table} d "
            "JOIN tbl_stock_tickers s ON s.id = d.ticker_id "
            "WHERE s.symbol = %s ORDER BY d.date", (symbol,))
        rows = cur.fetchall()
    return [(r[0], float(r[1])) for r in rows]


# ─────────────────────────────── simulation ─────────────────────────────────

def _price(data, tid, exec_date, fill):
    d = data[tid]
    j = bisect.bisect_left(d['dates'], exec_date)
    if j >= len(d['dates']):
        return None
    if (d['dates'][j] - exec_date).days > 7:
        return None
    px = float(d['open'][j]) if fill == 'open' else float(d['close'][j])
    if px <= 0:
        px = float(d['close'][j])
    return px if px > 0 else None


def _sma_series(px, period):
    out = np.full(len(px), np.nan)
    for i in range(period - 1, len(px)):
        seg = px[i - period + 1:i + 1]
        if np.isfinite(seg).all():
            out[i] = float(seg.mean())
    return out


def run_sim(data, args, bench_rows=None, active_universe=None, entry_filter=None):
    all_dates = sorted(set().union(*(set(d['dates']) for d in data.values())))
    counts = defaultdict(int)
    for d in data.values():
        for dt in d['dates']:
            counts[dt] += 1
    min_t = max(1, min(10, len(data))) if args.tickers else MIN_TICKERS
    all_dates = [dt for dt in all_dates if counts[dt] >= min_t]
    if args.start:
        all_dates = [dt for dt in all_dates if dt >= args.start]
    if args.end:
        all_dates = [dt for dt in all_dates if dt <= args.end]
    if len(all_dates) < 30:
        raise SystemExit(f'not enough dates after filters: {len(all_dates)}')

    if args.market_filter != 'none' and bench_rows:
        m = {d: p for d, p in bench_rows}
        px, last = [], None
        for d in all_dates:
            last = m.get(d, last)
            px.append(last)
        px = np.asarray(px, dtype=np.float64)
        period = int(args.market_filter.rsplit('sma', 1)[1])
        sma = _sma_series(px, period)
        risk_on = np.isfinite(sma) & (px > sma)
    else:
        risk_on = np.ones(len(all_dates), dtype=bool)

    if args.p20w_gate != 'none':
        payload = fetch_live_leg_ema_series(20, ['QQQ', 'VTI', 'VTV'])
        flags = flags_from_live_leg_ema_series(all_dates, payload)
        counts = sum(flags[s].astype(int) for s in payload['symbols'])
        need = {'any': 1, 'majority': 2, 'all': 3}[args.p20w_gate]
        risk_on &= counts >= need

    sym_to_tid = {d['symbol']: tid for tid, d in data.items()}
    week_end = [True] * len(all_dates)
    for k in range(len(all_dates) - 1):
        week_end[k] = all_dates[k].isocalendar()[:2] != all_dates[k + 1].isocalendar()[:2]
    hwm = INITIAL_CAPITAL
    cooldown = 0
    last_i = {tid: -1 for tid in data}
    positions = {}
    cash = INITIAL_CAPITAL
    pending = None
    equity_curve, used_dates, exposure = [], [], []
    flows, trades = [], []
    cost = args.cost

    def _entry(sym, qty, px, day, gross, signal_date=None):
        pos = positions.get(sym)
        if pos is None:
            positions[sym] = {'shares': qty, 'cost_basis': gross,
                              'entry_date': day, 'entry_signal_date': signal_date,
                              'last_buy': day}
        else:
            pos['shares'] += qty
            pos['cost_basis'] += gross
            pos['last_buy'] = day

    def _exit(sym, qty, px, day, reason='signal', record=True, signal_date=None):
        pos = positions.get(sym)
        if pos is None or qty <= 0:
            return
        qty = min(qty, pos['shares'])
        avg = pos['cost_basis'] / pos['shares'] if pos['shares'] else px
        removed = avg * qty
        proceeds = qty * px * (1 - cost)
        pnl = proceeds - removed
        if record:
            trades.append({
                'symbol': sym, 'qty': qty,
                'entry_signal_date': pos.get('entry_signal_date'),
                'entry_date': pos['entry_date'],
                'exit_signal_date': signal_date,
                'exit_date': day, 'entry_px': avg / (1 + cost) if avg else px,
                'exit_px': px, 'pnl': pnl, 'ret': pnl / removed if removed else 0.0,
                'reason': reason,
            })
        pos['shares'] -= qty
        pos['cost_basis'] -= removed
        if pos['shares'] <= 1e-9:
            del positions[sym]

    def _mark(day):
        val = cash
        for sym, pos in positions.items():
            tid = sym_to_tid[sym]
            i = last_i[tid]
            if i >= 0:
                val += pos['shares'] * float(data[tid]['close'][i])
        return val

    def _invested(day):
        val = 0.0
        for sym, pos in positions.items():
            tid = sym_to_tid[sym]
            i = last_i[tid]
            if i >= 0:
                val += pos['shares'] * float(data[tid]['close'][i])
        return val

    def _execute(book, exec_date, equity_dec, signal_date=None):
        nonlocal cash
        target = set(book['target'])

        # 1) full exits: held but not in the target book (mirror sell fired)
        for sym in list(positions):
            if sym in target:
                continue
            tid = sym_to_tid[sym]
            px = _price(data, tid, exec_date, args.fill)
            if px is None:
                continue
            q = positions[sym]['shares']
            flows.append((exec_date, q * px))
            cash += q * px * (1 - cost)
            _exit(sym, q, px, exec_date, 'sell', signal_date=signal_date)

        # 2) trims, then buys/top-ups
        target_val = equity_dec / (max(1, len(target)) if getattr(args, "ew_by_target", False) else args.top_n)
        band = args.rebalance_band / 100.0
        buys = {}
        for sym in book['target']:
            tid = sym_to_tid.get(sym)
            if tid is None:
                continue
            px = _price(data, tid, exec_date, args.fill)
            if px is None:
                continue
            cur = positions.get(sym, {}).get('shares', 0.0) * px
            if cur > target_val * (1 + band):
                excess = cur - target_val
                if excess >= args.min_notional:
                    q = excess / px
                    flows.append((exec_date, q * px))
                    cash += q * px * (1 - cost)
                    _exit(sym, q, px, exec_date, 'trim', record=False)
            elif cur < target_val * (1 - band):
                need = target_val - cur
                if need >= args.min_notional:
                    buys[sym] = need

        total = sum(buys.values())
        if total <= 0:
            return
        scale = min(1.0, cash / total)
        for sym, need in buys.items():
            tid = sym_to_tid[sym]
            px = _price(data, tid, exec_date, args.fill)
            if px is None:
                continue
            notional = need * scale
            q = notional / px
            gross = q * px * (1 + cost)
            if gross > cash:
                q = cash / (px * (1 + cost))
                gross = q * px * (1 + cost)
            if q * px < 1.0:
                continue
            cash -= gross
            flows.append((exec_date, q * px))
            _entry(sym, q, px, exec_date, gross, signal_date=signal_date)

    for k, day in enumerate(all_dates):
        for tid, d in data.items():
            j = d['date_to_i'].get(day)
            if j is not None:
                last_i[tid] = j

        if pending is not None:
            _execute(pending['book'], day, pending['equity'],
                     pending.get('signal_date'))
            pending = None

        eq = _mark(day)
        equity_curve.append(eq)
        used_dates.append(day)
        exposure.append(_invested(day) / eq if eq > 0 else 0.0)

        if k == len(all_dates) - 1:
            break

        cooldown_before = cooldown
        if cooldown > 0:
            cooldown -= 1
        stop_today = False
        if args.hwm_stop > 0 and cooldown_before == 0 and week_end[k]:
            if eq <= hwm * (1 - args.hwm_stop / 100.0):
                stop_today = True
                cooldown = args.cooldown
                hwm = eq
        if not stop_today:
            hwm = max(hwm, eq)

        blocked = (not risk_on[k]) or cooldown_before > 0 or stop_today
        held = list(positions)
        if blocked:
            book = {'target': [], 'sells': held, 'new': [], 'missing': [],
                    'held_alive': []}
            pending = {'book': book, 'equity': eq, 'signal_date': day}
            continue

        active = active_universe(day) if active_universe is not None else None
        states = {}
        for sym in held:
            tid = sym_to_tid[sym]
            i = last_i[tid]
            if i >= 0:
                states[sym] = cmo_core.signal_at(data[tid]['arr'], i)

        held_alive = [s for s in held if not (s in states and states[s].sell)]
        slots = args.top_n - len(held_alive)
        if slots > 0:
            for tid, d in data.items():
                sym = d['symbol']
                if sym in positions:
                    continue
                if active is not None and sym not in active:
                    continue
                i = last_i[tid]
                if i >= 1 and bool(d['arr']['buy'][i]):
                    sig0 = cmo_core.signal_at(d['arr'], i)
                    if entry_filter is not None and not entry_filter(sig0):
                        continue
                    states[sym] = sig0

        book = cmo_core.build_book(held, states, args.top_n)

        if args.stop_loss > 0:
            forced = set()
            for sym, pos in positions.items():
                tid = sym_to_tid[sym]
                i = last_i[tid]
                if i < 0:
                    continue
                avg = pos['cost_basis'] / pos['shares'] if pos['shares'] else 0.0
                px = float(data[tid]['close'][i])
                if avg > 0 and px <= avg * (1 - args.stop_loss / 100.0):
                    forced.add(sym)
            if forced:
                book['target'] = [s for s in book['target'] if s not in forced]
                book['sells'] = list(dict.fromkeys(book.get('sells', []) + list(forced)))

        pending = {'book': book, 'equity': eq, 'signal_date': day}

    open_positions = []
    for sym, pos in positions.items():
        tid = sym_to_tid[sym]
        i = last_i[tid]
        px = float(data[tid]['close'][i]) if i >= 0 else 0.0
        avg = pos['cost_basis'] / pos['shares'] if pos['shares'] else 0.0
        open_positions.append({
            'symbol': sym, 'qty': pos['shares'],
            'entry_signal_date': pos.get('entry_signal_date'),
            'entry_date': pos['entry_date'], 'exit_date': None,
            'entry_px': avg / (1 + cost) if avg else px,
            'exit_px': px, 'pnl': pos['shares'] * px - pos['cost_basis'],
            'ret': px / avg - 1.0 if avg else 0.0, 'reason': 'open',
        })

    return {
        'dates': used_dates,
        'equity': equity_curve,
        'exposure': exposure,
        'flows': flows,
        'trades': trades,
        'open_positions': open_positions,
        'all_dates': all_dates,
        'risk_on': risk_on,
    }


# ──────────────────────────────── metrics ───────────────────────────────────

def _metrics(equity, dates, exposure, flows, trades, periods=252):
    eq = np.asarray(equity, dtype=np.float64)
    if len(eq) < 2:
        return {}
    rets = np.diff(eq) / eq[:-1]
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    total = float(eq[-1] / eq[0] - 1)
    cagr = float((eq[-1] / eq[0]) ** (1 / years) - 1) if eq[0] > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1).min())
    sharpe = float(rets.mean() / rets.std(ddof=0) * math.sqrt(periods)) if rets.std(ddof=0) > 0 else 0.0
    d0, d1 = dates[0], dates[-1]
    closed = [t for t in trades if d0 <= t['exit_date'] <= d1]
    wins = [t for t in closed if t['pnl'] > 0]
    hold = float(np.mean([(t['exit_date'] - t['entry_date']).days for t in closed])) if closed else 0.0
    notional = sum(n for d, n in flows if d0 <= d <= d1)
    turn = float(notional / max(eq.mean(), 1.0) / years)
    expo = float(np.mean([e for e, d in zip(exposure, dates) if d0 <= d <= d1])) if exposure else 0.0
    return {
        'total': total, 'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe,
        'trades': len(closed), 'win': float(len(wins) / len(closed)) if closed else 0.0,
        'avg_hold': hold, 'turnover': turn,
        'exposure': expo, 'final': float(eq[-1]),
    }


def _slice(metrics_input, start, end, periods=252):
    dates, eq, exposure, flows, trades = metrics_input
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if len(idx) < 2:
        return None
    lo, hi = idx[0], idx[-1]
    return _metrics(eq[lo:hi + 1], dates[lo:hi + 1], exposure[lo:hi + 1],
                    flows, trades, periods)


def _print_metrics(label, m):
    if not m:
        print(f'  {label:<14} (no data)')
        return
    print(f'  {label:<14} '
          f'Win {m["win"]*100:>4.0f}%  MaxDD {m["mdd"]*100:>7.1f}%  '
          f'ret {m["total"]*100:>8.1f}%  Sharpe {m["sharpe"]:>5.2f}  '
          f'n {m["trades"]:>5}  hold {m["avg_hold"]:>5.0f}d  '
          f'turn {m["turnover"]:>5.2f}x/y  expo {m["exposure"]*100:>3.0f}%  '
          f'CAGR {m["cagr"]*100:>6.1f}%')


# ────────────────────────────── event study ─────────────────────────────────

def _universe_returns(data, all_dates):
    di = {d: i for i, d in enumerate(all_dates)}
    sums = np.zeros(len(all_dates))
    cnts = np.zeros(len(all_dates))
    for d in data.values():
        prev = None
        for i, day in enumerate(d['dates']):
            k = di.get(day)
            if k is not None and k > 0 and prev is not None and prev > 0:
                sums[k] += d['close'][i] / prev - 1.0
                cnts[k] += 1
            prev = d['close'][i]
    out = np.zeros(len(all_dates))
    nz = cnts > 0
    out[nz] = sums[nz] / cnts[nz]
    return out


def event_study(data, all_dates, horizons=HORIZONS, start=None, end=None, gate=None):
    ew = _universe_returns(data, all_dates)
    cum = np.cumprod(1.0 + ew)
    di = {d: i for i, d in enumerate(all_dates)}
    out = {h: {'fwd': [], 'excess': []} for h in horizons}
    n_events = 0
    for d in data.values():
        arr = d['arr']
        closes = d['close']
        for i in np.flatnonzero(arr['buy']):
            day = d['dates'][i]
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            k = di.get(day)
            if k is None:
                continue
            if gate is not None and not gate[k]:
                continue
            n_events += 1
            for h in horizons:
                if i + h >= len(closes) or k + h >= len(all_dates):
                    continue
                fwd = closes[i + h] / closes[i] - 1.0
                univ = cum[k + h] / cum[k] - 1.0
                out[h]['fwd'].append(fwd)
                out[h]['excess'].append(fwd - univ)
    return n_events, out


def _print_event_study(n_events, es):
    print(f'  {"horizon":>8} {"n":>8} {"mean":>8} {"median":>8} {"win":>6} '
          f'{"excess":>8} {"ex-win":>7}')
    for h in sorted(es):
        fwd = np.asarray(es[h]['fwd'])
        ex = np.asarray(es[h]['excess'])
        if len(fwd) == 0:
            continue
        print(f'  {h:>6}d {len(fwd):>8,} {fwd.mean()*100:>7.2f}% '
              f'{np.median(fwd)*100:>7.2f}% {(fwd > 0).mean()*100:>5.0f}% '
              f'{ex.mean()*100:>7.2f}% {(ex > 0).mean()*100:>6.0f}%')


def _benchmark(conn, symbol, all_dates, timeframe='day', periods=252):
    rows = load_benchmark(conn, symbol, timeframe)
    if not rows:
        return None
    m = {d: p for d, p in rows}
    px = []
    last = None
    for d in all_dates:
        last = m.get(d, last)
        if last is not None:
            px.append(last)
    px = np.asarray(px, dtype=float)
    if len(px) < 2:
        return None
    rets = np.diff(px) / px[:-1]
    years = max((all_dates[-1] - all_dates[0]).days / 365.25, 1e-9)
    peak = np.maximum.accumulate(px)
    return {
        'total': float(px[-1] / px[0] - 1),
        'cagr': float((px[-1] / px[0]) ** (1 / years) - 1),
        'mdd': float((px / peak - 1).min()),
        'sharpe': float(rets.mean() / rets.std(ddof=0) * math.sqrt(periods)) if rets.std(ddof=0) > 0 else 0.0,
    }


# ────────────────────────────────── main ────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description='CMO strategy backtest (Book A)')
    p.add_argument('--timeframe', choices=['day', 'week'], default='day',
                   help='Alpaca adjusted bar source: daily or weekly')
    p.add_argument('--top-n', type=int, default=25)
    p.add_argument('--start', default=None,
                   help='inclusive start date (default: beginning of dataset)')
    p.add_argument('--end', default=None)
    p.add_argument('--tickers', default=None, help='comma-separated subset')
    p.add_argument('--ma-type', choices=['wma', 'ema'], default='wma')
    p.add_argument('--window', type=int, default=10)
    p.add_argument('--mode',
                   choices=['armed', 'any_in_window', 'same_bar', 'chain', 'cmo_bb'],
                   default='armed')
    p.add_argument('--sell-mode', choices=['mirror', 'any'], default='mirror')
    p.add_argument('--fill', choices=['open', 'close'], default='open')
    p.add_argument('--cost', type=float, default=DEFAULT_COST)
    p.add_argument('--rebalance-band', type=float, default=20.0,
                   help='trim/top-up only beyond this %% of target (live: 20)')
    p.add_argument('--min-notional', type=float, default=500.0,
                   help='skip rebalance deltas below this (live: 500)')
    p.add_argument('--no-event-study', action='store_true')
    p.add_argument('--market-filter', default='none',
                   choices=['none', 'spy_sma50', 'spy_sma100', 'spy_sma200'],
                   help='risk-off overlay: hold cash while SPY is below its SMA')
    p.add_argument('--stop-loss', type=float, default=0.0,
                   help='per-position stop from avg cost, percent (0=off)')
    p.add_argument('--hwm-stop', type=float, default=0.0,
                   help='weekly-close account HWM stop, percent (0=off; live stock leg: 15)')
    p.add_argument('--cooldown', type=int, default=5,
                   help='sessions with no buys after an HWM stop (live: 5)')
    p.add_argument('--p20w-gate', default='none',
                   choices=['none', 'any', 'majority', 'all'],
                   help='live stock-leg P20w CoreEW gate (PHP-canonical; live: any)')
    p.add_argument('--json', default=None, help='optional JSON output path')
    p.add_argument('--trade-csv', default=None, help='optional per-trade CSV output path')
    args = p.parse_args(argv)

    if args.start:
        args.start = date.fromisoformat(args.start)
    if args.end:
        args.end = date.fromisoformat(args.end)
    symbols = set(args.tickers.split(',')) if args.tickers else None

    periods = 52 if args.timeframe == 'week' else 252
    conn = db_module.get_conn()
    try:
        print(f'Loading {args.timeframe} bars (enabled stocks)...', flush=True)
        data = load_universe(conn, symbols, args.timeframe)
        print(f'  {len(data)} tickers with >= {cmo_core.WARMUP_BARS} bars')

        for tid, d in data.items():
            ind = cmo_core.indicators(d, ma_type=args.ma_type)
            d['arr'] = cmo_core.build_signal_arrays(
                ind, window=args.window, mode=args.mode, sell_mode=args.sell_mode)
            d['date_to_i'] = {dt: i for i, dt in enumerate(d['dates'])}

        print(f'Running: {args.timeframe}, top {args.top_n}, CMO{cmo_core.CMO_PERIOD}, '
              f'MACD {cmo_core.MACD_FAST}/{cmo_core.MACD_SLOW}/{cmo_core.MACD_SIGNAL} '
              f'{args.ma_type.upper()}, window {args.window}, mode {args.mode}, '
              f'sell {args.sell_mode}, fill {args.fill}, cost {args.cost:.4%}, '
              f'filter {args.market_filter}, stop {args.stop_loss:g}%, '
              f'hwm {args.hwm_stop:g}%/{args.cooldown}d, gate {args.p20w_gate}')
        bench = (load_benchmark(conn, 'SPY', args.timeframe)
                 if args.market_filter != 'none' else None)
        res = run_sim(data, args, bench)
        dates = res['dates']
        unit = 'weeks' if args.timeframe == 'week' else 'sessions'
        print(f'  Window: {dates[0]} -> {dates[-1]} ({len(dates)} {unit})')

        full = _metrics(res['equity'], dates, res['exposure'],
                        res['flows'], res['trades'], periods)
        _print_metrics('FULL', full)

        print('\n  Sub-windows:')
        slices = [
            ('2017-2020', date(2017, 1, 1), date(2020, 12, 31)),
            ('2021-2023', date(2021, 1, 1), date(2023, 12, 31)),
            ('2024-now', date(2024, 1, 1), dates[-1]),
        ]
        mi = (dates, res['equity'], res['exposure'], res['flows'], res['trades'])
        for label, s, e in slices:
            _print_metrics(label, _slice(mi, s, e, periods))

        spy = _benchmark(conn, 'SPY', dates, args.timeframe, periods)
        if spy:
            print(f'\n  SPY buy-hold   ret {spy["total"]*100:>9.1f}%  '
                  f'CAGR {spy["cagr"]*100:>7.1f}%  DD {spy["mdd"]*100:>7.1f}%  '
                  f'Sharpe {spy["sharpe"]:.2f}')

        if not args.no_event_study:
            gated = args.p20w_gate != 'none' or args.market_filter != 'none'
            gate = res['risk_on'] if gated else None
            tag = 'gated ' if gated else ''
            n, es = event_study(data, res['all_dates'], gate=gate)
            print(f'\n  Signal event study — {tag}{n:,} actionable buy triggers')
            _print_event_study(n, es)
            for label, s, e in slices:
                n2, es2 = event_study(data, res['all_dates'], start=s, end=e, gate=gate)
                print(f'\n  [{label}]')
                _print_event_study(n2, es2)

        if args.trade_csv:
            fields = ['symbol', 'qty', 'entry_signal_date', 'entry_date',
                      'exit_signal_date', 'exit_date', 'entry_px', 'exit_px',
                      'pnl', 'ret', 'reason']
            with open(args.trade_csv, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(res['trades'])
                w.writerows(res['open_positions'])
            print(f'\n  wrote {args.trade_csv}')

        if args.json:
            with open(args.json, 'w') as f:
                json.dump({'args': {k: str(v) for k, v in vars(args).items()},
                           'full': full}, f, indent=2)
            print(f'\n  wrote {args.json}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
