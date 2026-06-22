#!/usr/bin/env python3
"""One-time script to populate tbl_stock_tickers.company_name from stockanalysis.com."""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'scanner', 'services'))
from config import get_db_conn

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
}


def fetch_company_name(symbol: str) -> str | None:
    slug = symbol.lower()
    url = f'https://stockanalysis.com/stocks/{slug}/'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        h1 = soup.find('h1')
        if not h1:
            return None
        name = h1.get_text(strip=True)
        return re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    except Exception:
        return None


def worker(ticker_id: int, symbol: str) -> bool:
    time.sleep(1.0)
    name = fetch_company_name(symbol)
    if not name:
        print(f'  [{symbol}] failed')
        return False

    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE tbl_stock_tickers SET company_name = %s WHERE id = %s', (name, ticker_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f'  [{symbol}] DB error: {e}')
        return False
    finally:
        conn.close()


def main():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id, symbol FROM tbl_stock_tickers WHERE company_name IS NULL AND enabled = true ORDER BY symbol')
        tickers = cur.fetchall()
    conn.close()

    if not tickers:
        print('All tickers already have company names.')
        return

    total = len(tickers)
    print(f'Populating company names for {total} tickers...')

    success = 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(worker, tid, sym): sym for tid, sym in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            sym = futures[future]
            if future.result():
                success += 1
                print(f'  [{sym}] OK ({i}/{total})')

    print(f'\nDone. {success}/{total} populated.')


if __name__ == '__main__':
    main()
