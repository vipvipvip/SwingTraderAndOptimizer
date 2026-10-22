#!/usr/bin/env python3
"""
Earnings Screener CLI
---------------------
Finds stocks with upcoming earnings where DAILY MACD just turned positive.
The pattern: daily MACD turns bullish BEFORE earnings -> potential earnings pop.

MACD is computed inline from settled daily closes (the stored MACD columns were
dropped 2026-09-26 as lookahead-biased legacy artifacts).

Usage:
    python earnings_screener.py --refresh          # Cache next 4 weeks of earnings dates
    python earnings_screener.py                    # Run screener (default: 14 days)
    python earnings_screener.py --days 7           # Look 7 days ahead
    python earnings_screener.py --min-freshness 3  # Only signals whose daily cross is <= 3 bars old
"""

import argparse
import json
import sys
import os
import requests
from datetime import datetime, timedelta
from typing import Optional

import psycopg2
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

# Load env from MTF config (has SLACK_WEBHOOK_URL)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', 'swingtrader', 'services', 'mtf', '.env'))

# Add parent dir for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_CONFIG
from fundamentals_research import (
    FundamentalsResearch, format_label, format_detail, format_rating, format_table,
    slack_table_block as fundamentals_slack_table,
)
from table_fmt import numeric_cells, render_table, slack_table_block

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

# State file tracks the last result set sent to Slack so repeated identical
# lists (every 30-min timer run) don't spam the channel. Only a changed set
# (new ticker in/out, or a fresh crossover) triggers a new message.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.earnings_screener_state.json')


def _state_signature(results):
    """Stable fingerprint of a result set: sorted (ticker, freshness, fund score)
    triples. Returned as JSON-native values so a JSON round-trip preserves it."""
    return sorted(
        [r['ticker'], r['freshness'], bool(r['just_turned_positive']),
         (r.get('fundamentals') or {}).get('score')]
        for r in results
    )


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get('signature')
    except (OSError, ValueError):
        return None


def _save_state(signature):
    with open(STATE_FILE, 'w') as f:
        json.dump({'signature': signature, 'updated_at': datetime.now().isoformat()}, f)


# ── DB Helpers ──────────────────────────────────────────────────────────────

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)


def _send_slack(msg, blocks=None):
    """Send message to Slack.

    `blocks` renders a native Block Kit layout (real aligned grids). If Slack
    rejects the block payload — older workspace, unsupported block type — the
    plain-text version is posted instead so the report is never lost.
    """
    if not SLACK_WEBHOOK_URL:
        print("[SLACK] No webhook URL configured")
        return
    payload = {'text': msg}
    if blocks:
        payload['blocks'] = blocks
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        print("[SLACK] Message sent")
    except Exception as e:
        if blocks:
            print(f"[SLACK] Block payload rejected ({e}); retrying as plain text")
            try:
                r = requests.post(SLACK_WEBHOOK_URL, json={'text': msg}, timeout=10)
                r.raise_for_status()
                print("[SLACK] Message sent (plain text)")
                return
            except Exception as e2:
                print(f"[SLACK] Error: {e2}")
                return
        print(f"[SLACK] Error: {e}")


_RESULTS_COLUMNS = (
    ('Ticker', 'l', 8),
    ('Earnings', 'r', 10),
    ('Days', 'r', 5),
    ('MACD', 'r', 8),
    ('Signal', 'r', 8),
    ('Hist', 'r', 8),
    ('Close', 'r', 8),
    ('Fresh', 'r', 6),
    ('Fund', 'r', 6),
    ('Rate', 'r', 6),
)


def _results_rows(results) -> list:
    """Cell matrix for the results table — shared by both renderers.

    Numeric columns are rendered at one shared width so their decimals line up
    vertically instead of ragged per row.
    """
    macd = numeric_cells([r['macd'] for r in results], 4)
    signal = numeric_cells([r['macd_signal'] for r in results], 4)
    hist = numeric_cells([r['macd_hist'] for r in results], 4)
    close = numeric_cells([r['close'] for r in results], 2, prefix='$')

    rows = []
    for idx, r in enumerate(results):
        fresh = f"{r['freshness']}d".rjust(4)
        fresh += '*' if r['just_turned_positive'] else ' '
        rows.append([
            r['ticker'],
            str(r['earnings_date']),
            str(r['days_until_earnings']),
            macd[idx],
            signal[idx],
            hist[idx],
            close[idx],
            fresh,
            format_label(r.get('fundamentals')),
            format_rating(r.get('fundamentals')),
        ])
    return rows


