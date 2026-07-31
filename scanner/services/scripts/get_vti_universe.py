"""Fetch VTI-like universe from Alpaca: all active US equities.

Filters: Price > $10, non-OTC, common stocks only.
Volume filtering skipped — IEX feed lacks reliable volume data.
MTF scoring naturally filters low-quality/low-volume stocks.

Usage:
    python get_vti_universe.py [--dry-run] [--min-price 10]
"""

import argparse
import os
import sys
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import API_KEY, SECRET_KEY, get_db_conn

ALPACA_TRADE_BASE = 'https://paper-api.alpaca.markets'


UNWANTED_FUND_PATTERNS = [
    # Leveraged / inverse products
    'PROSHARES ULTRA', 'DIREXION DAILY', 'MICROSECTORS', ' ETRACS ', 'VELOCITYSHARES',
    ' 2X ', ' 3X ', '-2X', '-3X', 'INVERSE', 'LEVERAGED',
    # Commodity / currency
    'CURRENCYSHARES', 'GOLD TRUST', 'GOLD MINISHARES', 'SILVER TRUST', 'GOLD DOUBLE LONG',
    'OIL FUND', 'NATURAL GAS FUND', 'GAS FUND', 'COPPER FUND', 'COMMODITY',
    'PRECIOUS METALS', 'UNITED STATES OIL', 'UNITED STATES NATURAL GAS',
    # Bitcoin / crypto
    'BITCOIN', 'ETHEREUM', 'CRYPTO', 'BLOCKCHAIN',
    # Preferred shares
    'PREFERRED',
]


def _is_unwanted_fund(name, symbol):
    """True if asset is a leveraged/inverse/commodity/currency/bitcoin/preferred
    fund that Alpaca misclassifies as a us_equity common stock."""
    upper = (name or symbol).upper()
    return any(p in upper for p in UNWANTED_FUND_PATTERNS)


