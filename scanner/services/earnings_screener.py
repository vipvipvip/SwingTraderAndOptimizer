#!/usr/bin/env python3
"""
Earnings Screener CLI
---------------------
Finds stocks with upcoming earnings where hourly MACD just turned positive.
The pattern: hourly MACD turns bullish BEFORE earnings → potential earnings pop.

Usage:
    python earnings_screener.py --refresh          # Cache next 4 weeks of earnings dates
    python earnings_screener.py                    # Run screener (default: 14 days)
    python earnings_screener.py --days 7           # Look 7 days ahead
    python earnings_screener.py --min-freshness 3  # Only signals from last 3 days
"""

import argparse
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

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')


# ── DB Helpers ──────────────────────────────────────────────────────────────

def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)


def _send_slack(msg):
    """Send message to Slack."""
    if not SLACK_WEBHOOK_URL:
        print("[SLACK] No webhook URL configured")
        return
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={'text': msg}, timeout=10)
        r.raise_for_status()
        print("[SLACK] Message sent")
    except Exception as e:
        print(f"[SLACK] Error: {e}")


def _send_slack_message(results):
    """Format and send earnings screener results to Slack using terminal table format."""
    if not results:
        return

    # Build the same table format as terminal output
    lines = ["*Earnings Crossover — Upcoming Earnings + Bullish Hourly MACD*\n"]
    lines.append("```")
    lines.append(f"{'Ticker':<8} {'Earnings':>10} {'Days':>5} {'MACD':>8} {'Signal':>8} {'Hist':>8} {'Close':>8} {'Fresh':>6}")
    lines.append(f"{'-'*8} {'-'*10} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")

    for r in results:
        fresh_str = f"{r['freshness']}d"
        if r['just_turned_positive']:
            fresh_str = f"{r['freshness']}d *"

        lines.append(f"{r['ticker']:<8} {str(r['earnings_date']):>10} {r['days_until_earnings']:>5} "
                     f"{r['macd']:>8.4f} {r['macd_signal']:>8.4f} {r['macd_hist']:>8.4f} "
                     f"${r['close']:>7.2f} {fresh_str:>6}")

    lines.append("```")
    lines.append(f"*{len(results)} stocks with upcoming earnings + bullish MACD* — sorted by freshness (most recent first)")

    # Comma-delimited ticker list
    ticker_list = ','.join(r['ticker'] for r in results)
    lines.append(f"\n{ticker_list}")

    _send_slack("\n".join(lines))


def refresh_earnings_calendar(lookahead_days: int = 28):
    """
    Fetch upcoming earnings dates for all tickers in our DB.
    Stores in tbl_earnings_calendar for fast lookups.
    """
    conn = get_db_conn()
    cur = conn.cursor()

    # Get all tickers from DB
    cur.execute("SELECT symbol FROM tbl_stock_tickers WHERE enabled = true")
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


