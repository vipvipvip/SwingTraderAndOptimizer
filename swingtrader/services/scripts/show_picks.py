#!/usr/bin/env python3
"""Show current picks and P&L for MTF Top-N and Daily Signal strategies.

Picks come from the pick-history CSVs (data/mtf_picks_*.csv); holdings and
entry prices come from the live mtf_positions table (DB), not state files.
"""

import csv
import io
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MTF_DATA = os.path.join(BASE, 'mtf', 'data')
DS_CSV = os.path.join(BASE, 'ema_sma_crossover', 'data', 'daily_signals.csv')
sys.path.insert(0, os.path.join(BASE, 'mtf'))
import config
import db as db_module
import executor
from format_etf import etf_table_lines


def db_close(symbol):
    try:
        r = subprocess.run(
            ['docker', 'exec', 'swingtrader-db', 'psql', '-U', 'swingtrader', '-d', 'swingtrader', '-t',
             '-c', f"SELECT close, date FROM tbl_scanner_tickers_daily WHERE ticker_id=(SELECT id FROM tbl_stock_tickers WHERE symbol='{symbol}') ORDER BY date DESC LIMIT 1"],
            capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split('|')
        daily_close = float(parts[0]) if parts and parts[0].strip() and parts[0].strip() != '(0 rows)' else None
        daily_date = parts[1].strip()[:10] if len(parts) > 1 else ''

        r = subprocess.run(
            ['docker', 'exec', 'swingtrader-db', 'psql', '-U', 'swingtrader', '-d', 'swingtrader', '-t',
             '-c', f"SELECT close, date FROM tbl_scanner_tickers_1hour WHERE ticker_id=(SELECT id FROM tbl_stock_tickers WHERE symbol='{symbol}') ORDER BY date DESC LIMIT 1"],
            capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split('|')
        hourly_close = float(parts[0]) if parts and parts[0].strip() and parts[0].strip() != '(0 rows)' else None
        hourly_date = parts[1].strip()[:10] if len(parts) > 1 else ''

        if daily_close is not None and hourly_close is not None:
            return daily_close if daily_date >= hourly_date else hourly_close
        return daily_close if daily_close is not None else hourly_close
    except Exception:
        pass
    return None


def _latest_pick_rows(mode):
    """Return the most recent date's pick rows from the pick-history CSV.

    Columns (positional): date, rank, symbol, score, gap_w, atr_dist,
    freshness, entry_date, close. A header row may or may not be present.
    """
    path = os.path.join(MTF_DATA, f'mtf_picks_{mode}.csv')
    try:
        with open(path) as f:
            rows = list(csv.reader(f))
    except FileNotFoundError:
        return None
    if not rows:
        return None
    if rows[0] and rows[0][0] == 'date':
        rows = rows[1:]
    if not rows:
        return None
    latest_date = rows[-1][0]
    out = []
    for r in rows:
        if r[0] != latest_date or len(r) < 9:
            continue
        out.append({
            'date': latest_date, 'symbol': r[2], 'score': float(r[3]),
            'gap_w': float(r[4]), 'atr_dist': float(r[5]), 'freshness': int(r[6]),
            'entry_date': r[7], 'close': float(r[8]),
        })
    return out or None


def _db_positions(mode):
    """Held positions from mtf_positions, filtered to the mode's universe."""
    is_etf = mode == 'etf'
    conn = db_module.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT p.symbol, p.quantity, p.entry_price, p.entry_at
                FROM mtf_positions p
                JOIN tbl_stock_tickers s ON s.id = p.ticker_id
                WHERE s.is_etf = %s
            ''', (is_etf,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r[0]: {'qty': float(r[1]), 'price': float(r[2]) if r[2] else 0,
                   'date': str(r[3])[:10] if r[3] else '?'} for r in rows}


def _alpaca_equity(mode):
    """Live Alpaca account equity for the mode's paper account."""
    try:
        executor._set_alpaca_keys(mode)
        account = executor._get_account()
        return float(account.get('equity', 0))
    except Exception:
        return None


def show_mtf(label, mode, tsv=False):
    rows = _latest_pick_rows(mode)
    if not rows:
        return
    picks = [r['symbol'] for r in rows]
    date = rows[0]['date']
    positions = _db_positions(mode)
    entry_prices = {sym: {'price': p['price'], 'date': p['date']}
                    for sym, p in positions.items() if p['price']}

    if tsv:
        print(f"\n{label}  |  {date}")
        top_n = []
        score_detail = {}
        for r in rows:
            sym = r['symbol']
            now = db_close(sym) or 0
            top_n.append({'symbol': sym, 'score': float(r['score']),
                          'freshness': int(r['freshness']), 'gap_w': float(r['gap_w'])})
            score_detail[sym] = {'close': now}
        for line in etf_table_lines(top_n, score_detail, entry_prices, tsv=True):
            print(line)
        print(','.join(picks))
        return

    print(f"\n{'─' * 88}")
    print(f"  {label}  —  {len(positions)} positions  |  {date}")
    print(f"{'─' * 88}")
    print(f"  {'Ticker':8s}  {'Entry $':>8s}  {'Now $':>8s}  {'P&L $':>9s}  {'P&L %':>7s}  {'Fresh':>5s}  {'Score':>5s}  {'Date':>10s}")
    print(f"  {'─' * 74}")
    for r in rows:
        sym = r['symbol']
        score = float(r['score'])
        freshness = int(r['freshness'])
        ep = positions.get(sym, {}).get('price', 0)
        ed = positions.get(sym, {}).get('date', '?')
        now = db_close(sym)
        days = f'{freshness}d' if freshness < 999 else 'old'
        if now and ep:
            pl = now - ep
            print(f"  {sym:8s}  ${ep:<6.2f}  ${now:<6.2f}  ${pl:>+8.2f}  {(pl/ep)*100:>+6.2f}%  {days:>5s}  {score:>4.1f}  {ed:>10s}")
        else:
            print(f"  {sym:8s}  ${ep:<6.2f}  {'N/A':>8s}  {'N/A':>9s}  {'N/A':>7s}  {days:>5s}  {score:>4.1f}  {ed:>10s}")

    print(','.join(picks))


def show_daily():
    try:
        txt = open(DS_CSV).read().strip()
    except FileNotFoundError:
        return
    entries = []
    for r in csv.DictReader(io.StringIO(txt)):
        sym = r.get('ticker', '')
        dt = r.get('date', '')
        try:
            entry = float(r.get('close_price', 0))
        except (ValueError, TypeError):
            continue
        reason = r.get('reason', '') or ''
        typ = 'INFANCY' if 'INFANCY' in reason else 'MATURE'
        entries.append((sym, dt, entry, typ))

    entries.sort(key=lambda x: x[1], reverse=True)
    latest_date = entries[0][1] if entries else '?'
    latest = [e for e in entries if e[1] == latest_date]

    print(f"\n{'─' * 60}")
    print(f"  Daily Signal — {latest_date}  ({len(latest)} entries)")
    print(f"{'─' * 60}")
    print(f"  {'Symbol':8s} {'Entry':>8s} {'Now':>9s} {'P&L %':>8s} {'Type':8s}")
    print(f"  {'─' * 42}")
    for sym, dt, entry, typ in latest:
        now = db_close(sym)
        now_s = f"${now:<6.2f}" if now else 'N/A'
        ret = f"{(now-entry)/entry*100:+.2f}%" if now else 'N/A'
        print(f"  {sym:8s} ${entry:<5.2f}  {now_s:>8s}  {ret:>7s}  {typ:8s}")

    print(','.join(sym for sym, _, _, _ in latest))


def show_summary():
    rows = []
    for label, mode, cap in [('MTF Stock', 'stock', config.INITIAL_CAPITAL),
                             ('MTF ETF', 'etf', config.INITIAL_CAPITAL)]:
        eq = _alpaca_equity(mode)
        if eq:
            rows.append((label, cap, eq))

    spy = db_close('SPY') or 748.23
    spy_ref = 749.66  # SPY on 7/13
    spy_ret = (spy - spy_ref) / spy_ref * 100

    print(f"\n{'=' * 72}")
    print(f"  PORTFOLIO SUMMARY")
    print(f"{'=' * 72}")
    print(f"  {'Strategy':30s} {'Capital':>9s} {'Equity':>10s} {'Return':>8s} {'vs SPY':>8s}")
    print(f"  {'─' * 67}")
    for label, cap, eq in rows:
        ret = (eq - cap) / cap * 100
        print(f"  {label:30s} ${cap:>7,} ${eq:>8,.2f}  {ret:>+7.2f}%  {ret-spy_ret:>+7.2f}%")
    print(f"  {'SPY':30s} {'':>9s} {'':>10s}  {spy_ret:>+7.2f}%")


def main():
    show_mtf('MTF Stock', 'stock')
    show_mtf('MTF ETF', 'etf', tsv=True)
    show_daily()
    show_summary()


if __name__ == '__main__':
    main()
