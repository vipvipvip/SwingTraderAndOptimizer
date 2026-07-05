"""Fetch 30-min OHLC bars from Alpaca REST API.

Alpaca serves 30Min bars natively via the v2/bars endpoint.
The Python SDK (alpaca-py) doesn't expose 30Min in TimeFrame enum,
so we call the REST API directly.
"""
import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

_API_KEY = os.getenv('ALPACA_API_KEY')
_SECRET = os.getenv('ALPACA_SECRET_KEY')
_DATA_URL = 'https://data.alpaca.markets'
_TRADE_URL = 'https://api.alpaca.markets'
_HEADERS = {
    'APCA-API-KEY-ID': _API_KEY,
    'APCA-API-SECRET-KEY': _SECRET,
}


def fetch_bars(symbol, timeframe, start=None, limit=1):
    """Fetch bars for a symbol at any timeframe.

    Args:
        symbol: ticker symbol
        timeframe: Alpaca timeframe string e.g. '30Min', '1Hour', '1Day'
        start: ISO datetime string (optional)
        limit: max bars to return (default 1 = latest bar)
    Returns:
        list of dicts: [{t, o, h, l, c, v}, ...] sorted ascending
    """
    url = f'{_DATA_URL}/v2/stocks/{symbol}/bars'
    params = {
        'timeframe': timeframe,
        'limit': limit,
        'feed': 'iex',
        'adjustment': 'split',
    }
    if start:
        params['start'] = start

    resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
    if resp.status_code >= 400:
        print(f'[PRICE] Alpaca error {resp.status_code} for {symbol} ({timeframe}): {resp.text}')
        return []

    data = resp.json()
    return data.get('bars', [])


def fetch_all_bars(symbol, timeframe, start='2020-01-01T00:00:00Z'):
    """Fetch ALL historical bars for a symbol at given timeframe (with pagination)."""
    all_bars = []
    page_token = None

    while True:
        url = f'{_DATA_URL}/v2/stocks/{symbol}/bars'
        params = {
            'timeframe': timeframe,
            'limit': 10000,
            'feed': 'iex',
            'adjustment': 'split',
            'start': start,
        }
        if page_token:
            params['page_token'] = page_token

        resp = requests.get(url, headers=_HEADERS, params=params, timeout=60)
        if resp.status_code >= 400:
            print(f'[PRICE] Error fetching {symbol} ({timeframe}): {resp.text}')
            break

        data = resp.json()
        bars = data.get('bars', [])
        all_bars.extend(bars)
        page_token = data.get('next_page_token')
        if not page_token:
            break

    return all_bars


def fetch_30min_bars(symbol, start=None, limit=1):
    """Fetch 30-minute bars for a symbol (backwards compat)."""
    return fetch_bars(symbol, '30Min', start, limit)


def fetch_all_30min_bars(symbol, start='2020-01-01T00:00:00Z'):
    """Fetch ALL historical 30-minute bars for a symbol (backwards compat)."""
    return fetch_all_bars(symbol, '30Min', start)


def fetch_daily_bars(symbol, start='2020-01-01T00:00:00Z'):
    """Fetch ALL historical daily bars for a symbol."""
    return fetch_all_bars(symbol, '1Day', start)


def latest_daily_bar(symbol):
    """Get the most recent daily bar for a symbol."""
    bars = fetch_bars(symbol, '1Day', limit=1)
    return bars[0] if bars else None


def is_trading_day(dt=None):
    """Check if date is a trading day via Alpaca Calendar API."""
    from datetime import date, datetime as dt_mod
    if dt is None:
        dt = dt_mod.now().date()
    if isinstance(dt, dt_mod):
        dt = dt.date()
    r = requests.get(
        f'{_TRADE_URL}/v2/calendar',
        params={'start': dt.isoformat(), 'end': dt.isoformat()},
        headers=_HEADERS,
        timeout=10,
    )
    if r.status_code != 200:
        print(f'[CALENDAR] API error {r.status_code}, assuming trading day')
        return True
    data = r.json()
    return len(data) > 0


def next_trading_dates(start, count=5):
    """Return the next `count` trading days starting from `start` (inclusive)."""
    from datetime import date, datetime as dt_mod, timedelta
    if isinstance(start, dt_mod):
        start = start.date()
    end = start + timedelta(days=count * 2 + 14)  # generous range
    r = requests.get(
        f'{_TRADE_URL}/v2/calendar',
        params={'start': start.isoformat(), 'end': end.isoformat()},
        headers=_HEADERS,
        timeout=10,
    )
    if r.status_code != 200:
        print(f'[CALENDAR] API error {r.status_code}, falling back to weekday check')
        days = []
        c = start
        while len(days) < count:
            if c.weekday() < 5:
                days.append(c)
            c += timedelta(days=1)
        return days
    data = r.json()
    out = []
    for entry in data:
        d = date.fromisoformat(entry['date'])
        out.append(d)
        if len(out) >= count:
            break
    return out


def fetch_trades(symbol, since=None, limit=10000):
    """Fetch raw trade ticks from Alpaca.

    Args:
        symbol: ticker
        since: ISO datetime string — fetch trades after this time
        limit: max trades (max 10000)
    Returns:
        list of dicts: [{t, p, s}, ...] sorted ascending (oldest first)
    """
    url = f'{_DATA_URL}/v2/stocks/{symbol}/trades'
    params = {'feed': 'iex', 'sort': 'asc', 'limit': limit}
    if since:
        params['start'] = since

    trades = []
    while True:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
        if resp.status_code >= 400:
            print(f'[PRICE] Trades error {resp.status_code} for {symbol}: {resp.text}')
            break
        data = resp.json()
        batch = data.get('trades', [])
        trades.extend(batch)
        token = data.get('next_page_token')
        if not token:
            break
        params['page_token'] = token

    return trades


def latest_trade_price(symbol):
    """Get the most recent trade price (for order execution, not bars)."""
    url = f'{_DATA_URL}/v2/stocks/trades/latest'
    resp = requests.get(url, headers=_HEADERS,
                        params={'symbols': symbol, 'feed': 'iex'}, timeout=10)
    if resp.status_code >= 400:
        return None
    data = resp.json()
    trade = data.get('trades', {}).get(symbol)
    return float(trade['p']) if trade and 'p' in trade else None
