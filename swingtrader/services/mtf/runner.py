#!/usr/bin/env python3
"""MTF Top-N Daily Runner — Phase 2 (Live Trading).

Daily one-shot: scores all stocks using Multi-TF criteria,
picks top N, executes live Alpaca rotation, sends Slack alert.
"""

import os
import csv
import sys
import time
import subprocess

from format_etf import etf_table_lines
import argparse
import traceback
import requests
from datetime import datetime, time as dt_time, date as dt_date, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import db as db_module
import executor

NY = ZoneInfo('America/New_York')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
SCANNER_VENV_PYTHON = os.path.join(PROJECT_ROOT, 'scanner', '.venv', 'bin', 'python')
POPULATE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'populate_tickers.py')
COMPUTE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'compute_indicators.py')
DATA_GATE_SCRIPT = os.path.join(PROJECT_ROOT, 'scanner', 'services', 'scripts', 'data_readiness.py')
DATA_RETRIES = 3
DATA_RETRY_DELAY = 60
# Proceed with scoring if only a few tickers lack the latest daily bar
# (e.g. a single stock whose price feed glitched). Abort only when more than
# this many are missing — a broad outage would poison the rotation.
MISSING_TOLERANCE = 5
# Decoupled score+execute: the 10:25 service runs --action score THEN
# --action execute in sequence. Execute must only trade the pending written by
# that same run — anything older (e.g. leftover from a failed prior score) is
# refused so stale picks never fill at a 10:25 market order.
FRESH_PENDING_MAX_AGE_HOURS = 6

MODE_LABEL = {'stock': 'stocks', 'etf': 'ETFs', 'all': 'stocks+ETFs'}
CSV_SUFFIX = {'stock': '_stock', 'etf': '_etf'}
# ETF leg runs the weekly EMA10>SMA40 rotation (EMASMA), not Multi-TF.
# Stock-leg --strategy emasma also uses the same weekly EMA/SMA rotation
# (validated to replace the v2 freshest-crossover strategy).
STRATEGY_TAG = {'stock': 'MTF-TopN', 'etf': 'EMA-SMA', 'all': 'MTF+EMA-SMA'}
STRATEGY_NAME = {'stock': 'Multi-TF', 'etf': 'EMA/SMA'}


def _csv_path(name, mode='stock'):
    return os.path.join(BASE_DIR, 'data', f'mtf_{name}{CSV_SUFFIX[mode]}.csv')

MAX_DB_RETRIES = 3
DB_RETRY_DELAY = 5
MAX_STALE_DAYS = 2


def _send_slack(msg, mode='stock'):
    if not config.SLACK_WEBHOOK_URL:
        return
    label = MODE_LABEL.get(mode, mode)
    tag = STRATEGY_TAG.get(mode, 'MTF-TopN')
    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[{tag} {label}] {msg}'}, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _send_slack_alert(msg, mode='stock'):
    """Send a bright red danger-banner Slack alert."""
    if not config.SLACK_WEBHOOK_URL:
        return
    label = MODE_LABEL.get(mode, mode)
    tag = STRATEGY_TAG.get(mode, 'MTF-TopN')
    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={
            'text': f'🚨🔴 *[{tag} {label}] DATA INCOMPLETE* 🔴🚨',
            'attachments': [{'color': 'danger', 'fallback': msg, 'text': msg}]
        }, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f'[SLACK] Error: {e}')


def _send_crash_alert(exc_info, mode='stock'):
    """Send a Slack alert when the runner crashes unexpectedly."""
    tb = ''.join(traceback.format_exception(*exc_info))
    msg = f'⚠️ *CRASH* — `--mode {mode}`\n```{tb[-2000:]}```'
    _send_slack(msg, mode)


def _get_db_conn():
    for attempt in range(1, MAX_DB_RETRIES + 1):
        try:
            return db_module.get_conn()
        except Exception as e:
            print(f'[DB] Connection attempt {attempt}/{MAX_DB_RETRIES} failed: {e}')
            if attempt < MAX_DB_RETRIES:
                time.sleep(DB_RETRY_DELAY)
    raise RuntimeError(f'Could not connect to database after {MAX_DB_RETRIES} attempts')


def _check_data_freshness(conn, mode='stock', fresh=False):
    """Verify daily + hourly scanner data is fresh enough to generate reliable signals.

    Resilient to server-off days: when data is stale but the machine has just
    booted (a missed-day catch-up scenario), this triggers the scanner daily
    backfill (populate + compute) and retries before giving up — so a boot
    after an outage always has a chance to trade the current day instead of
    silently skipping it (the previous behavior). `fresh` accepts a partial
    current-day daily bar (v2 intraday cap).
    """
    latest = db_module.get_latest_daily_bar_date(conn)
    if latest is None:
        _send_slack('❌ No daily bar data found in scanner tables — aborting', mode)
        return False
    age = (dt_date.today() - latest).days

    # self-heal: for a boot-day catch-up, run the daily backfill and recheck.
    if age > MAX_STALE_DAYS:
        print(f'[MTF] {mode} data stale ({latest}, {age}d old) — triggering backfill to self-heal')
        _send_slack(
            f'⚠️ {MODE_LABEL[mode]} data {age}d old (latest {latest}) — server was likely down; '
            f'running daily backfill + retry', mode)
        healed = False
        for attempt in range(1, DATA_RETRIES + 1):
            _backfill_daily(conn, mode)
            time.sleep(DATA_RETRY_DELAY)
            # READ COMMITTED: the caller's conn re-snapshots each statement, so
            # re-reading through it sees the freshly committed backfill data.
            latest = db_module.get_latest_daily_bar_date(conn)
            if latest is None:
                continue
            age = (dt_date.today() - latest).days
            if age <= MAX_STALE_DAYS:
                print(f'[MTF] {mode} data healed: latest bar now {latest} ({age}d old)')
                healed = True
                break
        if not healed:
            _send_slack(
                f'❌ Stale daily data after {DATA_RETRIES} backfill retries: latest bar {latest} '
                f'({age}d old) — skipping {MODE_LABEL[mode]} run today', mode)
            return False

    if age > 1:
        _send_slack(
            f'⚠️  Daily bar data is {age}d old (latest: {latest}) — picks may be based on stale prices',
            mode)

    # Deep data-readiness gate: verifies that bars (incl. hourly — which the
    # old `fresh` shortcut skipped entirely, and which capture_hourly cannot
    # heal across a multi-day server-off gap) AND stored indicators (atr_stop)
    # are complete on the newest bars before any scoring/trading. If not, it
    # self-heals (calendar-aware backfill + recompute) and re-verifies.
    # `fresh` is intentionally no longer consulted here: the gate already
    # tolerates a partial current-day bar via its coverage-based rules.
    return _run_readiness_gate(mode)


