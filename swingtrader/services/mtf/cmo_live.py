#!/usr/bin/env python3
import argparse
import math
import os
import subprocess
import sys
import traceback
from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo

import numpy as np
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import cmo_core  # noqa: E402
import cmo_universe  # noqa: E402
import config  # noqa: E402
import db as db_module  # noqa: E402
import executor  # noqa: E402
import runner  # noqa: E402
from backtest_trio_ew import (fetch_live_leg_ema_series,  # noqa: E402
                              flags_from_live_leg_ema_series)
from portfolio_guard import GuardConfig, GuardState, step as guard_step  # noqa: E402

NY = ZoneInfo('America/New_York')
MODE = 'cmo40'
TAG = 'CMO-Bounce40'
BOUNCE_LO = -40.0
BOUNCE_EXIT = 30.0
BOUNCE_HARD_STOP = -60.0
BB_GAP_MULT = 0.99
HWM_STOP_PCT = 0.15
HWM_COOLDOWN_SESSIONS = 5
REBALANCE_BAND_PCT = 20.0
MIN_TRADE_NOTIONAL = 500.0
MARKET_GATE_LEGS = ('QQQ', 'VTI', 'VTV')
MARKET_GATE_NEED = 2
GUARD_CFG = GuardConfig(
    hwm_stop_pct=HWM_STOP_PCT,
    sweep_pct=0.0,
    cooldown_sessions=HWM_COOLDOWN_SESSIONS,
    reset_hwm_on_stop=True,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cmo_positions (
    ticker_id INTEGER PRIMARY KEY REFERENCES tbl_stock_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(12,4) NOT NULL,
    entry_price NUMERIC(12,4),
    entry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS cmo_trades (
    id SERIAL PRIMARY KEY,
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


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def _send_slack(msg, alert=False, no_slack=False):
    if no_slack or not config.SLACK_WEBHOOK_URL:
        return
    try:
        acct_no = executor._get_account_number()
    except Exception:
        acct_no = '?'
    text = f'{"🚨 " if alert else ""}[{TAG}] [Paper:{acct_no}] {msg}'
    try:
        executor._session.post(config.SLACK_WEBHOOK_URL, json={'text': text}, timeout=30)
    except Exception as exc:
        print(f'[CMO-LIVE] Slack error: {exc}', flush=True)


def _latest_settled_date(conn):
    expected = db_module.count_enabled_tickers(conn, is_etf=False)
    required = max(int(expected * runner.COVERAGE_DATE_PICK), 1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.date::date FROM tbl_prices_daily d "
            "JOIN tbl_stock_tickers s ON s.id=d.ticker_id "
            "WHERE s.enabled=true AND s.is_etf=false AND d.date::date < CURRENT_DATE "
            "GROUP BY d.date::date HAVING COUNT(DISTINCT d.ticker_id) >= %s "
            "ORDER BY d.date::date DESC LIMIT 1", (required,))
        row = cur.fetchone()
    return row[0] if row else None


def _week_end(conn, sig_date):
    expected = db_module.count_enabled_tickers(conn, is_etf=False)
    required = max(int(expected * runner.COVERAGE_DATE_PICK), 1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT d.date::date FROM tbl_prices_daily d "
            "JOIN tbl_stock_tickers s ON s.id=d.ticker_id "
            "WHERE s.enabled=true AND s.is_etf=false "
            "AND d.date::date > %s AND d.date::date < CURRENT_DATE "
            "GROUP BY d.date::date HAVING COUNT(DISTINCT d.ticker_id) >= %s",
            (sig_date, required))
        later = [r[0] for r in cur.fetchall()]
    key = sig_date.isocalendar()[:2]
    return not any(d.isocalendar()[:2] == key for d in later)


def _ensure_data(sig_date, no_slack=False):
    conn = db_module.get_conn()
    try:
        gap = runner._sessions_since(conn, sig_date)
        if gap > runner.MAX_STALE_SESSIONS:
            _send_slack(
                f'⚠️ settled data {sig_date} is {gap} session(s) behind — running price heal',
                no_slack=no_slack)
            for _ in range(runner.DATA_RETRIES):
                runner._backfill_daily(conn, 'stock')
                gap = runner._sessions_since(conn, sig_date)
                if gap <= runner.MAX_STALE_SESSIONS:
                    break
        if gap > runner.MAX_STALE_SESSIONS:
            raise RuntimeError(f'settled data still {gap} session(s) behind after heal')
    finally:
        conn.close()

    cmd = [runner.SCANNER_VENV_PYTHON, runner.DATA_GATE_SCRIPT,
           '--ensure', '--tf', 'day,week', '--mode', 'stock']
    print(f'[CMO-LIVE] $ {" ".join(cmd)}', flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.stdout:
        print(result.stdout[-1500:], flush=True)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr[-800:], flush=True)
        raise RuntimeError(f'data readiness gate failed with exit {result.returncode}')


def _bounce_arrays(daily):
    ind = cmo_core.indicators(daily, ma_type='wma')
    arr = cmo_core.build_signal_arrays(ind, mode='cmo_bb', sell_mode='mirror')
    valid = arr['valid']
    cmo = arr['cmo']
    buy = valid & cmo_core._cross_above_zero_event(cmo - BOUNCE_LO)
    sell = valid & (cmo_core._cross_above_zero_event(cmo - BOUNCE_EXIT)
                    | (cmo < BOUNCE_HARD_STOP))
    arr['buy'] = buy
    arr['sell'] = sell
    arr['last_cmo_up'] = cmo_core._last_event_index(buy)
    return arr


def _load_signals(symbols, sig_date, conn):
    if not symbols:
        return {}, {}
    tickers = []
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, symbol FROM tbl_stock_tickers '
            'WHERE enabled=true AND is_etf=false AND symbol = ANY(%s) ORDER BY symbol',
            (list(symbols),))
        tickers = cur.fetchall()
    raw = db_module.bulk_load_daily(conn, [t[0] for t in tickers])
    states = {}
    closes = {}
    for tid, symbol in tickers:
        d = raw.get(tid)
        if not d or len(d['dates']) < cmo_core.WARMUP_BARS:
            continue
        dates = list(d['dates'])
        if sig_date not in dates:
            continue
        i = dates.index(sig_date)
        dates = dates[:i + 1]
        close = np.asarray(d['close'][:i + 1], dtype=np.float64)
        if not np.isfinite(close).all() or (close <= 0).any():
            continue
        arr = _bounce_arrays({'close': close, 'dates': dates})
        sig = cmo_core.signal_at(arr, i)
        if not sig.valid:
            continue
        states[symbol] = sig
        closes[symbol] = float(close[i])
    return states, closes


def _entry_ok(sig):
    return (np.isfinite(sig.ema10) and np.isfinite(sig.bb_mid)
            and sig.bb_mid > 0 and sig.ema10 >= sig.bb_mid * BB_GAP_MULT)


def _p20w_majority(sig_date):
    payload = fetch_live_leg_ema_series(20, list(MARKET_GATE_LEGS))
    flags = flags_from_live_leg_ema_series([sig_date], payload)
    count = sum(int(bool(flags[s][0])) for s in payload['symbols'])
    return count >= MARKET_GATE_NEED, count


def _get_cmo_position(conn, symbol):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT symbol, quantity, entry_price, entry_at FROM cmo_positions '
            'WHERE symbol=%s', (symbol,))
        return cur.fetchone()


def _upsert_cmo_position(conn, symbol, qty, entry_price, entry_at):
    ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
    if not ticker_id:
        return
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO cmo_positions (ticker_id, symbol, quantity, entry_price, entry_at, updated_at) '
            'VALUES (%s,%s,%s,%s,%s,NOW()) ON CONFLICT (ticker_id) DO UPDATE SET '
            'quantity=EXCLUDED.quantity, entry_price=EXCLUDED.entry_price, '
            'entry_at=EXCLUDED.entry_at, updated_at=NOW()',
            (ticker_id, symbol, qty, round(entry_price, 4), entry_at))
    conn.commit()


