#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import traceback
from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cmo_universe  # noqa: E402
import config  # noqa: E402
import db as db_module  # noqa: E402
import executor  # noqa: E402
import runner  # noqa: E402

NY = ZoneInfo('America/New_York')
ETF_MODE = 'etf'
STOCK_MODE = 'stock'
TAGS = {'etf': 'S1-ETF', 'stock': 'S1-STOCK'}
COST = 0.0005
REBALANCE_BAND_PCT = 20.0
MIN_TRADE_NOTIONAL = 500.0
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS s1_runs (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(10) NOT NULL,
    sig_date DATE NOT NULL,
    action VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    detail TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (mode, sig_date, action)
);
CREATE TABLE IF NOT EXISTS s1_trades (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(10) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL,
    price NUMERIC(12,4) NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    reason VARCHAR(40) NOT NULL DEFAULT '',
    pnl_dollar NUMERIC(14,4),
    pnl_pct NUMERIC(10,4),
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def _now():
    return datetime.now(NY)


def _send_slack(mode, msg, alert=False, no_slack=False):
    if no_slack or not config.SLACK_WEBHOOK_URL:
        return
    try:
        acct_no = executor._get_account_number()
    except Exception:
        acct_no = '?'
    text = f'{"🚨 " if alert else ""}[{TAGS[mode]}] [Paper:{acct_no}] {msg}'
    try:
        executor._session.post(config.SLACK_WEBHOOK_URL, json={'text': text}, timeout=30)
    except Exception as exc:
        print(f'[S1-LIVE] Slack error: {exc}', flush=True)


def _pool(mode, conn, sig_date):
    if mode == STOCK_MODE:
        result = cmo_universe.active_universe(sig_date, conn=conn)
        return sorted(result['symbols'])
    return sorted(symbol for _, symbol in db_module.get_all_tickers(conn, is_etf=True))


def _latest_settled_date(conn, mode):
    expected = db_module.count_enabled_tickers(conn, is_etf=mode == ETF_MODE)
    required = max(int(expected * runner.COVERAGE_DATE_PICK), 1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.date::date FROM tbl_prices_daily d "
            "JOIN tbl_stock_tickers s ON s.id=d.ticker_id "
            "WHERE s.enabled=true AND s.is_etf=%s AND d.date::date < CURRENT_DATE "
            "GROUP BY d.date::date HAVING COUNT(DISTINCT d.ticker_id) >= %s "
            "ORDER BY d.date::date DESC LIMIT 1", (mode == ETF_MODE, required))
        row = cur.fetchone()
    return row[0] if row else None


def _load_history(conn, mode, pool, sig_date):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.symbol, p.date, p.open, p.close FROM tbl_prices_daily p "
            "JOIN tbl_stock_tickers s ON s.id=p.ticker_id "
            "WHERE s.symbol = ANY(%s) AND p.date::date <= %s::date ORDER BY p.date",
            (pool, sig_date))
        drows = cur.fetchall()
        cur.execute(
            "SELECT s.symbol, p.date, p.close FROM tbl_prices_weekly p "
            "JOIN tbl_stock_tickers s ON s.id=p.ticker_id "
            "WHERE s.symbol = ANY(%s) ORDER BY p.date", (pool,))
        wrows = cur.fetchall()
    d = pd.DataFrame(drows, columns=['symbol', 'date', 'open', 'close'])
    w = pd.DataFrame(wrows, columns=['symbol', 'date', 'close'])
    for df in (d, w):
        df['date'] = pd.to_datetime(df['date'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
    d['open'] = pd.to_numeric(d['open'], errors='coerce')
    d = d.pivot(index='date', columns='symbol', values='close').reindex(columns=pool)
    w = w.pivot(index='date', columns='symbol', values='close').reindex(columns=pool)
    return d, w


def _ema(series, span):
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _signals(d, w, sig_date):
    d10, d20 = _ema(d, 10), _ema(d, 20)
    valid = np.isfinite(d10) & np.isfinite(d20)
    cross_up = (valid & (d10 > d20) & (d10.shift(1) <= d20.shift(1))).fillna(False)
    settled = w[[(week + pd.Timedelta(days=7)).date() <= sig_date for week in w.index]]
    cross_dn_daily = pd.DataFrame(False, index=d.index, columns=d.columns)
    if not settled.empty:
        w10, w20 = _ema(settled, 10), _ema(settled, 20)
        wstate = (w10 > w20).where(np.isfinite(w10) & np.isfinite(w20), False)
        wdn = (~wstate) & wstate.shift(1).fillna(False)
        for week in settled.index:
            flags = wdn.loc[week]
            if not flags.any():
                continue
            later = d[d.index >= week + pd.Timedelta(days=7)]
            if later.empty:
                continue
            first_day = later.index[0]
            for sym in flags[flags].index:
                cross_dn_daily.loc[first_day, sym] = True
    held = {s: False for s in d.columns}
    for day in d.index:
        for s in d.columns:
            if not held[s] and bool(cross_up.loc[day, s]):
                held[s] = True
            elif held[s] and bool(cross_dn_daily.loc[day, s]):
                held[s] = False
    active = {s for s in d.columns if held[s]}
    return active


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def _claim(conn, mode, sig_date, action):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO s1_runs (mode, sig_date, action, status, detail) "
            "VALUES (%s, %s, %s, 'running', %s) "
            "ON CONFLICT (mode, sig_date, action) DO UPDATE SET "
            "status='running', detail=EXCLUDED.detail, updated_at=NOW() "
            "WHERE s1_runs.status <> 'ok' RETURNING id",
            (mode, sig_date, action, None))
        row = cur.fetchone()
    conn.commit()
    return bool(row)


def _record_run(conn, mode, sig_date, status, detail, action='execute'):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE s1_runs SET status=%s, detail=%s, updated_at=NOW() "
            "WHERE mode=%s AND sig_date=%s AND action=%s",
            (status, detail[:1000] if detail else None, mode, sig_date, action))
    conn.commit()


