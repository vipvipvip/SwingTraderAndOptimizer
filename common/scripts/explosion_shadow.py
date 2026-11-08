#!/usr/bin/env python3
"""Explosion shadow leg — paper-only forward test of the P_expl ranker.

NO ORDERS. This script:
  1. builds the weekly feature panel (same code as scan/backtest),
  2. calls `imminent_probability.select()` at the last settled week,
  3. records picks and hypothetical fills/exits in a JSON ledger,
  4. optionally posts a Slack summary.

Run weekly after the settled weekly bar is available (Monday after the close).
The selection path is identical to `--scan` and `--backtest`; only the
execution assumptions differ (entry at the next Monday's open, +30% target,
13-week time exit, no slippage/commissions).
"""
import argparse
import json
import os
from pathlib import Path
import urllib.request

import pandas as pd

import imminent_probability as ip

LEDGER = Path(__file__).resolve().parent / 'jerk' / 'shadow_ledger.json'
TARGET = 0.30
HORIZON_WEEKS = 13
STOP = 0.0


def load_ledger():
    if LEDGER.exists():
        with open(LEDGER) as fh:
            return json.load(fh)
    return {'updated_at': None, 'runs': {}, 'positions': []}


def save_ledger(ledger):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix('.json.tmp')
    with open(tmp, 'w') as fh:
        json.dump(ledger, fh, indent=2, sort_keys=True)
    tmp.replace(LEDGER)