def _backfill_daily(conn, mode='stock'):
    """Run the scanner daily backfill (populate + compute) to self-heal stale data.
    Invested tickers are force-fetched so exit signals always have fresh prices.
    Best-effort; returns nothing. Presence callback already refreshed conn."""
    invested = ''
    try:
        invested = ','.join(sorted(db_module.get_all_positions(conn).keys()))
    except Exception:
        invested = ''
    try:
        cmd = [SCANNER_VENV_PYTHON, POPULATE_SCRIPT, '--timeframe', 'day', '--workers', '10']
        if invested:
            cmd += ['--priority', invested]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        subprocess.run(
            [SCANNER_VENV_PYTHON, COMPUTE_SCRIPT, '--timeframe', 'day', '--workers', '10'],
            check=True, capture_output=True, timeout=300)
        print(f'[MTF] {mode} daily backfill complete')
    except subprocess.CalledProcessError as e:
        print(f'[MTF] Backfill script failed: {e}')
    except subprocess.TimeoutExpired:
        print(f'[MTF] Backfill script timed out')


def _run_readiness_gate(mode='stock'):
    """Invoke the scanner Data Readiness Gate (data_readiness.py) for the mode.

    Gate = verify -> repair (calendar-aware backfill of missing bars incl. the
    hourly holes capture_hourly can't heal, + indicator recompute) -> re-verify.
    Subspawns the scanner venv (this process runs under the optimizer venv).
    Returns True only if ALL checked timeframes are READY (exit 0)."""
    # ETF v2 relies on weekly EMA/SMA; stock v2 on hourly ratchet + fresh hourly.
    tfs = {'stock': 'day,hour', 'etf': 'day,week'}.get(mode, 'day,hour')
    cmd = [SCANNER_VENV_PYTHON, DATA_GATE_SCRIPT, '--ensure', '--tf', tfs,
           '--mode', mode]
    print(f'[MTF] Running data-readiness gate for {mode} (tfs: {tfs})...', flush=True)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.stdout:
            print(r.stdout[-1500:])
        if r.returncode != 0:
            _send_slack(
                f'❌ Data readiness NOT met for {MODE_LABEL[mode]} (exit {r.returncode}) — '
                f'skipping run today', mode)
            print(f'[MTF] Readiness stderr: {r.stderr[-800:]}' if r.stderr else '')
            return False
        return True
    except subprocess.TimeoutExpired:
        _send_slack(f'❌ Data readiness gate timed out for {MODE_LABEL[mode]} — skipping', mode)
        return False
    except Exception as e:
        _send_slack(f'⚠️  Data readiness gate crashed for {MODE_LABEL[mode]}: {e}', mode)
        return False


def _ensure_csv():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)


def _ensure_daily_data(conn, mode, now, today, fresh=False):
    """Check all enabled tickers have complete daily data. Retry populate+compute if not.
    For evening runs (>= 15:30 ET) requires TODAY's bar; earlier runs fall back to the
    latest available daily date (e.g. yesterday mid-morning).
    Returns (success, message, conn). conn may be a new connection after retry."""
    is_etf = mode == 'etf'
    # Fix #3: derive the expected count from the live enabled universe so the
    # completeness guard never drifts from reality (config values were stale).
    expected = db_module.count_enabled_tickers(conn, is_etf=is_etf)
    EVENING_CUTOFF = dt_time(15, 30)

    # v2-fresh: score on TODAY and use partial-day bars as-is. The intraday
    # hourly sampler (swingtrader-scanner-hourly) feeds today's bars; today's
    # daily bar is partial until the 16:30 backfill, which is accepted here
    # (matches the user's chosen fresh-13:00 model). No completeness retry.
    if fresh:
        return True, f'v2-fresh: scoring on {today} (partial-day data accepted)', conn, today

    required_date = today
    if now.time() < EVENING_CUTOFF:
        # Pre-evening: pick the latest SETTLED daily date (strictly before
        # today, so today's in-progress/partial bar is never scored) with
        # near-full universe coverage (within MISSING_TOLERANCE). This keeps
        # emasma on the last genuinely complete daily close even when a few
        # tickers are missing one bar (e.g. 1432/1433) — previously the strict
        # full-count filter fell back to a stale date (09-02) for stocks while
        # the ETF leg scored today's partial bar.
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.date::date
                FROM tbl_scanner_tickers_daily d
                JOIN tbl_stock_tickers s ON d.ticker_id = s.id
                WHERE s.enabled = true AND s.is_etf = %s
                  AND d.date::date < %s::date
                GROUP BY d.date::date
                HAVING COUNT(DISTINCT d.ticker_id) >= %s
                ORDER BY d.date::date DESC
                LIMIT 1
            """, (is_etf, today, expected - MISSING_TOLERANCE))
            row = cur.fetchone()
        if row is None:
            return False, f'No complete daily data date found for {MODE_LABEL[mode]}', conn, None
        required_date = row[0]
        print(f'[MTF] Pre-evening run — latest settled date: {required_date}')

    for attempt in range(1, DATA_RETRIES + 2):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT d.ticker_id)
                FROM tbl_scanner_tickers_daily d
                JOIN tbl_stock_tickers s ON d.ticker_id = s.id
                WHERE d.date::date = %s AND s.enabled = true AND s.is_etf = %s
            """, (required_date, is_etf))
            today_count = cur.fetchone()[0]

        if today_count >= expected:
            print(f'[MTF] Data complete: {today_count}/{expected} {MODE_LABEL[mode]}')
            return True, '', conn, required_date

        missing = expected - today_count
        if missing <= MISSING_TOLERANCE:
            print(f'[MTF] Data nearly complete: {today_count}/{expected} {MODE_LABEL[mode]} '
                  f'({missing} missing, within tolerance {MISSING_TOLERANCE}) — proceeding')
            return True, f'{today_count}/{expected} {MODE_LABEL[mode]} have daily data ({missing} missing)', conn, required_date

        msg = f'[{required_date}] {today_count}/{expected} {MODE_LABEL[mode]} have daily data'
        print(f'[MTF] {msg}')

        if attempt > DATA_RETRIES:
            return False, msg, conn, required_date

        print(f'[MTF] Retry {attempt}/{DATA_RETRIES}: running populate_tickers + compute_indicators...')
        # Force-fetch invested tickers so exit signals always have fresh prices.
        _backfill_daily(conn, mode)
        conn.close()

        print(f'[MTF] Waiting {DATA_RETRY_DELAY}s before recheck...')
        time.sleep(DATA_RETRY_DELAY)
        conn = _get_db_conn()

    return False, 'unexpected error', conn, required_date