def _insert_trade(conn, mode, symbol, side, qty, price, executed_at, reason,
                  entry_price=None):
    ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
    pnl = pnl_pct = None
    if ticker_id is None:
        print(f'[S1-LIVE] no ticker_id for {symbol}; trade not logged', flush=True)
        return
    if side == 'SELL' and entry_price:
        pnl = (price - entry_price) * qty
        pnl_pct = (price - entry_price) / entry_price * 100
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO s1_trades (mode, symbol, side, quantity, price, executed_at, "
            "reason, pnl_dollar, pnl_pct) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (mode, symbol, side, qty, round(price, 4), executed_at, reason,
             round(pnl, 4) if pnl is not None else None,
             round(pnl_pct, 4) if pnl_pct is not None else None))
    conn.commit()


def _execute_order(mode, conn, symbol, qty, side, executed_at, reason, lines,
                   dry_run, entry_price=None):
    qty = int(qty)
    if qty < 1:
        return False
    if dry_run:
        lines.append(f'  [DRY-RUN] {side} {qty} {symbol} [{reason}]')
        return True
    try:
        order = executor._place_order(symbol, qty, side)
    except Exception as exc:
        msg = f'{symbol} {side} order failed: {exc}'
        _send_slack(mode, msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    try:
        filled = executor._wait_for_fill(order.get('id'))
    except Exception as exc:
        msg = f'{symbol} {side} fill check failed after order {order.get("id")}: {exc}'
        _send_slack(mode, msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    if not filled or filled.get('status') != 'filled':
        status = (filled or order).get('status')
        msg = f'{symbol} {side} order {order.get("id")} not filled: {status}'
        _send_slack(mode, msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    filled_qty = int(float(filled.get('filled_qty') or qty))
    price = float(filled.get('filled_avg_price') or 0)
    if filled_qty < 1 or price <= 0:
        msg = f'{symbol} {side} fill missing qty/price'
        _send_slack(mode, msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    _insert_trade(conn, mode, symbol, side, filled_qty, price, executed_at,
                  reason, entry_price=entry_price)
    lines.append(f'  {side} {filled_qty} {symbol} @ ${price:.2f} [{reason}]')
    return True


def _market_check(mode, dry_run):
    if dry_run:
        return True
    now = _now()
    if dt_time(9, 30) <= now.time() < dt_time(10, 0):
        _send_slack(mode, '⚠️ 09:30–10:00 ET warm-up — no orders placed', alert=True)
        return False
    try:
        clock = executor._get_clock()
    except Exception as exc:
        _send_slack(mode, f'⚠️ Alpaca clock failed ({exc}) — no orders placed', alert=True)
        return False
    if not clock.get('is_open'):
        print('[S1-LIVE] market closed — no orders placed', flush=True)
        return False
    return True


def _ensure_data(mode, dry_run):
    cmd = [runner.SCANNER_VENV_PYTHON, runner.DATA_GATE_SCRIPT,
           '--check' if dry_run else '--ensure', '--tf', 'day,week', '--mode', mode]
    print(f'[S1-LIVE] $ {" ".join(cmd)}', flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.stdout:
        print(result.stdout[-1500:], flush=True)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr[-800:], flush=True)
        raise RuntimeError(f'data readiness gate failed with exit {result.returncode}')


def _handover(mode, conn, executed_at, dry_run, no_slack, lines):
    if not dry_run:
        executor._cancel_all_open_orders()
    positions = executor._get_alpaca_positions()
    if not positions:
        lines.append('  handover: no positions to liquidate')
        return True
    ok = True
    sold = 0
    for symbol in sorted(positions):
        qty = abs(int(float(positions[symbol].get('qty', 0))))
        if qty < 1:
            continue
        price = float(positions[symbol].get('current_price') or 0)
        entry = float(positions[symbol].get('avg_entry_price') or price)
        result = _execute_order(mode, conn, symbol, qty, 'SELL', executed_at,
                                'handover', lines, dry_run, entry_price=entry)
        ok = ok and result
        sold += int(result)
    lines.append(f'  handover complete: {sold} position(s) sold, no buys')
    return ok


def _qty(position):
    return max(int(float(position.get('qty') or 0)), 0)


def _price(symbol, positions):
    price = float(positions.get(symbol, {}).get('current_price') or 0)
    if not price:
        price = executor._latest_trade_price(symbol)
    return float(price or 0)


def _run(args):
    mode = args.mode
    dry_run = args.dry_run
    conn = db_module.get_conn()
    _ensure_tables(conn)
    lines = []
    sig_date = None
    try:
        executor._set_alpaca_keys(mode)
        executor._wait_for_network()
        if not _market_check(mode, dry_run):
            return 0
        if args.handover:
            if not args.skip_gate:
                _ensure_data(mode, dry_run)
            ok = _handover(mode, conn, _now(), dry_run, args.no_slack, lines)
            summary = f'HANDOVER {mode} | ' + ' | '.join(lines)
            print(f'[S1-LIVE] {summary}', flush=True)
            _send_slack(mode, summary, alert=not ok, no_slack=args.no_slack)
            return 0 if ok else 1
        if not args.skip_gate:
            _ensure_data(mode, dry_run)
        sig_date = args.sig_date or _latest_settled_date(conn, mode)
        if sig_date is None:
            raise RuntimeError('no settled daily date found')
        if isinstance(sig_date, str):
            sig_date = date.fromisoformat(sig_date)
        pool = _pool(mode, conn, sig_date)
        if not dry_run and not _claim(conn, mode, sig_date, 'execute'):
            print(f'[S1-LIVE] already executed for {mode} {sig_date} — skipping', flush=True)
            return 0
        all_ok = True
        d, w = _load_history(conn, mode, pool, sig_date)
        targets = _signals(d, w, sig_date)
        if not dry_run:
            executor._cancel_all_open_orders()
        positions = executor._get_alpaca_positions()
        account = executor._get_account()
        equity = float(account.get('equity', 0))
        cash = float(account.get('cash', 0))
        sim_positions = {s: dict(p) for s, p in positions.items()} if dry_run else None
        exits = set(positions) - targets
        lines.append(f'sig={sig_date} equity=${equity:,.0f} cash=${cash:,.0f} '
                     f'pool={len(pool)} held={len(positions)} targets={len(targets)} '
                     f'exits={len(exits)}')
        executed_at = _now()
        sell_lines = []
        buy_lines = []
        each = equity / len(targets) if targets else 0.0
        sell_plan = []
        for s in sorted(exits):
            qty = _qty(positions[s])
            if qty:
                sell_plan.append((s, qty, 'outside-target',
                                  float(positions[s].get('avg_entry_price') or 0)))
        for s in sorted(set(positions) & targets):
            qty = _qty(positions[s])
            if not qty:
                continue
            price = _price(s, positions)
            if not price or not each:
                continue
            drift = (qty * price - each) / each * 100
            trim = int((qty * price - each) / price)
            if drift > REBALANCE_BAND_PCT and trim > 0 and trim * price >= MIN_TRADE_NOTIONAL:
                sell_plan.append((s, trim, 'rebalance-trim',
                                  float(positions[s].get('avg_entry_price') or 0)))
        for s, qty, reason, entry_price in sell_plan:
            ok = _execute_order(mode, conn, s, qty, 'SELL', executed_at, reason,
                                sell_lines, dry_run, entry_price=entry_price)
            all_ok = all_ok and ok
            if ok and dry_run:
                cash += qty * _price(s, sim_positions) * (1 - COST)
                left = _qty(sim_positions.get(s, {})) - qty
                if left > 0:
                    sim_positions[s]['qty'] = left
                else:
                    sim_positions.pop(s, None)
        if dry_run:
            positions = sim_positions
        else:
            account = executor._get_account()
            cash = float(account.get('cash', 0))
            positions = executor._get_alpaca_positions()
        buy_plan = []
        for s in sorted(targets):
            price = _price(s, positions)
            if not price or not each:
                continue
            held_qty = _qty(positions.get(s, {}))
            value = held_qty * price
            drift = (value - each) / each * 100
            if held_qty and abs(drift) < REBALANCE_BAND_PCT:
                continue
            delta = each - value
            if delta <= 0:
                continue
            qty = int(delta / (price * (1 + COST)))
            if qty * price < MIN_TRADE_NOTIONAL:
                continue
            reason = 'rebalance-add' if held_qty else 'daily-entry'
            buy_plan.append([s, qty, price, reason])
        needed = sum(qty * price * (1 + COST) for _, qty, price, _ in buy_plan)
        if needed > cash and needed > 0:
            scale = max(cash * 0.995 / needed, 0.0)
            for plan in buy_plan:
                plan[1] = int(plan[1] * scale)
        cash_left = cash
        for s, qty, price, reason in buy_plan:
            if qty < 1 or qty * price < MIN_TRADE_NOTIONAL:
                continue
            qty = min(qty, int(cash_left / (price * (1 + COST))))
            if qty < 1:
                continue
            ok = _execute_order(mode, conn, s, qty, 'BUY', executed_at, reason,
                                buy_lines, dry_run)
            all_ok = all_ok and ok
            if ok:
                cash_left -= qty * price * (1 + COST)
        lines.extend(sell_lines)
        lines.extend(buy_lines)
        summary = f'{mode.upper()} sig={sig_date} | ' + ' | '.join(lines)
        if not all_ok:
            summary = f'PARTIAL/FAILED orders | {summary}'
        print(f'[S1-LIVE] {summary}', flush=True)
        _send_slack(mode, summary, alert=not all_ok, no_slack=args.no_slack)
        if not dry_run:
            _record_run(conn, mode, sig_date, 'ok' if all_ok else 'error', summary)
        return 0 if all_ok else 1
    except Exception:
        msg = traceback.format_exc()
        print(f'[S1-LIVE] CRASH ```{msg[-1800:]}```', flush=True)
        _send_slack(mode, f'⚠️ CRASH sig={sig_date} ```{msg[-1800:]}```',
                    alert=True, no_slack=args.no_slack)
        if sig_date and not dry_run:
            _record_run(conn, mode, sig_date, 'error', msg[-1000:])
        return 1
    finally:
        conn.close()


def _recap(mode, send_slack=True):
    conn = db_module.get_conn()
    _ensure_tables(conn)
    try:
        executor._set_alpaca_keys(mode)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sig_date, status, detail FROM s1_runs "
                "WHERE mode=%s AND action='execute' ORDER BY sig_date DESC LIMIT 1", (mode,))
            run = cur.fetchone()
            cur.execute(
                "SELECT symbol, side, quantity, price, reason FROM s1_trades "
                "WHERE mode=%s AND executed_at::date = CURRENT_DATE ORDER BY id", (mode,))
            trades = cur.fetchall()
        lines = []
        if run:
            lines.append(f'sig={run[0]} status={run[1]}')
        else:
            lines.append('no S1 run recorded')
        buys = [t for t in trades if t[1] == 'BUY']
        sells = [t for t in trades if t[1] == 'SELL']
        lines.append(f'trades={len(trades)} buys={len(buys)} sells={len(sells)}')
        for symbol, side, qty, price, reason in sells[:20]:
            lines.append(f'  SELL {int(qty)} {symbol} @ ${float(price):.2f} [{reason}]')
        for symbol, side, qty, price, reason in buys[:20]:
            lines.append(f'  BUY {int(qty)} {symbol} @ ${float(price):.2f} [{reason}]')
        if len(trades) > 40:
            lines.append(f'  ... {len(trades) - 40} more')
        summary = f'{mode.upper()} RECAP | ' + ' | '.join(lines)
        print(f'[S1-LIVE] {summary}', flush=True)
        if send_slack:
            _send_slack(mode, summary)
        return True
    except Exception:
        print(f'[S1-LIVE] RECAP CRASH ```{traceback.format_exc()[-1200:]}```', flush=True)
        return False
    finally:
        conn.close()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=[ETF_MODE, STOCK_MODE], required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--no-slack', action='store_true')
    p.add_argument('--handover', action='store_true')
    p.add_argument('--skip-gate', action='store_true')
    p.add_argument('--sig-date')
    p.add_argument('--recap', action='store_true')
    args = p.parse_args(argv)
    if args.recap:
        return 0 if _recap(args.mode, send_slack=not args.no_slack) else 1
    return _run(args)


if __name__ == '__main__':
    sys.exit(main())
