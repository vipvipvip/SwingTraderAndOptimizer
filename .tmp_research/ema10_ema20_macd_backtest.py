#!/usr/bin/env python3
import csv
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MTF = ROOT / 'swingtrader' / 'services' / 'mtf'
sys.path.insert(0, str(MTF))
import db as db_module

SYMBOLS = ('VTV', 'VTI', 'SPY')
BENCH = 'SPY'
CAPITAL = 100_000.0
COST = 0.0005
WARMUP = 41
FIELDS = ['symbol', 'qty', 'entry_signal_date', 'entry_date',
          'exit_signal_date', 'exit_date', 'entry_px', 'exit_px',
          'pnl', 'ret', 'reason']


def _ema(values, span):
    return pd.Series(values, dtype=float).ewm(
        span=span, adjust=False, min_periods=span).mean().to_numpy()


def load(conn, timeframe):
    symbols = SYMBOLS + (BENCH,)
    ids = {s: db_module.get_ticker_id_from_symbol(conn, s) for s in symbols}
    missing = [s for s, tid in ids.items() if tid is None]
    if missing:
        raise SystemExit(f'missing ticker ids: {missing}')
    loader = db_module.bulk_load_weekly if timeframe == 'week' else db_module.bulk_load_daily
    raw = loader(conn, ids.values())
    by_id = {v: k for k, v in ids.items()}
    out = {}
    for tid, d in raw.items():
        symbol = by_id.get(tid)
        if symbol is None:
            continue
        close = np.asarray(d['close'], dtype=float)
        opn = np.asarray(d['open'], dtype=float)
        opn = np.where(opn > 0, opn, close)
        ema10 = _ema(close, 10)
        ema20 = _ema(close, 20)
        val = ema10 - ema20
        avg = _ema(val, 40)
        out[symbol] = {
            'dates': d['dates'], 'open': opn, 'close': close,
            'ema10': ema10, 'ema20': ema20, 'diff': val - avg,
        }
    return out


def align(out, timeframe):
    common = set.intersection(*(set(out[s]['dates']) for s in out))
    today = date.today()
    if timeframe == 'week':
        cutoff = today - timedelta(days=today.weekday())
        common = {d for d in common if d < cutoff}
    else:
        common = {d for d in common if d < today}
    dates = sorted(common)
    aligned = {}
    for symbol, d in out.items():
        idx = {dt: i for i, dt in enumerate(d['dates'])}
        rows = [idx[dt] for dt in dates]
        aligned[symbol] = {
            k: np.asarray(d[k])[rows]
            for k in ('open', 'close', 'ema10', 'ema20', 'diff')
        }
    return dates, aligned


def simulate(dates, s, symbol):
    n = len(dates)
    cash = CAPITAL
    shares = 0.0
    basis = 0.0
    entry_sig = None
    entry_date = None
    entry_px = 0.0
    trades = []
    equity = []
    exposure = []
    for i in range(n):
        mark = cash + shares * s['close'][i]
        equity.append(float(mark))
        exposure.append(float(shares * s['close'][i] / mark) if mark else 0.0)
        if i < WARMUP or i >= n - 1:
            continue
        buy = bool(s['diff'][i] > 0 and s['diff'][i - 1] <= 0
                   and s['ema10'][i] > s['ema20'][i])
        sell = bool(shares > 0 and s['ema10'][i] < s['ema20'][i]
                    and s['ema20'][i] < s['ema20'][i - 1]
                    and s['diff'][i] < 0)
        fill_px = float(s['open'][i + 1])
        if sell:
            proceeds = shares * fill_px * (1 - COST)
            pnl = proceeds - basis
            trades.append({
                'symbol': symbol, 'qty': shares,
                'entry_signal_date': entry_sig, 'entry_date': entry_date,
                'exit_signal_date': dates[i], 'exit_date': dates[i + 1],
                'entry_px': entry_px, 'exit_px': fill_px,
                'pnl': pnl, 'ret': pnl / basis if basis else 0.0,
                'reason': 'signal',
            })
            cash += proceeds
            shares = 0.0
            basis = 0.0
            entry_sig = None
            entry_date = None
            entry_px = 0.0
        elif buy and shares == 0 and cash > 0:
            qty = cash / (fill_px * (1 + COST))
            if qty > 0:
                shares = qty
                basis = cash
                entry_px = fill_px
                entry_sig = dates[i]
                entry_date = dates[i + 1]
                cash = 0.0
    if shares > 0:
        px = float(s['close'][-1])
        value = shares * px
        trades.append({
            'symbol': symbol, 'qty': shares,
            'entry_signal_date': entry_sig, 'entry_date': entry_date,
            'exit_signal_date': None, 'exit_date': None,
            'entry_px': entry_px, 'exit_px': px,
            'pnl': value - basis, 'ret': (value - basis) / basis if basis else 0.0,
            'reason': 'open',
        })
    return {'equity': equity, 'exposure': exposure, 'trades': trades}