def _compute_score(weekly, daily, hourly, wi, di, hi, sig_date):
    if wi < config.WARMUP_BARS or di < 1 or hi < 1:
        return None

    wc = weekly['close'][wi]
    we = weekly['ema'][wi]
    ws = weekly['sma'][wi]
    dc = daily['close'][di]
    de = daily['ema'][di]
    ds = daily['sma'][di]
    hc = hourly['close'][hi]
    ha = hourly['atr_stop'][hi]

    # Use math.isnan (fast scalar) instead of np.isnan (slow array alloc)
    import math
    if any(math.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
        return None
    if we <= ws or de <= ds:
        return None
    if hc <= ha or hc <= 0:
        return None

    gap_w = (wc - ws) / ws * 100
    atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0

    # Find freshness: walk backward through weekly data to find last EMA/SMA crossover
    days_since = 999
    w_ema = weekly['ema']
    w_sma = weekly['sma']
    w_dates = weekly['dates']
    for j in range(wi, 0, -1):
        wj_ema = w_ema[j]
        wj_sma = w_sma[j]
        wj_ema_prev = w_ema[j - 1]
        wj_sma_prev = w_sma[j - 1]
        if not (math.isnan(wj_ema) or math.isnan(wj_sma) or math.isnan(wj_ema_prev) or math.isnan(wj_sma_prev)):
            if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                days_since = (sig_date - w_dates[j]).days
                break

    gap_pts = min(gap_w / 20, 3)
    atr_pts = min(atr_dist / 1.5, 3)
    fresh_pts = max(0, 2 - days_since / 60)
    score = round(gap_pts + atr_pts + fresh_pts, 1)

    return {
        'score': score,
        'gap_w': round(gap_w, 1),
        'atr_dist': round(atr_dist, 2),
        'freshness': days_since,
        'close': round(dc, 2),
        'name': None,
    }


def _compute_emasma_score(weekly, daily_close, wi, sig_date):
    """EMA/SMA score for ETF rotation (matches backtest --score emasma).

    Pure weekly strategy: long when weekly EMA10 > SMA40, flat otherwise.
    Rank = min(gap_w / 5, 5) where gap_w is the weekly close vs SMA40 gap.
    No daily/hourly/ATR filters.
    """
    if wi < config.WARMUP_BARS:
        return None

    wc = weekly['close'][wi]
    we = weekly['ema'][wi]
    ws = weekly['sma'][wi]

    import math
    if any(math.isnan(x) for x in (wc, we, ws)):
        return None
    if we <= ws:
        return None

    gap_w = (wc - ws) / ws * 100
    score = round(min(gap_w / 5, 5), 2)

    # Freshness: days since last weekly EMA/SMA crossover (informational)
    days_since = 999
    w_ema = weekly['ema']
    w_sma = weekly['sma']
    w_dates = weekly['dates']
    for j in range(wi, 0, -1):
        wj_ema = w_ema[j]
        wj_sma = w_sma[j]
        wj_ema_prev = w_ema[j - 1]
        wj_sma_prev = w_sma[j - 1]
        if not (math.isnan(wj_ema) or math.isnan(wj_sma) or math.isnan(wj_ema_prev) or math.isnan(wj_sma_prev)):
            if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                days_since = (sig_date - w_dates[j]).days
                break

    return {
        'score': score,
        'gap_w': round(gap_w, 1),
        'atr_dist': 0.0,
        'freshness': days_since,
        'close': round(daily_close, 2),
        'name': None,
    }


def _compute_v2_score(weekly, daily, hourly, wi, di, hi, sig_date):
    """v2 freshest-crossover score for the stock leg.

    Entry (all must hold, matching backtest_v2.py):
      weekly + daily EMA10 > SMA40 (bullish trend)
      hourly MACD +ve: macd_line > macd_signal (histogram green)
      fresh bullish hourly CO (EMA10>SMA40) within V2_FRESH_BARS bars at hi
    Rank = score = higher for fresher cross (older cross => lower score), so
    the daily top-N selects the freshest turnouts (backtest showed ranking by
    freshest CO beats the MTF score).
    """
    import math
    if wi < config.WARMUP_BARS or di < 1 or hi < 1:
        return None
    we = weekly['ema'][wi]; ws = weekly['sma'][wi]
    de = daily['ema'][di]; ds = daily['sma'][di]
    if any(math.isnan(x) for x in (we, ws, de, ds)):
        return None
    if we <= ws or de <= ds:
        return None

    e = hourly['ema10']; s = hourly['sma40']
    ml = hourly['macd_line']; ms = hourly['macd_signal']
    if hi >= len(e) or hi >= len(ml):
        return None
    if ml[hi] is None or ms[hi] is None or math.isnan(ml[hi]) or math.isnan(ms[hi]):
        return None
    if not (ml[hi] > ms[hi]):          # MACD +ve (histogram green)
        return None
    # MACD histogram momentum guard: exclude when histogram has faded below
    # V2_HIST_PEAK_FLOOR of its peak over the trailing lookback window
    # (shorter bars = decelerating drive, even while EMA/SMA CO is still +ve).
    hist_now = ml[hi] - ms[hi]
    _w0 = max(0, hi - config.V2_HIST_PEAK_LOOKBACK)
    _hist_peak = max((ml[j] - ms[j] for j in range(_w0, hi)
                      if ml[j] is not None and ms[j] is not None
                      and not math.isnan(ml[j]) and not math.isnan(ms[j])),
                     default=None)
    if _hist_peak is not None and hist_now < _hist_peak * config.V2_HIST_PEAK_FLOOR:
        return None
    if e[hi] is None or s[hi] is None or s[hi] <= 0 or math.isnan(e[hi]) or math.isnan(s[hi]):
        # no EMA/SMA yet (warmup), and CO not determinable
        return None

    # freshness: last bullish CO (EMA10 crossed above SMA40) within V2_FRESH_BARS
    cross_age = None
    for j in range(hi, max(0, hi - config.V2_FRESH_BARS) - 1, -1):
        if e[j] is None or s[j] is None:
            continue
        jp = j - 1
        if jp >= 0 and e[jp] is not None and s[jp] is not None:
            if e[j] > s[j] and e[jp] <= s[jp]:
                cross_age = hi - j
                break
        elif jp < 0:
            if e[j] > s[j]:
                cross_age = hi - j
                break
    if cross_age is None:
        return None

    wc = weekly['close'][wi]
    dc = daily['close'][di]
    gap_w = (wc - ws) / ws * 100
    # score: prefer freshest cross; also nudge by diff % above weekly SMA40
    fresh_pts = max(0.0, 10.0 - cross_age / config.V2_FRESH_BARS * 10.0)
    gap_pts = min(max(gap_w, 0) / 20, 3)
    score = round(fresh_pts + gap_pts, 2)
    return {
        'score': score,
        'gap_w': round(gap_w, 1),
        'atr_dist': round((dc - (daily['sma'][di] if not math.isnan(daily['sma'][di]) else dc)) / dc * 100, 2),
        'freshness': max(1, cross_age // 9),   # bars -> approx days
        'close': round(dc, 2),
        'name': None,
        'cross_age_bars': cross_age,
    }


def _get_ticker_name(conn, tid):
    with conn.cursor() as cur:
        cur.execute('SELECT symbol FROM tbl_stock_tickers WHERE id = %s', (tid,))
        row = cur.fetchone()
        return row[0] if row else None


def _format_regime(pct):
    if pct is None:
        return '--'
    if pct < 35:
        return f'{pct:.0f}% uptrend \u26a0\ufe0f Risk-off'
    elif pct < 55:
        return f'{pct:.0f}% uptrend \u2796 Neutral'
    else:
        return f'{pct:.0f}% uptrend \u2705 Risk-on'


def _run_single_mode(mode, now, today, strategy='mtf', fresh=False):
    """Run evening scoring for one mode. Returns (success, slack_lines, sig_date).
    Analytics only — saves pending picks for the morning executor. No Alpaca calls.
    Does NOT send Slack. Does NOT catch exceptions (caller must handle)."""
    conn = _get_db_conn()
    is_etf = mode == 'etf'
    print(f'[MTF] Mode: {MODE_LABEL[mode]}')

    # Data freshness check — self-heals via daily backfill on boot-day catch-up.
    # `fresh` accepts a partial current-day daily bar (v2 intraday cap).
    if not _check_data_freshness(conn, mode, fresh=fresh):
        db_module.log_run(conn, mode, today, 'score', 'error', 'stale data')
        conn.close()
        return False, [f'Skipped {MODE_LABEL[mode]} — stale data'], None

    # Guard: all tickers must have complete daily data before proceeding
    ok, msg, conn, guard_date = _ensure_daily_data(conn, mode, now, today, fresh=fresh)
    if not ok:
        db_module.log_run(conn, mode, today, 'score', 'error', msg)
        conn.close()
        slack_msg = f'{MODE_LABEL[mode]}: {msg}\nRetried {DATA_RETRIES}x — aborting. No picks or trades today.'
        _send_slack_alert(slack_msg, mode)
        lines = [f'Skipped {MODE_LABEL[mode]} — incomplete daily data', msg]
        print(f'[MTF] {" / ".join(lines)}')
        return False, lines, None
    guard_date = guard_date or today

    tickers = db_module.get_all_tickers(conn, is_etf=is_etf)
    print(f'[MTF] Loaded {len(tickers)} {MODE_LABEL[mode]}')

    ticker_names = {}
    company_names = {}
    for tid, sym in tickers:
        ticker_names[tid] = sym
        if is_etf:
            company_names[tid] = db_module.get_etf_name(conn, tid) or sym

    # Bulk load all data (3 queries instead of 3 × N tickers)
    enabled_tids = set(ticker_names.keys())
    print(f'[MTF] Loading weekly data...', flush=True)
    weekly_data = db_module.bulk_load_weekly(conn, enabled_tids)
    print(f'[MTF] Loading daily data...', flush=True)
    daily_data_raw = db_module.bulk_load_daily(conn, enabled_tids)
    uses_hourly = (not is_etf) and strategy in ('mtf', 'v2')
    if uses_hourly:
        print(f'[MTF] Loading hourly data...', flush=True)
        if strategy == 'v2':
            hourly_data_raw = db_module.bulk_load_hourly_full(conn, enabled_tids)
        else:
            hourly_data_raw = db_module.bulk_load_hourly(conn, enabled_tids)
    else:
        hourly_data_raw = {}

    # Filter to enabled tickers with all needed timeframes. emasma (stock or
    # ETF) is weekly-only scoring — needs weekly + daily (daily for close);
    # the stock MTF/v2 score additionally needs hourly. ETF leg always stays
    # emasma regardless of the --strategy flag.
    weekly_data = {tid: d for tid, d in weekly_data.items()
                   if tid in enabled_tids and len(d['dates']) >= config.WARMUP_BARS}
    daily_data = {}
    hourly_data = {}
    for tid in weekly_data:
        if tid in daily_data_raw and len(daily_data_raw[tid]['dates']) >= 2:
            daily_data[tid] = daily_data_raw[tid]
        if tid in hourly_data_raw and len(hourly_data_raw[tid]['dates']) >= 2:
            hourly_data[tid] = hourly_data_raw[tid]
    if uses_hourly:
        valid_tids = set(weekly_data) & set(daily_data) & set(hourly_data)
    else:
        valid_tids = set(weekly_data) & set(daily_data)
    weekly_data = {tid: weekly_data[tid] for tid in valid_tids}
    daily_data = {tid: daily_data[tid] for tid in valid_tids}
    if uses_hourly:
        hourly_data = {tid: hourly_data[tid] for tid in valid_tids}
    print(f'[MTF] Tickers with all required timeframes: {len(weekly_data)}')

    daily_idx = {}
    daily_dates_sorted = {}
    for tid in daily_data:
        dates = daily_data[tid]['dates']
        daily_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        daily_dates_sorted[tid] = dates
    weekly_idx = {}
    weekly_dates_sorted = {}
    for tid in weekly_data:
        dates = weekly_data[tid]['dates']
        weekly_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        weekly_dates_sorted[tid] = dates
    hourly_idx = {}
    hourly_dates_sorted = {}
    for tid in hourly_data:
        dates = hourly_data[tid]['dates']
        hourly_idx[tid] = {dt: i for i, dt in enumerate(dates)}
        hourly_dates_sorted[tid] = dates

    def _nearest_date_idx(date_map, dates, target):
        if target in date_map:
            return date_map[target]
        for d in reversed(dates):
            if d <= target:
                return date_map.get(d)
        return None

    latest_date = db_module.get_latest_daily_bar_date(conn)
    if latest_date is None:
        conn.close()
        return False, ['No daily data found'], None

    if fresh:
        # v2-fresh: score on TODAY's bars (intraday hourly sampled at ~13:10;
        # today's daily bar is partial until the 16:30 backfill — accepted).
        sig_date = today
    else:
        # For pre-evening runs, score on the last COMPLETE date (guard_date),
        # not the partial current-day bars.
        sig_date = guard_date if guard_date else latest_date

    print(f'[MTF] Signal date: {sig_date}')

    # Fix #2 per-ticker freshness baseline: the most recent daily date with
    # (near-)full coverage of the mode's enabled universe — i.e. the last
    # COMPLETE trading day. This is robust to the intraday partial backfill
    # (e.g. a Tue-morning run where ~950 tickers already have today's bar but
    # ~484 still sit on the prior complete day). Comparing each ticker's last
    # bar against this baseline (NOT the absolute frontier, which partial data
    # skews) isolates only genuinely stale tickers — those lagging the baseline
    # by more than one trading day (fetch failures), like HIFS (last bar Sep 2
    # while the cohort baseline is Sep 4). Such tickers had been getting scored
    # on stale prices via the nearest-date fallback and traded as NEW entries.
    baseline = db_module.get_last_complete_daily_date(conn, is_etf=is_etf)
    if baseline is None:
        conn.close()
        return False, ['No complete daily data date found'], None
    STALE_LAG_DAYS = 1  # allow a single missing trading day; flag >=2

    candidates = []
    for tid in weekly_data:
        di = _nearest_date_idx(daily_idx[tid], daily_dates_sorted[tid], sig_date)
        wi = _nearest_date_idx(weekly_idx[tid], weekly_dates_sorted[tid], sig_date)
        if di is None or wi is None:
            continue
        # Fix #2: exclude tickers whose last daily bar lags the prior complete
        # trading day by more than one day. Preserves held positions (the
        # executor keeps held-but-unscored symbols) but never enters them NEW.
        daily_bar_date = daily_data[tid]['dates'][di]
        if (baseline - daily_bar_date).days > STALE_LAG_DAYS:
            print(f'[MTF] ⚠️ {ticker_names[tid]} excluded — stale daily bar {daily_bar_date} '
                  f'(baseline {baseline})')
            continue
        if is_etf or strategy == 'emasma':
            result = _compute_emasma_score(weekly_data[tid], daily_data[tid]['close'][di], wi, sig_date)
        elif strategy == 'v2':
            hi = _nearest_date_idx(hourly_idx[tid], hourly_dates_sorted[tid], sig_date)
            if hi is None:
                continue
            result = _compute_v2_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                                       wi, di, hi, sig_date)
        else:
            hi = _nearest_date_idx(hourly_idx[tid], hourly_dates_sorted[tid], sig_date)
            if hi is None:
                continue
            result = _compute_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                                    wi, di, hi, sig_date)
        if result is None:
            continue
        result['tid'] = tid
        result['symbol'] = ticker_names[tid]
        result['name'] = company_names.get(tid)
        candidates.append(result)

    lines = []
    if not candidates:
        db_module.log_run(conn, mode, sig_date, 'score', 'error', 'no qualifying picks')
        lines.append(f'No qualifying {MODE_LABEL[mode]} on {sig_date}')
        conn.close()
        return False, lines, sig_date

    # Sort by score DESC, then by weekly gap DESC for a deterministic,
    # replicable selection when many tickers tie at the emasma score cap (5).
    candidates.sort(key=lambda x: (-x['score'], -x['gap_w']))
    top_n = candidates[:config.ETF_TOP_N if is_etf else config.TOP_N]

    score_detail = {}
    for t in candidates:
        score_detail[t['symbol']] = {
            'score': t['score'], 'gap_w': t['gap_w'],
            'atr_dist': t['atr_dist'], 'freshness': t['freshness'],
            'close': t['close'], 'name': t['name'],
        }
    top_symbols = [t['symbol'] for t in top_n]

    # Real holdings from the live Alpaca-executed portfolio (mtf_positions)
    all_positions = db_module.get_all_positions(conn)
    mode_symbols = set(ticker_names.values())
    held = {sym for sym in all_positions if sym in mode_symbols}
    entry_map = {sym: pos['entry_price'] for sym, pos in all_positions.items() if sym in mode_symbols}

    held_out = sorted(sym for sym in held if sym not in top_symbols)
    # Guard: don't flag positions with no score today as OUT — they either
    # failed the bullish filter or had missing data; the executor preserves
    # them for the same reason (avoids whipsaw on a marginal filter flip).
    data_gap_held = [sym for sym in held_out if sym not in score_detail]
    for sym in data_gap_held:
        print(f'[MTF] ⚠️ {sym} held but not scored today (failed filter or data gap) — preserving position')
    dropped = [sym for sym in held_out if sym in score_detail]
    new_entries = sorted(sym for sym in top_symbols if sym not in held)

    _ensure_csv()
    picks_csv = _csv_path('picks', mode)
    header = ['date', 'rank', 'symbol', 'score', 'gap_w', 'atr_dist', 'freshness', 'entry_date', 'close']
    rows = []
    if os.path.exists(picks_csv):
        with open(picks_csv, newline='') as f:
            reader = csv.reader(f)
            for r in reader:
                if r and r[0] == 'date':
                    continue
                if r and r[0] != str(sig_date):
                    rows.append(r)
    for i, t in enumerate(top_n, 1):
        if t['freshness'] < 999:
            entry_date = str(sig_date - timedelta(days=t['freshness']))
        else:
            entry_date = ''
        rows.append([str(sig_date), i, t['symbol'], t['score'],
                     t['gap_w'], t['atr_dist'], t['freshness'], entry_date, t['close']])
    with open(picks_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    # ── Save pending picks for morning execution ──
    # Full score_detail (ALL scored symbols, not just top-10) so the executor
    # can distinguish a real drop (has a score, out of top-10) from a no-score
    # preserve (failed filter or missing data) when selling.
    db_module.save_pending(conn, mode, top_symbols, score_detail, sig_date)

    # MTM = REAL Alpaca account equity for this mode (position values + cash).
    # If Alpaca is reachable, report exactly what the account shows so Slack
    # matches Alpaca. Fall back to DB-held qty x close only if Alpaca fails.
    mtm_value = None
    try:
        executor._set_alpaca_keys(mode)
        acct = executor._get_account()
        mtm_value = float(acct.get('equity', 0))
    except Exception:
        mtm_value = None

    if mtm_value is None:
        mtm_value = 0.0
        for sym, pos in all_positions.items():
            if sym not in held:
                continue
            sd = score_detail.get(sym)
            close = sd['close'] if sd else None
            if not close:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT close FROM tbl_scanner_tickers_daily "
                            "WHERE ticker_id=(SELECT id FROM tbl_stock_tickers WHERE symbol=%s) "
                            "ORDER BY date DESC LIMIT 1", (sym,))
                        row = cur.fetchone()
                        close = float(row[0]) if row else None
                except Exception:
                    close = None
            if close:
                mtm_value += pos['quantity'] * close

    # Build message
    label = MODE_LABEL[mode]
    strategy_name = STRATEGY_NAME.get(mode, 'Multi-TF')
    if strategy_name == 'Multi-TF' and strategy == 'emasma':
        strategy_name = 'EMA/SMA'
    lines.append(f'*{strategy_name} Top {config.ETF_TOP_N if is_etf else config.TOP_N} — {sig_date} ({label})*')
    lines.append('```')

    try:
        pct = db_module.compute_market_breadth_from_data(weekly_data, daily_data, is_etf=is_etf)
        if pct is not None:
            lines.append(f'Breadth: {_format_regime(pct)}')
            lines.append('')
    except Exception:
        pass

    display_n = sorted(top_n, key=lambda t: t['symbol'])
    if is_etf:
        entry_prices = {sym: {'price': entry_map.get(sym) or 0, 'date': ''} for sym in top_symbols}
        lines.extend(etf_table_lines(display_n, score_detail, entry_prices))
    else:
        lines.append(f'{"#":<3} {"Ticker":<8} {"Score":>5} {"Gap":>7} {"Fresh":>7}')
        lines.append(f'{"-"*3} {"-"*8} {"-"*5} {"-"*7} {"-"*7}')
        for i, t in enumerate(display_n, 1):
            days_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
            lines.append(
                f'{i:<3} {t["symbol"]:<8} {t["score"]:>5.1f} '
                f'{t["gap_w"]:>+6.1f}% {days_str:>7}'
            )

    if new_entries or dropped or data_gap_held:
        lines.append('')
        if new_entries:
            details = [f'{s} ({score_detail.get(s, {}).get("score", 0):.1f})' for s in new_entries]
            lines.append(f'NEW: {", ".join(details)}')
        if dropped:
            lines.append(f'OUT: {", ".join(dropped)}')
        if data_gap_held:
            lines.append(f'⚠️ preserved (not scored today — filter or data gap): {", ".join(data_gap_held)}')
    else:
        lines.append('')
        lines.append('No changes since last run')

    lines.append('')
    lines.append(f'MTM: ${mtm_value:,.0f}  |  Positions: {len(held)}  |  Picks: {len(top_symbols)}')

    # Comma-delimited ticker list (alpha-sorted)
    lines.append('')
    lines.append(','.join(sorted(top_symbols)))

    lines.append('```')

    db_module.log_run(conn, mode, sig_date, 'score', 'ok')
    conn.close()
    return True, lines, sig_date


