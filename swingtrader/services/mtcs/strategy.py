import numpy as np
import pandas as pd

import config
import spectral


def compute_weekly_regime(daily_df):
    weekly = daily_df.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()
    closes_w = weekly['close'].values.astype(float)
    if len(closes_w) < 30:
        return None
    w = spectral.dominant_cycle(closes_w, 10)
    phase = w['phase_deg']
    smoothed = spectral.smooth_ema(phase, 3)[-1]
    return 'bull' if smoothed < 180 else 'bear'


def backtest(symbol, daily_df, capital=100000):
    closes = daily_df['close'].values.astype(float)
    dates = daily_df.index
    n = len(closes)

    weekly_regime = compute_weekly_regime(daily_df)

    min_bars = 60
    position = False
    entry_price = 0
    entry_date = None
    equity = capital
    trades = []
    equity_curve = np.full(n, capital)

    for i in range(min_bars, n):
        window = closes[:i + 1]
        dc = spectral.dominant_cycle(window)
        sine = dc['sine_smoothed']
        lead = dc['lead_smoothed']
        s0, s1 = sine[-2], sine[-1]
        l0, l1 = lead[-2], lead[-1]

        buy = s0 < l0 and s1 >= l1
        sell = s0 > l0 and s1 <= l1

        if not position:
            if buy and weekly_regime != 'bear':
                position = True
                entry_price = closes[i]
                entry_date = dates[i]
        else:
            if sell:
                exit_price = closes[i]
                ret = (exit_price - entry_price) / entry_price
                trade_pnl = equity * ret * 0.95
                equity += trade_pnl
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': dates[i],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return': ret,
                    'pnl': trade_pnl,
                })
                position = False
        equity_curve[i] = equity

    if position:
        exit_price = closes[-1]
        ret = (exit_price - entry_price) / entry_price
        trade_pnl = equity * ret * 0.95
        equity += trade_pnl
        trades.append({
            'entry_date': entry_date,
            'exit_date': dates[-1],
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return': ret,
            'pnl': trade_pnl,
            'open': True,
        })

    total_return = (equity - capital) / capital * 100
    daily_returns = np.diff(equity_curve) / equity_curve[:-1]
    daily_returns = daily_returns[~np.isnan(daily_returns)]
    sharpe = 0
    if len(daily_returns) > 0 and np.std(daily_returns) > 0:
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)

    wins = sum(1 for t in trades if t['return'] > 0)
    win_rate = wins / len(trades) * 100 if trades else 0

    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak * 100
    max_dd = abs(min(0, np.min(dd)))

    final_dc = spectral.dominant_cycle(closes)
    fft_cycles = final_dc.get('fft_cycles', [])
    cycle_str = ', '.join([f"{c['period']}d" for c in fft_cycles]) if fft_cycles else 'none'

    return {
        'symbol': symbol,
        'total_return': total_return,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'trades': len(trades),
        'max_drawdown': max_dd,
        'final_equity': equity,
        'equity_curve': equity_curve,
        'dominant_cycles': cycle_str,
        'weekly_regime': weekly_regime,
        'trades_detail': trades,
    }


def check_signal(conn, ticker_id):
    import db as db_module
    closes, count = db_module.get_daily_candles(conn, ticker_id)
    if count < config.WARMUP_BARS:
        return None, None

    prices = np.array(closes)
    dc = spectral.dominant_cycle(prices)
    sine = dc['sine_smoothed']
    lead = dc['lead_smoothed']

    s0, s1 = sine[-2], sine[-1]
    l0, l1 = lead[-2], lead[-1]

    buy = s0 < l0 and s1 >= l1
    sell = s0 > l0 and s1 <= l1

    pos = db_module.get_position(conn, ticker_id)
    in_position = pos is not None and float(pos[1]) > 0

    if not in_position and buy:
        return 'BUY', prices[-1]
    if in_position and sell:
        return 'SELL', prices[-1]

    return None, None
