#!/usr/bin/env python3
"""coreew_growth_csv.py — per-trading-day growth CSV for the CoreEW paper account.

Reads the CoreEW Alpaca paper account (#PA3GKZYLVO68) directly from the API and
writes one row per trading day since inception:

  Date, <TICKER>_alloc_pct, <TICKER>_trade_price, <TICKER>_close_price,
  <TICKER>_return_pct, portfolio_cum_return_pct, spy_bh_cum_return_pct,
  cash, portfolio_value, spy_bh_portfolio_value

The file has a two-row header: a group row (Allocation / Prices / Return) over
the matching column blocks, then the per-column names.

  - allocation:      ticker market value / portfolio value at close
  - trade price:      qty-weighted average fill price of that day's fills (blank if none)
  - close price:      SIP daily close (raw, unadjusted; IEX for the newest day)
  - ticker return:    unrealized return vs average cost (blank if not held)
  - portfolio return: cumulative vs the $100,000 inception deposit
  - cash:             deposit - net fills - fees, through that day's close
  - portfolio value:  calculated = cash + sum(qty * close)

The calculated portfolio value is validated against Alpaca's official end-of-day
equity (portfolio history) on every row; the run prints the ending comparison and
fails if it is off by more than --tolerance-pct (default 0.1%).

Read-only: never places orders and never writes state.

Usage:
  python3 coreew_growth_csv.py
  python3 coreew_growth_csv.py --out /tmp/coreew_growth.csv
  python3 coreew_growth_csv.py --tolerance-pct 0.25
"""

import argparse
import csv
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, '..', '..', 'backend', '.env')
PAPER_URL = 'https://paper-api.alpaca.markets'
DATA_URL = 'https://data.alpaca.markets'
MARKET_TZ = ZoneInfo('America/New_York')
SETTLED_AFTER_ET = (16, 5)
INITIAL_CAPITAL = 100000.0
TICKERS = ['QQQ', 'VTI', 'VTV']
BENCHMARK = 'SPY'


def _read_env(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _get(url, headers, params=None):
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f'Alpaca {url} failed ({resp.status_code}): {resp.text}')
    return resp.json()


def _fetch_orders(headers):
    """All orders (any status), ascending; pages on updated_at."""
    out = []
    params = {'status': 'all', 'direction': 'asc', 'limit': 500}
    while True:
        page = _get(f'{PAPER_URL}/v2/orders', headers, params)
        if not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
        last = page[-1].get('updated_at')
        if not last:
            break
        params['after'] = (datetime.fromisoformat(last.replace('Z', '+00:00'))
                           + timedelta(seconds=1)).isoformat()
    return out


def _fetch_activities(headers):
    """All account activities; pages on page_token."""
    out = []
    params = {'page_size': 100}
    while True:
        page = _get(f'{PAPER_URL}/v2/account/activities', headers, params)
        if not page:
            break
        out.extend(page)
        if len(page) < 100:
            break
        params['page_token'] = page[-1]['id']
    return out


def _bars(headers, symbols, start, end, feed='sip'):
    bars = {}
    params = {'symbols': ','.join(symbols), 'timeframe': '1Day', 'start': start,
              'end': end, 'adjustment': 'raw', 'feed': feed, 'limit': 10000}
    while True:
        page = _get(f'{DATA_URL}/v2/stocks/bars', headers, params)
        for sym, rows in (page.get('bars') or {}).items():
            for b in rows:
                bars.setdefault(sym, {})[b['t'][:10]] = b['c']
        token = page.get('next_page_token')
        if not token:
            break
        params['page_token'] = token
    return bars


def _load_bars(headers, symbols, start, end_excl, today):
    """SIP bars, split to the IEX feed over the recent window SIP won't serve."""
    try:
        return _bars(headers, symbols, start, end_excl, feed='sip'), 'sip'
    except RuntimeError as exc:
        if '403' not in str(exc):
            raise
    split = (today - timedelta(days=1)).isoformat()
    bars = _bars(headers, symbols, start, split, feed='sip') if split > start else {}
    recent = _bars(headers, symbols, split, end_excl, feed='iex')
    for sym, closes in recent.items():
        bars.setdefault(sym, {}).update(closes)
    return bars, 'iex-fallback'


