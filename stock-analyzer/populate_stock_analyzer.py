#!/usr/bin/env python3
"""Scrape fundamental data from stockanalysis.com and populate tbl_stock_analyzer.

Modes:
  --fundamentals   Scrape revenue/net income/EPS/shares/etc from stockanalysis.com
                   and recompute valuation price. (Slow — 503 HTTP requests.)
  --valuation      Fetch latest quotes from Alpaca and update db_close +
                   recompute db_valuation_price from existing fundamentals. (Fast.)
  (no flag)        Run both: fundamentals first, then valuation.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import psycopg2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scanner', 'services'))
from config import get_db_conn, API_KEY, SECRET_KEY

BASE_URL = 'https://stockanalysis.com/stocks'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

FIELD_MAP = {
    'Revenue (ttm)': 'db_revenue',
    'Net Income':    'db_net_income',
    'EPS':           'db_eps',
    'Shares Out':    'db_shares_outstanding',
    'PE Ratio':      'db_pe_ratio',
    'Forward PE':    'db_forward_pe',
    'Dividend':      'db_dividend',
}

REQUIRED_FIELDS = {'db_revenue', 'db_net_income', 'db_eps', 'db_shares_outstanding'}

MULTIPLIERS = {'T': 1e12, 'B': 1e9, 'M': 1e6, 'K': 1e3}

# Valuation parameters (from DKC_StockAnalyzer spreadsheet)
EQUITY_PAYBACK_YRS = 5.0
EQUITY_PCT = 0.37924860296721596
LOAN_MONTHS = 300
LOAN_RATE = 0.07


def _pmt(rate, nper, pv):
    """PMT(rate, nper, pv) — equivalent to Excel/Google Sheets PMT."""
    if rate == 0:
        return -pv / nper
    r1 = (1 + rate) ** nper
    return -pv * rate * r1 / (r1 - 1)


DEBT_FACTOR = _pmt(LOAN_RATE / 12, LOAN_MONTHS, -1) * 12
_e2 = EQUITY_PAYBACK_YRS / EQUITY_PCT
NOI_PCT_TO_OWNERS = 1 - _e2 * DEBT_FACTOR * (1 - EQUITY_PCT)


def compute_valuation_price(revenue: float, net_income: float, shares: float) -> float | None:
    if not revenue or not shares or shares == 0 or revenue == 0:
        return None

    ni = net_income
    rev = revenue
    shr = shares

    rrm = (ni - ni * NOI_PCT_TO_OWNERS) / DEBT_FACTOR / (1 - EQUITY_PCT) / rev
    max_price = rev * rrm
    owners = ni * NOI_PCT_TO_OWNERS
    max_debt = ni - owners
    loan = min(max_price, max(max_debt / EQUITY_PCT, max_price * (1 - EQUITY_PCT)))
    equity = max(0, max_price - loan)
    offer = loan + equity
    eq_noi = ni * EQUITY_PAYBACK_YRS
    price_to_pay = eq_noi / EQUITY_PCT
    fair_price = min(price_to_pay / shr, offer / shr)

    return fair_price


def normalize_symbol(symbol: str) -> str:
    return symbol.lower()


def parse_numeric(raw: str) -> float | None:
    if not raw or raw in ('N/A', '-', 'n/a'):
        return None

    val = raw.strip().lstrip('$').replace(',', '')
    val = re.sub(r'\(.*?\)', '', val).strip()
    val = re.sub(r'[+\-]\d+[\d.]*%$', '', val).strip()

    if not val or val in ('N/A', '-'):
        return None

    suffix = val[-1].upper()
    if suffix in MULTIPLIERS:
        try:
            return float(val[:-1]) * MULTIPLIERS[suffix]
        except ValueError:
            return None

    try:
        return float(val)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Fundamentals mode: scrape stockanalysis.com
# ---------------------------------------------------------------------------

def scrape_ticker(symbol: str) -> dict | None:
    slug = normalize_symbol(symbol)
    url = f'{BASE_URL}/{slug}/'

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 404:
                print(f'  [{symbol}] 404 — not found on stockanalysis.com')
                return None
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            print(f'  [{symbol}] fetch failed after 3 attempts: {e}')
            return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    data = {}

    for row in soup.find_all('tr'):
        tds = row.find_all('td')
        if len(tds) < 2:
            continue
        label = tds[0].get_text(strip=True)
        if label in FIELD_MAP:
            value_text = tds[1].get_text(strip=True)
            data[FIELD_MAP[label]] = parse_numeric(value_text)

    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        truly_missing = [f for f in missing if f not in data]
        if truly_missing:
            print(f'  [{symbol}] missing required fields: {truly_missing}')
            return None

    for col in FIELD_MAP.values():
        data.setdefault(col, None)

    data['db_valuation_price'] = compute_valuation_price(
        data['db_revenue'], data['db_net_income'], data['db_shares_outstanding']
    )

    return data


def fundamentals_worker(symbol: str, ticker_id: int, scrape_date: datetime, dry_run: bool) -> bool:
    time.sleep(1.0)

    data = scrape_ticker(symbol)
    if data is None:
        return False

    if dry_run:
        print(f'  [{symbol}] (dry-run) {data}')
        return True

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM tbl_stock_analyzer WHERE ticker_id = %s', (ticker_id,))
            cur.execute(
                """INSERT INTO tbl_stock_analyzer
                   (ticker_id, date, db_revenue, db_net_income, db_eps,
                    db_shares_outstanding, db_pe_ratio, db_forward_pe, db_dividend,
                    db_valuation_price)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    ticker_id,
                    scrape_date,
                    data['db_revenue'],
                    data['db_net_income'],
                    data['db_eps'],
                    data['db_shares_outstanding'],
                    data['db_pe_ratio'],
                    data['db_forward_pe'],
                    data['db_dividend'],
                    data['db_valuation_price'],
                ),
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'  [{symbol}] DB error: {e}')
        return False
    finally:
        conn.close()


