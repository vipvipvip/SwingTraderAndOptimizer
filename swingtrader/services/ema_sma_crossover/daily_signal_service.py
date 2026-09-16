#!/usr/bin/env python3
"""Multi-timeframe daily signal scanner — runs after market close.

Emit ONLY tickers where ALL THREE EM(10)>SM(40) crossovers are done:
1. WCO done — weekly EMA10 > SMA40 (settled weekly bar)
2. DCO done — daily EMA10 > SMA40 (settled daily bar)
3. HCO done + fresh — hourly EMA10 > SMA40 with the up-cross within the last
   1-2 trading days of the SETTLED hourly series (quality-gated: degraded /
   synthetic bars, vol < MIN_HOURLY_VOL, are dropped so today's partial capture
   never drives the signal).

Sends Slack summary and logs entry signals to CSV.
"""
import json
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

MIN_HOURLY_VOL = 1000.0  # drop degraded/synthetic hourly bars (DB vol 40-700)


def _bar_date(r):
    return r['dt'].date() if hasattr(r['dt'], 'date') else r['dt']

import config
import db as db_module

NY = ZoneInfo('America/New_York')
SIGNALS_CSV = os.path.join(os.path.dirname(__file__), 'data', 'daily_signals.csv')
STATE_FILE = os.path.join(os.path.dirname(__file__), '.daily_signal_state.json')
TS_START = datetime(2023, 6, 30).date()
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCANNER_VENV_PYTHON = os.path.join(PROJECT_ROOT, 'scanner', '.venv', 'bin', 'python')
DATA_GATE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'data_readiness.py')

def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[DAILY] {msg}'}, timeout=10)
        if r.status_code != 200:
            print(f'[SLACK] Non-200: {r.status_code} {r.text[:120]}')
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