def _adjust_cmo_position(conn, symbol, qty):
    with conn.cursor() as cur:
        cur.execute('UPDATE cmo_positions SET quantity=%s, updated_at=NOW() WHERE symbol=%s',
                    (qty, symbol))
    conn.commit()


def _delete_cmo_position(conn, symbol):
    with conn.cursor() as cur:
        cur.execute('DELETE FROM cmo_positions WHERE symbol=%s', (symbol,))
    conn.commit()


def _insert_cmo_trade(conn, symbol, side, qty, price, executed_at, reason='',
                      pnl_dollar=None, pnl_pct=None):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO cmo_trades (symbol, side, quantity, price, executed_at, reason, '
            'pnl_dollar, pnl_pct) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (symbol, side, qty, round(price, 4), executed_at, reason,
             round(pnl_dollar, 4) if pnl_dollar is not None else None,
             round(pnl_pct, 4) if pnl_pct is not None else None))
    conn.commit()


def _position_entry_price(conn, symbol, pos, fallback):
    row = _get_cmo_position(conn, symbol)
    if row and row[2]:
        return float(row[2])
    avg = pos.get('avg_entry_price') if pos else None
    if avg:
        return float(avg)
    return float(fallback)


def _already_ran(conn, sig_date):
    with conn.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM mtf_runs WHERE mode=%s AND sig_date=%s '
            "AND action='execute' AND status='ok' LIMIT 1", (MODE, sig_date))
        return cur.fetchone() is not None