def _run_execute_pending(mode, today, dry_run=False):
    """Execute pending picks saved by the inline score step (same 10:25 run).
    Returns (success, lines, sig_date)."""
    conn = _get_db_conn()
    pending = db_module.get_pending(conn, mode)
    if not pending:
        msg = f'No pending trades for {MODE_LABEL[mode]}'
        print(f'[MTF] {msg}')
        conn.close()
        return False, [msg], None

    # Freshness guard (decoupled-score failures): ONLY trade pending written by
    # this morning's inline score ExecStart. Anything older is residue of a
    # failed prior run (e.g. the 2026-09-11 leftover that got traded at 10:26
    # "by luck") and must NOT execute at a 10:25 fill. Score+execute run
    # back-to-back in the same service, so a healthy pending is minutes old.
    created_raw = pending['created_at']
    created_utc = created_raw.replace(tzinfo=None)
    age_hours = (datetime.utcnow().replace(tzinfo=None) - created_utc).total_seconds() / 3600
    if age_hours > FRESH_PENDING_MAX_AGE_HOURS:
        msg = (f'⏸ Skipping stale pending for {MODE_LABEL[mode]} '
               f'(created {created_raw:%Y-%m-%d %H:%M} UTC, sig {pending["sig_date"]}, '
               f'{age_hours:.1f}h old) — score step did not refresh today; no trades.')
        print(f'[MTF] {msg}')
        db_module.log_run(conn, mode, pending['sig_date'], 'execute', 'skipped',
                          'stale pending (score step did not refresh)')
        conn.close()
        return False, [msg], None

    top_symbols = pending['top_symbols']
    score_detail = pending['score_detail']
    sig_date = pending['sig_date']
    ts = pending['created_at']

    lines = []
    lines.append(f'*Executing {MODE_LABEL[mode]} trades (scored {ts})*')
    print(f'[MTF] Executing pending trades for {MODE_LABEL[mode]} (scored {ts})')

    try:
        if dry_run:
            # Full rotation preview (equal-weight sizing, no orders / no DB writes).
            try:
                dry_lines = executor.execute_rotation(top_symbols, score_detail, mode, dry_run=True)
            except Exception:
                # Fall back to the simple set-diff preview if the full path fails
                # (e.g. network issue) so the dry-run still reports skew.
                executor._set_alpaca_keys(mode)
                held = set(executor._get_alpaca_positions().keys())
                t = set(top_symbols)
                dry_lines = ['  ⚠️ full rotation preview failed — set-diff only:'
                             f' would buy: {", ".join(sorted(t - held)) or "none"}'
                             f' | would sell: {", ".join(sorted(held - t)) or "none"}']
                print(f'[MTF] DRY-RUN {mode}: would buy {sorted(t-held)} / sell {sorted(held-t)}')
            lines.append('🧪 DRY-RUN — no orders placed, DB untouched.')
            lines.extend(dry_lines)
        else:
            live_lines = executor.execute_rotation(top_symbols, score_detail, mode)
            if live_lines:
                lines.extend(live_lines)
            db_module.clear_pending(conn, mode, sig_date)
            db_module.log_run(conn, mode, sig_date, 'execute', 'ok')
            print(f'[MTF] Pending trades cleared for {MODE_LABEL[mode]}')
    except Exception as e:
        if not dry_run:
            db_module.log_run(conn, mode, sig_date, 'execute', 'error', str(e))
        lines.append(f'')
        lines.append(f'⚠️ Execution failed: {e}')
        import traceback
        traceback.print_exc()

    conn.close()
    return True, lines, str(today)