def _settled_last_day(today_et):
    if today_et.weekday() < 5 and (today_et.hour, today_et.minute) >= SETTLED_AFTER_ET:
        return today_et.date()
    d = today_et.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def build_rows(headers):
    orders = _fetch_orders(headers)
    fills = [o for o in orders if o['status'] == 'filled' and o.get('filled_at')]
    fills.sort(key=lambda o: o['filled_at'])

    activities = _fetch_activities(headers)
    fees = defaultdict(float)
    deposits = 0.0
    for a in activities:
        amount = float(a.get('net_amount') or 0)
        if a['activity_type'] == 'FEE':
            fees[a['date']] += amount
        elif a['activity_type'] == 'JNLC':
            deposits += amount

    now_et = datetime.now(MARKET_TZ)
    first_day = date.fromisoformat(fills[0]['filled_at'][:10])
    last_day = _settled_last_day(now_et)

    bars, feed = _load_bars(headers, TICKERS + [BENCHMARK], first_day.isoformat(),
                            (last_day + timedelta(days=1)).isoformat(),
                            now_et.date())
    trading_days = sorted({d for closes in bars.values() for d in closes
                           if first_day.isoformat() <= d <= last_day.isoformat()})
    spy_closes = bars.get(BENCHMARK, {})
    spy_base = next((spy_closes[d] for d in trading_days if d in spy_closes), None)

    hist = _get(f'{PAPER_URL}/v2/account/portfolio/history', headers,
                {'period': '1A', 'timeframe': '1D'})
    equity = {}
    for ts, eq in zip(hist.get('timestamp') or [], hist.get('equity') or []):
        equity[datetime.fromtimestamp(ts, MARKET_TZ).date().isoformat()] = float(eq)

    qty = defaultdict(float)
    basis = defaultdict(float)
    trade_vwap = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    cash = deposits
    fill_idx = 0
    rows = []
    for day in trading_days:
        while fill_idx < len(fills) and fills[fill_idx]['filled_at'][:10] <= day:
            o = fills[fill_idx]
            sym = o['symbol']
            q = float(o['filled_qty'])
            px = float(o['filled_avg_price'])
            if o['side'] == 'buy':
                cash -= q * px
                basis[sym] += q * px
                qty[sym] += q
            else:
                cash += q * px
                if qty[sym] > 1e-9:
                    basis[sym] -= q * (basis[sym] / qty[sym])
                qty[sym] -= q
            if abs(qty[sym]) < 1e-9:
                qty[sym] = 0.0
                basis[sym] = 0.0
            if abs(basis[sym]) < 1e-6:
                basis[sym] = 0.0
            tv = trade_vwap[day][sym]
            tv[0] += q * px
            tv[1] += q
            fill_idx += 1
        cash += fees.get(day, 0.0)

        market_value = sum(qty[s] * bars.get(s, {}).get(day, 0.0) for s in TICKERS)
        pv = cash + market_value

        row = {'Date': day}
        for sym in TICKERS:
            close = bars.get(sym, {}).get(day)
            mv = qty[sym] * close if close else 0.0
            row[f'{sym}_alloc_pct'] = (mv / pv * 100.0) if pv else 0.0
            tv = trade_vwap[day].get(sym)
            row[f'{sym}_trade_price'] = (tv[0] / tv[1]) if tv and tv[1] else None
            row[f'{sym}_close_price'] = close
            avg_cost = basis[sym] / qty[sym] if qty[sym] > 1e-9 else None
            row[f'{sym}_return_pct'] = ((close - avg_cost) / avg_cost * 100.0
                                        if avg_cost and close else None)
        row['portfolio_cum_return_pct'] = (pv / INITIAL_CAPITAL - 1.0) * 100.0
        row['cash'] = cash
        row['portfolio_value'] = pv
        row['alpaca_equity'] = equity.get(day)
        spy_close = spy_closes.get(day)
        row['spy_bh_cum_return_pct'] = ((spy_close / spy_base - 1.0) * 100.0
                                    if spy_close and spy_base else None)
        row['spy_bh_portfolio_value'] = (INITIAL_CAPITAL * spy_close / spy_base
                                         if spy_close and spy_base else None)
        rows.append(row)

    checked = [r for r in rows if r['alpaca_equity'] is not None]
    diffs = [(r['Date'], r['portfolio_value'] - r['alpaca_equity']) for r in checked]
    last = rows[-1]
    validation = {
        'feed': feed,
        'checked': len(checked),
        'last_date': last['Date'],
        'calc': last['portfolio_value'],
        'alpaca': last['alpaca_equity'],
        'diff': last['portfolio_value'] - last['alpaca_equity'] if last['alpaca_equity'] else None,
        'max_abs': max(diffs, key=lambda x: abs(x[1])) if diffs else None,
    }
    return rows, validation


