#!/usr/bin/env python3
"""MTCS (Multi-Timeframe Cycle Strategy) — live signal service.

Poll daily OHLC from shared DB every 30 minutes during market hours,
compute Hilbert Transform cycle signals, and send Slack notifications.
No trade execution — signal-only.
"""
import csv
import os
import signal as _signal
import time
import numpy as np
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import db as db_module
import spectral
from strategy import check_signal

NY = ZoneInfo('America/New_York')
running = True
TRADES_CSV = os.path.join(os.path.dirname(__file__), 'mtcs_trades.csv')


def _handle_sigterm(sig, frame):
    global running
    print('\n[MTCS RUNNER] SIGTERM received, shutting down...')
    running = False


def _is_market_hours(now_ny):
    if now_ny.weekday() >= 5:
        return False
    open_min = config.MARKET_OPEN[0] * 60 + config.MARKET_OPEN[1]
    close_min = config.MARKET_CLOSE[0] * 60 + config.MARKET_CLOSE[1]
    now_min = now_ny.hour * 60 + now_ny.minute
    return open_min <= now_min < close_min


def _sleep_until_market_open():
    now = datetime.now(NY)
    target = now.replace(
        hour=config.MARKET_OPEN[0], minute=config.MARKET_OPEN[1],
        second=0, microsecond=0,
    )
    if target < now:
        target = target + timedelta(days=1)
        while target.weekday() >= 5:
            target += timedelta(days=1)
    sec = max(0, (target - now).total_seconds())
    print(f'[MTCS RUNNER] Market closed. Sleeping {sec/3600:.1f}h until {target}')
    time.sleep(sec)


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[MTCS] {msg}'}, timeout=5)
    except Exception as e:
        print(f'[MTCS SLACK] Error: {e}')


def _append_trade_csv(symbol, entry_date, entry_price, exit_date, exit_price, pnl_pct):
    fresh = not os.path.exists(TRADES_CSV)
    with open(TRADES_CSV, 'a', newline='') as f:
        w = csv.writer(f)
        if fresh:
            w.writerow(['symbol', 'entry_date', 'entry_price', 'exit_date', 'exit_price', 'pnl_pct'])
        w.writerow([symbol, entry_date, round(entry_price, 2), exit_date, round(exit_price, 2), round(pnl_pct, 2)])


_ALPACA_HEADERS = {
    'APCA-API-KEY-ID': config.ALPACA_API_KEY,
    'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY,
}


def _latest_price(symbol):
    url = f'https://data.alpaca.markets/v2/stocks/trades/latest'
    try:
        resp = requests.get(url, headers=_ALPACA_HEADERS,
                            params={'symbols': symbol, 'feed': 'iex'}, timeout=5)
        if resp.status_code < 400:
            trade = resp.json().get('trades', {}).get(symbol)
            if trade and 'p' in trade:
                return float(trade['p'])
    except Exception:
        pass
    return None


def get_current_cycle_info(conn, ticker_id):
    closes, _ = db_module.get_daily_candles(conn, ticker_id)
    if not closes or len(closes) < 30:
        return '--'
    dc = spectral.dominant_cycle(np.array(closes))
    fft = dc.get('fft_cycles', [])
    cycle_str = ', '.join(f"{c['period']}d" for c in fft[:2]) if fft else '--'
    return cycle_str


def run():
    _signal.signal(_signal.SIGTERM, _handle_sigterm)
    _signal.signal(_signal.SIGINT, _handle_sigterm)

    db_module.init_db()
    conn = db_module.get_conn()

    try:
        ticker_ids = {}
        for sym in config.TICKERS:
            tid = db_module.ensure_ticker(conn, sym)
            ticker_ids[sym] = tid
            print(f'[MTCS RUNNER] {sym} → ticker_id={tid}')

        # Track which daily bar we've last processed per ticker
        last_bar_dates = {}
        for sym, tid in ticker_ids.items():
            ts = db_module.get_latest_candle_ts(conn, tid)
            last_bar_dates[tid] = ts

        while running:
            now_ny = datetime.now(NY)

            if not _is_market_hours(now_ny):
                conn.close()
                _sleep_until_market_open()
                conn = db_module.get_conn()
                print(f'[MTCS RUNNER] Market open, resuming...')
                continue

            cycle_start = time.time()
            cycle_count = getattr(run, 'cycle_count', 0) + 1
            run.cycle_count = cycle_count

            new_signals = []
            for sym in config.TICKERS:
                tid = ticker_ids[sym]
                latest_ts = db_module.get_latest_candle_ts(conn, tid)

                # Check if new daily bar appeared
                if latest_ts == last_bar_dates.get(tid):
                    continue
                last_bar_dates[tid] = latest_ts

                signal, _ = check_signal(conn, tid)
                if signal is None:
                    continue

                daily_closes, _ = db_module.get_daily_candles(conn, tid)
                last_close = daily_closes[-1] if daily_closes else None
                live = _latest_price(sym)
                price = live if live else last_close
                price_source = 'live' if live else ('close' if last_close else 'none')

                now = datetime.now(NY)
                pos = db_module.get_position(conn, tid)
                in_position = pos is not None and float(pos[1]) > 0

                if signal == 'BUY' and not in_position:
                    db_module.upsert_position(conn, tid, sym, 1, price, now)
                    db_module.insert_trade(conn, tid, sym, 'BUY', price, latest_ts, now)
                    cycle_info = get_current_cycle_info(conn, tid)
                    msg = (f'BUY {sym} @ ${price:.2f} ({price_source})  |  '
                           f'cycles: {cycle_info}  |  '
                           f'D({config.DETREND_PERIOD}) S({config.SMOOTHING})')
                    print(f'[MTCS RUNNER] {msg}')
                    _send_slack(msg)
                    new_signals.append((sym, 'BUY', price))

                elif signal == 'SELL' and in_position:
                    entry_price = float(pos[2]) if pos[2] else 0
                    entry_date = str(pos[3].date()) if pos[3] else '?'
                    pnl_pct = (price - entry_price) / entry_price * 100 if entry_price else 0
                    _append_trade_csv(sym, entry_date, entry_price,
                                      str(latest_ts.date()), price, pnl_pct)
                    db_module.delete_position(conn, tid)
                    db_module.insert_trade(conn, tid, sym, 'SELL', price, latest_ts, now)
                    msg = (f'SELL {sym} @ ${price:.2f} ({price_source})  |  '
                           f'PnL: {pnl_pct:+.2f}%  |  '
                           f'D({config.DETREND_PERIOD}) S({config.SMOOTHING})')
                    print(f'[MTCS RUNNER] {msg}')
                    _send_slack(msg)
                    new_signals.append((sym, 'SELL', price))

            if not new_signals and cycle_count % 5 == 1:
                print(f'[MTCS RUNNER] heartbeat — cycle #{cycle_count}, no new bars/signals')

            elapsed = time.time() - cycle_start
            sleep_sec = max(5, config.POLL_INTERVAL_SEC - int(elapsed))
            if running:
                time.sleep(sleep_sec)

    finally:
        conn.close()
    print('[MTCS RUNNER] Shutdown complete')


if __name__ == '__main__':
    run()
