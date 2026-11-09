#!/usr/bin/env python3
"""Explosion shadow leg — paper-only forward test of the P_expl ranker.

NO ORDERS. This script:
  1. builds the weekly feature panel (same code as scan/backtest),
  2. calls `imminent_probability.select()` at the last settled week,
  3. records picks and hypothetical fills/exits in a JSON ledger,
  4. posts a Slack signal-state snapshot plus the three signal variations.

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

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tbl_explosion_signal_state (
    run_date DATE NOT NULL,
    ticker_id BIGINT NOT NULL REFERENCES tbl_stock_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    weekly_on BOOLEAN NOT NULL,
    daily_on BOOLEAN NOT NULL,
    weekly_date DATE,
    daily_date DATE,
    weekly_state VARCHAR(8),
    daily_state VARCHAR(8),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_date, ticker_id)
);
CREATE INDEX IF NOT EXISTS idx_expl_state_run
    ON tbl_explosion_signal_state(run_date);
"""


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


def _env_value(key, default=None):
    val = os.getenv(key)
    if not val:
        env = Path(__file__).resolve().parents[2] / 'swingtrader/services/mtf/.env'
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + '='):
                    val = line.split('=', 1)[1].strip().strip('"').strip("'")
    return val or default


def _webhook_url():
    return _env_value('SLACK_WEBHOOK_URL')