def daily_bars(symbol, start, end):
    conn = ip.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.date, d.open, d.high, d.low, d.close
            FROM tbl_prices_daily d
            JOIN tbl_stock_tickers s ON s.id = d.ticker_id
            WHERE s.symbol = %s AND d.date >= %s AND d.date <= %s
            ORDER BY d.date
        """, (symbol.upper(), start, end))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close'])
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['date'])
    for c in ['open', 'high', 'low', 'close']:
        df[c] = df[c].astype(float)
    return df


def add_picks(ledger, picks, asof):
    asof_s = str(pd.Timestamp(asof).date())
    if asof_s in ledger['runs']:
        return []
    existing = {p['symbol'] for p in ledger['positions']
                if p['status'] != 'closed'}
    added = []
    for _, r in picks.iterrows():
        if r['symbol'] in existing:
            continue
        ledger['positions'].append({
            'symbol': r['symbol'],
            'signal_date': asof_s,
            'entry_date': str((pd.Timestamp(asof) + pd.Timedelta(days=7)).date()),
            'entry_px': None,
            'status': 'pending',
            'p_expl': float(r['p_expl']),
            'target': TARGET,
            'horizon_weeks': HORIZON_WEEKS,
            'stop': STOP,
            'target_px': None,
            'stop_px': None,
            'exit_date': None,
            'exit_px': None,
            'ret': None,
            'reason': None,
            'last_close': None,
            'last_date': None,
        })
        added.append(r['symbol'])
    ledger['runs'][asof_s] = [r['symbol'] for _, r in picks.iterrows()]
    return added


def update_positions(ledger, today):
    today = pd.Timestamp(today).normalize()
    events = []
    for p in ledger['positions']:
        if p['status'] == 'closed':
            continue
        bars = daily_bars(p['symbol'], pd.Timestamp(p['entry_date']), today)
        if bars.empty:
            continue
        if p['status'] == 'pending':
            b = bars.iloc[0]
            p['entry_date'] = str(b['date'].date())
            p['entry_px'] = float(b['open'])
            p['target_px'] = round(p['entry_px'] * (1 + p['target']), 4)
            if p['stop']:
                p['stop_px'] = round(p['entry_px'] * (1 - p['stop']), 4)
            p['status'] = 'open'
            events.append(('fill', p['symbol'], p['entry_px'], p['entry_date']))
        if p['status'] != 'open':
            continue
        for _, b in bars.iterrows():
            if b['date'] <= pd.Timestamp(p['entry_date']):
                continue
            p['last_close'] = float(b['close'])
            p['last_date'] = str(b['date'].date())
            if p['stop_px'] and b['low'] <= p['stop_px']:
                p['exit_date'] = str(b['date'].date())
                p['exit_px'] = float(min(p['stop_px'], b['open']))
                p['reason'] = 'stop'
            elif b['high'] >= p['target_px']:
                p['exit_date'] = str(b['date'].date())
                p['exit_px'] = float(max(p['target_px'], b['open']))
                p['reason'] = 'target'
            elif (b['date'] - pd.Timestamp(p['entry_date'])).days >= p['horizon_weeks'] * 7:
                p['exit_date'] = str(b['date'].date())
                p['exit_px'] = float(b['close'])
                p['reason'] = 'time'
            if p['reason']:
                p['ret'] = p['exit_px'] / p['entry_px'] - 1.0
                p['status'] = 'closed'
                events.append(('exit', p['symbol'], p['exit_px'],
                               p['exit_date'], p['reason'], p['ret']))
                break
    return events


def summary(ledger, asof, added, events, picks, regime=None):
    blocked = regime is not None and not regime['ok']
    head = 'blocked by regime' if blocked else f"{len(added)} new, {len(picks)} picks"
    lines = [f"asof {pd.Timestamp(asof).date()} | {head}"]
    if regime is not None:
        lines.append(f"regime: daily={'ON' if regime['daily'] else 'OFF'} "
                     f"weekly={'ON' if regime['weekly'] else 'OFF'} -> "
                     f"{'ALLOW' if regime['ok'] else 'BLOCK new entries'}")
    if not blocked:
        if added:
            lines.append('NEW: ' + ' '.join(added))
        elif len(picks):
            lines.append('PICKS: ' + ' '.join(picks['symbol'].tolist()))
    fills = [e for e in events if e[0] == 'fill']
    exits = [e for e in events if e[0] == 'exit']
    if fills:
        lines.append('ENTRY(paper): ' + ' '.join(
            f"{s}@{px:.2f}({d})" for _, s, px, d in fills))
    if exits:
        lines.append('EXITS: ' + ' '.join(
            f"{s}@{px:.2f} {why} {ret * 100:+.1f}%"
            for _, s, px, d, why, ret in exits))
    openp = [p for p in ledger['positions'] if p['status'] == 'open']
    if openp:
        bits = []
        for p in openp:
            last = p['last_close'] or p['entry_px']
            bits.append(f"{p['symbol']} {(last / p['entry_px'] - 1) * 100:+.1f}%")
        lines.append(f"OPEN({len(openp)}): " + ' '.join(bits))
    closed = [p for p in ledger['positions'] if p['status'] == 'closed']
    if closed:
        hit = sum(1 for p in closed if p['ret'] >= TARGET) / len(closed)
        avg = sum(p['ret'] for p in closed) / len(closed)
        lines.append(f"CLOSED({len(closed)}): hit={hit:.0%} avg={avg * 100:+.1f}%")
    return '\n'.join(lines)


def send_slack(msg):
    url = os.getenv('SLACK_WEBHOOK_URL')
    if not url:
        env = Path(__file__).resolve().parents[2] / 'swingtrader/services/mtf/.env'
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith('SLACK_WEBHOOK_URL='):
                    url = line.split('=', 1)[1].strip().strip('"').strip("'")
    if not url:
        print('[slack] no webhook configured')
        return
    body = json.dumps({'text': f'[EXPL-SHADOW] {msg}'}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as exc:
        print(f'[slack] error: {exc}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asof', help='settle-as-of date (default: today)')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--min-dvol', type=float, default=50e6,
                    help='min trailing 13w dollar volume in $/week')
    ap.add_argument('--no-slack', action='store_true')
    ap.add_argument('--no-regime', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    panel = ip.feature_panel()
    asof = ip.last_settled(panel, today=args.asof)
    if asof is None:
        raise SystemExit('no settled weekly bar')
    bundle = ip.load_model()
    picks = ip.select(panel, asof, bundle=bundle, top_n=args.top,
                      min_dvol=args.min_dvol)
    reg = None if args.no_regime else ip.regime_at(ip.regime_series(), asof)

    ledger = load_ledger()
    added = add_picks(ledger, picks, asof) if (reg is None or reg['ok']) else []
    events = update_positions(ledger, today=pd.Timestamp.today())
    ledger['updated_at'] = pd.Timestamp.now().isoformat()
    msg = summary(ledger, asof, added, events, picks, reg)

    print(msg)
    if args.dry_run:
        print(f'[dry-run] ledger not saved ({len(ledger["positions"])} positions)')
        return
    save_ledger(ledger)
    if not args.no_slack:
        send_slack(msg)


if __name__ == '__main__':
    main()
