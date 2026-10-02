#!/usr/bin/env python3
"""alpaca_report.py — read-only per-strategy Alpaca trading/positions report.

Pulls each strategy's Alpaca paper account directly from the API (authoritative
order + position history) and prints a strategy snapshot (one column per
strategy, inception → today vs SPY buy-and-hold from the same inception date)
followed by per-strategy detail since inception:

  - Snapshot: inception date, initial amount, current equity, $ gain, % gain,
    SPY B&H over the same window, and the % difference
  - Account: number, status, equity, cash, buying power, portfolio value
  - Activity: first/last fill, buy/sell counts, total turnover
  - Current positions: qty, avg entry, mark, market value, unrealized PnL
  - Closed trades: per-symbol realized PnL (average-cost method), win rate
  - Totals: realized + unrealized + overall PnL since inception

Strategies and their accounts:
  mtf-stock  MTF Top-N stocks  #PA368CPXNS13  (keys: swingtrader/services/mtf/.env)
  mtf-etf    EMA/SMA ETF leg   #PA3U8GZ96PEN  (keys: swingtrader/services/mtf/.env)
  coreew    CoreEW trio        #PA3GKZYLVO68  (keys: swingtrader/backend/.env)

Never places orders and never writes state. Only reads Alpaca + the DB.

Usage:
  python3 alpaca_report.py                # all strategies
  python3 alpaca_report.py --strategy mtf-stock mtf-etf coreew
  python3 alpaca_report.py --snapshot     # snapshot table only
  python3 alpaca_report.py --live-spy     # benchmark through today's partial close
  python3 alpaca_report.py --json         # machine-readable (--snapshot = snapshot JSON)
  python3 alpaca_report.py --open-only    # skip closed-trade detail, positions only
"""

import argparse
import json
import os
import sys
import textwrap
import time
from datetime import datetime

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
MTF_DIR = os.path.join(BASE, '..', 'mtf')
BACKEND_DIR = os.path.join(BASE, '..', '..', 'backend')
PAPER_URL = 'https://paper-api.alpaca.markets'

STRATEGIES = {
    'mtf-stock': {'name': 'TOP stocks', 'acct': 'PA368CPXNS13',
                  'env': os.path.join(MTF_DIR, '.env'),
                  'keys': ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY'),
                  'initial_capital': 100000.0},
    'mtf-etf': {'name': 'TOP ETFs', 'acct': 'PA3U8GZ96PEN',
                'env': os.path.join(MTF_DIR, '.env'),
                'keys': ('ALPACA_ETF_API_KEY', 'ALPACA_ETF_SECRET_KEY'),
                'initial_capital': 100000.0},
    'coreew': {'name': 'CORE ETF', 'acct': 'PA3GKZYLVO68',
              'env': os.path.join(BACKEND_DIR, '.env'),
              'keys': ('ALPACA_API_KEY', 'ALPACA_SECRET_KEY'),
              'initial_capital': 100000.0},
}


