#!/usr/bin/env python3
"""Show current picks and P&L for MTF Top-N and Daily Signal strategies."""

import csv
import io
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MTF_DATA = os.path.join(BASE, 'mtf', 'data')
DS_CSV = os.path.join(BASE, 'ema_sma_crossover', 'data', 'daily_signals.csv')


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


def _parse_entry_dates(csv_path, picks):
    """Scan portfolio CSV to find entry date + price for each currently held pick."""
    entry_dates = {}
    entry_prices = {}
    try:
        with open(csv_path) as f:
            rows = [l for l in f.read().strip().split('\n') if l]
    except (FileNotFoundError, OSError):
        return entry_dates, entry_prices

    if len(rows) < 2:
        return entry_dates, entry_prices

    first_date = rows[1].split(',')[0]
    active = {}    # symbol -> entry_date
    prices = {}    # symbol -> entry_price
    for line in rows:
        parts = line.split(',')
        if len(parts) < 7:
            continue
        date = parts[0]
        buys = parts[5].strip()
        sells = parts[6].strip()

        if sells:
            for seg in sells.split('|'):
                seg = seg.strip()
                if seg:
                    sym_sold = seg.split()[0] if ' ' in seg else seg
                    active.pop(sym_sold, None)
                    prices.pop(sym_sold, None)

        if buys and '@' in buys:
            for seg in buys.split('|'):
                seg = seg.strip()
                if '@' in seg:
                    parts_b = seg.split(' @ $')
                    sym_bought = parts_b[0].strip()
                    active[sym_bought] = date
                    try:
                        prices[sym_bought] = float(parts_b[1])
                    except (IndexError, ValueError):
                        pass

    for sym in picks:
        if sym in active:
            entry_dates[sym] = active[sym]
            if sym in prices:
                entry_prices[sym] = prices[sym]
        else:
            entry_dates[sym] = first_date
    return entry_dates, entry_prices


def show_mtf(label, state_file, csv_file, capital):
    path = os.path.join(os.path.dirname(MTF_DATA), state_file)
    try:
        state = json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return

    picks = state.get('last_picks', [])
    scores = state.get('last_scores', {})
    positions = state.get('portfolio', {}).get('positions', {})
    date = state.get('last_date', '?')
    if not picks:
        return

    entry_dates, csv_prices = _parse_entry_dates(os.path.join(MTF_DATA, csv_file), set(picks))

    print(f"\n{'─' * 80}")
    print(f"  {label}  —  {len(picks)} positions  |  {date}")
    print(f"{'─' * 80}")
    print(f"  {'Ticker':8s}  {'Entry $':>8s}  {'Now $':>8s}  {'P&L $':>9s}  {'P&L %':>7s}  {'Score':>5s}  {'Entry':>10s}")
    print(f"  {'─' * 66}")
    for sym in picks:
        info = scores.get(sym, {})
        score = info.get('score', 0)
        entry = (
            csv_prices.get(sym)                         # 1. CSV buy price (most accurate)
            or positions.get(sym, {}).get('entry_price') # 2. State portfolio entry_price (carries)
            or float(info.get('close', 0))               # 3. State last_scores close (fallback)
        )
        now = db_close(sym)
        ed = entry_dates.get(sym, '?')
        if now and entry:
            pl = now - entry
            print(f"  {sym:8s}  ${entry:<6.2f}  ${now:<6.2f}  ${pl:>+8.2f}  {(pl/entry)*100:>+6.2f}%  {score:>4.1f}  {ed:>10s}")
        else:
            print(f"  {sym:8s}  ${entry:<6.2f}  {'N/A':>8s}  {'N/A':>9s}  {'N/A':>7s}  {score:>4.1f}  {ed:>10s}")


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


def _live_mtm(state_file):
    """Compute live MTM from state positions + db_close() prices."""
    path = os.path.join(os.path.dirname(MTF_DATA), state_file)
    try:
        state = json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    portfolio = state.get('portfolio', {})
    cash = portfolio.get('cash', 0)
    positions = portfolio.get('positions', {})
    mtm = cash
    for sym, pos in positions.items():
        close = db_close(sym)
        if close:
            mtm += pos['shares'] * close
    return mtm


def show_summary():
    configs = [
        ('MTF Stock (default)', '.mtf_state_stock.json', 100000),
        ('MTF Stock (min-score 5)', '.mtf_state_min5_stock.json', 100000),
        ('MTF ETF', '.mtf_state_etf.json', 100000),
    ]
    lines = []
    for label, state_file, cap in configs:
        mtm = _live_mtm(state_file)
        if mtm is not None:
            lines.append((label, cap, mtm))

    spy = db_close('SPY') or 748.23
    spy_ref = 749.66  # SPY on 7/13
    spy_ret = (spy - spy_ref) / spy_ref * 100

    print(f"\n{'=' * 72}")
    print(f"  PORTFOLIO SUMMARY")
    print(f"{'=' * 72}")
    print(f"  {'Strategy':30s} {'Capital':>9s} {'MTM':>10s} {'Return':>8s} {'vs SPY':>8s}")
    print(f"  {'─' * 67}")
    for label, cap, mtm in lines:
        ret = (mtm - cap) / cap * 100
        print(f"  {label:30s} ${cap:>7,} ${mtm:>8,.2f}  {ret:>+7.2f}%  {ret-spy_ret:>+7.2f}%")
    print(f"  {'SPY':30s} {'':>9s} {'':>10s}  {spy_ret:>+7.2f}%")


def main():
    show_mtf('MTF Stock (default)', '../mtf/.mtf_state_stock.json', 'mtf_portfolio_stock.csv', 100000)
    show_mtf('MTF Stock (min-score 5)', '../mtf/.mtf_state_min5_stock.json', 'mtf_portfolio_min5_stock.csv', 100000)
    show_mtf('MTF ETF', '../mtf/.mtf_state_etf.json', 'mtf_portfolio_etf.csv', 100000)
    show_daily()
    show_summary()


if __name__ == '__main__':
    main()