def send_slack(msg, limit=3500):
    """Post to Slack, chunking at `limit` chars per webhook call."""
    url = _webhook_url()
    if not url:
        print('[slack] no webhook configured')
        return
    chunks, cur = [], ''
    for line in msg.split('\n'):
        while len(line) > limit:
            cut = line.rfind(' ', 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(line[:cut])
            line = line[cut:].lstrip()
        if cur and len(cur) + 1 + len(line) > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = line if not cur else cur + '\n' + line
    if cur:
        chunks.append(cur)
    for ch in chunks:
        body = json.dumps({'text': f'[EXPL-SHADOW] {ch}'}).encode()
        req = urllib.request.Request(
            url, data=body, headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception as exc:
            print(f'[slack] error: {exc}')


def ensure_state_table():
    conn = ip.connect()
    try:
        cur = conn.cursor()
        cur.execute(STATE_SCHEMA)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def ticker_id_map():
    conn = ip.connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, symbol FROM tbl_stock_tickers WHERE enabled")
        return {sym: tid for tid, sym in cur.fetchall()}
    finally:
        conn.close()


def build_states(panel, asof, daily_asof, min_dvol):
    """Weekly + daily ON/OFF for the liquid universe at `asof`."""
    wk = ip.weekly_signal_states(panel, asof)
    wk = wk[wk['dvol13'].fillna(0) >= min_dvol]
    dy = ip.daily_signal_states(asof=daily_asof)
    cur = wk.rename(columns={'date': 'weekly_date', 'state': 'weekly_state',
                             'on': 'weekly_on'})[
        ['symbol', 'weekly_date', 'weekly_state', 'weekly_on']]
    cur = cur.merge(
        dy.rename(columns={'date': 'daily_date', 'state': 'daily_state',
                           'on': 'daily_on'})[
            ['symbol', 'daily_date', 'daily_state', 'daily_on']],
        on='symbol', how='left')
    cur['daily_on'] = cur['daily_on'].fillna(False).astype(bool)
    return cur.reset_index(drop=True)


def previous_states(run_date):
    conn = ip.connect()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, weekly_on, daily_on
            FROM tbl_explosion_signal_state
            WHERE run_date = (
                SELECT max(run_date) FROM tbl_explosion_signal_state
                WHERE run_date < %s)
        """, (pd.Timestamp(run_date).date(),))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=['symbol', 'weekly_on', 'daily_on'])


def store_states(run_date, states, ids):
    from psycopg2.extras import execute_values
    rows = []
    for _, r in states.iterrows():
        tid = ids.get(r['symbol'])
        if tid is None:
            continue
        wd, dd = r['weekly_date'], r['daily_date']
        rows.append((
            pd.Timestamp(run_date).date(), int(tid), r['symbol'],
            bool(r['weekly_on']), bool(r['daily_on']),
            None if pd.isna(wd) else pd.Timestamp(wd).date(),
            None if pd.isna(dd) else pd.Timestamp(dd).date(),
            r.get('weekly_state'), r.get('daily_state'),
        ))
    if not rows:
        return 0
    conn = ip.connect()
    try:
        cur = conn.cursor()
        execute_values(cur, """
            INSERT INTO tbl_explosion_signal_state
                (run_date, ticker_id, symbol, weekly_on, daily_on,
                 weekly_date, daily_date, weekly_state, daily_state)
            VALUES %s
            ON CONFLICT (run_date, ticker_id) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                weekly_on = EXCLUDED.weekly_on,
                daily_on = EXCLUDED.daily_on,
                weekly_date = EXCLUDED.weekly_date,
                daily_date = EXCLUDED.daily_date,
                weekly_state = EXCLUDED.weekly_state,
                daily_state = EXCLUDED.daily_state
        """, rows)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return len(rows)


def state_message(asof, states, prev, regime=None):
    def names(mask):
        return sorted(states.loc[mask, 'symbol'].tolist())

    w_on = names(states['weekly_on'])
    d_on = names(states['daily_on'])
    both = names(states['weekly_on'] & states['daily_on'])
    lines = [f"asof {pd.Timestamp(asof).date()} | "
             f"weekly ON {len(w_on)} | daily ON {len(d_on)} | "
             f"both ON {len(both)}"]
    if regime is not None:
        lines.append(f"regime: daily={'ON' if regime['daily'] else 'OFF'} "
                     f"weekly={'ON' if regime['weekly'] else 'OFF'}")
    lines.append(f"WEEKLY ON({len(w_on)}): " + (', '.join(w_on) or '-'))
    lines.append(f"DAILY ON({len(d_on)}): " + (', '.join(d_on) or '-'))
    lines.append(f"BOTH ON({len(both)}): " + (', '.join(both) or '-'))
    if prev is None or prev.empty:
        lines.append("OFF: first run (no prior snapshot)")
        return '\n'.join(lines)
    m = states[['symbol', 'weekly_on', 'daily_on']].merge(
        prev, on='symbol', how='outer', suffixes=('', '_prev'))
    for c in ['weekly_on', 'daily_on', 'weekly_on_prev', 'daily_on_prev']:
        if c not in m.columns:
            m[c] = False
        m[c] = m[c].fillna(False).astype(bool)
    w_off = sorted(m.loc[m['weekly_on_prev'] & ~m['weekly_on'], 'symbol'])
    d_off = sorted(m.loc[m['daily_on_prev'] & ~m['daily_on'], 'symbol'])
    lines.append(f"WEEKLY OFF({len(w_off)}): " + (', '.join(w_off) or '-'))
    lines.append(f"DAILY OFF({len(d_off)}): " + (', '.join(d_off) or '-'))
    return '\n'.join(lines)


def variations_message(asof, states, regime=None):
    """Signal variations, comma-delimited, for Slack."""
    def lst(mask):
        return ', '.join(sorted(states.loc[mask, 'symbol'].tolist())) or '-'

    w_fire = states['weekly_state'] == 'FIRE'
    d_fire = states['daily_state'] == 'FIRE'
    both = states['weekly_on'] & states['daily_on']
    wd = pd.to_datetime(states['weekly_date']).max()
    dd = pd.to_datetime(states['daily_date']).max()

    head = [f"asof {pd.Timestamp(asof).date()} | universe {len(states)}",
            f"weekly bar {wd.date() if pd.notna(wd) else '-'} | "
            f"daily bar {dd.date() if pd.notna(dd) else '-'}"]
    if regime is not None:
        head.append(f"regime: daily={'ON' if regime['daily'] else 'OFF'} "
                    f"weekly={'ON' if regime['weekly'] else 'OFF'}")
    blocks = [
        (f"FIRE ONLY - weekly ({int(w_fire.sum())})", lst(w_fire)),
        (f"FIRE ONLY - daily ({int(d_fire.sum())})", lst(d_fire)),
        (f"WEEKLY AND DAILY ON ({int(both.sum())})", lst(both)),
    ]
    out = head + ['']
    for title, body in blocks:
        out += [title, body, '']
    return '\n'.join(out).rstrip() + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asof', help='settle-as-of date (default: today)')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--min-dvol', type=float, default=50e6,
                    help='min trailing 13w dollar volume in $/week')
    ap.add_argument('--no-slack', action='store_true')
    ap.add_argument('--print-variations', action='store_true',
                    help='print the variations block to stdout')
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

    states = build_states(panel, asof, args.asof, args.min_dvol)
    prev = None
    stored = 0
    if not args.dry_run:
        ensure_state_table()
        prev = previous_states(asof)
        stored = store_states(asof, states, ticker_id_map())
    msg_states = state_message(asof, states, prev, reg)
    msg_variations = variations_message(asof, states, reg)

    ledger = load_ledger()
    added = add_picks(ledger, picks, asof) if (reg is None or reg['ok']) else []
    events = update_positions(ledger, today=pd.Timestamp.today())
    ledger['updated_at'] = pd.Timestamp.now().isoformat()
    msg_ledger = summary(ledger, asof, added, events, picks, reg)

    print(msg_states)
    print(msg_ledger)
    if args.print_variations:
        print('[variations]')
        print(msg_variations)
    if args.dry_run:
        print(f'[dry-run] state/ledger not saved '
              f'({len(states)} states, {len(ledger["positions"])} positions)')
        return
    save_ledger(ledger)
    print(f'[state] stored {stored} rows for run_date {pd.Timestamp(asof).date()}')
    if not args.no_slack:
        send_slack(msg_states + '\n\n' + msg_variations)


if __name__ == '__main__':
    main()