def _format_results_table(results) -> list:
    """Render the results table. Shared by the terminal and the Slack report.

    Column widths come from the rendered cells, so a wide value widens its
    column for every row instead of shifting the rest of the row out of
    alignment with the header.
    """
    return render_table(_RESULTS_COLUMNS, _results_rows(results))


def _send_slack_message(results):
    """Format and send earnings screener results to Slack.

    The tables are posted as native Slack table blocks. A fenced code block is
    only monospaced inside the message bubble — in notifications, search
    results and channel previews Slack renders the same text as proportional
    type, which collapses every column. The plain-text table is kept as the
    fallback for workspaces that reject the block payload.

    Layout: results table, summary, fundamentals table, then the
    comma-delimited ticker list at the very bottom.
    """
    if not results:
        return

    title = "*Earnings Crossover — Upcoming Earnings + Bullish Daily MACD*"
    summary = (f"*{len(results)} stocks with upcoming earnings + bullish MACD* "
               "— sorted by freshness (most recent first)")
    legend = ("_Rate = Yahoo analyst consensus (1=Strong Buy … 5=Strong Sell; "
              "SB/B/H/S/SS = grade, number = mean). Fund = 0-8 growth score; "
              "`*` = max, `!` = outside $5-50B scope._")
    ticker_list = ','.join(r['ticker'] for r in results)

    lines = [title, "", "```"]
    lines.extend(_format_results_table(results))
    lines.append("```")
    lines.append(summary)
    lines.append(legend)

    researched = [r for r in results if r.get('fundamentals')]
    fundamentals_note = ("*Fundamentals (Fund = 0-8 growth score; `*` = max, "
                         "`!` = outside $5-50B scope. Rate = Yahoo consensus, "
                         "not CFRA):*")
    if researched:
        lines.append("")
        lines.append(fundamentals_note)
        lines.append("```")
        lines.extend(format_table([(r['ticker'], r.get('fundamentals')) for r in results]))
        lines.append("```")

    lines.append("")
    lines.append(ticker_list)

    blocks = [
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': title}},
        slack_table_block(_RESULTS_COLUMNS, _results_rows(results)),
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': f"{summary}\n{legend}"}},
    ]
    if researched:
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': fundamentals_note}})
        blocks.append(fundamentals_slack_table([(r['ticker'], r.get('fundamentals')) for r in results]))
    blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': ticker_list}})

    _send_slack("\n".join(lines), blocks)


def refresh_earnings_calendar(lookahead_days: int = 28):
    """
    Fetch upcoming earnings dates for all tickers in our DB.
    Stores in tbl_earnings_calendar for fast lookups.
    """
    conn = get_db_conn()
    cur = conn.cursor()

    # Get all tickers from DB
    cur.execute("SELECT symbol FROM tbl_stock_tickers WHERE enabled = true and is_etf=false")
    tickers = [row[0] for row in cur.fetchall()]
    print(f"Checking earnings dates for {len(tickers)} tickers...")

    cutoff = datetime.now().date() + timedelta(days=lookahead_days)
    found = 0
    errors = 0

    # Process in batches to avoid rate limits
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        print(f"  Batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1}: {len(batch)} tickers...")

        for ticker in batch:
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar

                if cal is None or (isinstance(cal, dict) and len(cal) == 0):
                    continue

                # Get earnings date (calendar is a dict)
                earnings_date = None
                if isinstance(cal, dict):
                    earnings_date = cal.get('Earnings Date')
                    if earnings_date and isinstance(earnings_date, list) and len(earnings_date) > 0:
                        earnings_date = earnings_date[0]

                if earnings_date is None:
                    continue

                # Convert to date
                if hasattr(earnings_date, 'date'):
                    earnings_date = earnings_date.date()
                elif isinstance(earnings_date, str):
                    earnings_date = pd.Timestamp(earnings_date).date()

                # Only cache if within lookahead window
                if earnings_date <= cutoff:
                    # Get quarter/year from calendar (not always available)
                    quarter = cal.get('Quarter', None) if isinstance(cal, dict) else None
                    year = cal.get('Year', None) if isinstance(cal, dict) else None

                    cur.execute("""
                        INSERT INTO tbl_earnings_calendar (ticker, earnings_date, quarter, year, updated_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (ticker) DO UPDATE SET
                            earnings_date = EXCLUDED.earnings_date,
                            quarter = EXCLUDED.quarter,
                            year = EXCLUDED.year,
                            updated_at = NOW()
                    """, (ticker, earnings_date, quarter, year))
                    found += 1

            except Exception as e:
                errors += 1
                # Silently skip errors (rate limits, missing data, etc.)

        conn.commit()

    cur.close()
    conn.close()

    print(f"\nRefresh complete:")
    print(f"  Found: {found} tickers with earnings in next {lookahead_days} days")
    print(f"  Errors: {errors} tickers skipped")
    return found