def write_csv(rows, path):
    cols = ['Date']
    cols += [f'{s}_alloc_pct' for s in TICKERS]
    cols += [f'{s}_trade_price' for s in TICKERS]
    cols += [f'{s}_close_price' for s in TICKERS]
    cols += [f'{s}_return_pct' for s in TICKERS]
    cols += ['portfolio_cum_return_pct', 'spy_bh_cum_return_pct',
             'cash', 'portfolio_value', 'spy_bh_portfolio_value']
    groups = [''] * len(cols)
    groups[cols.index('QQQ_alloc_pct')] = 'Allocation'
    groups[cols.index('QQQ_trade_price')] = 'Prices'
    groups[cols.index('QQQ_return_pct')] = 'Return'
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(groups)
        w.writerow(cols)
        for row in rows:
            out = [row['Date']]
            out += [round(row[f'{s}_alloc_pct'], 4) for s in TICKERS]
            out += ['' if row[f'{s}_trade_price'] is None else round(row[f'{s}_trade_price'], 6)
                    for s in TICKERS]
            out += ['' if row[f'{s}_close_price'] is None else round(row[f'{s}_close_price'], 6)
                    for s in TICKERS]
            out += ['' if row[f'{s}_return_pct'] is None else round(row[f'{s}_return_pct'], 4)
                    for s in TICKERS]
            out += [round(row['portfolio_cum_return_pct'], 4)]
            out += ['' if row['spy_bh_cum_return_pct'] is None
                    else round(row['spy_bh_cum_return_pct'], 4)]
            out += [round(row['cash'], 2), round(row['portfolio_value'], 2)]
            out += ['' if row['spy_bh_portfolio_value'] is None
                    else round(row['spy_bh_portfolio_value'], 2)]
            w.writerow(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=os.path.join(BASE, 'coreew_PA3GKZYLVO68_growth.csv'))
    ap.add_argument('--tolerance-pct', type=float, default=0.1,
                    help='max allowed ending-value gap vs Alpaca, in percent (default 0.1)')
    args = ap.parse_args()
    env = _read_env(ENV_PATH)
    headers = {'APCA-API-KEY-ID': env['ALPACA_API_KEY'],
               'APCA-API-SECRET-KEY': env['ALPACA_SECRET_KEY']}
    acct = _get(f'{PAPER_URL}/v2/account', headers)
    if acct['account_number'] != 'PA3GKZYLVO68':
        raise SystemExit(f"Wrong account: {acct['account_number']} (expected PA3GKZYLVO68)")
    rows, val = build_rows(headers)
    write_csv(rows, args.out)
    print(f'{len(rows)} rows -> {args.out}')

    print(f"\nValidation vs Alpaca (official EOD equity, prices: {val['feed']}):")
    if val['alpaca'] is None:
        print(f"  {val['last_date']}  calculated {val['calc']:.2f}  Alpaca n/a  (no EOD equity)")
        print('  WARN: could not validate the ending value')
        return
    pct = abs(val['diff']) / val['alpaca'] * 100.0
    print(f"  {val['last_date']}  calculated {val['calc']:.2f}  "
          f"Alpaca {val['alpaca']:.2f}  diff {val['diff']:+.2f} ({pct:.4f}%)")
    if val['max_abs']:
        day, diff = val['max_abs']
        print(f"  max |diff| over {val['checked']} days: {diff:+.2f} ({day})")
    if pct > args.tolerance_pct:
        print(f"  FAIL: ending value off by {pct:.4f}% (tolerance {args.tolerance_pct}%)")
        raise SystemExit(1)
    print('  PASS')


if __name__ == '__main__':
    main()
