#!/usr/bin/env python3
"""Add or remove a ticker from the EMAC strategy.

Usage:
  python3 manageTicker.py --add SYMBOL    # add ticker
  python3 manageTicker.py --remove SYMBOL # remove ticker

Steps:
  1. Updates TICKERS list in config.py
  2. Backfills historical data (add) or clears DB data (remove)
  3. Restarts the emac-runner service
"""
import re
import sys
import os
from datetime import datetime

import config
import db as db_module
from price_collector import fetch_all_30min_bars


def _config_path():
    return os.path.join(os.path.dirname(__file__), 'config.py')


def _get_tickers(content):
    m = re.search(r"TICKERS\s*=\s*\[([^\]]+)\]", content)
    if not m:
        return None, None, None
    return m.group(0), m.group(1), re.findall(r"'(\w+)'", m.group(1))


def add_to_config(sym):
    path = _config_path()
    with open(path) as f:
        content = f.read()

    full, tickers_str, current = _get_tickers(content)
    if full is None:
        print('✗ Could not find TICKERS list in config.py')
        return False

    if sym in current:
        print(f'  {sym} already in TICKERS')
        return True

    new_tickers = tickers_str.rstrip() + f", '{sym}'"
    content = content.replace(tickers_str, new_tickers)

    with open(path, 'w') as f:
        f.write(content)
    print(f'  Added {sym} to TICKERS')
    return True


def remove_from_config(sym):
    path = _config_path()
    with open(path) as f:
        content = f.read()

    full, tickers_str, current = _get_tickers(content)
    if full is None:
        print('✗ Could not find TICKERS list in config.py')
        return False

    if sym not in current:
        print(f'  {sym} not in TICKERS')
        return True

    remaining = [f"'{s}'" for s in current if s != sym]
    new_full = full.replace(tickers_str, ', '.join(remaining))
    content = content.replace(full, new_full)

    with open(path, 'w') as f:
        f.write(content)
    print(f'  Removed {sym} from TICKERS')
    return True


def backfill(sym):
    db_module.init_db()
    conn = db_module.get_conn()
    try:
        tid = db_module.ensure_ticker(conn, sym)
        print(f'  ticker_id={tid}')

        bars = fetch_all_30min_bars(sym)
        if not bars:
            print(f'  ✗ No historical data from Alpaca')
            return False

        rows = []
        for b in bars:
            ts = b['t']
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            rows.append((tid, ts, float(b['o']), float(b['h']),
                         float(b['l']), float(b['c']), int(b['v'])))

        db_module.insert_candles_bulk(conn, rows)
        count = db_module.candle_count(conn, tid)
        print(f'  ✓ {count} historical candles stored')
        return True
    finally:
        conn.close()


def clear_db(sym):
    db_module.init_db()
    conn = db_module.get_conn()
    try:
        tid = db_module.get_ticker_id(conn, sym)
        if not tid:
            print(f'  {sym} not found in DB')
            return True

        with conn.cursor() as cur:
            cur.execute('DELETE FROM emac_candles WHERE ticker_id = %s', (tid,))
            cur.execute('DELETE FROM emac_trades WHERE ticker_id = %s', (tid,))
            cur.execute('DELETE FROM emac_positions WHERE ticker_id = %s', (tid,))
        conn.commit()
        print(f'  ✓ Cleared DB data for {sym}')
        return True
    finally:
        conn.close()


def restart_service():
    code = os.system('sudo systemctl restart emac-runner')
    if code == 0:
        print('  ✓ emac-runner restarted')
        return True
    print('  ✗ Restart failed (run manually: sudo systemctl restart emac-runner)')
    return False


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    sym = sys.argv[2].upper()

    if action == '--remove':
        print(f'\n[{sym}] Removing ticker from EMAC strategy...')
        if not remove_from_config(sym):
            sys.exit(1)
        clear_db(sym)
    elif action == '--add':
        print(f'\n[{sym}] Adding ticker to EMAC strategy...')
        if not add_to_config(sym):
            sys.exit(1)
        if not backfill(sym):
            sys.exit(1)
    else:
        print(f'✗ Unknown action: {action}\n')
        print(__doc__)
        sys.exit(1)

    restart_service()
    print(f'\n✓ Done. Monitor: journalctl -u emac-runner -f\n')


if __name__ == '__main__':
    main()