def get_all_us_equities():
    """Fetch all active US equity assets from Alpaca Trading API."""
    headers = {
        'APCA-API-KEY-ID': API_KEY,
        'APCA-API-SECRET-KEY': SECRET_KEY,
    }
    url = f'{ALPACA_TRADE_BASE}/v2/assets'
    params = {
        'status': 'active',
        'asset_class': 'us_equity',
        'limit': 10000,
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    assets = resp.json()

    symbols = []
    for a in assets:
        sym = a.get('symbol', '')
        exchange = a.get('exchange', '')
        name = a.get('name', '')
        # Skip OTC, warrants, non-standard symbols
        if exchange in ('OTC',) or not sym.replace('.', '').replace('-', '').isalnum():
            continue
        if a.get('class') not in ('us_equity',):
            continue
        symbols.append({'symbol': sym, 'exchange': exchange, 'name': name or ''})

    symbols.sort(key=lambda x: x['symbol'])
    print(f'Fetched {len(symbols)} active US equity symbols from Alpaca')
    return symbols


def get_latest_prices_batch(symbols, client):
    """Get latest trade prices for a batch of symbols using Alpaca Data API."""
    from alpaca.data.requests import StockLatestTradeRequest

    results = {}
    batch_size = 200

    for i in range(0, len(symbols), batch_size):
        batch = [s['symbol'] for s in symbols[i:i + batch_size]]
        try:
            request = StockLatestTradeRequest(symbol_or_symbols=batch, feed='iex')
            trades = client.get_stock_latest_trade(request)
            for sym, trade in trades.items():
                price = float(trade.price)
                if price > 0:
                    results[sym] = price
        except Exception as e:
            print(f'  Snapshot batch {i // batch_size + 1} error: {e}')
        if i + batch_size < len(symbols):
            time.sleep(0.2)

    return results


def main():
    parser = argparse.ArgumentParser(description='Fetch VTI-like universe from Alpaca')
    parser.add_argument('--dry-run', action='store_true', help='Show results without inserting')
    parser.add_argument('--min-price', type=float, default=10.0, help='Minimum price filter (default: $10)')
    args = parser.parse_args()

    from alpaca.data.historical import StockHistoricalDataClient
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

    print('Step 1: Fetching all active US equity symbols...')
    all_assets = get_all_us_equities()

    print(f'\nStep 2: Getting latest prices for {len(all_assets)} symbols...')
    prices = get_latest_prices_batch(all_assets, client)
    print(f'  Got prices for {len(prices)} symbols')

    # Filter by price and exclude ETFs
    asset_map = {a['symbol']: a for a in all_assets}

    # Load existing ETF symbols from DB
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT symbol FROM tbl_etf_tickers")
            etf_symbols = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    qualified = []
    etf_skipped = 0
    for sym, price in prices.items():
        if price < args.min_price:
            continue
        asset = asset_map.get(sym, {})
        name = asset.get('name', '').upper()
        # Skip ETFs: check DB table + name heuristic
        if sym in etf_symbols or ' ETF ' in name or name.endswith(' ETF'):
            etf_skipped += 1
            continue
        # Skip funds (not individual stocks)
        if ' FUND' in name or ' FUNDS' in name or name.endswith(' FUND'):
            etf_skipped += 1
            continue
        # Skip preferred shares (e.g. ALB.PRA) but keep class shares (BRK.A, BF.B)
        if '.PR' in sym.upper() or '.PREF' in sym.upper():
            continue
        # Skip leveraged/inverse/commodity/currency/bitcoin/preferred funds that
        # Alpaca misclassifies as us_equity (ProShares Ultra, MicroSectors, ETNs,
        # CurrencyShares, gold/silver trusts, etc.)
        if _is_unwanted_fund(name, sym):
            etf_skipped += 1
            continue
        qualified.append({
            'symbol': sym,
            'price': price,
            'exchange': asset.get('exchange', ''),
            'name': asset.get('name', ''),
        })

    if etf_skipped:
        print(f'  (Skipped {etf_skipped} ETFs)')

    qualified.sort(key=lambda x: x['price'], reverse=True)
    print(f'\nResult: {len(qualified)} tickers qualify (Price >= ${args.min_price})')

    # Exchange breakdown
    from collections import Counter
    exch_counts = Counter(q['exchange'] for q in qualified)
    print('  Exchange breakdown:')
    for ex, cnt in exch_counts.most_common():
        print(f'    {ex}: {cnt}')

    # Show top/bottom 10
    print('\n--- Top 10 by Price ---')
    for q in qualified[:10]:
        print(f"  {q['symbol']:>8s}  ${q['price']:>10.2f}  {q['exchange']:>5s}  {q['name'][:40]}")

    print(f'\n--- Bottom 10 by Price ---')
    for q in qualified[-10:]:
        print(f"  {q['symbol']:>8s}  ${q['price']:>10.2f}  {q['exchange']:>5s}  {q['name'][:40]}")

    if args.dry_run:
        print('\n[DRY RUN] Not inserting into database.')
        return

    # Bulk insert into tbl_stock_tickers
    print(f'\nInserting {len(qualified)} tickers into tbl_stock_tickers...')
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            # Get existing symbols
            cur.execute("SELECT symbol, enabled FROM tbl_stock_tickers WHERE is_etf = false")
            existing = {row[0]: row[1] for row in cur.fetchall()}

            new_symbols = [q['symbol'] for q in qualified if q['symbol'] not in existing]
            disabled_symbols = [q['symbol'] for q in qualified
                                if q['symbol'] in existing and not existing[q['symbol']]]

            # Bulk insert new tickers
            if new_symbols:
                for s in new_symbols:
                    cur.execute(
                        "INSERT INTO tbl_stock_tickers (symbol, enabled, is_etf, created_at, updated_at) "
                        "VALUES (%s, true, false, NOW(), NOW()) ON CONFLICT (symbol) DO NOTHING",
                        (s,),
                    )

            # Enable previously disabled tickers
            if disabled_symbols:
                cur.execute(
                    "UPDATE tbl_stock_tickers SET enabled=true, updated_at=NOW() "
                    "WHERE symbol = ANY(%s) AND is_etf = false",
                    (disabled_symbols,),
                )

            conn.commit()
            added = len(new_symbols)
            updated = len(disabled_symbols)
    finally:
        conn.close()

    print(f'Done. Added: {added}, Enabled (was disabled): {updated}, Total: {added + updated}')

    # Summary
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM tbl_stock_tickers WHERE enabled=true AND is_etf=false")
            total_enabled = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM tbl_stock_tickers WHERE enabled=true")
            total_all = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM tbl_stock_tickers")
            total_all_tickers = cur.fetchone()[0]
            print(f'\nDB state: {total_enabled} enabled stocks, {total_all} total enabled (incl ETFs), {total_all_tickers} total')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