def _ensure_data_ready():
    """Gate: verify bar integrity + indicator coverage before scoring.  Returns False
    (skip run + Slack alert) if the gate cannot confirm data readiness."""
    try:
        r = subprocess.run(
            [SCANNER_VENV_PYTHON, DATA_GATE_SCRIPT, '--ensure', '--tf', 'day,hour,week',
             '--mode', 'all', '--workers', '10'],
            capture_output=True, text=True, timeout=1800)
        if r.stdout:
            print(r.stdout[-1200:])
        if r.returncode != 0:
            _send_slack('⚠️ scanner data not ready after repair — skipping Daily Signal run')
            return False
        return True
    except Exception as e:
        _send_slack(f'⚠️ data-readiness gate crashed: {e} — skipping Daily Signal run')
        return False


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

    # Data-integrity gate: verify bar completeness + indicator coverage (and
    # repair if a server was off for days) BEFORE any scoring/trading.
    if not _ensure_data_ready():
        conn.close()
        return

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
        hourly_raw = _batch_load_bars(conn, ticker_ids, 'tbl_scanner_tickers_1hour', 'date', limit=300)

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
        new_signals_logged = []

        for tid, sym in id_to_symbol.items():
            w_raw = weekly_by_tid.get(tid, [])
            d_raw = daily_by_tid.get(tid, [])
            h_raw = hourly_by_tid.get(tid, [])

            # Need SMA(40) periods of data
            if len(w_raw) < sma_period + 5 or len(d_raw) < sma_period + 5:
                continue

            w_close = np.array([r['close'] for r in w_raw])
            d_close = np.array([r['close'] for r in d_raw])

            w_ema = pd.Series(w_close).ewm(span=ema_period, adjust=False).mean().values
            w_sma = pd.Series(w_close).rolling(window=sma_period).mean().values
            d_ema = pd.Series(d_close).ewm(span=ema_period, adjust=False).mean().values
            d_sma = pd.Series(d_close).rolling(window=sma_period).mean().values

            # Last SETTLED bars only — exclude today's in-progress/partial bars
            wi = next((i for i in range(len(w_raw) - 1, -1, -1) if _bar_date(w_raw[i]) < now_date), -1)
            di = next((i for i in range(len(d_raw) - 1, -1, -1) if _bar_date(d_raw[i]) < now_date), -1)
            if wi < 0 or di < 0:
                continue

            if any(np.isnan(x) for x in (w_ema[wi], w_sma[wi], d_ema[di], d_sma[di])):
                continue

            # WCO / DCO done?
            weekly_bullish = w_ema[wi] > w_sma[wi]
            daily_bullish = d_ema[di] > d_sma[di]

            # WCO + DCO done → breadth tally (hourly only gates entry emission)
            if not (weekly_bullish and daily_bullish):
                continue
            uptrend_tickers.append(sym)

            # Hourly: quality-gated SETTLED series (drop degraded/synthetic bars + today)
            h_valid = [r for r in h_raw if (r['volume'] or 0) >= MIN_HOURLY_VOL and _bar_date(r) < now_date]
            h_close = np.array([r['close'] for r in h_valid])
            if len(h_close) < sma_period + 5:
                continue
            h_ema = pd.Series(h_close).ewm(span=ema_period, adjust=False).mean().values
            h_sma = pd.Series(h_close).rolling(window=sma_period).mean().values
            hi = len(h_close) - 1
            if any(np.isnan(x) for x in (h_ema[hi], h_sma[hi])):
                continue

            # HCO done + fresh: current hourly bull AND the up-cross within the
            # last 1-2 trading days of the settled hourly series (may be 1-2d old).
            cross_dt = None
            for j in range(hi, 0, -1):
                if np.isnan(h_sma[j]) or np.isnan(h_sma[j - 1]):
                    continue
                if h_ema[j] > h_sma[j] and h_ema[j - 1] <= h_sma[j - 1]:
                    cross_dt = _bar_date(h_valid[j])
                    break
            settled_days = sorted({_bar_date(r) for r in h_valid})
            h_fresh = (h_ema[hi] > h_sma[hi]) and cross_dt is not None and cross_dt in settled_days[-2:]

            # Emit ONLY when all three COs are done: W bull + D bull + H bull&fresh (<=2d old)
            if not h_fresh:
                continue

            # Momentum score (unchanged weights) from top predictive features
            atr_stop = float(h_valid[hi]['atr_stop']) if h_valid[hi]['atr_stop'] else 0
            atr_dist = (h_close[hi] - atr_stop) / h_close[hi] * 100 if atr_stop > 0 else 0
            gap_w_pct = (w_close[wi] - w_sma[wi]) / w_sma[wi] * 100

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

            entry_price = h_close[hi]
            entry_signals.append({
                'ticker': sym,
                'close': entry_price,
                'date': h_valid[hi]['dt'],
                'score': score,
                'gap_w': round(gap_w_pct, 1),
                'atr_dist': round(atr_dist, 1),
                'infancy': is_infancy,
                'days_weekly': days_since_weekly,
                'hco': cross_dt,
            })

            # Log to CSV + state dedup
            prev = state.get(sym, {})
            if prev.get('action') != 'ENTRY' or prev.get('date') != today_str:
                label = 'INFANCY' if is_infancy else 'MATURE'
                _log_csv(today_str, sym, 'ENTRY', entry_price,
                         f'All-3 CO (W+D bull, HCO {cross_dt}) ({label}, score={score}, gap_w={gap_w_pct:.1f}%, atr_dist={atr_dist:.1f}%, wk_cross={days_since_weekly}d)')
                state[sym] = {'action': 'ENTRY', 'date': today_str}
                new_signals_logged.append(sym)

        # ── Build Slack message ──
        total = len(ticker_ids)
        uptrend_count = len(uptrend_tickers)
        signal_count = len(entry_signals)

        pct_uptrend = uptrend_count * 100 // total
        if pct_uptrend < 35:
            regime = '⚠️ Risk-off'
        elif pct_uptrend > 54:
            regime = '✅ Risk-on'
        else:
            regime = '➖ Neutral'

        lines = [
            f'*Daily Signal* — {today_str} (all-3 COs only)',
            f'In uptrend (W+D): {uptrend_count}/{total} ({pct_uptrend}%) — {regime}',
        ]

        if entry_signals:
            infancy = [s for s in entry_signals if s['infancy']]
            mature = [s for s in entry_signals if not s['infancy']]

            def fmt_signal(s):
                return (f'{s["ticker"]} (HCO {s.get("hco")}, score={s["score"]}, '
                        f'gap_w={s["gap_w"]}%, atr={s["atr_dist"]}%, wk={s["days_weekly"]}d)')

            if infancy:
                infancy.sort(key=lambda s: s['score'], reverse=True)
                sig_lines = '\n'.join(fmt_signal(s) for s in infancy)
                lines.append(f'🚀 *Infancy entries ({len(infancy)}):*')
                lines.append(f'```' + sig_lines + '```')
                lines.append('Tickers: ' + ', '.join(s['ticker'] for s in infancy))
            if mature:
                mature.sort(key=lambda s: s['score'], reverse=True)
                sig_lines = '\n'.join(fmt_signal(s) for s in mature)
                lines.append(f'📈 *Mature entries ({len(mature)}):*')
                lines.append(f'```' + sig_lines + '```')
                lines.append('Tickers: ' + ', '.join(s['ticker'] for s in mature))
        else:
            lines.append('No tickers with all 3 crossovers (W+D bull, fresh HCO <=2d old) today')

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