def check_hourly_macd(ticker: str) -> dict:
    """
    Check if hourly MACD line crossed above zero recently.
    Only returns results if the LAST crossover was bullish (MACD line crossing above 0).
    """
    conn = get_db_conn()
    cur = conn.cursor()

    # Get ticker_id first
    cur.execute("SELECT id FROM tbl_stock_tickers WHERE symbol = %s", (ticker,))
    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        return None

    ticker_id = result[0]

    # Get latest hourly bars with MACD line crossover detection
    cur.execute("""
        WITH crosses AS (
            SELECT date, macd_line, macd_signal, macd_histogram, close,
                   CASE 
                       WHEN macd_line > 0 AND LAG(macd_line) OVER (ORDER BY date) <= 0 THEN 'BULL'
                       WHEN macd_line <= 0 AND LAG(macd_line) OVER (ORDER BY date) > 0 THEN 'BEAR'
                   END as cross_type
            FROM tbl_scanner_tickers_1hour
            WHERE ticker_id = %s
        )
        SELECT date, macd_line, macd_signal, macd_histogram, close, cross_type
        FROM crosses
        ORDER BY date DESC
        LIMIT 30
    """, (ticker_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if len(rows) < 2:
        return None

    # Find the LAST crossover event
    last_cross = None
    last_cross_idx = None
    for i, row in enumerate(rows):
        if row[5] is not None:  # cross_type is not null
            last_cross = row[5]
            last_cross_idx = i
            break

    # If no crossover found, skip
    if last_cross is None:
        return None

    # Only keep if last crossover was BULLISH (MACD line crossed above 0)
    if last_cross != 'BULL':
        return None

    # Current state
    curr_date = rows[0][0]
    curr_macd = rows[0][1]
    curr_signal = rows[0][2]
    curr_hist = rows[0][3]
    curr_close = rows[0][4]

    # Freshness = number of bars since last crossover
    freshness = last_cross_idx

    return {
        'ticker': ticker,
        'macd_bullish': curr_macd > 0,
        'just_turned_positive': last_cross_idx == 0,  # Crossover happened on latest bar
        'freshness': freshness,  # 0 = today, 1 = yesterday, etc.
        'macd': curr_macd,
        'macd_signal': curr_signal,
        'macd_hist': curr_hist,
        'close': curr_close,
        'last_bar_date': curr_date,
    }


def run_screener(days_ahead: int = 14, fresh_only: bool = True, send_slack: bool = False):
    """
    Screen for stocks with upcoming earnings AND bullish hourly MACD.
    Sorted by freshness (most recent crossover first).
    """
    # Step 1: Get tickers with upcoming earnings
    upcoming = get_upcoming_earnings(days_ahead)

    if not upcoming:
        print(f"No tickers with earnings in next {days_ahead} days.")
        print("Run with --refresh to update earnings calendar.")
        return

    print(f"Found {len(upcoming)} tickers with earnings in next {days_ahead} days.")
    print("Checking hourly MACD signals...\n")

    results = []

    for ticker, earnings_date, quarter, year in upcoming:
        macd_info = check_hourly_macd(ticker)

        if macd_info is None:
            continue

        # Calculate days until earnings
        days_until = (earnings_date - datetime.now().date()).days

        # Apply fresh-only filter
        if fresh_only and not macd_info['just_turned_positive']:
            continue

        results.append({
            **macd_info,
            'earnings_date': earnings_date,
            'days_until_earnings': days_until,
        })

    # Sort by freshness (0 = today first, then 1, 2, etc.)
    results.sort(key=lambda x: x['freshness'])

    # Display results
    if not results:
        print("No stocks match criteria (upcoming earnings + bullish hourly MACD).")
        return

    print(f"{'='*80}")
    print(f"EARNINGS MOMENTUM SCREENER — {len(results)} stocks with upcoming earnings + bullish MACD")
    print(f"{'='*80}\n")

    print(f"{'Ticker':<8} {'Earnings':>10} {'Days':>5} {'MACD':>8} {'Signal':>8} {'Hist':>8} {'Close':>8} {'Fresh':>6}")
    print(f"{'-'*8} {'-'*10} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")

    for r in results:
        # Color coding
        fresh_str = f"{r['freshness']}d"
        if r['just_turned_positive']:
            fresh_str = f"{r['freshness']}d *"

        print(f"{r['ticker']:<8} {str(r['earnings_date']):>10} {r['days_until_earnings']:>5} "
              f"{r['macd']:>8.4f} {r['macd_signal']:>8.4f} {r['macd_hist']:>8.4f} "
              f"${r['close']:>7.2f} {fresh_str:>6}")

    print(f"\n* = Just turned positive (fresh crossover)")
    print(f"\nSorted by freshness (most recent crossover first).")

    # Comma-delimited ticker list
    ticker_list = ','.join(r['ticker'] for r in results)
    print(f"\n{ticker_list}")

    # Send to Slack if requested
    if send_slack and results:
        _send_slack_message(results)


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
        description='Earnings Momentum Screener — Find stocks with upcoming earnings + bullish hourly MACD'
    )
    parser.add_argument('--refresh', action='store_true',
                        help='Refresh earnings calendar cache (next 4 weeks)')
    parser.add_argument('--days', type=int, default=14,
                        help='Look N days ahead for earnings (default: 14)')
    parser.add_argument('--fresh-only', action='store_true', default=True,
                        help='Only show tickers where MACD just turned positive (default: on)')
    parser.add_argument('--all', action='store_true',
                        help='Show all tickers with bullish MACD (not just fresh)')
    parser.add_argument('--stats', action='store_true',
                        help='Show earnings calendar stats')
    parser.add_argument('--slack', action='store_true',
                        help='Send results to Slack')

    args = parser.parse_args()

    if args.refresh:
        print("Refreshing earnings calendar cache...")
        refresh_earnings_calendar(lookahead_days=28)
        show_stats()
    elif args.stats:
        show_stats()
    else:
        run_screener(days_ahead=args.days, fresh_only=args.fresh_only and not args.all, send_slack=args.slack)


if __name__ == '__main__':
    main()
