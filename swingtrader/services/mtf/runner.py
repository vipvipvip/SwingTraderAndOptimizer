#!/usr/bin/env python3
"""MTF Top-N Daily Runner — Phase 1 (Paper Trading).

Daily one-shot: scores all S&P 500 stocks using Multi-TF criteria,
picks top 10, logs picks + paper portfolio to CSV, sends Slack alert.

MTCS (Hilbert sine/lead) continues running alongside during Phase 1.
"""

import json
import os
import csv
import sys
import numpy as np
import requests
from datetime import datetime, date as dt_date
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import db as db_module

NY = ZoneInfo('America/New_York')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PICKS_CSV = os.path.join(BASE_DIR, 'data', 'mtf_picks.csv')
PORTFOLIO_CSV = os.path.join(BASE_DIR, 'data', 'mtf_portfolio.csv')
STATE_FILE = os.path.join(BASE_DIR, '.mtf_state.json')


def _send_slack(msg):
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={'text': f'[MTF-TopN] {msg}'}, timeout=10)
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
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)


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

    if any(np.isnan(x) for x in (wc, we, ws, dc, de, ds, hc, ha)):
        return None
    if we <= ws or de <= ds:
        return None
    if hc <= ha or hc <= 0:
        return None

    gap_w = (wc - ws) / ws * 100
    atr_dist = (hc - ha) / hc * 100 if ha > 0 else 0

    days_since = 999
    for j in range(wi, 0, -1):
        wj_ema = weekly['ema'][j]
        wj_sma = weekly['sma'][j]
        wj_ema_prev = weekly['ema'][j - 1]
        wj_sma_prev = weekly['sma'][j - 1]
        if (not np.isnan(wj_ema) and not np.isnan(wj_sma)
                and not np.isnan(wj_ema_prev) and not np.isnan(wj_sma_prev)):
            if wj_ema > wj_sma and wj_ema_prev <= wj_sma_prev:
                days_since = (sig_date - weekly['dates'][j]).days
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