def _run_sector_info(conn, now, today):
    """Score sector ETFs for informational Slack only. No portfolio/state/CSV."""
    print('[MTF] Scoring sector ETFs (info only)...')

    tickers = db_module.get_sector_tickers(conn)
    if not tickers:
        return ['  No sector ETFs found']

    weekly_data = {}
    daily_data = {}
    hourly_data = {}
    ticker_names = {}
    for tid, sym in tickers:
        ticker_names[tid] = sym
        w = db_module.load_weekly(conn, tid)
        d = db_module.load_daily(conn, tid)
        h = db_module.load_hourly(conn, tid)
        if w and d and h:
            weekly_data[tid] = w
            daily_data[tid] = d
            hourly_data[tid] = h

    if not weekly_data:
        return ['  No sector ETFs with all 3 timeframes']

    daily_idx = {}
    for tid in daily_data:
        daily_idx[tid] = {dt: i for i, dt in enumerate(daily_data[tid]['dates'])}
    weekly_idx = {}
    for tid in weekly_data:
        weekly_idx[tid] = {dt: i for i, dt in enumerate(weekly_data[tid]['dates'])}
    hourly_idx = {}
    for tid in hourly_data:
        hourly_idx[tid] = {dt: i for i, dt in enumerate(hourly_data[tid]['dates'])}

    def _nearest(date_map, dates, target):
        if target in date_map:
            return date_map[target]
        for d in reversed(dates):
            if d <= target:
                return date_map.get(d)
        return None

    latest_date = db_module.get_latest_daily_bar_date(conn)
    if latest_date is None:
        return ['  No daily data']

    sig_date = latest_date
    if now.weekday() == 0 and (now.hour < 9 or (now.hour == 9 and now.minute < 30)):
        last_trading = today - timedelta(days=3)
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM tbl_scanner_tickers_daily WHERE date::date = %s LIMIT 1', (last_trading,))
            if cur.fetchone():
                sig_date = last_trading

    rows = []
    flat = []
    for tid in weekly_data:
        di = _nearest(daily_idx[tid], daily_data[tid]['dates'], sig_date)
        wi = _nearest(weekly_idx[tid], weekly_data[tid]['dates'], sig_date)
        hi = _nearest(hourly_idx[tid], hourly_data[tid]['dates'], sig_date)
        if di is None or wi is None or hi is None:
            continue
        sym = ticker_names[tid]
        # Official ranking = the audited sector strategy: weekly EMA10>SMA40
        # gap (--score emasma, top-3 rotation). Adds price/trend/ATR context.
        res = _compute_emasma_score(weekly_data[tid], daily_data[tid]['close'][di],
                                    wi, sig_date)
        if res is None:
            flat.append(sym)  # weekly bearish — not eligible
            continue
        ctx = _compute_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                             wi, di, hi, sig_date)
        rows.append({
            'symbol': sym,
            'score': res['score'],
            'gap_w': res['gap_w'],
            'freshness': res['freshness'],
            'close': res['close'],
            'atr_dist': ctx['atr_dist'] if ctx else None,
            'wk_ema': float(weekly_data[tid]['ema'][wi]),
            'wk_sma': float(weekly_data[tid]['sma'][wi]),
        })

    lines = []
    lines.append(f'*Sector ETFs — top-3 (ema-sma) — {sig_date}*')
    lines.append('```')

    if not rows and not flat:
        lines.append('  No sector ETFs with data')
        lines.append('```')
        return lines

    rows.sort(key=lambda x: -x['score'])
    top3 = rows[:3]
    rest = rows[3:]

    # Tabular header
    lines.append(f'{"#":<3} {"Ticker":<7} {"Score":>5} {"Gap":>7} {"Fresh":>7} '
                 f'{"Close":>9} {"ATR%":>6} {"WkEMA":>8} {"WkSMA":>8}')
    lines.append(f'{"-"*3} {"-"*7} {"-"*5} {"-"*7} {"-"*7} '
                 f'{"-"*9} {"-"*6} {"-"*8} {"-"*8}')

    if not rows:
        lines.append('  All sectors weekly bearish (flat)')
    else:
        for i, t in enumerate(top3, 1):
            days_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
            atr_col = (f'{t["atr_dist"]:+.1f}%' if t['atr_dist'] is not None
                       else '—')
            lines.append(
                f'{i:<3} {t["symbol"]:<7} {t["score"]:>5.1f} {t["gap_w"]:>+6.1f}% {days_str:>7} '
                f'${t["close"]:>8,.2f} {atr_col:>6} '
                f'${t["wk_ema"]:>7,.1f} ${t["wk_sma"]:>7,.1f}'
            )

        if rest:
            lines.append('')
            lines.append('Next: ' + ' | '.join(
                f'{t["symbol"]} {t["score"]:.1f}' for t in rest))

    if flat:
        lines.append('')
        lines.append(f'Flat (weekly EMA10<=SMA40): {", ".join(flat)}')

    # Comma-delimited ticker list (alpha-sorted)
    sector_symbols = sorted(t['symbol'] for t in rows) + sorted(flat)
    lines.append('')
    lines.append(','.join(sector_symbols))
    lines.append('```')

    return lines


