"""Backtest the live CHAND rule (computeChandelierSignal) on QQQ/VTI/VTV.

Faithful to swingtrader/backend/TradeExecutorService.php (+ MarketDataTrait):

In position  -> SELL (signal at close i, fill at open i+1) when any of:
  * chandelier: close < highest_high_since_entry - ATR * mult
  * profit-lock (defaults ratio 0.5, arm 0.01):
      peak gain since entry >= arm -> sell when close < entry + ratio*(high-entry)
  * regression exit: normalized OLS slope of last N closes < threshold
      QQQ slope_pct < -0.5 ; VTV slope_atr < -2.0 ; VTI none
Flat (no position) -> BUY only when BOTH:
  * we did not exit today (no same-day re-entry)
  * close > max(high of last `period` bars) - ATR * entry_mult
Bars: one per trading day (getOhlcBars filters hourly table to the 04:00-05:00
UTC midnight bar). ATR = simple mean of last `period` TRs (pairs of bars).
Compares each symbol vs its own buy & hold.

Usage: python3 backtest_chand.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_conn  # noqa: E402

COST = 0.0005
CAPITAL = 100_000.0

# live base_case params from strategy_parameters (2026-06-03 rows, base_case=true)
PARAMS = {
    'QQQ': dict(period=18, mult=3.5, entry_mult=1.5, atr_period=18, reg_window=8,
                reg_threshold=-0.5, reg_type='slope_pct'),
    'VTI': dict(period=18, mult=3.0, entry_mult=1.0, atr_period=18, reg_window=None,
                reg_threshold=None, reg_type=None),
    'VTV': dict(period=18, mult=2.5, entry_mult=2.0, atr_period=18, reg_window=3,
                reg_threshold=-2.0, reg_type='slope_atr'),
}
PROFIT_LOCK_RATIO = 0.5
PROFIT_LOCK_ARM = 0.01


def load_daily(symbol):
    conn = get_conn()
    rows = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT h.timestamp, h.open, h.high, h.low, h.close '
                'FROM tbl_etf_tickers_1hour h JOIN tbl_etf_tickers t ON t.id=h.ticker_id '
                'WHERE t.symbol=%s AND EXTRACT(HOUR FROM h.timestamp) IN (4,5) '
                'AND EXTRACT(MINUTE FROM h.timestamp)=0 '
                'ORDER BY h.timestamp ASC', (symbol,))
            rows = cur.fetchall()
    finally:
        conn.close()
    bars = []
    for ts, o, h, l, c in rows:
        bars.append({'date': ts.date(), 'open': float(o), 'high': float(h),
                     'low': float(l), 'close': float(c)})
    return bars


def atr(bars, period, i):
    """Simple mean of last `period` TRs using bars[0..i] (matches calculateATR)."""
    if i < period:
        return None
    trs = []
    for j in range(i - period, i):
        h, l, pc = bars[j + 1]['high'], bars[j + 1]['low'], bars[j]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def reg_slope(bars, window, i):
    """OLS slope of last `window` closes up to bar i (matches linearRegSlope)."""
    if i < window - 1:
        return None
    closes = [bars[j]['close'] for j in range(i - window + 1, i + 1)]
    x = np.arange(window, dtype=float)
    y = np.array(closes, dtype=float)
    n = window
    denom = n * np.sum(x * x) - np.sum(x) ** 2
    if denom == 0:
        return None
    return (n * np.sum(x * y) - np.sum(x) * np.sum(y)) / denom


def simulate(symbol, bars):
    p = PARAMS[symbol]
    period = p['period']
    trade_log = []
    cash = CAPITAL
    shares = 0.0
    entry_price = 0.0
    entry_i = None  # bar index of the fill day
    last_exit_i = None  # bar index of the last exit (no same-day re-entry)
    curve = []
    curve_dates = []

    for i in range(len(bars)):
        bar = bars[i]
        action = None

        if shares > 0 and entry_i is not None:
            # ---- in position: check exits using bars[0..i] -----------------
            a = atr(bars, p['atr_period'], i)
            # highest high since entry: bars strictly AFTER the fill day
            since = [b for k, b in enumerate(bars) if k > entry_i and k <= i]
            if since and a is not None:
                highest_high = max(x['high'] for x in since)
                # chandelier stop
                if bar['close'] < highest_high - a * p['mult']:
                    action = 'sell'
                # profit lock (defaults; params absent from DB schema)
                if action is None and highest_high > entry_price:
                    peak_gain = (highest_high - entry_price) / entry_price
                    if peak_gain >= PROFIT_LOCK_ARM:
                        lock = entry_price + PROFIT_LOCK_RATIO * (highest_high - entry_price)
                        if bar['close'] < lock:
                            action = 'sell'
                # regression exit
                if action is None and p['reg_window'] and p['reg_threshold'] is not None:
                    slope = reg_slope(bars, p['reg_window'], i)
                    if slope is not None:
                        if p['reg_type'] == 'slope_pct' and bar['close'] > 0:
                            norm = (slope / bar['close']) * 100
                        elif p['reg_type'] == 'slope_atr' and a > 0:
                            norm = slope / a
                        else:
                            norm = slope
                        if norm is not None and norm < p['reg_threshold']:
                            action = 'sell'
        elif shares == 0:
            # ---- flat: entry only above entry level, and not on exit day ----
            if last_exit_i is None or i != last_exit_i:
                a = atr(bars, p['atr_period'], i)
                if i >= period and a is not None:
                    rolling_high = max(bars[j]['high'] for j in range(i - period + 1, i + 1))
                    entry_level = rolling_high - a * p['entry_mult']
                    if bar['close'] > entry_level:
                        action = 'buy'

        # ---- execute at next bar open (signal judged on close of bar i) -----
        if action and i + 1 < len(bars):
            exec_bar = bars[i + 1]
            price = exec_bar['open']
            if action == 'sell' and shares > 0:
                ret = (price - entry_price) / entry_price - COST
                cash += shares * price * (1 - COST)
                trade_log.append((bar['date'], 'SELL', price, ret))
                shares = 0.0
                entry_price = 0.0
                last_exit_i = i + 1
            elif action == 'buy' and shares == 0:
                shares = cash * (1 - COST) / price
                entry_price = price
                entry_i = i + 1
                cash = 0.0
                trade_log.append((bar['date'], 'BUY', price, None))

        curve_dates.append(bar['date'])
        curve.append(cash + shares * bar['close'])

    return trade_log, curve_dates, curve


def buy_and_hold(bars):
    first_open = bars[0]['open']
    shares = CAPITAL * (1 - COST) / first_open
    curve = [shares * b['close'] for b in bars]
    dates = [b['date'] for b in bars]
    final = shares * bars[-1]['close'] * (1 - COST)
    return dates, curve, final


def stats(curve, dates, label):
    final = curve[-1]
    total = (final / CAPITAL - 1) * 100
    maxdd = 0.0
    peak = curve[0]
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100
        maxdd = max(maxdd, dd)
    years = max(len(dates) / 252.0, 1e-9)
    cagr = ((final / CAPITAL) ** (1 / years) - 1) * 100
    rets = np.diff(curve) / np.abs(curve[:-1])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if len(rets) > 1 and np.std(rets) > 0 else 0.0
    print(f'{label:38s} final ${final:12,.2f}  total {total:+9.2f}%  CAGR {cagr:+7.2f}%  '
          f'MaxDD {maxdd:6.2f}%  Sharpe {sharpe:5.2f}')
    return total, maxdd, cagr, sharpe


if __name__ == '__main__':
    symbols = ['QQQ', 'VTI', 'VTV']
    print(f'CHAND reprise (live base_case params, daily bars, COST={COST}, capital ${CAPITAL:,.0f})\n')
    tot_chand = 0.0
    tot_bh = 0.0
    for sym in symbols:
        bars = load_daily(sym)
        print(f'  --- {sym}: {len(bars)} daily bars {bars[0]["date"]} -> {bars[-1]["date"]} '
              f'(period {PARAMS[sym]["period"]}, mult {PARAMS[sym]["mult"]}, entry_mult {PARAMS[sym]["entry_mult"]}, '
              f'reg {PARAMS[sym]["reg_type"] or "none"} {PARAMS[sym]["reg_threshold"]})')
        tl, cd, curve = simulate(sym, bars)
        tot, dd, cagr, sh = stats(curve, cd, f'  CHAND {sym}')
        tot_chand += tot
        n_buy = sum(1 for t in tl if t[1] == 'BUY')
        n_sell = sum(1 for t in tl if t[1] == 'SELL')
        wins = [t for t in tl if t[1] == 'SELL' and t[3] and t[3] > 0]
        print(f'    trades: {n_buy} buys, {n_sell} sells, {len(wins)} win ({len(wins)/max(n_sell,1)*100:.0f}% win rate)')
        bhd, bhcurve, bhfinal = buy_and_hold(bars)
        tb, _, _, _ = stats(bhcurve, bhd, f'  Buy&Hold {sym}')
        tot_bh += tb
        print()

    print(f'  Equal-weight trio: CHAND +{tot_chand/3:+.1f}% vs B&H +{tot_bh/3:+.1f}% '
          f'(delta {(tot_chand - tot_bh)/3:+.1f}pp/sym)')