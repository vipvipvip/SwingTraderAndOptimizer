#!/usr/bin/env python3
"""Compare all strategy variants in one run."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import config
from price_collector import fetch_all_30min_bars, fetch_all_bars, fetch_daily_bars
from backtest_daily import run as run_daily

CAPITAL = config.INITIAL_CAPITAL
COST = config.COST_PER_TRADE


def _bars_to_df(bars):
    records = [{'timestamp': b['t'], 'open': float(b['o']), 'high': float(b['h']),
                'low': float(b['l']), 'close': float(b['c']), 'volume': int(b['v'])} for b in bars]
    df = pd.DataFrame(records)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df.set_index('timestamp', inplace=True)
    df = df.sort_index()
    return df


def _daily_bars_to_series(bars):
    records = []
    for b in bars:
        ts_str = b['t']
        d = (ts_str.split('T')[0] if 'T' in ts_str else str(ts_str)[:10])
        records.append({'date': d, 'close': float(b['c'])})
    df = pd.DataFrame(records)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').set_index('date')
    return df['close']


def _daily_bullish_regime(daily_closes):
    vals = daily_closes.values.astype(float)
    series = pd.Series(vals, index=daily_closes.index)
    ema = series.ewm(span=config.EMA_PERIOD, adjust=False).mean()
    sma = series.rolling(window=config.SMA_PERIOD).mean()
    return pd.Series(ema.values > sma.values, index=daily_closes.index).fillna(False)


def _daily_regime_allows_entry(daily_bullish, dt_index):
    dt_ts = pd.Timestamp(dt_index).tz_localize(None)
    past = daily_bullish[daily_bullish.index <= dt_ts]
    return bool(past.iloc[-1]) if len(past) >= 2 else False


def _weekly_bullish_regime(symbol):
    bars = fetch_all_bars(symbol, '1Week', start='2020-01-01T00:00:00Z')
    if not bars or len(bars) < 50:
        return None
    closes = np.array([float(b['c']) for b in bars])
    series = pd.Series(closes)
    ema = series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma = series.rolling(window=config.SMA_PERIOD).mean().values
    dates = pd.to_datetime([b['t'] for b in bars])
    return pd.Series(ema > sma, index=dates).fillna(False)


def _weekly_regime_allows_entry(weekly_bullish, dt_index):
    dt_ts = pd.Timestamp(dt_index)
    past = weekly_bullish[weekly_bullish.index <= dt_ts]
    return bool(past.iloc[-1]) if len(past) >= 2 else False


def _compute_atr(df, period=14):
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    close = df['close'].values.astype(float)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = np.zeros(len(df))
    atr[:period] = np.nan
    atr[period] = tr[:period].mean()
    for i in range(period + 1, len(df)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period
    return atr


def run_30min_baseline(df):
    """EMA> SMA entry, EMA cross below exit (no daily filter)."""
    return _run_30min_core(df, daily_bullish=None, weekly_bullish=None,
                          profit_target=None, trailing_atr=None, pullback=False)


def run_30min_daily_filter(df, daily_bullish):
    """With daily regime filter."""
    return _run_30min_core(df, daily_bullish=daily_bullish, weekly_bullish=None,
                          profit_target=None, trailing_atr=None, pullback=False)


def run_30min_weekly_filter(df, weekly_bullish):
    """With weekly regime filter."""
    return _run_30min_core(df, daily_bullish=None, weekly_bullish=weekly_bullish,
                          profit_target=None, trailing_atr=None, pullback=False)


def run_30min_profit_target(df, daily_bullish=None):
    """Exit at 2x ATR profit target or EMA cross below."""
    return _run_30min_core(df, daily_bullish=daily_bullish, weekly_bullish=None,
                          profit_target=2.0, trailing_atr=None, pullback=False)


def run_30min_trailing_stop(df, daily_bullish=None):
    """Trailing ATR stop (2x) for exit."""
    return _run_30min_core(df, daily_bullish=daily_bullish, weekly_bullish=None,
                          profit_target=None, trailing_atr=2.0, pullback=False)


def run_30min_pullback(df, daily_bullish=None):
    """Pullback entry within daily uptrend."""
    return _run_30min_core(df, daily_bullish=daily_bullish, weekly_bullish=None,
                          profit_target=None, trailing_atr=None, pullback=True)


def _run_30min_core(df, daily_bullish=None, weekly_bullish=None,
                    profit_target=None, trailing_atr=None, pullback=False):
    n = len(df)
    if n < config.SMA_PERIOD + 2:
        return None, None

    o = df['open'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)
    atr = _compute_atr(df)

    series = pd.Series(c)
    ema = series.ewm(span=config.EMA_PERIOD, adjust=False).mean().values
    sma = series.rolling(window=config.SMA_PERIOD).mean().values

    warmup = config.SMA_PERIOD + 1
    trades = []
    equity = CAPITAL
    in_pos = False
    entry_price = 0
    entry_idx = 0
    equity_before = CAPITAL
    highest_since_entry = 0
    eq_curve = [equity]

    for i in range(warmup, n):
        if np.isnan(ema[i]) or np.isnan(sma[i]):
            continue
        po, pc, ts = o[i], c[i], df.index[i]

        # Exit check
        if in_pos:
            exit_signal = False
            exit_reason = ''

            # Check EMA cross below
            if not np.isnan(ema[i-1]) and not np.isnan(sma[i-1]):
                if ema[i] < sma[i] and ema[i-1] >= sma[i-1]:
                    exit_signal = True
                    exit_reason = 'ema_cross'

            # Profit target
            if profit_target and not exit_signal and not np.isnan(atr[i]):
                gain_pct = (h[i] - entry_price) / entry_price
                if gain_pct >= profit_target * atr[i] / entry_price:
                    exit_signal = True
                    exit_reason = 'profit_target'

            # Trailing ATR stop
            if trailing_atr and not exit_signal and not np.isnan(atr[i]):
                highest_since_entry = max(highest_since_entry, h[i])
                stop_level = highest_since_entry - trailing_atr * atr[i]
                if pc <= stop_level:
                    exit_signal = True
                    exit_reason = 'trailing_stop'

            if exit_signal:
                exit_price = po  # exit on next open
                ret = (exit_price - entry_price) / entry_price - COST
                trades.append({'entry_price': entry_price, 'exit_price': exit_price,
                               'entry_at': str(df.index[entry_idx]),
                               'exit_at': str(df.index[i]),
                               'return': ret, 'reason': exit_reason})
                equity *= (1 + ret)
                in_pos = False
                continue

            # Mark-to-market
            shares = equity_before / entry_price
            eq_curve.append(equity_before + shares * (pc - entry_price))

        # Entry check
        if not in_pos:
            regime_ok = True
            if daily_bullish is not None:
                regime_ok = _daily_regime_allows_entry(daily_bullish, ts)
            if weekly_bullish is not None and regime_ok:
                regime_ok = _weekly_regime_allows_entry(weekly_bullish, ts)
            if not regime_ok:
                eq_curve.append(eq_curve[-1] if eq_curve else equity)
                continue

            ema_gt = ema[i] > sma[i]

            if pullback:
                # Pullback: price near EMA(10) within uptrend
                if not ema_gt:
                    eq_curve.append(eq_curve[-1] if eq_curve else equity)
                    continue
                ema_val = ema[i]
                dist_from_ema = (pc - ema_val) / ema_val
                if dist_from_ema > -0.005:  # not a pullback (price above EMA)
                    eq_curve.append(eq_curve[-1] if eq_curve else equity)
                    continue
            elif not ema_gt:
                eq_curve.append(eq_curve[-1] if eq_curve else equity)
                continue

            entry_price = po
            entry_idx = i
            equity_before = eq_curve[-1] if eq_curve else equity
            highest_since_entry = h[i]
            in_pos = True
            eq_curve.append(equity_before)

    if in_pos:
        exit_price = c[-1]
        ret = (exit_price - entry_price) / entry_price - COST
        trades.append({'entry_price': entry_price, 'exit_price': exit_price,
                       'entry_at': str(df.index[entry_idx]),
                       'exit_at': str(df.index[-1]),
                       'return': ret, 'reason': 'force_close'})
        equity *= (1 + ret)

    if not trades:
        return None, None

    trades_df = pd.DataFrame(trades)
    wins = (trades_df['return'] > 0).sum()
    eq_arr = np.array(eq_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = np.max((peak - eq_arr) / peak) if len(eq_arr) > 1 else 0
    metrics = {
        'total_trades': len(trades_df),
        'winning_trades': int(wins),
        'win_rate': wins / len(trades_df),
        'avg_return': float(trades_df['return'].mean()),
        'total_return': (equity - CAPITAL) / CAPITAL,
        'max_drawdown': float(dd) if not np.isnan(dd) else 0,
    }
    return trades, metrics


def print_result(label, sym, metrics, bh_ret):
    if metrics is None or metrics['total_trades'] == 0:
        print(f'  {label:<28s}  ✗ No trades')
        return metrics
    vs = metrics['total_return'] - bh_ret
    arrow = '▲' if vs > 0 else '▼'
    print(f'  {label:<28s}  {metrics["total_trades"]:>4d}  {metrics["win_rate"]*100:>5.1f}%  {metrics["avg_return"]*100:>+7.2f}%  {metrics["total_return"]*100:>+9.2f}%  {metrics["max_drawdown"]*100:>5.1f}%  {bh_ret*100:>+8.2f}%  {vs*100:>+9.2f}% {arrow}')
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', nargs='+', default=config.TICKERS)
    args = parser.parse_args()

    variants = [
        ('Daily EMA/SMA', lambda df, db, wb, sym: run_daily(df)),
        ('30m EMA/SMA (no filter)', lambda df, db, wb, sym: run_30min_baseline(df)),
        ('30m + daily filter', lambda df, db, wb, sym: run_30min_daily_filter(df, db)),
        ('30m + weekly filter', lambda df, db, wb, sym: run_30min_weekly_filter(df, wb)),
        ('30m + profit target 2ATR', lambda df, db, wb, sym: run_30min_profit_target(df, db)),
        ('30m + trailing stop 2ATR', lambda df, db, wb, sym: run_30min_trailing_stop(df, db)),
        ('30m + pullback entry', lambda df, db, wb, sym: run_30min_pullback(df, db)),
    ]

    print(f'\n{"="*120}')
    print(f'  EMAC STRATEGY COMPARISON')
    print(f'  All variants: EMA({config.EMA_PERIOD})/SMA({config.SMA_PERIOD}) crossover')
    print(f'{"="*120}\n')

    all_data = {}

    for sym in args.tickers:
        print(f'[{sym}] Loading data...')

        # Load daily data
        daily_bars = fetch_daily_bars(sym)
        if not daily_bars:
            print(f'  ✗ No daily data')
            continue
        daily_closes = _daily_bars_to_series(daily_bars)
        bh_ret = (daily_closes.iloc[-1] - daily_closes.iloc[0]) / daily_closes.iloc[0]
        daily_bullish = _daily_bullish_regime(daily_closes)

        # Load weekly bullish regime
        weekly_bullish = _weekly_bullish_regime(sym)
        if weekly_bullish is not None:
            bullish_wks = weekly_bullish.sum()
            total_wks = len(weekly_bullish)
            print(f'  Weekly regime: {bullish_wks}/{total_wks} weeks bullish ({bullish_wks/total_wks*100:.0f}%)')
        else:
            print(f'  Weekly regime: unavailable')

        # Load 30-min data
        bars_30 = fetch_all_30min_bars(sym)
        if not bars_30:
            print(f'  ✗ No 30-min data')
            continue
        df_30 = _bars_to_df(bars_30)
        df_daily = None
        if len(daily_bars) > 0:
            # Daily variant uses its own data loading
            pass

        print(f'  Daily: {len(daily_bars)} bars  |  30-min: {len(df_30)} bars')
        print(f'  BH Return: {bh_ret*100:+.2f}%')
        print()
        print(f'  {"Variant":<28s}  {"Trades":>4s}  {"Win%":>5s}  {"Avg Ret":>7s}  {"Total Ret":>9s}  {"Max DD":>5s}  {"BH Ret":>8s}  {"vs BH":>9s}')
        print(f'  {"-"*100}')

        results = []
        daily_trades = None
        for label, fn in variants:
            if label == 'Daily EMA/SMA':
                df_d = pd.DataFrame({
                    'close': daily_closes.values,
                    'open': daily_closes.values,
                    'high': daily_closes.values,
                    'low': daily_closes.values,
                }, index=daily_closes.index)
                trades, metrics = run_daily(df_d)
            else:
                trades, metrics = fn(df_30, daily_bullish, weekly_bullish, sym)

            metrics = print_result(label, sym, metrics, bh_ret)
            results.append((label, metrics))

        print()

        # Store for summary
        all_data[sym] = {'results': results, 'bh': bh_ret}

    # Summary table
    print(f'\n{"="*120}')
    print(f'  FINAL COMPARISON (avg across tickers)')
    print(f'{"="*120}')
    print(f'  {"Variant":<28s}  {"Trades":>4s}  {"Win%":>5s}  {"Avg Ret":>7s}  {"Total Ret":>9s}  {"Max DD":>5s}  {"vs BH":>9s}')
    print(f'  {"-"*85}')

    for label, _ in variants:
        totals = []
        for sym_data in all_data.values():
            for l, m in sym_data['results']:
                if l == label and m and m['total_trades'] > 0:
                    totals.append(m)
        if not totals:
            print(f'  {label:<28s}  {"--":>4s}  {"--":>5s}  {"--":>7s}  {"--":>9s}  {"--":>5s}  {"--":>9s}')
            continue
        avg_tr = np.mean([t['total_trades'] for t in totals])
        avg_wr = np.mean([t['win_rate'] for t in totals])
        avg_ar = np.mean([t['avg_return'] for t in totals])
        avg_ret = np.mean([t['total_return'] for t in totals])
        avg_dd = np.mean([t['max_drawdown'] for t in totals])
        bhs = [d['bh'] for d in all_data.values()]
        avg_bh = np.mean(bhs)
        avg_vs = avg_ret - avg_bh
        arrow = '▲' if avg_vs > 0 else '▼'
        print(f'  {label:<28s}  {avg_tr:>4.0f}  {avg_wr*100:>5.1f}%  {avg_ar*100:>+7.2f}%  {avg_ret*100:>+9.2f}%  {avg_dd*100:>5.1f}%  {avg_vs*100:>+9.2f}% {arrow}')

    print()


if __name__ == '__main__':
    import argparse
    main()