def _read_env(path):
    """Parse a KEY=VALUE .env file into a dict (quoted values stripped)."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _get(url, headers, params=None):
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    if resp.status_code >= 400:
        raise RuntimeError(f'Alpaca {url} failed ({resp.status_code}): {resp.text}')
    return resp.json()


def _fetch_all_fills(headers):
    """Paginate the full filled-order history in ascending order (since inception)."""
    fills = []
    after = None
    while True:
        params = {'status': 'filled', 'direction': 'asc', 'limit': 500}
        if after:
            params['after'] = after
        page = _get(f'{PAPER_URL}/v2/orders', headers, params)
        if not page:
            break
        fills.extend(page)
        if len(page) < 500:
            break
        after = page[-1]['updated_at']
        if after:
            try:
                after = (datetime.fromisoformat(after.replace('Z', '+00:00')) - time_tick()).isoformat()
            except Exception:
                break
    return fills


def time_tick():
    from datetime import timedelta
    return timedelta(seconds=2)


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def _spy_closes(start, end, headers=None):
    """SPY daily closes over [start, end] ascending — [{'t': date, 'c': close}].

    Uses the Alpaca data API when headers are available, otherwise falls back
    to the scanner DB daily table (same fallback chain as every other read here).
    """
    bars = []
    if headers:
        try:
            data = _get('https://data.alpaca.markets/v2/stocks/bars', headers,
                        params={'symbols': 'SPY', 'timeframe': '1Day',
                                'adjustment': 'split', 'start': start,
                                'end': end, 'limit': 10000})
            bars = [{'t': str(b['t'])[:10], 'c': float(b['c'])}
                    for b in data.get('bars', {}).get('SPY') or []]
        except Exception:
            bars = []
    if not bars:
        try:
            sys.path.insert(0, MTF_DIR)
            import db as db_module
            conn = db_module.get_conn()
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT date, close FROM tbl_scanner_tickers_daily '
                    'WHERE ticker_id = (SELECT id FROM tbl_stock_tickers '
                    "WHERE symbol = 'SPY') AND date >= %s AND date <= %s "
                    'ORDER BY date ASC', (start, end))
                bars = [{'t': str(r[0])[:10], 'c': float(r[1])} for r in cur.fetchall()]
            conn.close()
        except Exception:
            bars = []
    return bars


def _spy_window(closes, inception, end_date=None):
    """SPY buy-and-hold over [inception, end_date] from an ascending close list.

    Entry is the first close on/after inception (you cannot buy before the
    account existed), exit the last close on/before end_date. None if the window
    has fewer than two bars.
    """
    win = [b for b in closes if b['t'] >= inception]
    if end_date:
        win = [b for b in win if b['t'] <= end_date]
    if len(win) < 2:
        return None
    s, e = float(win[0]['c']), float(win[-1]['c'])
    if s <= 0:
        return None
    return {'start': win[0]['t'], 'end': win[-1]['t'], 'start_close': s,
            'end_close': e, 'pct': (e - s) / s * 100}


def _spy_return(start, end, headers=None):
    """SPY buy-and-hold return (%) over the report window [start, end] (inclusive).

    Returns a dict with start/end closes and the return %, or None if the window
    can't be resolved.
    """
    return _spy_window(_spy_closes(start, end, headers), start, end)


def _build_snapshot(reports, headers=None, live_spy=False):
    """Strategy-vs-SPY snapshot: one column per strategy, inception → as-of.

    Inception is the date of the first filled trade. Initial is the strategy's
    declared starting capital, current is Alpaca account equity. The benchmark is
    SPY buy-and-hold over each strategy's own inception date, priced on the last
    settled close (`--live-spy` extends it through today's partial close).
    """
    today = datetime.now().date().isoformat()
    cols = []
    for r in reports:
        c = {'strategy': r.get('strategy'), 'account': r.get('account'),
             'error': r.get('error'), 'initial': r.get('initial_capital'),
             'inception': (r.get('first_fill') or '')[:10] or None,
             'current': r.get('equity'), 'gain': None, 'gain_pct': None,
             'spy': None, 'vs_spy_pts': None}
        if c['current'] is not None and c['initial']:
            c['gain'] = c['current'] - c['initial']
            c['gain_pct'] = c['gain'] / c['initial'] * 100
        cols.append(c)

    inceptions = sorted(c['inception'] for c in cols if c['inception'])
    if inceptions:
        closes = _spy_closes(inceptions[0], today, headers)
        if not live_spy:
            closes = [b for b in closes if b['t'] < today]
        for c in cols:
            if not c['inception']:
                continue
            win = _spy_window(closes, c['inception'])
            if not win:
                continue
            win['gain'] = (c['initial'] or 0.0) * win['pct'] / 100.0
            c['spy'] = win
            if c['gain_pct'] is not None:
                c['vs_spy_pts'] = c['gain_pct'] - win['pct']

    as_of = max((c['spy']['end'] for c in cols if c['spy']), default=None)
    return {'as_of': as_of, 'benchmark': 'SPY', 'live_spy': live_spy,
            'today': today, 'strategies': cols}


def _avg_cost_realized(fills):
    """Average-cost realized PnL per symbol from a fill list.

    Returns (per_symbol, realized_total):
      per_symbol[symbol] = {'buys': n, 'sells': n, 'qty_bought', 'qty_sold',
                            'realized': float, 'open_qty', 'open_cost'}
    """
    book = {}
    for o in fills:
        side = o.get('side')
        symbol = o.get('symbol')
        qty = float(o.get('filled_qty') or 0)
        price = float(o.get('filled_avg_price') or 0)
        if qty <= 0 or price <= 0 or side not in ('buy', 'sell'):
            continue
        b = book.setdefault(symbol, {
            'buys': 0, 'sells': 0, 'qty_bought': 0.0, 'qty_sold': 0.0,
            'realized': 0.0, 'open_qty': 0.0, 'open_cost': 0.0})
        if side == 'buy':
            b['buys'] += 1
            b['qty_bought'] += qty
            b['open_qty'] += qty
            b['open_cost'] += price * qty
        else:
            b['sells'] += 1
            b['qty_sold'] += qty
            if b['open_qty'] > 0:
                avg = b['open_cost'] / b['open_qty']
                close_qty = min(qty, b['open_qty'])
                b['realized'] += (price - avg) * close_qty
                b['open_cost'] -= avg * close_qty
                b['open_qty'] -= close_qty
            else:
                # Short / data anomaly — book the full notional as realized.
                b['realized'] += price * qty
        if b['open_qty'] <= 1e-9:
            b['open_qty'] = 0.0
            b['open_cost'] = 0.0
    realized_total = sum(b['realized'] for b in book.values())
    return book, realized_total


def _headers_for(tag):
    """Alpaca auth headers for a strategy's account, or None if keys are missing."""
    env = _read_env(tag['env'])
    api_key = env.get(tag['keys'][0])
    api_secret = env.get(tag['keys'][1])
    if not api_key or not api_secret:
        return None
    return {'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': api_secret}


def _alpaca_account_report(tag):
    headers = _headers_for(tag)
    if not headers:
        return {'strategy': tag['name'], 'account': tag['acct'],
                'error': 'API keys not found in env file',
                'initial_capital': tag.get('initial_capital'), 'equity': None}

    try:
        account = _get(f'{PAPER_URL}/v2/account', headers)
        positions = _get(f'{PAPER_URL}/v2/positions', headers)
        fills = _fetch_all_fills(headers)
    except Exception as e:
        return {'strategy': tag['name'], 'account': tag['acct'],
                'error': f'API error: {e}',
                'initial_capital': tag.get('initial_capital'), 'equity': None}

    book, realized_total = _avg_cost_realized(fills)

    pos_rows = []
    unrealized_total = 0.0
    for p in sorted(positions, key=lambda x: x.get('symbol', '')):
        qty = float(p.get('qty') or 0)
        if abs(qty) < 1e-9:
            continue
        mv = float(p.get('market_value') or 0)
        up = float(p.get('unrealized_pl') or 0)
        unrealized_total += up
        pos_rows.append({
            'symbol': p.get('symbol'),
            'qty': qty,
            'avg_entry': float(p.get('avg_entry_price') or 0),
            'mark': float(p.get('current_price') or 0),
            'market_value': mv,
            'unrealized_pl': up,
            'unrealized_pct': float(p.get('unrealized_plpc') or 0) * 100,
        })

    buy_count = sum(1 for o in fills if o.get('side') == 'buy')
    sell_count = sum(1 for o in fills if o.get('side') == 'sell')
    spent = sum(float(o.get('filled_qty') or 0) * float(o.get('filled_avg_price') or 0)
                for o in fills if o.get('side') == 'buy')
    proceeds = sum(float(o.get('filled_qty') or 0) * float(o.get('filled_avg_price') or 0)
                   for o in fills if o.get('side') == 'sell')

    first_fill = min((_parse_ts(o.get('filled_at')) for o in fills if o.get('filled_at')),
                     default=None)
    last_fill = max((_parse_ts(o.get('filled_at')) for o in fills if o.get('filled_at')),
                    default=None)

    spy = None
    if first_fill and last_fill:
        spy = _spy_return(first_fill.date().isoformat(), last_fill.date().isoformat(),
                          headers)

    closed = []
    winners = 0
    for sym in sorted(book):
        b = book[sym]
        if b['sells'] > 0:
            if b['realized'] > 0:
                winners += 1
            closed.append({'symbol': sym, **b})

    report = {
        'strategy': tag['name'],
        'account': account.get('account_number', tag['acct']),
        'status': account.get('status'),
        'equity': float(account.get('equity') or 0),
        'cash': float(account.get('cash') or 0),
        'buying_power': float(account.get('buying_power') or 0),
        'portfolio_value': float(account.get('portfolio_value') or 0),
        'first_fill': first_fill.isoformat() if first_fill else None,
        'last_fill': last_fill.isoformat() if last_fill else None,
        'fills': len(fills),
        'buys': buy_count,
        'sells': sell_count,
        'turnover_spent': spent,
        'turnover_proceeds': proceeds,
        'realized_pnl': realized_total,
        'unrealized_pnl': unrealized_total,
        'total_pnl': realized_total + unrealized_total,
        'initial_capital': tag.get('initial_capital'),
        'portfolio_return_pct': ((realized_total + unrealized_total)
                                 / tag.get('initial_capital', 1.0) * 100),
        'spy': spy,
        'positions': pos_rows,
        'closed': closed,
        'closed_win_rate': (winners / len(closed) * 100) if closed else None,
    }
    return report


def _fmt_money(v):
    return f'${v:,.2f}'


def _fmt_signed_money(v):
    return ('+' if v >= 0 else '-') + _fmt_money(abs(v))


def _title_box(text):
    """Boxed section title (border sized to the text)."""
    return '\n'.join(['┌' + '─' * (len(text) + 2) + '┐',
                      '│' + f' {text} ' + '│',
                      '└' + '─' * (len(text) + 2) + '┘'])


def _cell(value, fmt, empty='—'):
    return empty if value is None else fmt(value)


def _fmt_snapshot(snap):
    """Strategy × SPY-B&H snapshot table (one column per strategy) + footnotes."""
    cols = snap['strategies']
    as_of = (f'{snap["today"]} (live, partial close)' if snap['live_spy']
             else snap['as_of'] or 'no data')
    lines = [_title_box(f'Strategy snapshot — each strategy vs SPY B&H '
                        f'(as of {as_of})')]

    rows = [
        ['Inception'] + [_cell(c['inception'], str) for c in cols],
        ['Initial'] + [_cell(c['initial'], _fmt_money) for c in cols],
        ['Current'] + [_cell(c['current'], _fmt_money) for c in cols],
        ['$ Gain'] + [_cell(c['gain'], _fmt_signed_money) for c in cols],
        ['% Gain'] + [_cell(c['gain_pct'], lambda v: f'{v:+.2f}%') for c in cols],
        ['SPY B&H $'] + [_cell(c['spy'] and c['spy']['gain'], lambda v: f'{v:+,.0f}')
                         for c in cols],
        ['SPY B&H %'] + [_cell(c['spy'] and c['spy']['pct'], lambda v: f'{v:+.2f}%')
                         for c in cols],
        ['vs SPY'] + [_cell(c['vs_spy_pts'], lambda v: f'{v:+.2f} pts') for c in cols],
    ]
    lines.extend(_table(['Metric'] + [c['strategy'] for c in cols], rows,
                        aligns=['<'] + ['>'] * len(cols)))

    bench = ('today\'s partial close' if snap['live_spy']
             else f'last settled close {snap["as_of"] or "unavailable"}')
    notes = [
        'Inception = date of the first filled trade. Current = Alpaca account '
        'equity (cash + positions).',
        'Initial = declared starting capital; a cash transfer into an account '
        'would skew its return.',
        f'SPY B&H = split-adjusted close on that strategy\'s inception date → '
        f'{bench}; dividends excluded.',
        'vs SPY = strategy % gain − SPY % gain, in percentage points (over '
        'different inception windows — not a like-for-like period).',
    ]
    notes += [f"{c['strategy']}: unavailable — {c['error']}"
              for c in cols if c.get('error')]
    for note in notes:
        lines.extend(textwrap.wrap(note, width=78,
                                   subsequent_indent='  '))
    return '\n'.join(lines)


def _table(headers, rows, aligns=None):
    """Render a bordered table (box-drawing). Returns a list of lines."""
    aligns = aligns or ['<'] * len(headers)
    widths = [len(h) for h in headers]
    data = [[str(c) if c is not None else '' for c in r] for r in rows]
    for r in data:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))

    def hline(l, m, r):
        return f'{l}{m.join("─" * (w + 2) for w in widths)}{r}'

    lines = []
    lines.append(hline('┌', '┬', '┐'))
    head = []
    for i, h in enumerate(headers):
        head.append(f'{" " + h + " ":{aligns[i]}{widths[i] + 2}}')
    lines.append('│' + '│'.join(head) + '│')
    lines.append(hline('├', '┼', '┤'))
    for r in data:
        row = []
        for i, c in enumerate(r):
            row.append(f'{" " + c + " ":{aligns[i]}{widths[i] + 2}}')
        lines.append('│' + '│'.join(row) + '│')
    lines.append(hline('└', '┴', '┘'))
    return lines