def _record_run(conn, sig_date, status, detail):
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO mtf_runs (mode, sig_date, action, status, detail, created_at) '
            'VALUES (%s,%s,%s,%s,%s,NOW())',
            (MODE, sig_date, 'execute', status, detail[:1000] if detail else None))
    conn.commit()


def _execute_order(symbol, qty, side, conn, executed_at, reason, entry_price=None,
                   dry_run=False, lines=None, update_position=True):
    qty = int(qty)
    if qty < 1:
        return False
    if dry_run:
        lines.append(f'  [DRY-RUN] {side.upper()} {qty} {symbol}')
        return False
    order = executor._place_order(symbol, qty, side)
    filled = executor._wait_for_fill(order.get('id'))
    if not filled or filled.get('status') != 'filled':
        status = (filled or order).get('status')
        msg = f'{symbol} {side.upper()} order {order.get("id")} not filled: {status}'
        _send_slack(msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    filled_qty = int(float(filled.get('filled_qty') or qty))
    price = float(filled.get('filled_avg_price') or 0)
    if filled_qty < 1 or price <= 0:
        msg = f'{symbol} {side.upper()} fill missing qty/price'
        _send_slack(msg, alert=True)
        lines.append(f'  ❌ {msg}')
        return False
    if side == 'sell':
        avg = float(entry_price or price)
        pnl = (price - avg) * filled_qty
        pnl_pct = (price - avg) / avg * 100 if avg else 0.0
        _insert_cmo_trade(conn, symbol, 'SELL', filled_qty, price, executed_at,
                          reason=reason, pnl_dollar=pnl, pnl_pct=pnl_pct)
        if update_position:
            row = _get_cmo_position(conn, symbol)
            if row:
                new_qty = max(0.0, float(row[1]) - filled_qty)
                if new_qty <= 0:
                    _delete_cmo_position(conn, symbol)
                else:
                    _adjust_cmo_position(conn, symbol, new_qty)
    else:
        _insert_cmo_trade(conn, symbol, 'BUY', filled_qty, price, executed_at, reason=reason)
        if update_position:
            row = _get_cmo_position(conn, symbol)
            new_qty = filled_qty + (float(row[1]) if row else 0.0)
            avg = float(entry_price or price)
            if row and row[2]:
                old_qty = float(row[1])
                avg = (float(row[2]) * old_qty + avg * filled_qty) / new_qty
            _upsert_cmo_position(conn, symbol, new_qty, avg, executed_at)
    lines.append(f'  {side.upper()} {filled_qty} {symbol} @ ${price:.2f} [{reason}]')
    return True


def _market_check(dry_run):
    if dry_run:
        return True
    now = _now()
    if dt_time(9, 30) <= now.time() < dt_time(10, 0):
        _send_slack('⚠️ 09:30–10:00 ET warm-up — no orders placed', alert=True)
        return False
    try:
        clock = executor._get_clock()
    except Exception as exc:
        _send_slack(f'⚠️ Alpaca clock failed ({exc}) — no orders placed', alert=True)
        return False
    if not clock.get('is_open'):
        print('[CMO-LIVE] market closed — no orders placed', flush=True)
        return False
    return True


def _handover(conn, executed_at, dry_run, no_slack, lines):
    positions = executor._get_alpaca_positions()
    if not dry_run:
        executor._cancel_all_open_orders()
    if not positions:
        lines.append('  handover: no stock positions to liquidate')
    failed = []
    for symbol in sorted(positions):
        qty = abs(int(float(positions[symbol].get('qty', 0))))
        if qty < 1:
            continue
        price = float(positions[symbol].get('current_price') or 0)
        entry = _position_entry_price(conn, symbol, positions[symbol], price)
        filled = _execute_order(symbol, qty, 'sell', conn, executed_at, 'handover',
                                entry_price=entry, dry_run=dry_run, lines=lines,
                                update_position=False)
        if not dry_run:
            if filled:
                _delete_cmo_position(conn, symbol)
                ticker_id = db_module.get_ticker_id_from_symbol(conn, symbol)
                if ticker_id:
                    db_module.delete_position(conn, ticker_id)
            else:
                failed.append(symbol)
    if not dry_run:
        account = executor._get_account()
        equity = float(account.get('equity', 0))
        state = GuardState(hwm=equity)
        db_module.save_guard_state(conn, MODE, state.to_dict(), '')
        if failed:
            msg = f'handover fills incomplete: {", ".join(sorted(failed))} — DB rows retained'
            _send_slack(msg, alert=True, no_slack=no_slack)
            lines.append(f'  ⚠️ {msg}')
        _record_run(conn, date.today(), 'ok' if not failed else 'error',
                    f'handover {len(positions) - len(failed)}/{len(positions)} filled')
    lines.append(f'  handover complete: {len(positions)} position(s), no buys')


def _run(args):
    dry_run = args.dry_run
    sig_date = None
    conn = db_module.get_conn()
    _ensure_tables(conn)
    lines = []
    try:
        executor._set_alpaca_keys('stock')
        executor._wait_for_network()
        if not _market_check(dry_run):
            print('[CMO-LIVE] skipped', flush=True)
            return 0
        executed_at = _now()
        sig_date = args.sig_date or _latest_settled_date(conn)
        if sig_date is None:
            raise RuntimeError('no settled daily date found')
        if isinstance(sig_date, str):
            sig_date = date.fromisoformat(sig_date)

        if args.handover:
            _handover(conn, executed_at, dry_run, args.no_slack, lines)
            summary = f'HANDOVER sig={sig_date} | ' + ' | '.join(lines)
            print(f'[CMO-LIVE] {summary}', flush=True)
            _send_slack(summary, no_slack=args.no_slack)
            return 0

        if not dry_run and _already_ran(conn, sig_date):
            print(f'[CMO-LIVE] already executed for {sig_date} — skipping', flush=True)
            return 0
        if not dry_run:
            _ensure_data(sig_date, no_slack=args.no_slack)

        universe = cmo_universe.active_universe(sig_date, conn=conn)
        positions = executor._get_alpaca_positions()
        account = executor._get_account()
        cash = float(account.get('cash', 0))
        if args.assume_flat and not dry_run:
            raise RuntimeError('--assume-flat is only valid with --dry-run')
        if args.assume_flat:
            positions = {}
            cash = float(account.get('equity', 0))
        held = sorted(positions)
        symbols = sorted(universe['symbols'] | set(held))
        states, closes = _load_signals(symbols, sig_date, conn)

        mark_equity = cash
        for sym in held:
            px = closes.get(sym)
            if px is None:
                px = float(positions[sym].get('current_price') or 0)
            mark_equity += abs(float(positions[sym].get('qty', 0))) * px

        raw_guard, guard_week = db_module.get_guard_state(conn, MODE, ensure=not dry_run)
        guard = (GuardState.from_dict(raw_guard) if raw_guard
                 else GuardState(hwm=mark_equity))
        if guard.hwm <= 0:
            guard.hwm = mark_equity
            guard.sweep_hwm = mark_equity
        guard, decision = guard_step(
            guard, GUARD_CFG, equity=mark_equity, session=str(sig_date),
            allow_sweep=False, allow_stop=_week_end(conn, sig_date))

        risk_on, gate_count = _p20w_majority(sig_date)
        blocked = bool(decision.liquidate or decision.paused or not risk_on)

        held_alive = []
        sells = []
        for sym in held:
            sig = states.get(sym)
            if sig is None:
                held_alive.append(sym)
                lines.append(f'  ⚠️ {sym} held but not scored — preserving')
            elif sig.sell:
                sells.append(sym)
            else:
                held_alive.append(sym)

        new = []
        if not blocked:
            candidates = [s for s in universe['symbols']
                          if s not in positions and s in states
                          and states[s].buy and _entry_ok(states[s])]
            candidates.sort(key=lambda s: cmo_core.rank_key(s, states[s]))
            new = candidates

        if blocked:
            target = []
            sells = sorted(set(held) | set(sells))
        else:
            target = held_alive + new
            target_set = set(target)
            for sym in held:
                if sym not in target_set and sym not in sells:
                    sells.append(sym)

        target_value = mark_equity / len(target) if target else 0.0
        available = cash
        sell_orders = []
        buy_orders = []
        for sym in sorted(set(sells)):
            pos = positions.get(sym)
            if not pos:
                continue
            qty = abs(int(float(pos.get('qty', 0))))
            if qty < 1:
                continue
            px = float(pos.get('current_price') or 0) or closes.get(sym, 0)
            if px > 0:
                available += qty * px
            sell_orders.append((sym, qty))
        for sym in target:
            pos = positions.get(sym)
            qty_now = abs(int(float(pos.get('qty', 0)))) if pos else 0
            value_now = qty_now * closes.get(sym, 0)
            if value_now > target_value * (1 + REBALANCE_BAND_PCT / 100):
                excess = value_now - target_value
                if excess >= MIN_TRADE_NOTIONAL and closes.get(sym, 0) > 0:
                    sell_qty = min(math.ceil(excess / closes[sym]), max(0, qty_now - 1))
                    if sell_qty > 0:
                        live_px = float(pos.get('current_price') or 0) or closes[sym]
                        available += sell_qty * live_px
                        sell_orders.append((sym, sell_qty))
            elif value_now < target_value * (1 - REBALANCE_BAND_PCT / 100):
                need = target_value - value_now
                if need >= MIN_TRADE_NOTIONAL and closes.get(sym, 0) > 0:
                    buy_orders.append((sym, need))

        needs = sum(need for _, need in buy_orders)
        scale = min(1.0, available / needs) if needs > 0 else 0.0
        final_buys = []
        for sym, need in buy_orders:
            px = closes.get(sym, 0)
            if px <= 0:
                continue
            qty = int(math.floor(need * scale / px))
            if qty > 0 and qty * px <= available:
                final_buys.append((sym, qty))
                available -= qty * px

        if not dry_run:
            for sym in sorted(set(target) | set(positions)):
                executor._cancel_orders_for_symbol(sym)

        for sym, qty in sorted(sell_orders):
            pos = positions.get(sym, {})
            entry = _position_entry_price(conn, sym, pos, closes.get(sym, 0))
            reason = 'guard_stop' if decision.liquidate else (
                'market_gate_off' if not risk_on else 'signal')
            if sym not in sells and sym in target:
                reason = 'trim'
            _execute_order(sym, qty, 'sell', conn, executed_at, reason,
                           entry_price=entry, dry_run=dry_run, lines=lines)
        for sym, qty in sorted(final_buys):
            _execute_order(sym, qty, 'buy', conn, executed_at, 'entry',
                           entry_price=closes.get(sym), dry_run=dry_run, lines=lines)

        if not dry_run:
            db_module.save_guard_state(conn, MODE, guard.to_dict(), guard_week)
            _record_run(conn, sig_date, 'ok', f'{len(sell_orders)} sells, {len(final_buys)} buys')

        counts = universe['counts']
        summary = (
            f'sig={sig_date} week={universe["week"] or "none"} '
            f'universe={len(universe["symbols"])} '
            f'(RS{counts["rs"]}/MTF{counts["mtf"]}/TO{counts["takeoff"]}/'
            f'EXPL{counts["expl"]}/DS{counts["dsignal"]}) '
            f'P20w={"ON" if risk_on else "OFF"}({gate_count}/3) '
            f'book={len(target)} sells={len(sell_orders)} buys={len(final_buys)} '
            f'equity=${mark_equity:,.0f} HWM=${guard.hwm:,.0f} '
            f'pause={guard.pause_sessions}'
        )
        if decision.reason and decision.reason not in ('normal', 'already_marked'):
            summary += f' guard={decision.reason}'
        print(f'[CMO-LIVE] {summary}', flush=True)
        for line in lines:
            print(line, flush=True)
        _send_slack(summary + '\n' + '\n'.join(lines), no_slack=args.no_slack)
        return 0
    except Exception:
        tb = traceback.format_exc()
        print(tb, flush=True)
        _send_slack(f'⚠️ CRASH ```{tb[-1800:]}```', alert=True, no_slack=args.no_slack)
        try:
            if not dry_run:
                _record_run(conn, sig_date or date.today(), 'error', tb)
        except Exception:
            pass
        return 1
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description='Daily CMO bounce40 stock executor')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--no-slack', action='store_true')
    p.add_argument('--handover', action='store_true',
                   help='liquidate the existing MTF-stock book and seed fresh state')
    p.add_argument('--assume-flat', action='store_true',
                   help='dry-run only: ignore current stock positions')
    p.add_argument('--sig-date', help='override settled signal date (YYYY-MM-DD)')
    return _run(p.parse_args())


if __name__ == '__main__':
    sys.exit(main())
