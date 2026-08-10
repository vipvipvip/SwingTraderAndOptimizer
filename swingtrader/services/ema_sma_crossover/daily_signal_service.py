#!/usr/bin/env python3
"""Multi-timeframe daily signal scanner — runs after market close.

Scans all S&P 500 stocks for:
1. Multi-timeframe uptrend (weekly + daily EMA(10) > SMA(40))
2. Fresh 1-hour entry signals within uptrend
3. New daily uptrend crossovers

Sends Slack summary and logs entry signals to CSV.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import config
import db as db_module

NY = ZoneInfo('America/New_York')
SIGNALS_CSV = os.path.join(os.path.dirname(__file__), 'data', 'daily_signals.csv')
STATE_FILE = os.path.join(os.path.dirname(__file__), '.daily_signal_state.json')
TS_START = datetime(2023, 6, 30).date()

def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[DAILY] {msg}'}, timeout=10)
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def _save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def _ensure_csv():
    os.makedirs(os.path.dirname(SIGNALS_CSV), exist_ok=True)
    if not os.path.exists(SIGNALS_CSV):
        with open(SIGNALS_CSV, 'w') as f:
            f.write('date,ticker,action,close_price,reason\n')


def _log_csv(date_str, ticker, action, price, reason):
    with open(SIGNALS_CSV, 'a') as f:
        f.write(f'{date_str},{ticker},{action},{price:.2f},{reason}\n')


def _batch_load_bars(conn, ticker_ids, table, date_col, limit=80):
    """Load most recent bars for all tickers in one query."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute(f"""
            SELECT ticker_id, {date_col} AS dt, close::float8 AS close,
                   volume, macd_histogram::float8, ppo_histogram::float8, atr_stop::float8
            FROM (
                SELECT ticker_id, {date_col}, close, volume,
                       macd_histogram, ppo_histogram, atr_stop,
                       ROW_NUMBER() OVER (PARTITION BY ticker_id ORDER BY {date_col} DESC) AS rn
                FROM {table}
                WHERE ticker_id = ANY(%s)
            ) sub
            WHERE rn <= %s
            ORDER BY ticker_id, {date_col} ASC
        """, (list(ticker_ids), limit))
        rows = cur.fetchall()
    finally:
        cur.close()
    return rows


def run():
    print(f'[DAILY] Multi-TF scan starting at {datetime.now(NY)}')
    db_module.init_db()
    conn = db_module.get_conn()
    state = _load_state()
    _ensure_csv()

    try:
        # Load all enabled tickers
        with conn.cursor() as cur:
            cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE enabled = true ORDER BY symbol')
            all_tickers = dict(cur.fetchall())

        ticker_ids = list(all_tickers.keys())
        id_to_symbol = all_tickers
        ema_period = config.EMA_PERIOD
        sma_period = config.SMA_PERIOD

        # Batch-load bars for all three timeframes
        print(f'  Loading data for {len(ticker_ids)} tickers...')
        weekly_raw = _batch_load_bars(conn, ticker_ids, 'tbl_scanner_tickers', 'date', limit=300)
        daily_raw = _batch_load_bars(conn, ticker_ids, 'tbl_scanner_tickers_daily', 'date', limit=300)
        hourly_raw = _batch_load_bars(conn, ticker_ids, 'tbl_scanner_tickers_1hour', 'date', limit=80)

        # Organize by ticker_id
        weekly_by_tid = {}
        for r in weekly_raw:
            weekly_by_tid.setdefault(r['ticker_id'], []).append(r)

        daily_by_tid = {}
        for r in daily_raw:
            daily_by_tid.setdefault(r['ticker_id'], []).append(r)

        hourly_by_tid = {}
        for r in hourly_raw:
            hourly_by_tid.setdefault(r['ticker_id'], []).append(r)

        now_date = datetime.now(NY).date()
        today_str = str(now_date)

        uptrend_tickers = []
        entry_signals = []
        new_daily_uptrend = []
        new_signals_logged = []

        for tid, sym in id_to_symbol.items():
            w_raw = weekly_by_tid.get(tid, [])
            d_raw = daily_by_tid.get(tid, [])
            h_raw = hourly_by_tid.get(tid, [])

            # Need SMA(40) periods of data
            if len(w_raw) < sma_period + 5 or len(d_raw) < sma_period + 5 or len(h_raw) < sma_period + 5:
                continue

            w_close = np.array([r['close'] for r in w_raw])
            d_close = np.array([r['close'] for r in d_raw])
            h_close = np.array([r['close'] for r in h_raw])

            w_ema = pd.Series(w_close).ewm(span=ema_period, adjust=False).mean().values
            w_sma = pd.Series(w_close).rolling(window=sma_period).mean().values
            d_ema = pd.Series(d_close).ewm(span=ema_period, adjust=False).mean().values
            d_sma = pd.Series(d_close).rolling(window=sma_period).mean().values
            h_ema = pd.Series(h_close).ewm(span=ema_period, adjust=False).mean().values
            h_sma = pd.Series(h_close).rolling(window=sma_period).mean().values

            # Latest values
            wi = len(w_close) - 1
            di = len(d_close) - 1
            hi = len(h_close) - 1

            if any(np.isnan(x) for x in (w_ema[wi], w_sma[wi], d_ema[di], d_sma[di], h_ema[hi], h_sma[hi])):
                continue

            weekly_bullish = w_ema[wi] > w_sma[wi]
            daily_bullish = d_ema[di] > d_sma[di]
            daily_date = d_raw[di]['dt']

            # New daily uptrend: fresh daily crossover today
            d_fresh_cross = (
                d_ema[di] > d_sma[di]
                and d_ema[di - 1] <= d_sma[di - 1]
                and str(daily_date) == today_str
            )
            if d_fresh_cross:
                new_daily_uptrend.append({
                    'ticker': sym,
                    'close': d_close[di],
                    'daily_date': daily_date,
                })

            # 1-hour fresh crossover (last completed bar)
            h_fresh_cross = (
                h_ema[hi] > h_sma[hi]
                and h_ema[hi - 1] <= h_sma[hi - 1]
            )

            if weekly_bullish and daily_bullish:
                uptrend_tickers.append(sym)

                # Computer momentum score from top predictive features
                atr_stop = float(h_raw[hi]['atr_stop']) if h_raw[hi]['atr_stop'] else 0
                atr_dist = (h_close[hi] - atr_stop) / h_close[hi] * 100 if atr_stop > 0 else 0
                gap_w_pct = (w_close[wi] - w_sma[wi]) / w_sma[wi] * 100
                gap_d_pct = (d_close[di] - d_sma[di]) / d_sma[di] * 100

                # Days since weekly cross (freshness check)
                days_since_weekly = 999
                for j in range(wi, 0, -1):
                    if w_ema[j] > w_sma[j] and w_ema[j-1] <= w_sma[j-1]:
                        days_since_weekly = (w_raw[wi]['dt'] - w_raw[j]['dt']).days if hasattr(w_raw[wi]['dt'], '__sub__') else 999
                        break

                is_infancy = days_since_weekly < 60

                score = 0
                score += min(gap_w_pct / 20, 3)       # weekly gap: 0-3 pts (cap at 60%+)
                score += min(atr_dist / 1.5, 3)        # ATR distance: 0-3 pts (cap at 4.5%+)
                freshness = max(0, 2 - days_since_weekly / 60)  # 0-2 pts, decays from 2 at day 0 to 0 at day 120
                score += freshness
                score = round(score, 1)

                if h_fresh_cross:
                    entry_price = h_close[hi]
                    entry_signals.append({
                        'ticker': sym,
                        'close': entry_price,
                        'date': h_raw[hi]['dt'],
                        'score': score,
                        'gap_w': round(gap_w_pct, 1),
                        'atr_dist': round(atr_dist, 1),
                        'infancy': is_infancy,
                        'days_weekly': days_since_weekly,
                    })

                    # Log to CSV + state dedup
                    prev = state.get(sym, {})
                    if prev.get('action') != 'ENTRY' or prev.get('date') != today_str:
                        label = 'INFANCY' if is_infancy else 'MATURE'
                        _log_csv(today_str, sym, 'ENTRY', entry_price,
                                 f'Multi-TF signal ({label}, score={score}, gap_w={gap_w_pct:.1f}%, atr_dist={atr_dist:.1f}%, wk_cross={days_since_weekly}d)')
                        state[sym] = {'action': 'ENTRY', 'date': today_str}
                        new_signals_logged.append(sym)

        # ── Build Slack message ──
        total = len(ticker_ids)
        uptrend_count = len(uptrend_tickers)
        signal_count = len(entry_signals)
        new_daily_count = len(new_daily_uptrend)

        pct_uptrend = uptrend_count * 100 // total
        if pct_uptrend < 35:
            regime = '⚠️ Risk-off'
        elif pct_uptrend > 54:
            regime = '✅ Risk-on'
        else:
            regime = '➖ Neutral'

        lines = [
            f'*Daily Signal* — {today_str}',
            f'In uptrend: {uptrend_count}/{total} ({pct_uptrend}%) — {regime}',
        ]

        if entry_signals:
            infancy = [s for s in entry_signals if s['infancy']]
            mature = [s for s in entry_signals if not s['infancy']]

            def fmt_signal(s):
                return f'{s["ticker"]} (score={s["score"]}, gap_w={s["gap_w"]}%, atr={s["atr_dist"]}%, wk={s["days_weekly"]}d)'

            if infancy:
                infancy.sort(key=lambda s: s['score'], reverse=True)
                sig_lines = '\n'.join(fmt_signal(s) for s in infancy)
                lines.append(f'🚀 *Infancy entries ({len(infancy)}):*')
                lines.append(f'```' + sig_lines + '```')
            if mature:
                mature.sort(key=lambda s: s['score'], reverse=True)
                sig_lines = '\n'.join(fmt_signal(s) for s in mature)
                lines.append(f'📈 *Mature entries ({len(mature)}):*')
                lines.append(f'```' + sig_lines + '```')
        else:
            lines.append('No fresh 1-hour entry signals today')

        if new_daily_uptrend:
            daily_tickers = ', '.join(s['ticker'] for s in new_daily_uptrend)
            lines.append(f'📈 *New daily uptrend ({new_daily_count}):* {daily_tickers}')

        slack_msg = '\n'.join(lines)
        print(f'\n[DAILY] Result:\n{slack_msg}\n')
        _send_slack(slack_msg)

        print(f'[DAILY] New entry signals logged: {len(new_signals_logged)}')
        print(f'[DAILY] Multi-TF scan complete')

    finally:
        _save_state(state)
        conn.close()


if __name__ == '__main__':
    run()