def benchmark(dates, s):
    px = s['close']
    eq = CAPITAL * px / px[0]
    return {
        'equity': [float(v) for v in eq],
        'exposure': [1.0] * len(dates),
        'trades': [],
    }


def metrics(equity, dates, exposure, trades, periods):
    eq = np.asarray(equity, dtype=float)
    rets = np.diff(eq) / eq[:-1]
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    total = float(eq[-1] / eq[0] - 1)
    cagr = float((eq[-1] / eq[0]) ** (1 / years) - 1) if eq[0] > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1).min())
    sd = float(rets.std(ddof=0))
    sharpe = float(rets.mean() / sd * math.sqrt(periods)) if sd > 0 else 0.0
    closed = [t for t in trades if t['exit_date'] is not None]
    wins = [t for t in closed if t['pnl'] > 0]
    return {
        'total': total, 'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe,
        'trades': len(closed), 'win': len(wins) / len(closed) if closed else 0.0,
        'exposure': float(np.mean(exposure)), 'final': float(eq[-1]),
    }


def print_metrics(label, m):
    print(f'  {label:<14} ret {m["total"] * 100:>9.1f}%  '
          f'CAGR {m["cagr"] * 100:>6.1f}%  MDD {m["mdd"] * 100:>7.1f}%  '
          f'Sharpe {m["sharpe"]:>5.2f}  trades {m["trades"]:>4}  '
          f'win {m["win"] * 100:>4.0f}%  expo {m["exposure"] * 100:>3.0f}%  '
          f'final ${m["final"]:>11,.0f}')


def write_trades(path, trades):
    rows = sorted(trades, key=lambda r: (r['entry_date'] or date.min, r['symbol']))
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    conn = db_module.get_conn()
    try:
        for timeframe, periods, filename in (
            ('day', 252, 'ema10_ema20_macd_daily_trades.csv'),
            ('week', 52, 'ema10_ema20_macd_weekly_trades.csv'),
        ):
            out = load(conn, timeframe)
            dates, aligned = align(out, timeframe)
            if len(dates) <= WARMUP + 1:
                raise SystemExit(f'not enough {timeframe} bars')
            print(f'\n=== {timeframe.upper()} ===')
            print(f'Window: {dates[0]} -> {dates[-1]} ({len(dates)} bars)')
            all_trades = []
            for symbol in SYMBOLS:
                sim = simulate(dates, aligned[symbol], symbol)
                all_trades.extend(sim['trades'])
                print_metrics(symbol, metrics(
                    sim['equity'], dates, sim['exposure'], sim['trades'], periods))
            bench = benchmark(dates, aligned[BENCH])
            print_metrics('SPY B&H', metrics(
                bench['equity'], dates, bench['exposure'], bench['trades'], periods))
            path = ROOT / 'common' / 'docs' / 'trade_books' / filename
            write_trades(path, all_trades)
            print(f'Trades: {path} ({len(all_trades)} rows)')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
