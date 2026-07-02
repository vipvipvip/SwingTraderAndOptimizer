import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

import config
import db as db_module
from price_collector import latest_trade_price

NY = ZoneInfo('America/New_York')


def _alpaca_headers():
    return {
        'APCA-API-KEY-ID': config.ALPACA_API_KEY,
        'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY,
        'Content-Type': 'application/json',
    }


def _get_order(order_id):
    url = f'{config.ALPACA_BASE_URL}/v2/orders/{order_id}'
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        return None
    return resp.json()


def _cancel_orders_for_symbol(symbol):
    """Cancel all open orders for a symbol (stale orders from prior crashes)."""
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    params = {'symbols': symbol, 'status': 'open'}
    resp = requests.get(url, headers=_alpaca_headers(), params=params, timeout=10)
    if resp.status_code >= 400:
        return
    open_orders = resp.json()
    for order in open_orders:
        oid = order.get('id')
        if oid:
            requests.delete(f'{config.ALPACA_BASE_URL}/v2/orders/{oid}',
                            headers=_alpaca_headers(), timeout=5)
            print(f'[EXECUTOR] Cancelled stale order {oid} for {symbol}')


def _place_order(symbol, qty, side):
    url = f'{config.ALPACA_BASE_URL}/v2/orders'
    payload = {
        'symbol': symbol,
        'qty': str(qty),
        'side': side,
        'type': 'market',
        'time_in_force': 'day',
    }
    resp = requests.post(url, headers=_alpaca_headers(), json=payload, timeout=10)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca order failed ({resp.status_code}): {resp.text}')
    return resp.json()


def _wait_for_fill(order_id, max_retries=10, delay=1):
    """Poll order until filled or max_retries. Returns fill price or None."""
    for _ in range(max_retries):
        order = _get_order(order_id)
        if order is None:
            return None
        filled_qty = float(order.get('filled_qty', 0))
        if filled_qty > 0:
            return float(order.get('filled_avg_price', 0))
        time.sleep(delay)
    return None


def _get_account():
    url = f'{config.ALPACA_BASE_URL}/v2/account'
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        raise Exception(f'Alpaca account failed: {resp.text}')
    return resp.json()


_account_number = None


def _get_account_number():
    global _account_number
    if _account_number is None:
        acct = _get_account()
        _account_number = acct.get('account_number', '?')
    return _account_number


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    tag = f'[EMAC] [Paper:{_get_account_number()}]'
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'{tag} {msg}'}, timeout=5)
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _get_alpaca_positions():
    url = f'{config.ALPACA_BASE_URL}/v2/positions'
    resp = requests.get(url, headers=_alpaca_headers(), timeout=10)
    if resp.status_code >= 400:
        return {}
    return {p['symbol']: p for p in resp.json()}


def _partial_sell(conn, symbol, qty_to_sell):
    """Sell a specific number of shares, update DB. Returns proceeds."""
    pos = db_module.get_position(conn, db_module.get_ticker_id(conn, symbol))
    if not pos:
        return 0.0
    current_qty = int(float(pos[1]))
    qty_to_sell = min(qty_to_sell, current_qty)
    if qty_to_sell < 1:
        return 0.0

    _cancel_orders_for_symbol(symbol)
    order = _place_order(symbol, qty_to_sell, 'sell')
    fill_price = float(order['filled_avg_price']) if order.get('filled_avg_price') else None
    order_id = order.get('id')
    if not fill_price and order_id:
        fill_price = _wait_for_fill(order_id)
    if not fill_price:
        return 0.0

    remaining_qty = current_qty - qty_to_sell
    now = datetime.now(NY)
    if remaining_qty > 0:
        db_module.upsert_position(conn, pos[0], symbol, remaining_qty, fill_price, now)
    else:
        db_module.delete_position(conn, db_module.get_ticker_id(conn, symbol))

    entry_price = float(pos[2]) if pos[2] else 0
    pnl_pct = (fill_price - entry_price) / entry_price * 100 if entry_price else 0
    msg = (f'SELL {qty_to_sell} {symbol} @ ${fill_price:.2f}  |  '
           f'Remaining {remaining_qty} shares  |  PnL: {pnl_pct:+.2f}%')
    print(f'[EXECUTOR] {msg}')
    _send_slack(msg)
    return fill_price * qty_to_sell