def _run_market_regime(conn, now, today):
    """Weekly EMA10>SMA40 gate state for VTI/SPY/QQQ/VTV (info-only Slack section).
    Shows the last 4 weekly bars with BULL/bear per gate ETF plus agreement count."""
    print('[MTF] Scoring market regime (VTI/SPY/QQQ/VTV weekly)...')

    tickers = db_module.get_market_gate_tickers(conn)
    if not tickers:
        return ['  No market gate ETFs found']

    tid_by_sym = {sym: tid for tid, sym in tickers}
    sym_order = db_module.MARKET_GATE_ETFS

    weekly_data = {}
    for sym in sym_order:
        tid = tid_by_sym.get(sym)
        if tid is None:
            continue
        w = db_module.load_weekly(conn, tid)
        if w and len(w['dates']) >= 40:
            # Keep exactly one bar per ISO week: the Monday-stamped (full-week)
            # one. The yfinance fallback in populate_tickers.py can stamp the
            # in-progress week with the capture date instead of Monday (e.g.
            # QQQ recorded a bar dated 2026-09-08 for the 09-07 week after a
            # 09-08 IEX miss), which otherwise shows as a '-' row and a bogus
            # 1/4 agreement in the regime table.
            keep = [i for i, d in enumerate(w['dates']) if d.weekday() == 0]
            if len(keep) >= 40:
                weekly_data[sym] = {k: [w[k][i] for i in keep] for k in ('dates', 'close', 'ema', 'sma')}

    if not weekly_data:
        return ['  No market gate weekly data']

    # Latest weekly date available for the gate ETFs
    all_dates = sorted(set().union(*[set(w['dates']) for w in weekly_data.values()]))
    if not all_dates:
        return ['  No market gate weekly data']
    last_date = all_dates[-1]

    # Last 4 distinct weekly dates
    last4 = all_dates[-4:]

    lines = []
    lines.append(f'*Market Regime — {last_date}*')
    lines.append('```')
    hdr = f'{"Week":<12}' + ''.join(f'{sym:<7}' for sym in sym_order) + 'Agree'
    lines.append(hdr)
    lines.append('-' * len(hdr))

    def _state_at(sym, d):
        w = weekly_data.get(sym)
        if w is None:
            return '-'
        try:
            i = w['dates'].index(d)
        except ValueError:
            return '-'
        ema = w['ema'][i]
        sma = w['sma'][i]
        if ema is None or sma is None or ema != ema or sma != sma:  # NaN-safe
            return '-'
        return 'BULL' if ema > sma else 'bear'

    for d in last4:
        agree = 0
        row = f'{str(d):<12}'
        for sym in sym_order:
            st = _state_at(sym, d)
            row += f'{st:<7}'
            if st == 'BULL':
                agree += 1
        row += f'{agree}/4'
        lines.append(row)

    # Context hint, only when gates agree
    agree_now = sum(1 for sym in sym_order if _state_at(sym, last_date) == 'BULL')
    if agree_now == 4:
        lines.append('')
        lines.append('Risk-on (4/4)')
    elif agree_now == 0:
        lines.append('')
        lines.append('⚠️ Risk-off (0/4)')
    lines.append('```')

    return lines