def _fmt_report(r):
    lines = []
    if 'error' in r:
        lines.append(f"== {r['strategy']} ({r.get('account', '?')}) — {r['error']} ==")
        return '\n'.join(lines)

    title = f" {r['strategy']} ({r['account']}) — {r.get('status', '?')} "
    lines.extend(_title_box(title).split('\n'))

    if r.get('first_fill'):
        info_rows = []
        if 'equity' in r:
            info_rows.append(['Equity', _fmt_money(r['equity'])])
            info_rows.append(['Cash', _fmt_money(r['cash'])])
            info_rows.append(['Buying power', _fmt_money(r['buying_power'])])
            info_rows.append(['Portfolio', _fmt_money(r['portfolio_value'])])
        info_rows.append(['First fill', r['first_fill'][:10]])
        info_rows.append(['Last fill', r['last_fill'][:10]])
        info_rows.append(['Fills', f"{r['fills']} ({r['buys']} buys / {r['sells']} sells)"])
        if r.get('turnover_spent'):
            info_rows.append(['Turnover', _fmt_money(r['turnover_spent'])])
        lines.extend(_table(['Field', 'Value'], info_rows))
        lines.append('')

    if r.get('positions'):
        pos_rows = [[p['symbol'], f"{p['qty']:.0f}", f"{p['avg_entry']:.2f}",
                     f"{p['mark']:.2f}", f"{p['market_value']:,.0f}",
                     f"{p['unrealized_pl']:,.2f}", f"{p['unrealized_pct']:.1f}%"]
                    for p in r['positions']]
        pos_rows.append(['', '', '', '', 'Total', f"{r['unrealized_pnl']:,.2f}", ''])
        lines.extend(_table(['Symbol', 'Qty', 'AvgEntry', 'Mark', 'MktVal',
                             'Unreal', '%'], pos_rows,
                            aligns=['<', '>', '>', '>', '>', '>', '>']))

        # -- Individual closed trades (commented out; summary + win rate only) --
        # closed_rows = [[c['symbol'], str(c['buys']), str(c['sells']),
        #                 f"{c['qty_bought']:.0f}", f"{c['qty_sold']:.0f}",
        #                 f"{c['realized']:,.2f}"] for c in r['closed']]
        # lines.extend(_table(['Symbol', 'Buys', 'Sells', 'Bought', 'Sold',
        #                      'Realized'], closed_rows,
        #                     aligns=['<', '>', '>', '>', '>', '>']))

        if r.get('closed'):
            wr = r.get('closed_win_rate')
            sum_rows = [['Realized PnL', _fmt_money(r['realized_pnl'])]]
            if wr is not None:
                sum_rows.append(
                    ['Win rate',
                     f"{wr:.0f}% ({sum(1 for c in r['closed'] if c['realized'] > 0)}/"
                     f"{len(r['closed'])})"])
            lines.extend(_table(['Summary', 'Value'], sum_rows))
        lines.append('')

    if 'total_pnl' in r:
        line = (f"Total PnL since inception: {_fmt_money(r['total_pnl'])} "
                f"(realized {_fmt_money(r['realized_pnl'])} + "
                f"unrealized {_fmt_money(r['unrealized_pnl'])})")
        if r.get('portfolio_return_pct') is not None and r.get('initial_capital'):
            line += f" = {r['portfolio_return_pct']:+.2f}% on {_fmt_money(r['initial_capital'])}"
        spy = r.get('spy')
        if spy:
            line += (f" | SPY B&H {spy['start']}→{spy['end']}: {spy['pct']:+.2f}% "
                     f"({_fmt_money(spy['start_close'])}→{_fmt_money(spy['end_close'])})")
        lines.append(line)
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='Per-strategy Alpaca trading report.')
    ap.add_argument('--strategy', nargs='*', choices=['mtf-stock', 'mtf-etf', 'coreew'],
                    help='which strategies to report (default: all)')
    ap.add_argument('--json', action='store_true', help='emit JSON')
    ap.add_argument('--open-only', action='store_true',
                    help='skip closed-trade detail, show account + positions only')
    ap.add_argument('--snapshot', action='store_true',
                    help='print only the strategy snapshot (per-strategy vs SPY B&H)')
    ap.add_argument('--live-spy', action='store_true',
                    help='benchmark SPY through today\'s partial close instead of '
                         'the last settled close')
    args = ap.parse_args()

    chosen = args.strategy or list(STRATEGIES)
    reports = []
    for tag in chosen:
        r = _alpaca_account_report(STRATEGIES[tag])
        if args.open_only:
            r.pop('closed', None)
        reports.append(r)

    bench_headers = next((h for h in (_headers_for(STRATEGIES[t]) for t in chosen)
                          if h), None)
    snap = _build_snapshot(reports, bench_headers, args.live_spy)
    for r, c in zip(reports, snap['strategies']):
        r['inception_date'] = c['inception']
        r['current_amount'] = c['current']
        r['gain'] = c['gain']
        r['gain_pct'] = c['gain_pct']
        r['spy_since_inception'] = c['spy']
        r['vs_spy_pts'] = c['vs_spy_pts']

    if args.json:
        print(json.dumps(snap if args.snapshot else reports, indent=2, default=str))
        return

    print(_fmt_snapshot(snap))
    if args.snapshot:
        return
    for r in reports:
        print()
        print(_fmt_report(r))
        print()


if __name__ == '__main__':
    main()