def get_upcoming_earnings(days_ahead: int = 14) -> list:
    """Get tickers with earnings in the next N days."""
    conn = get_db_conn()
    cur = conn.cursor()

    cutoff = datetime.now().date() + timedelta(days=days_ahead)
    cur.execute("""
        SELECT ticker, earnings_date, quarter, year
        FROM tbl_earnings_calendar
        WHERE earnings_date BETWEEN NOW() AND %s
        ORDER BY earnings_date
    """, (cutoff,))

    results = cur.fetchall()
    cur.close()
    conn.close()
    return results


def _macd_series(closes, fast=12, slow=26, signal=9):
    """Full MACD line / signal / histogram series, computed inline from closes.

    The stored MACD columns were dropped from the bar tables 2026-09-26 (they
    were lookahead-biased legacy artifacts), so MACD is derived here from raw
    closes instead of being read from the database.

    Each EMA is seeded with an SMA of its first `period` bars (standard
    convention) so early values are not distorted by a slow-decaying seed.
    Returns (None, None, None) when there isn't enough history.
    """
    if len(closes) < slow + signal:
        return None, None, None

    def ema(vals, period):
        k = 2.0 / (period + 1.0)
        out = [sum(vals[:period]) / period]          # SMA seed
        for v in vals[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    # fast_e is longer by (slow - fast) bars; align on the tail.
    macd_line = [f - s for f, s in zip(fast_e[slow - fast:], slow_e)]
    sig = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line[len(macd_line) - len(sig):], sig)]
    return macd_line, sig, hist


def check_daily_macd(ticker: str) -> dict:
    """
    Check if the DAILY MACD line crossed above zero recently.
    Only returns results if the LAST crossover was bullish (MACD line crossing above 0).

    Reads settled daily bars only (the newest complete date), matching the
    project's settled-bar rule: a partial current-day bar must never drive a
    signal.
    """
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM tbl_stock_tickers WHERE symbol = %s", (ticker,))
    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        return None

    ticker_id = result[0]

    # Last complete daily date across the whole table = the settled bar date.
    cur.execute("SELECT max(date) FROM tbl_prices_daily")
    settled = cur.fetchone()[0]
    if settled is None:
        cur.close()
        conn.close()
        return None

    # Oldest-first close series, settled bars only.
    cur.execute("""
        SELECT date, close
        FROM tbl_prices_daily
        WHERE ticker_id = %s AND date <= %s AND close IS NOT NULL
        ORDER BY date ASC
        LIMIT 400
    """, (ticker_id, settled))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if len(rows) < 40:
        return None

    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]

    series_m, series_s, series_h = _macd_series(closes)
    if series_m is None:
        return None

    # Find the LAST zero-line crossover of the MACD line (newest -> oldest).
    last_cross = None
    last_cross_idx = None
    for i in range(len(series_m) - 1, 0, -1):
        prev = series_m[i - 1]
        cur_m = series_m[i]
        if prev is None or cur_m is None:
            continue
        if prev <= 0 < cur_m:
            last_cross, last_cross_idx = 'BULL', i
            break
        if prev > 0 >= cur_m:
            last_cross, last_cross_idx = 'BEAR', i
            break

    if last_cross is None or last_cross != 'BULL':
        return None

    curr_macd = series_m[-1]
    curr_signal = series_s[-1]
    curr_hist = series_h[-1]
    curr_close = closes[-1]
    curr_date = dates[-1]

    if curr_macd is None or curr_close is None:
        return None

    # Freshness = number of DAILY bars since the crossover.
    freshness = (len(series_m) - 1) - last_cross_idx

    return {
        'ticker': ticker,
        'macd_bullish': curr_macd > 0,
        'just_turned_positive': freshness == 0,  # crossover on the latest settled bar
        'freshness': freshness,                  # 0 = latest settled bar, 1 = prior, etc.
        'macd': curr_macd,
        'macd_signal': curr_signal,
        'macd_hist': curr_hist,
        'close': curr_close,
        'last_bar_date': curr_date,
    }



