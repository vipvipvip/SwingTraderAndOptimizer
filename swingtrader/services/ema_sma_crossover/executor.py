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


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={'text': msg}, timeout=5)
    except Exception as e:
        print(f'[SLACK] Error: {e}')


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
    msg = (f'EMAC SELL {symbol} {qty} @ ${fill_price:.2f}  '
           f'PnL: ${pnl_dollar:.2f} ({pnl_pct*100:+.2f}%)')
    print(f'[EXECUTOR] {msg}')
    _send_slack(f'[EMAC] {msg}')
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
    msg = (f'EMAC BUY {symbol} {qty} @ ${fill_price:.2f} (${spent:.2f})  |  '
           f'EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) + MACD({config.MACD_FAST},{config.MACD_SLOW},{config.MACD_SIGNAL})')
    print(f'[EXECUTOR] {msg}')
    _send_slack(f'[EMAC] {msg}')
    return spent
