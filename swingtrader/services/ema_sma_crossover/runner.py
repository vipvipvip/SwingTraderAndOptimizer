#!/usr/bin/env python3
"""EMA(10)/SMA(40) + MACD(10,40,400) 30-min crossover — live trading runner.

Every 2 minutes during market hours, fetches raw trade ticks from Alpaca,
builds 30-min OHLCV bars, runs signal detection and executes trades.

Portfolio logic: sell first to free cash, then split remaining cash
equally among tickers with buy signals.
"""
import json
import math
import os
import signal
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import db as db_module
from candle_builder import CandleBuilder, BAR_MINUTES
from executor import sell_position, buy_position, _get_account, _cancel_orders_for_symbol, rebalance_for_buys
from price_collector import fetch_trades, is_trading_day, next_trading_dates
from strategy import check_signal, WARMUP

NY = ZoneInfo('America/New_York')
running = True
trades_dir = os.path.join(os.path.dirname(__file__), '.tracked_trades')
_trading_day_cache = [None]  # mutable cache for current run() call


def _handle_sigterm(sig, frame):
    global running
    print('\n[RUNNER] SIGTERM received, shutting down...')
    running = False


def _is_regular_hours_ts(dt):
    """Check if a datetime falls within regular trading hours (9:30 AM - 4:00 PM ET)."""
    et = dt.astimezone(NY)
    minutes = et.hour * 60 + et.minute
    open_min = config.MARKET_OPEN[0] * 60 + config.MARKET_OPEN[1]
    close_min = config.MARKET_CLOSE[0] * 60 + config.MARKET_CLOSE[1]
    return open_min <= minutes < close_min


def _is_market_hours(now_ny):
    if now_ny.weekday() >= 5:
        return False
    open_min = config.MARKET_OPEN[0] * 60 + config.MARKET_OPEN[1]
    close_min = config.MARKET_CLOSE[0] * 60 + config.MARKET_CLOSE[1]
    now_min = now_ny.hour * 60 + now_ny.minute
    return open_min <= now_min < close_min


def _seconds_until(target):
    return max(0, (target - datetime.now(NY)).total_seconds())


def _sleep_until_market_open():
    now = datetime.now(NY)
    target = now.replace(
        hour=config.MARKET_OPEN[0], minute=config.MARKET_OPEN[1] - 5,
        second=0, microsecond=0,
    )
    if target < now:
        market_open_today = now.replace(
            hour=config.MARKET_OPEN[0], minute=config.MARKET_OPEN[1],
            second=0, microsecond=0,
        )
        if now < market_open_today:
            target = market_open_today
        else:
            ntd = next_trading_dates(now + timedelta(days=1), count=1)
            if ntd:
                target = ntd[0]
                target = datetime(target.year, target.month, target.day,
                                  config.MARKET_OPEN[0], config.MARKET_OPEN[1] - 5,
                                  tzinfo=NY)
    sec = _seconds_until(target)
    print(f'[RUNNER] Market closed. Sleeping {sec/3600:.1f}h until {target}')
    time.sleep(sec)


def _sync_alpaca_positions(conn, ticker_ids):
    """Reconcile EMAC DB positions with actual Alpaca positions (e.g. after crash)."""
    import requests as http_req
    url = f'{config.ALPACA_BASE_URL}/v2/positions'
    headers = {
        'APCA-API-KEY-ID': config.ALPACA_API_KEY,
        'APCA-API-SECRET-KEY': config.ALPACA_SECRET_KEY,
    }
    try:
        resp = http_req.get(url, headers=headers, timeout=10)
        if resp.status_code >= 400:
            return
        alpaca_positions = {p['symbol']: p for p in resp.json()}
    except Exception:
        alpaca_positions = {}

    for sym, tid in ticker_ids.items():
        db_pos = db_module.get_position(conn, tid)
        alp_pos = alpaca_positions.get(sym)

        if alp_pos and (not db_pos or float(db_pos[1]) <= 0):
            qty = float(alp_pos['qty'])
            price = float(alp_pos['avg_entry_price'])
            print(f'[RUNNER] Syncing {sym} position: {qty} @ ${price:.2f} (Alpaca → DB)')
            db_module.upsert_position(conn, tid, sym, abs(qty), price,
                                      datetime.now(NY))