def run_screener(days_ahead: int = 7, fresh_only: bool = True, send_slack: bool = False,
                 max_fresh_days: int = 10, research: bool = True,
                 refresh_fundamentals: bool = False, scope_only: bool = False):
    """
    Screen for stocks with upcoming earnings AND bullish daily MACD.
    Restricted to earnings within `days_ahead` days and a MACD cross no older than
    `max_fresh_days` days. Sorted by freshness (most recent crossover first).

    When `research` is on, each pick is scored 0-8 on fundamentals (revenue and
    earnings growth, margin trend, minus red-flag deductions) and gated by the
    $5-50B R&D-adoption scope. Only tickers not already in the fundamentals cache
    are fetched; `refresh_fundamentals` forces a full re-fetch. `scope_only` drops
    out-of-scope tickers entirely.
    """
    # Step 1: Get tickers with upcoming earnings
    upcoming = get_upcoming_earnings(days_ahead)

    if not upcoming:
        print(f"No tickers with earnings in next {days_ahead} days.")
        print("Run with --refresh to update earnings calendar.")
        return

    print(f"Found {len(upcoming)} tickers with earnings in next {days_ahead} days.")
    print("Checking daily MACD signals...\n")

    results = []

    for ticker, earnings_date, quarter, year in upcoming:
        macd_info = check_daily_macd(ticker)

        if macd_info is None:
            continue

        # Calculate days until earnings
        days_until = (earnings_date - datetime.now().date()).days

        # Apply fresh-only filter
        if fresh_only and not macd_info['just_turned_positive']:
            continue

        # Freshness cap: ignore crosses older than max_fresh_days
        if max_fresh_days is not None and macd_info['freshness'] > max_fresh_days:
            continue

        # Earnings window: upcoming only, within days_ahead
        if not 0 <= days_until <= days_ahead:
            continue

        results.append({
            **macd_info,
            'earnings_date': earnings_date,
            'days_until_earnings': days_until,
        })

    # Sort by freshness (0 = today first, then 1, 2, etc.)
    results.sort(key=lambda x: x['freshness'])

    # Fundamentals research — score each pick on revenue/earnings growth.
    # Only new tickers hit the network; cached tickers are reused.
    if research and results:
        fund = FundamentalsResearch()
        for r in results:
            r['fundamentals'] = fund.get(r['ticker'], refresh=refresh_fundamentals)
        fund.save()
        if scope_only:
            results = [r for r in results if (r.get('fundamentals') or {}).get('in_scope') is not False]

    # Display results
    if not results:
        print("No stocks match criteria (upcoming earnings + bullish daily MACD).")
        return

    print(f"{'='*80}")
    print(f"EARNINGS MOMENTUM SCREENER — {len(results)} stocks with upcoming earnings + bullish DAILY MACD")
    print(f"{'='*80}\n")

    for line in _format_results_table(results):
        print(line)

    print(f"\n* = Just turned positive (fresh crossover)")
    print(f"Rate = Yahoo analyst consensus (1=Strong Buy … 5=Strong Sell; "
          f"SB/B/H/S/SS = grade, number = mean).")
    print(f"\nSorted by freshness (most recent crossover first).")

    if research:
        print(f"\nFundamentals (Fund = 0-8 growth score; * = max, ! = outside $5-50B scope; "
              f"Rate = Yahoo consensus; MC = margin compression -1, GW = goodwill impairment -2):")
        for line in format_table([(r['ticker'], r.get('fundamentals')) for r in results]):
            print(line)

    # Comma-delimited ticker list
    ticker_list = ','.join(r['ticker'] for r in results)
    print(f"\n{ticker_list}")

    # Send to Slack if requested — only when the result set changed since the
    # last run, so the 30-min timer doesn't spam identical lists.
    if send_slack and results:
        sig = _state_signature(results)
        if sig == _load_state():
            print(f"[SLACK] No change from last run — suppressing duplicate ({len(results)} stocks)")
        else:
            _send_slack_message(results)
            _save_state(sig)