def rebalance_for_buys(conn, buy_signals):
    """When new BUY signals fire, rebalance so all held tickers have equal dollar value.

    Args:
        conn: DB connection
        buy_signals: list of (symbol, ticker_id, signal_ts) for new BUY signals
    """
    if not buy_signals:
        return

    alpaca_positions = _get_alpaca_positions()
    account = _get_account()
    cash = float(account.get('cash', 0))

    buy_syms = {sym for sym, _, _ in buy_signals}
    held_syms = {s for s, p in alpaca_positions.items()
                 if float(p['qty']) > 0}
    all_syms = sorted(held_syms | buy_syms)

    values = {}
    for s in all_syms:
        if s in alpaca_positions:
            p = alpaca_positions[s]
            values[s] = float(p['qty']) * float(p['current_price'])
        else:
            values[s] = 0.0

    total = cash + sum(values.values())
    target = total / len(all_syms)
    print(f'[EXECUTOR] Rebalance: ${total:.0f} total → ${target:.0f}/ea for {all_syms}')
    _send_slack(f'Rebalance: ${total:.0f} total, ${target:.0f} target per ticker')

    # Sell excess from over-allocated tickers first
    for s in sorted(all_syms):
        if values[s] > target * 1.02:
            excess = values[s] - target
            price = float(alpaca_positions[s]['current_price']) if s in alpaca_positions else 0
            if price > 0:
                qty = int(excess / price)
                if qty > 0:
                    p = _partial_sell(conn, s, qty)
                    cash += p
                    values[s] -= p

    # Buy new signals up to target
    for sym, tid, sig_ts in buy_signals:
        current_val = values.get(sym, 0.0)
        if current_val >= target * 0.98:
            print(f'[EXECUTOR] {sym} already at ${current_val:.0f} near target ${target:.0f}')
            continue
        remaining = target - current_val
        reserve = 10 * len(all_syms)
        buy_amt = min(remaining, max(0, cash - reserve))
        if buy_amt > 0:
            spent = buy_position(conn, tid, sym, sig_ts, buy_amt)
            cash -= spent
            values[sym] += spent


def sell_position(conn, ticker_id, symbol, signal_ts):
    now = datetime.now(NY)
    pos = db_module.get_position(conn, ticker_id)
    if not pos or float(pos[1]) <= 0:
        print(f'[EXECUTOR] {symbol} no position, skipping SELL')
        return 0.0

    qty = float(pos[1])
    _cancel_orders_for_symbol(symbol)
    order = _place_order(symbol, int(qty), 'sell')
    order_id = order.get('id')
    fill_price = float(order['filled_avg_price']) if order.get('filled_avg_price') else None
    if not fill_price and order_id:
        fill_price = _wait_for_fill(order_id)
    if not fill_price:
        print(f'[EXECUTOR] {symbol} SELL order {order_id} never filled')
        return 0.0
    entry_price = float(pos[2]) if pos[2] else 0
    pnl_dollar = (fill_price - entry_price) * qty
    pnl_pct = (fill_price - entry_price) / entry_price if entry_price else 0
    proceeds = fill_price * qty

    db_module.delete_position(conn, ticker_id)
    db_module.insert_trade(conn, ticker_id, symbol, 'SELL', qty, fill_price, now,
                           signal_ts=signal_ts,
                           pnl_dollar=pnl_dollar, pnl_pct=pnl_pct,
                           close_reason='crossover')
    msg = (f'SELL {symbol} {qty} @ ${fill_price:.2f}  '
           f'PnL: ${pnl_dollar:.2f} ({pnl_pct*100:+.2f}%)')
    print(f'[EXECUTOR] {msg}')
    _send_slack(msg)
    return proceeds


def buy_position(conn, ticker_id, symbol, signal_ts, amount):
    now = datetime.now(NY)
    pos = db_module.get_position(conn, ticker_id)
    if pos and float(pos[1]) > 0:
        print(f'[EXECUTOR] {symbol} already in position, skipping BUY')
        return 0.0

    price = latest_trade_price(symbol)
    if not price:
        print(f'[EXECUTOR] {symbol} no price available, skipping BUY')
        return 0.0

    if amount < price:
        print(f'[EXECUTOR] {symbol} amount ${amount:.2f} < 1 share (${price:.2f})')
        return 0.0

    qty = int(amount * 0.95 / price)
    if qty < 1:
        print(f'[EXECUTOR] {symbol} amount ${amount:.2f} insufficient for 1 share')
        return 0.0

    _cancel_orders_for_symbol(symbol)
    try:
        order = _place_order(symbol, qty, 'buy')
    except Exception as e:
        print(f'[EXECUTOR] {symbol} order placement failed: {e}')
        return 0.0

    order_id = order.get('id')
    fill_price = float(order['filled_avg_price']) if order.get('filled_avg_price') else None
    if not fill_price and order_id:
        fill_price = _wait_for_fill(order_id)

    if not fill_price:
        fill_price = price  # fallback to pre-trade price

    spent = fill_price * qty

    db_module.upsert_position(conn, ticker_id, symbol, qty, fill_price, now)
    db_module.insert_trade(conn, ticker_id, symbol, 'BUY', qty, fill_price, now,
                           signal_ts=signal_ts)
    msg = (f'BUY {symbol} {qty} @ ${fill_price:.2f} (${spent:.2f})  |  '
           f'EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) + MACD({config.MACD_FAST},{config.MACD_SLOW},{config.MACD_SIGNAL})')
    print(f'[EXECUTOR] {msg}')
    _send_slack(msg)
    return spent