def run(mode='stock', live=False, strategy='mtf', dry_run=False, fresh=False):
    """Run evening scoring (action='score') or morning execution (action='execute')."""
    now = datetime.now(NY)
    today = now.date()
    action = 'execute' if live else 'score'
    if action == 'score':
        try:
            success, lines, sig_date = _run_single_mode(mode, now, today, strategy=strategy, fresh=fresh)
            msg = '\n'.join(lines)
            print(f'\n{msg}\n')
            _send_slack(msg, mode)
        except Exception:
            _send_crash_alert(sys.exc_info(), mode)
            raise
    else:
        try:
            success, lines, sig_date = _run_execute_pending(mode, today, dry_run=dry_run)
            msg = '\n'.join(lines)
            print(f'\n{msg}\n')
            if success:
                _send_slack(msg, mode)
        except Exception:
            _send_crash_alert(sys.exc_info(), mode)
            raise


def _run_execute_all(today, dry_run=False):
    """Execute pending trades for all modes. Sends ONE combined Slack message."""
    all_lines = []
    sig_date = str(today)

    for mode in ('stock', 'etf'):
        all_lines.append('')
        try:
            success, lines, sd = _run_execute_pending(mode, today, dry_run=dry_run)
            all_lines.extend(lines)
            if sd:
                sig_date = sd
        except Exception as exc:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            all_lines.append(f'❌ {MODE_LABEL[mode]} execution crashed: {exc}')
            all_lines.append(f'```{tb[-1500:]}```')
            print(f'[MTF] {mode} execution crashed: {exc}')

    header = f'MTF + EMA/SMA Execution — {sig_date} (stocks + ETFs)'
    full_msg = '\n'.join([header, '\u2501' * 32] + all_lines)
    print(f'\n{full_msg}\n')
    _send_slack(full_msg, 'all')