def run():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    db_module.init_db()
    conn = db_module.get_conn()
    builder = CandleBuilder(conn)

    try:
        ticker_ids = {}
        for sym in config.TICKERS:
            tid = db_module.ensure_ticker(conn, sym)
            ticker_ids[sym] = tid
            # Seed last_ts from persisted raw trades
            last = db_module.get_last_raw_trade_ts(conn, tid)
            if last:
                builder._last_ts[tid] = last.strftime('%Y-%m-%dT%H:%M:%SZ')
                print(f'[RUNNER] {sym} → ticker_id={tid}, last_raw_trade={last}')
            else:
                    print(f'[RUNNER] {sym} → ticker_id={tid}, no raw trades yet')

        _sync_alpaca_positions(conn, ticker_ids)

        while running:
            now_ny = datetime.now(NY)
            now_utc = datetime.now(ZoneInfo('UTC'))

            if not _is_market_hours(now_ny):
                conn.close()
                builder.save()
                _trading_day_cache[0] = None  # new day when we wake
                _sleep_until_market_open()
                conn = db_module.get_conn()
                builder.conn = conn
                print(f'[RUNNER] Market open, resuming...')
                continue

            if _trading_day_cache[0] is None:
                _trading_day_cache[0] = is_trading_day(now_ny)
            if not _trading_day_cache[0]:
                print(f'[RUNNER] {now_ny.date()} is not a trading day (holiday)')
                conn.close()
                builder.save()
                _trading_day_cache[0] = None
                _sleep_until_market_open()
                conn = db_module.get_conn()
                builder.conn = conn
                print(f'[RUNNER] Market open, resuming...')
                continue

            cycle_start = time.time()
            cycle_count = getattr(run, 'cycle_count', 0) + 1
            run.cycle_count = cycle_count

            # Periodically cancel stale open orders from prior crashes
            if cycle_count % 15 == 1:
                for sym in config.TICKERS:
                    _cancel_orders_for_symbol(sym)

            # ── Step 1: fetch trades, build 30-min bars ──
            for sym in config.TICKERS:
                tid = ticker_ids[sym]
                since = builder.get_last_ts(tid)
                trades = fetch_trades(sym, since=since)
                if trades:
                    print(f'[RUNNER] {sym} → {len(trades)} new trade ticks')
                    db_module.insert_raw_trades(conn, tid, trades)
                    builder.feed(tid, trades)

                # Always flush completed bars, even with no new trades
                completed = builder.pop_completed(tid, now_utc)
                for tid_f, bts, o, h, l, c, v in completed:
                    if not _is_regular_hours_ts(bts):
                        et_str = bts.astimezone(NY).strftime('%H:%M %Z')
                        print(f'[RUNNER] {sym} skipped bar {bts} ({et_str}) — outside regular hours')
                        continue
                    naive_ts = bts.replace(tzinfo=None)
                    db_module.insert_candle(conn, tid_f, naive_ts, o, h, l, c, v)
                    print(f'[RUNNER] {sym} 30-min bar built: {naive_ts} O={o} H={h} L={l} C={c} V={v}')

            builder.save()

            # ── Step 2: run signals on completed bars ──
            signals = []
            for sym in config.TICKERS:
                tid = ticker_ids[sym]
                count = db_module.candle_count(conn, tid)
                if count < WARMUP:
                    print(f'[RUNNER] {sym} warming up: {count}/{WARMUP} candles')
                    continue
                sig = check_signal(conn, tid)
                if sig:
                    cur = conn.cursor()
                    cur.execute(
                        'SELECT ts FROM emac_candles WHERE ticker_id = %s ORDER BY ts DESC LIMIT 1',
                        (tid,))
                    row = cur.fetchone()
                    sig_ts = row[0] if row else datetime.now(ZoneInfo('UTC'))

                    # Dedup: skip if we already processed this candle for this ticker
                    seen_key = (tid, sig_ts)
                    processed = getattr(run, '_processed_signals', set())
                    if seen_key in processed:
                        continue
                    processed.add(seen_key)
                    run._processed_signals = processed

                    signals.append((sym, tid, sig, sig_ts))

            # ── Step 3: sell first ──
            for sym, tid, sig, sig_ts in signals:
                if sig == 'SELL':
                    print(f'[RUNNER] {sym} SELL signal — selling first')
                    try:
                        sell_position(conn, tid, sym, sig_ts)
                    except Exception as e:
                        print(f'[RUNNER] {sym} SELL failed: {e}')

            # ── Step 4: rebalance portfolio for new buys ──
            buy_signals = [(sym, tid, sig_ts) for sym, tid, sig, sig_ts in signals if sig == 'BUY']
            if buy_signals:
                try:
                    rebalance_for_buys(conn, buy_signals)
                except Exception as e:
                    print(f'[RUNNER] rebalance failed: {e}')

            if not signals and cycle_count % 5 == 1:
                print(f'[RUNNER] heartbeat — cycle #{cycle_count}, no signals')

            elapsed = time.time() - cycle_start
            sleep_sec = max(5, config.POLL_INTERVAL_SEC - int(elapsed))
            if running:
                time.sleep(sleep_sec)

    finally:
        builder.save()
        conn.close()
    print('[RUNNER] Shutdown complete')


if __name__ == '__main__':
    run()