def run_fundamentals(tickers, workers, dry_run):
    scrape_date = datetime.now()
    total = len(tickers)
    print(f'[fundamentals] Scraping {total} tickers with {workers} workers'
          f'{" (dry-run)" if dry_run else ""}')
    print(f'Snapshot date: {scrape_date.strftime("%Y-%m-%d %H:%M")}')
    print()

    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fundamentals_worker, sym, tid, scrape_date, dry_run): sym
            for tid, sym in tickers
        }
        for i, future in enumerate(as_completed(futures), 1):
            sym = futures[future]
            try:
                if future.result():
                    success += 1
                    print(f'  [{sym}] OK  ({i}/{total})')
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                print(f'  [{sym}] exception: {e}')

    print(f'[fundamentals] Done. Success: {success}, Failed: {failed}, Total: {total}')
    print()


# ---------------------------------------------------------------------------
# Valuation mode: fetch latest quotes from Alpaca, update db_close + valuation
# ---------------------------------------------------------------------------

def fetch_alpaca_prices(symbols: list[str]) -> dict[str, float]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    prices = {}
    lock = __import__('threading').Lock()

    batch_size = 100
    batches = [symbols[i:i + batch_size] for i in range(0, len(symbols), batch_size)]

    def fetch_quotes(batch):
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=batch)
            quotes = client.get_stock_latest_quote(req)
            result = {}
            for sym, quote in quotes.items():
                mid = (quote.ask_price + quote.bid_price) / 2 if quote.ask_price and quote.bid_price else None
                if mid and mid > 0:
                    result[sym] = mid
            with lock:
                prices.update(result)
        except Exception as e:
            print(f'  Alpaca quote batch error: {e}')

    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(fetch_quotes, batches)

    missing = [s for s in symbols if s not in prices]
    if missing:
        missing_batches = [missing[i:i + batch_size] for i in range(0, len(missing), batch_size)]

        def fetch_trades(batch):
            try:
                req = StockLatestTradeRequest(symbol_or_symbols=batch)
                trades = client.get_stock_latest_trade(req)
                result = {}
                for sym, trade in trades.items():
                    if trade.price and trade.price > 0:
                        result[sym] = trade.price
                with lock:
                    prices.update(result)
            except Exception as e:
                print(f'  Alpaca trade batch error: {e}')

        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(fetch_trades, missing_batches)

    return prices