def run_all(live=False, strategy='mtf', dry_run=False, fresh=False):
    """Evening scoring (default) or morning execution (live=True)."""
    now = datetime.now(NY)
    today = now.date()
    action = 'execute' if live else 'score'

    if action == 'execute':
        _run_execute_all(today, dry_run=dry_run)
        return

    all_lines = []
    sig_date = None

    for mode in ('stock', 'etf'):
        all_lines.append('')
        try:
            success, lines, sd = _run_single_mode(mode, now, today, strategy=strategy, fresh=fresh)
            all_lines.extend(lines)
            if sd:
                sig_date = sd
        except Exception as exc:
            tb = ''.join(traceback.format_exception(*sys.exc_info()))
            all_lines.append(f'❌ {MODE_LABEL[mode]} crashed: {exc}')
            all_lines.append(f'```{tb[-1500:]}```')
            print(f'[MTF] {mode} crashed: {exc}')

    # Sector ETFs (informational only)
    all_lines.append('')
    try:
        conn = _get_db_conn()
        sector_lines = _run_sector_info(conn, now, today)
        all_lines.extend(sector_lines)
        conn.close()
    except Exception as exc:
        all_lines.append(f'❌ sector info crashed: {exc}')
        print(f'[MTF] sector info crashed: {exc}')

    # Market regime (informational only)
    all_lines.append('')
    try:
        conn = _get_db_conn()
        regime_lines = _run_market_regime(conn, now, today)
        all_lines.extend(regime_lines)
        conn.close()
    except Exception as exc:
        all_lines.append(f'❌ market regime crashed: {exc}')
        print(f'[MTF] market regime crashed: {exc}')

    if not sig_date:
        sig_date = str(today)

    header = (f'MTF Top {config.TOP_N} + EMA/SMA Top {config.ETF_TOP_N} '
          f'— {sig_date} (stocks + ETFs + sectors + regime)')
    full_msg = '\n'.join([header, '\u2501' * 32] + all_lines)
    print(f'\n{full_msg}\n')
    _send_slack(full_msg, 'all')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MTF Top-N Daily Runner')
    parser.add_argument('--action', choices=['score', 'execute'], default='score',
                        help='score (evening analytics) or execute (morning trades)')
    parser.add_argument('--mode', choices=['stock', 'etf', 'all'], default='stock',
                        help='Ticker universe (default: stock, use "all" for stocks+ETFs)')
    parser.add_argument('--strategy', choices=['mtf', 'v2', 'emasma'], default='mtf',
                        help='stock-leg scoring: mtf (default), v2 freshest-crossover '
                             'top-N, or emasma (weekly EMA10>SMA40 rotation, same as ETF leg)')
    parser.add_argument('--dry-run', action='store_true',
                        help='execute path: report pending buys/sells without placing orders')
    parser.add_argument('--fresh', action='store_true',
                        help='score/execute path: use TODAY\'s (intraday, partial-day) bars as the '
                             'signal date instead of the last complete date; requires the '
                             'swingtrader-scanner-hourly intraday sampler to have run')
    parser.add_argument('--live', action='store_true',
                        help='Deprecated: use --action execute instead')
    args = parser.parse_args()
    live = args.live or args.action == 'execute'
    if args.mode == 'all':
        run_all(live=live, strategy=args.strategy, dry_run=args.dry_run, fresh=args.fresh)
    else:
        run(mode=args.mode, live=live, strategy=args.strategy, dry_run=args.dry_run, fresh=args.fresh)