def run():
    now = datetime.now(NY)
    today = now.date()

    db_module.get_conn()
    conn = db_module.get_conn()
    try:
        tickers = db_module.get_all_tickers(conn)
        print(f'[MTF] Loaded {len(tickers)} tickers')

        # Load all three timeframes for all tickers
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
        print(f'[MTF] Tickers with all 3 timeframes: {len(weekly_data)}')

        # Build date index maps + sorted date lists for nearest-date lookups
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
            """Find index of nearest date <= target in sorted list."""
            if target in date_map:
                return date_map[target]
            for d in reversed(dates):
                if d <= target:
                    return date_map.get(d)
            return None

        # Latest bar date
        latest_date = db_module.get_latest_daily_bar_date(conn)
        if latest_date is None:
            print('[MTF] No daily data found')
            return

        sig_date = latest_date
        print(f'[MTF] Signal date: {sig_date}')

        # Compute scores
        candidates = []
        for tid in weekly_data:
            di = _nearest_date_idx(daily_idx[tid], daily_dates_sorted[tid], sig_date)
            wi = _nearest_date_idx(weekly_idx[tid], weekly_dates_sorted[tid], sig_date)
            hi = _nearest_date_idx(hourly_idx[tid], hourly_dates_sorted[tid], sig_date)
            if di is None or wi is None or hi is None:
                continue

            result = _compute_score(weekly_data[tid], daily_data[tid], hourly_data[tid],
                                    wi, di, hi, sig_date)
            if result is None:
                continue

            result['tid'] = tid
            result['symbol'] = ticker_names[tid]
            candidates.append(result)

        if not candidates:
            print('[MTF] No qualifying tickers')
            _send_slack(f'No qualifying tickers on {sig_date}')
            return

        # Sort by score DESC
        candidates.sort(key=lambda x: -x['score'])
        top_n = candidates[:config.TOP_N]

        # Build score details for state
        score_detail = {}
        for t in candidates:
            score_detail[t['symbol']] = {
                'score': t['score'],
                'gap_w': t['gap_w'],
                'atr_dist': t['atr_dist'],
                'freshness': t['freshness'],
                'close': t['close'],
            }
        top_symbols = [t['symbol'] for t in top_n]

        # Load previous state
        state = _load_state()
        prev_picks = state.get('last_picks', [])
        prev_scores = state.get('last_scores', {})
        prev_date = state.get('last_date')

        # Portfolio tracking
        portfolio = state.get('portfolio', {
            'cash': config.INITIAL_CAPITAL,
            'positions': {},
            'last_value': config.INITIAL_CAPITAL,
            'inception': str(today),
        })
        positions = portfolio['positions']
        cash = portfolio['cash']

        # Simulate rebalance: sell dropped, buy new entrants
        dropped = [s for s in prev_picks if s not in top_symbols]
        new_entries = [s for s in top_symbols if s not in prev_picks]
        buys = []
        sells = []
        trade_log_entries = []

        # Sell dropped positions
        for sym in dropped:
            if sym in positions:
                pos = positions[sym]
                entry_price = pos['entry_price']
                shares = pos['shares']
                close_price = prev_scores.get(sym, {}).get('close') or pos['entry_price']
                proceeds = shares * close_price * (1 - config.COST_PER_TRADE)
                ret = (close_price - entry_price) / entry_price - config.COST_PER_TRADE
                cash += proceeds
                sells.append(f'{sym} {ret*100:+.1f}%')
                trade_log_entries.append((str(sig_date), sym, 'SELL', f'{shares:.4f}',
                                          f'{close_price:.2f}', f'{ret*100:+.2f}%'))
                del positions[sym]

        # Buy new entries
        if new_entries:
            per_stock = (cash / len(new_entries)) if cash > 0 else 0
            for sym in new_entries:
                sd = score_detail.get(sym, {})
                bp = sd.get('close', 0)
                if bp <= 0:
                    continue
                shares = (per_stock / bp) * (1 - config.COST_PER_TRADE)
                cost = shares * bp
                cash -= cost
                positions[sym] = {'shares': round(shares, 4), 'entry_price': bp}
                buys.append(f'{sym} @ ${bp:.2f}')
                trade_log_entries.append((str(sig_date), sym, 'BUY', f'{shares:.4f}',
                                          f'{bp:.2f}', ''))

        # MTM positions
        mtm_value = cash
        for sym, pos in list(positions.items()):
            sd = score_detail.get(sym)
            if sd:
                close = sd['close']
                mtm_value += pos['shares'] * close * (1 - config.COST_PER_TRADE)

        total_ret = (mtm_value - config.INITIAL_CAPITAL) / config.INITIAL_CAPITAL * 100

        # Update portfolio state
        portfolio['cash'] = cash
        portfolio['last_value'] = round(mtm_value, 2)
        state['last_date'] = str(sig_date)
        state['last_picks'] = top_symbols
        state['last_scores'] = score_detail
        state['portfolio'] = portfolio
        _save_state(state)

        # Log picks to CSV
        _ensure_csv()
        picks_header = not os.path.exists(PICKS_CSV)
        with open(PICKS_CSV, 'a', newline='') as f:
            w = csv.writer(f)
            if picks_header:
                w.writerow(['date', 'rank', 'symbol', 'score', 'gap_w', 'atr_dist', 'freshness', 'close'])
            for i, t in enumerate(top_n, 1):
                w.writerow([str(sig_date), i, t['symbol'], t['score'],
                            t['gap_w'], t['atr_dist'], t['freshness'], t['close']])

        # Log portfolio to CSV
        port_header = not os.path.exists(PORTFOLIO_CSV)
        with open(PORTFOLIO_CSV, 'a', newline='') as f:
            w = csv.writer(f)
            if port_header:
                w.writerow(['date', 'cash', 'mtm_value', 'return_pct',
                            'positions_count', 'buys', 'sells'])
            w.writerow([str(sig_date), f'{cash:.2f}', f'{mtm_value:.2f}',
                        f'{total_ret:+.2f}%', len(positions),
                        '|'.join(buys), '|'.join(sells)])

        # Log trades
        trades_csv = os.path.join(BASE_DIR, 'data', 'mtf_trades.csv')
        trades_header = not os.path.exists(trades_csv)
        with open(trades_csv, 'a', newline='') as f:
            w = csv.writer(f)
            if trades_header:
                w.writerow(['date', 'symbol', 'side', 'shares', 'price', 'return'])
            for entry in trade_log_entries:
                w.writerow(entry)

        # Build Slack message
        lines = [f'Multi-TF Top {config.TOP_N} \u2014 {sig_date}']
        lines.append('\u2501' * 32)

        # Market breadth
        try:
            pct = db_module.get_market_breadth(conn)
            if pct is not None:
                lines.append(f'Breadth: {_format_regime(pct)}')
                lines.append('')
        except Exception:
            pass

        # Top 10 picks
        for i, t in enumerate(top_n, 1):
            fresh_str = f'{t["freshness"]}d' if t['freshness'] < 999 else 'old'
            lines.append(
                f'{i:2d}. {t["symbol"]:6s}  {t["score"]:.1f}  '
                f'gap {t["gap_w"]:+.1f}%  atr {t["atr_dist"]:.2f}%  {fresh_str}'
            )

        # Changes from yesterday
        if prev_date and str(prev_date) != str(sig_date):
            lines.append('')
            if new_entries or dropped:
                if new_entries:
                    details = []
                    for s in new_entries:
                        sd = score_detail.get(s, {})
                        details.append(f'{s} ({sd.get("score", 0):.1f})')
                    lines.append(f'  NEW: {", ".join(details)}')
                if dropped:
                    lines.append(f'  OUT: {", ".join(dropped)}')

        # Paper portfolio
        lines.append('')
        if prev_date and str(prev_date) != str(sig_date):
            prev_val = state.get('portfolio', {}).get('last_value', config.INITIAL_CAPITAL)
            if prev_val and prev_val > 0:
                daily_ret = (mtm_value - prev_val) / prev_val * 100
                lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}% total, {daily_ret:+.2f}% today)')
            else:
                lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}%)')
        else:
            lines.append(f'Portfolio: ${mtm_value:,.0f}  ({total_ret:+.1f}%)')

        lines.append(f'Positions: {len(positions)}  Cash: ${cash:,.0f}')
        msg = '\n'.join(lines)

        print(f'\n{msg}\n')
        _send_slack(msg)

    finally:
        conn.close()


if __name__ == '__main__':
    run()