def show_stats():
    """Show earnings calendar stats."""
    conn = get_db_conn()
    cur = conn.cursor()

    # Count total cached
    cur.execute("SELECT COUNT(*) FROM tbl_earnings_calendar")
    total = cur.fetchone()[0]

    # Count upcoming
    cur.execute("""
        SELECT COUNT(*) FROM tbl_earnings_calendar
        WHERE earnings_date >= NOW()
    """)
    upcoming = cur.fetchone()[0]

    # Count by week
    cur.execute("""
        SELECT 
            DATE_TRUNC('week', earnings_date) as week,
            COUNT(*) as count
        FROM tbl_earnings_calendar
        WHERE earnings_date BETWEEN NOW() AND NOW() + INTERVAL '4 weeks'
        GROUP BY week
        ORDER BY week
    """)
    weekly = cur.fetchall()

    cur.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"EARNINGS CALENDAR STATS")
    print(f"{'='*50}")
    print(f"Total cached: {total} tickers")
    print(f"Upcoming (next 4 weeks): {upcoming} tickers")
    print(f"\nBy week:")
    for week, count in weekly:
        print(f"  {week.strftime('%Y-%m-%d')}: {count} tickers")


def main():
    parser = argparse.ArgumentParser(
        description='Earnings Momentum Screener — Find stocks with upcoming earnings + bullish daily MACD'
    )
    parser.add_argument('--refresh', action='store_true',
                        help='Refresh earnings calendar cache (next 4 weeks)')
    parser.add_argument('--days', type=int, default=7,
                        help='Only earnings within the next N days (default: 7)')
    parser.add_argument('--max-fresh', type=int, default=10,
                        help='Only MACD crosses at most N days old (default: 10)')
    parser.add_argument('--fresh-only', action='store_true', default=True,
                        help='Only show tickers where MACD just turned positive (default: on)')
    parser.add_argument('--all', action='store_true',
                        help='Show all tickers with bullish MACD (not just fresh)')
    parser.add_argument('--stats', action='store_true',
                        help='Show earnings calendar stats')
    parser.add_argument('--slack', action='store_true',
                        help='Send results to Slack')
    parser.add_argument('--no-research', dest='research', action='store_false',
                        help='Skip the fundamentals research column (faster)')
    parser.add_argument('--refresh-fundamentals', action='store_true',
                        help='Force re-fetch of fundamentals for every ticker (ignore cache)')
    parser.add_argument('--scope-only', action='store_true',
                        help='Drop tickers outside the $5-50B R&D-adoption scope')

    args = parser.parse_args()

    if args.refresh:
        print("Refreshing earnings calendar cache...")
        refresh_earnings_calendar(lookahead_days=28)
        show_stats()
    elif args.stats:
        show_stats()
    else:
        run_screener(days_ahead=args.days, fresh_only=args.fresh_only and not args.all,
                     send_slack=args.slack, max_fresh_days=args.max_fresh,
                     research=args.research, refresh_fundamentals=args.refresh_fundamentals,
                     scope_only=args.scope_only)


if __name__ == '__main__':
    main()
