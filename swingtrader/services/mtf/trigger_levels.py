"""Trigger levels — next buy/sell price per ticker for CoreEW P20w.

Spec: common/docs/SPEC_trigger_levels.md. Read-only Slack report, NO orders, NO state writes.

CoreEW P20w (QQQ/VTI/VTV): the flip price is the last settled weekly EMA(20), read from the
PHP series (PHP-canonical — the signal is never re-implemented here).

Run with the MTF scorer venv from this directory; `--dry-run` prints instead of posting.
"""
import argparse
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import executor
import runner
from backtest_trio_ew import fetch_live_leg_ema_series

NY = ZoneInfo('America/New_York')
COREEW_SPAN = 20
COREEW_SYMBOLS = ['QQQ', 'VTI', 'VTV']

EXPLAINER = (
    'Each ticker has ONE flip price: out of the position it is the BUY trigger,\n'
    'in the position it is the SELL trigger. Only the Friday weekly CLOSE counts\n'
    '(acts the following Monday); touching it mid-week does nothing.\n'
    'CoreEW: weekly close vs its EMA20.'
)


# ---------------------------------------------------------------- report rows
def coreew_rows(live, settled):
    payload = fetch_live_leg_ema_series(COREEW_SPAN, COREEW_SYMBOLS)
    rows = []
    for sym in COREEW_SYMBOLS:
        last = payload['series'][sym][-1]
        is_long = bool(payload['state'][sym])
        trig = round(last['ema'], 2) if payload.get('warm') and last['week'] == payload['last_week'] else None
        rows.append(dict(sym=sym, long=is_long, live=live.get(sym), settled=settled.get(sym), trig=trig,
                         side='SELL <' if is_long else 'BUY  >', basis=f'EMA{COREEW_SPAN}'))
    return datetime.strptime(payload['last_week'], '%Y-%m-%d').date(), rows


# ---------------------------------------------------------------- formatting
def _px(v):
    return f'{v:,.2f}' if v is not None else 'n/a'


def _dist(trig, live):
    if trig is None or not live:
        return 'n/a'
    return f'{(trig - live) / live * 100:+.1f}%'


def table(headers, rows, right):
    """Header + dashed rule + rows, columns padded to their widest cell; `right` = right-aligned indexes."""
    cols = [headers] + rows
    w = [max(len(r[i]) for r in cols) for i in range(len(headers))]
    cell = lambda r: '  '.join(r[i].rjust(w[i]) if i in right else r[i].ljust(w[i]) for i in range(len(r))).rstrip()
    return [cell(headers), '  '.join('-' * x for x in w)] + [cell(r) for r in rows]


def trig_cell(r):
    return f"{r['side']} {_px(r['trig'])}" if r['trig'] is not None else 'n/a'


def build_message(now, week, core, explainer, next_decision):
    h = ['Ticker', 'State', 'Live', 'Settled', 'Trigger', 'Dist', 'Basis']
    core_t = table(h, [[r['sym'], 'LONG' if r['long'] else 'CASH', _px(r['live']), _px(r['settled']),
                        trig_cell(r), _dist(r['trig'], r['live']), r['basis']] for r in core], {2, 3, 5})
    blk = lambda lines: '```\n' + '\n'.join(lines) + '\n```'
    parts = [f"*Triggers — {now:%H:%M} ET · {now:%Y-%m-%d} · settled week {week}*"]
    if explainer:
        parts.append('_How to read_\n' + blk(EXPLAINER.splitlines()))
    parts += ['*CoreEW P20w*\n' + blk(core_t), next_decision]
    return '\n'.join(parts)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--no-explainer', action='store_true', help='omit the HOW TO READ block')
    ap.add_argument('--dry-run', action='store_true', help='print the message, do not post to Slack')
    args = ap.parse_args(argv)
    now = datetime.now(NY)
    conn = None
    try:
        conn = runner._get_db_conn()
        executor._set_alpaca_keys('etf')
        live = {s: executor._latest_trade_price(s) for s in COREEW_SYMBOLS}
        settled = executor.latest_settled_daily_closes(conn, COREEW_SYMBOLS)
        week, core = coreew_rows(live, settled)
        decide = week + timedelta(days=7 + 4)
        foot = f'Decides Fri {decide} close · acts Mon {decide + timedelta(days=3)}'
        msg = build_message(now, week, core, not args.no_explainer, foot)
    except Exception:
        if not args.dry_run:
            runner._send_crash_alert(sys.exc_info(), 'etf')
        raise
    finally:
        if conn:
            conn.close()
    print(msg)
    print(f'[TRIGGERS] message chars={len(msg)}')
    if not args.dry_run:
        runner._send_slack(msg, 'etf')
        print('[TRIGGERS] posted')


if __name__ == '__main__':
    main()