def run_valuation(tickers, dry_run):
    now = datetime.now()
    symbols = [sym for _, sym in tickers]
    ticker_map = {sym: tid for tid, sym in tickers}
    total = len(symbols)

    print(f'[valuation] Fetching latest quotes for {total} tickers from Alpaca...')
    prices = fetch_alpaca_prices(symbols)
    print(f'[valuation] Got prices for {len(prices)}/{total} tickers')
    print()

    if dry_run:
        for sym in sorted(prices):
            print(f'  [{sym}] (dry-run) close=${prices[sym]:.2f}')
        print(f'[valuation] Done (dry-run). {len(prices)} prices fetched.')
        print()
        return

    conn = get_db_conn()
    success = 0
    failed = 0
    try:
        with conn.cursor() as cur:
            for sym, price in prices.items():
                tid = ticker_map[sym]
                try:
                    cur.execute(
                        """UPDATE tbl_stock_analyzer
                           SET db_close = %s, date = %s
                           WHERE ticker_id = %s""",
                        (price, now, tid),
                    )
                    if cur.rowcount == 0:
                        print(f'  [{sym}] no existing row — run --fundamentals first')
                        failed += 1
                        continue

                    # Recompute valuation from stored fundamentals
                    cur.execute(
                        """SELECT db_revenue, db_net_income, db_shares_outstanding
                           FROM tbl_stock_analyzer WHERE ticker_id = %s""",
                        (tid,),
                    )
                    row = cur.fetchone()
                    if row and row[0] and row[1] and row[2]:
                        val_price = compute_valuation_price(
                            float(row[0]), float(row[1]), float(row[2])
                        )
                        cur.execute(
                            """UPDATE tbl_stock_analyzer
                               SET db_valuation_price = %s
                               WHERE ticker_id = %s""",
                            (val_price, tid),
                        )
                    success += 1
                except Exception as e:
                    print(f'  [{sym}] DB error: {e}')
                    failed += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f'[valuation] DB error: {e}')
    finally:
        conn.close()

    not_found = total - len(prices)
    print(f'[valuation] Done. Updated: {success}, Failed: {failed}, '
          f'No quote: {not_found}, Total: {total}')
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Populate tbl_stock_analyzer with fundamentals and/or valuation data')
    parser.add_argument('--fundamentals', action='store_true',
                        help='Scrape fundamentals from stockanalysis.com')
    parser.add_argument('--valuation', action='store_true',
                        help='Fetch latest price from Alpaca and update db_close + valuation')
    parser.add_argument('--workers', type=int, default=3,
                        help='Parallel workers for fundamentals scraping (default: 3)')
    parser.add_argument('--symbol', type=str,
                        help='Process a single ticker (for testing)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse and print but do not write to DB')
    args = parser.parse_args()

    # Default: run both if neither flag is specified
    run_fund = args.fundamentals or not (args.fundamentals or args.valuation)
    run_val = args.valuation or not (args.fundamentals or args.valuation)

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            if args.symbol:
                cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE symbol = %s',
                            (args.symbol.upper(),))
            else:
                cur.execute('SELECT id, symbol FROM tbl_stock_tickers '
                            'WHERE enabled = true ORDER BY symbol')
            tickers = cur.fetchall()
    finally:
        conn.close()

    if not tickers:
        print('No tickers found.')
        return

    if run_fund:
        run_fundamentals(tickers, args.workers, args.dry_run)

    if run_val:
        run_valuation(tickers, args.dry_run)


if __name__ == '__main__':
    main()
