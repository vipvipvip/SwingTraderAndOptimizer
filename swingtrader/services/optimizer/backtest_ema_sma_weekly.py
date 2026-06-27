"""Weekly EMA(10)/SMA(40) crossover backtest for 503 stocks + CHAND-on-weekly comparison"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import psycopg2
import psycopg2.extras
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

DB_CONFIG = {
    'host': '127.0.0.1', 'port': 5432,
    'database': 'swingtrader', 'user': 'swingtrader',
    'password': 'swingtrader_dev_password'
}

env_path = os.path.join(os.path.dirname(__file__), '..', '..', 'backend', '.env')
load_dotenv(env_path)
API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')

FAST = 10
SLOW = 40
COST = 0.0005
INITIAL_CAP = 100000

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def load_ticker_map():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, symbol FROM tbl_stock_tickers ORDER BY symbol")
    rows = cur.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}, {row[1]: row[0] for row in rows}

def load_weekly_data(ticker_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, open, high, low, close, volume
        FROM tbl_scanner_tickers
        WHERE ticker_id = %s AND date >= '2020-07-27'
        ORDER BY date
    """, (ticker_id,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    return df

def backtest_ema_sma(df, detailed=False):
    """EMA(10)/SMA(40) crossover. Signal at close bar i → execute at open bar i+1.
    
    Returns: dict with metrics. If detailed=True, also includes equity_curve and trade_equity.
    """
    n = len(df)
    if n < SLOW + 1:
        return None

    close = df['close'].values.astype(float)
    open_p = df['open'].values.astype(float)
    high_p = df['high'].values.astype(float)
    ema_fast = pd.Series(close).ewm(span=FAST, adjust=False).mean().to_numpy()
    sma_slow = pd.Series(close).rolling(window=SLOW).mean().to_numpy()

    warmup = SLOW + 1
    trades = []
    bar_equity = []
    trade_equity = [float(INITIAL_CAP)]
    in_position = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = float(INITIAL_CAP)

    for i in range(warmup, n):
        po = open_p[i]
        pc = float(close[i])

        if pending_exit and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False
            pending_exit = False

        if pending_entry and not in_position:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            in_position = True
            pending_entry = False

        if in_position and not pending_exit:
            if ema_fast[i] < sma_slow[i] and ema_fast[i-1] >= sma_slow[i-1]:
                pending_exit = True

        if not in_position and not pending_entry:
            if ema_fast[i] > sma_slow[i] and ema_fast[i-1] <= sma_slow[i-1]:
                pending_entry = True

        if i == n - 1 and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
                'simulated_close': True,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False

        if in_position:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    # Buy-and-hold from same warmup point
    bh_start = float(open_p[warmup])
    bh_end = float(close[-1])
    bh_return = (bh_end - bh_start) / bh_start

    # BH equity curve
    bh_equity = [float(INITIAL_CAP)]
    for i in range(warmup, n):
        bh_equity.append(INITIAL_CAP * float(close[i]) / bh_start)
    bh_max_dd = _calc_max_dd(bh_equity)

    result = {
        'total_trades': len(trades),
        'total_return': float((trade_equity[-1] - INITIAL_CAP) / INITIAL_CAP),
        'sharpe_ratio': float(_calc_sharpe(bar_equity)),
        'max_drawdown': float(_calc_max_dd(trade_equity)),
        'bh_return': float(bh_return),
        'bh_max_dd': float(bh_max_dd),
        'upside_capture': float((trade_equity[-1] - INITIAL_CAP) / (INITIAL_CAP * bh_return)) if bh_return > 0 else 0,
    }

    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        result.update({
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'avg_weeks_held': float(trades_df['weeks_held'].mean()),
        })
    else:
        result.update({
            'winning_trades': 0, 'win_rate': 0,
            'avg_return': 0, 'avg_weeks_held': 0,
        })

    if detailed:
        idx = df.index[warmup:]
        result['dates'] = idx
        result['bar_equity'] = bar_equity
        result['trade_equity'] = trade_equity
        result['bh_equity'] = bh_equity

    return result


def backtest_chand_weekly(df, params):
    """Chandelier exit on weekly data. Signal at close bar i → execute at open bar i+1."""
    n = len(df)
    period = int(params['period'])
    mult = float(params['mult'])
    entry_mult = params.get('entry_mult')
    reg_window = params.get('reg_window')
    reg_threshold = params.get('reg_threshold')
    reg_type = params.get('reg_type')

    open_p = df['open'].values.astype(float)
    high_p = df['high'].values.astype(float)
    low_p = df['low'].values.astype(float)
    close_p = df['close'].values.astype(float)

    prev_close = np.roll(close_p, 1)
    prev_close[0] = close_p[0]
    tr = np.maximum.reduce([high_p - low_p, np.abs(high_p - prev_close), np.abs(low_p - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values

    rolling_high = pd.Series(high_p).rolling(window=period, min_periods=1).max().values

    # Regression slope
    reg_slope = None
    if reg_window and reg_threshold and reg_type:
        raw = np.full(n, np.nan)
        for j in range(reg_window - 1, n):
            y = close_p[j - reg_window + 1 : j + 1]
            x = np.arange(reg_window)
            A = np.vstack([x, np.ones(reg_window)]).T
            m, _ = np.linalg.lstsq(A, y, rcond=None)[0]
            raw[j] = m
        reg_slope = np.full(n, np.nan)
        for j in range(n):
            if np.isnan(raw[j]):
                continue
            if reg_type == 'slope_atr':
                if atr[j] and not np.isnan(atr[j]) and atr[j] > 0:
                    reg_slope[j] = raw[j] / atr[j]
            elif reg_type == 'slope_pct':
                if close_p[j] > 0:
                    reg_slope[j] = raw[j] / close_p[j] * 100
            else:
                reg_slope[j] = raw[j]

    warmup = max(period, reg_window or 0)
    trades = []
    bar_equity = []
    trade_equity = [float(INITIAL_CAP)]
    in_position = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = float(INITIAL_CAP)
    high_since = 0.0

    for i in range(warmup, n):
        po = open_p[i]
        pc = close_p[i]
        ph = high_p[i]

        if pending_exit and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False
            pending_exit = False

        if pending_entry and not in_position:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            in_position = True
            high_since = ph
            pending_entry = False

        # Detect signals
        if not in_position and not pending_entry:
            if entry_mult is not None:
                entry_level = rolling_high[i] - atr[i] * entry_mult
                if pc > entry_level:
                    pending_entry = True
            else:
                pending_entry = True

        if in_position and not pending_exit:
            if ph > high_since:
                high_since = ph
            stop_level = high_since - atr[i] * mult
            if pc < stop_level:
                pending_exit = True
            if not pending_exit and reg_slope is not None and not np.isnan(reg_slope[i]):
                if reg_slope[i] < reg_threshold:
                    pending_exit = True

        if i == n - 1 and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
                'simulated_close': True,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False

        if in_position:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    if not trades:
        return None

    trades_df = pd.DataFrame(trades)
    wins = (trades_df['return'] > 0).sum()
    total_return = (trade_equity[-1] - INITIAL_CAP) / INITIAL_CAP
    sharpe = _calc_sharpe(bar_equity)
    max_dd = _calc_max_dd(trade_equity)

    return {
        'total_trades': len(trades_df),
        'winning_trades': int(wins),
        'win_rate': wins / len(trades_df),
        'avg_return': float(trades_df['return'].mean()),
        'total_return': float(total_return),
        'sharpe_ratio': float(sharpe),
        'max_drawdown': float(max_dd),
        'avg_weeks_held': float(trades_df['weeks_held'].mean()),
    }


def backtest_chand_entry_cross_exit(df, params):
    """CHAND entry (price > rolling_high - ATR*entry_mult) + EMA/SMA crossunder exit.
    
    Entry: CHAND style at close bar i → execute at open bar i+1.
    Exit:  EMA(10) < SMA(40) crossunder at close → execute at open.
    Optionally filters entry to only when EMA > SMA (uptrend filter).
    """
    n = len(df)
    if n < SLOW + 1:
        return None

    period = int(params['period'])
    entry_mult = float(params.get('entry_mult', 1.5))
    trend_filter = params.get('trend_filter', True)

    close = df['close'].values.astype(float)
    open_p = df['open'].values.astype(float)
    high_p = df['high'].values.astype(float)

    ema_fast = pd.Series(close).ewm(span=FAST, adjust=False).mean().to_numpy()
    sma_slow = pd.Series(close).rolling(window=SLOW).mean().to_numpy()

    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    low_p_vals = df['low'].values.astype(float)
    tr = np.maximum.reduce([high_p - low_p_vals,
                            np.abs(high_p - prev_close),
                            np.abs(low_p_vals - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values
    rolling_high = pd.Series(high_p).rolling(window=period, min_periods=1).max().values

    warmup = max(SLOW + 1, period)
    trades = []
    bar_equity = []
    trade_equity = [float(INITIAL_CAP)]
    in_position = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = float(INITIAL_CAP)
    high_since = 0.0

    for i in range(warmup, n):
        po = open_p[i]
        pc = close[i]
        ph = high_p[i]

        if pending_exit and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False
            pending_exit = False

        if pending_entry and not in_position:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            in_position = True
            high_since = ph
            pending_entry = False

        # Exit: EMA/SMA crossunder (at close)
        if in_position and not pending_exit:
            if ema_fast[i] < sma_slow[i] and ema_fast[i-1] >= sma_slow[i-1]:
                pending_exit = True

        # Entry: CHAND style (at close), optionally only when EMA > SMA
        if not in_position and not pending_entry:
            if not trend_filter or (ema_fast[i] > sma_slow[i]):
                entry_level = rolling_high[i] - atr[i] * entry_mult
                if pc > entry_level and not np.isnan(entry_level):
                    pending_entry = True

        if i == n - 1 and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
                'simulated_close': True,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False

        if in_position:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    bh_start = float(open_p[warmup])
    bh_end = float(close[-1])
    bh_return = (bh_end - bh_start) / bh_start

    result = {
        'total_trades': len(trades),
        'total_return': float((trade_equity[-1] - INITIAL_CAP) / INITIAL_CAP),
        'sharpe_ratio': float(_calc_sharpe(bar_equity)),
        'max_drawdown': float(_calc_max_dd(trade_equity)),
        'bh_return': float(bh_return),
    }
    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        result.update({
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'avg_weeks_held': float(trades_df['weeks_held'].mean()),
        })
    else:
        result.update({'winning_trades': 0, 'win_rate': 0, 'avg_return': 0, 'avg_weeks_held': 0})
    return result


def backtest_ema_chand(df, params):
    """EMA(10)/SMA(40) crossover for ENTRY + CHAND trailing stop for EXIT.
    
    Entry: signal at close bar i → execute at open bar i+1 (same as EMA/SMA).
    Exit:  CHAND trailing stop = high_since - ATR*mult, signal at close → exec at open.
    No regression exit.
    """
    n = len(df)
    if n < SLOW + 1:
        return None

    period = int(params['period'])
    mult = float(params['mult'])

    close = df['close'].values.astype(float)
    open_p = df['open'].values.astype(float)
    high_p = df['high'].values.astype(float)

    ema_fast = pd.Series(close).ewm(span=FAST, adjust=False).mean().to_numpy()
    sma_slow = pd.Series(close).rolling(window=SLOW).mean().to_numpy()

    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum.reduce([high_p - np.roll(high_p, 1),
                            np.abs(high_p - prev_close),
                            np.abs(low_p := df['low'].values.astype(float) - prev_close)])
    atr = pd.Series(tr).rolling(window=period).mean().values

    warmup = max(SLOW + 1, period)
    trades = []
    bar_equity = []
    trade_equity = [float(INITIAL_CAP)]
    in_position = False
    pending_entry = False
    pending_exit = False
    entry_price = 0.0
    entry_idx = 0
    equity_before = float(INITIAL_CAP)
    high_since = 0.0

    for i in range(warmup, n):
        po = open_p[i]
        pc = close[i]
        ph = high_p[i]

        if pending_exit and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * po * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': po,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False
            pending_exit = False

        if pending_entry and not in_position:
            entry_price = po
            entry_idx = i
            equity_before = trade_equity[-1]
            in_position = True
            high_since = ph
            pending_entry = False

        # Entry: EMA/SMA crossover (at close)
        if not in_position and not pending_entry:
            if ema_fast[i] > sma_slow[i] and ema_fast[i-1] <= sma_slow[i-1]:
                pending_entry = True

        # Exit: CHAND trailing stop (at close)
        if in_position and not pending_exit:
            if ph > high_since:
                high_since = ph
            stop_level = high_since - atr[i] * mult
            if pc < stop_level:
                pending_exit = True

        if i == n - 1 and in_position:
            allocated = equity_before
            deployed = allocated * (1 - COST)
            shares = deployed / entry_price
            net_proceeds = shares * pc * (1 - COST)
            net_dollar = net_proceeds - deployed
            net_pnl = net_dollar / deployed
            trades.append({
                'entry_price': entry_price, 'exit_price': pc,
                'entry_at': str(df.index[entry_idx]), 'exit_at': str(df.index[i]),
                'return': net_pnl, 'pnl_dollar': net_dollar, 'pnl_pct': net_pnl,
                'weeks_held': round(i - entry_idx, 1),
                'simulated_close': True,
            })
            trade_equity.append(trade_equity[-1] + net_dollar)
            in_position = False

        if in_position:
            shares = equity_before / entry_price
            bar_equity.append(equity_before + shares * (pc - entry_price))
        else:
            bar_equity.append(trade_equity[-1])

    bh_start = float(open_p[warmup])
    bh_end = float(close[-1])
    bh_return = (bh_end - bh_start) / bh_start

    result = {
        'total_trades': len(trades),
        'total_return': float((trade_equity[-1] - INITIAL_CAP) / INITIAL_CAP),
        'sharpe_ratio': float(_calc_sharpe(bar_equity)),
        'max_drawdown': float(_calc_max_dd(trade_equity)),
        'bh_return': float(bh_return),
    }
    if trades:
        trades_df = pd.DataFrame(trades)
        wins = (trades_df['return'] > 0).sum()
        result.update({
            'winning_trades': int(wins),
            'win_rate': wins / len(trades_df),
            'avg_return': float(trades_df['return'].mean()),
            'avg_weeks_held': float(trades_df['weeks_held'].mean()),
        })
    else:
        result.update({'winning_trades': 0, 'win_rate': 0, 'avg_return': 0, 'avg_weeks_held': 0})
    return result


def _calc_sharpe(equity_curve):
    if len(equity_curve) < 2:
        return 0.0
    eq = np.array(equity_curve, dtype=float)
    returns = np.diff(eq) / eq[:-1]
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(52))

def _calc_max_dd(equity_values):
    eq = np.array(equity_values, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(np.min(dd))


def fetch_weekly_alpaca(symbol):
    client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    end = datetime.now(ZoneInfo('America/New_York'))
    start = end - timedelta(days=365 * 10)
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Week,
                           start=start, end=end, feed='iex', limit=10000)
    bars = client.get_stock_bars(req)
    if not bars or symbol not in bars.data:
        return None
    rows = []
    for b in bars.data[symbol]:
        d = b.timestamp.date() if hasattr(b.timestamp, 'date') else b.timestamp
        rows.append({'date': d, 'open': b.open, 'high': b.high, 'low': b.low, 'close': b.close, 'volume': b.volume})
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    df = df.sort_index()
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df


def main():
    print(f"\n{'='*80}")
    print(f"  Weekly EMA({FAST})/SMA({SLOW}) Crossover — 503 Stocks")
    print(f"  Warmup: {SLOW+1} weeks | Cost: {COST*100:.1f}% per trade | Capital: ${INITIAL_CAP:,.0f}")
    print(f"  Data: tbl_scanner_tickers since 2020-07-27 (contiguous)")
    print(f"  Entry: signal at close → enter next bar open")
    print(f"{'='*80}\n")

    ticker_map, _ = load_ticker_map()
    ticker_ids = sorted(ticker_map.keys())
    results = []
    skipped = 0
    for tid in ticker_ids:
        sym = ticker_map[tid]
        df = load_weekly_data(tid)
        if df is None or len(df) < SLOW + 1:
            skipped += 1
            continue
        r = backtest_ema_sma(df)
        if r is None:
            skipped += 1
            continue
        r['symbol'] = sym
        r['ticker_id'] = tid
        r['weeks'] = len(df)
        results.append(r)

    print(f"  Backtested: {len(results)} tickers | Skipped: {skipped}\n")
    if not results:
        print("No results!")
        return

    dfr = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)

    # BH comparison
    dfr['bh_outperform'] = dfr['total_return'] > dfr['bh_return']
    dfr['strategy_wins'] = dfr['total_return'] > 0
    dfr['dd_protection'] = dfr['max_drawdown'] > dfr['bh_max_dd']  # strategy DD less negative
    dfr['capture_pct'] = dfr.apply(
        lambda r: r['total_return'] / r['bh_return'] * 100 if abs(r['bh_return']) > 0.01 else 0, axis=1)

    print(f"{'─'*80}")
    print(f"  PORTFOLIO SUMMARY — Strategy vs Buy & Hold")
    print(f"{'─'*80}")
    print(f"  Tickers:              {len(dfr)}")
    print(f"  Avg Strategy Ret:     {dfr['total_return'].mean()*100:>+7.2f}%")
    print(f"  Med Strategy Ret:     {dfr['total_return'].median()*100:>+7.2f}%")
    print(f"  Avg BH Return:        {dfr['bh_return'].mean()*100:>+7.2f}%")
    print(f"  Med BH Return:        {dfr['bh_return'].median()*100:>+7.2f}%")
    print(f"  Avg Upside Capture:   {dfr['capture_pct'].mean():.0f}%")
    print(f"  Med Upside Capture:   {dfr['capture_pct'].median():.0f}%")
    print(f"  Beat BH:              {dfr['bh_outperform'].sum()}/{len(dfr)} ({dfr['bh_outperform'].mean()*100:.0f}%)")
    print(f"  Positive Return:      {dfr['strategy_wins'].sum()}/{len(dfr)} ({dfr['strategy_wins'].mean()*100:.0f}%)")
    print(f"  Avg Sharpe:           {dfr['sharpe_ratio'].mean():.4f}")
    print(f"  Med Sharpe:           {dfr['sharpe_ratio'].median():.4f}")
    print(f"  Avg Strategy DD:      {dfr['max_drawdown'].mean()*100:.1f}%")
    print(f"  Avg BH DD:            {dfr['bh_max_dd'].mean()*100:.1f}%")
    print(f"  DD Protection (#):    {dfr['dd_protection'].sum()}/{len(dfr)}")
    print(f"  Med Trades:           {dfr['total_trades'].median():.0f}")
    print(f"  Med Weeks Held:       {dfr['avg_weeks_held'].mean():.1f}")

    # Top/Bottom by upside capture
    top_capture = dfr.nlargest(8, 'capture_pct')
    bot_capture = dfr.nsmallest(8, 'capture_pct')
    print(f"\n{'─'*80}")
    print(f"  BEST 8 BY UPSIDE CAPTURE (strategy vs BH)")
    print(f"{'─'*80}")
    for _, r in top_capture.iterrows():
        print(f"  {r['symbol']:>5s}  Cap {r['capture_pct']:>5.0f}%  "
              f"Str {r['total_return']*100:>+7.2f}%  "
              f"BH {r['bh_return']*100:>+7.2f}%  "
              f"DD {r['max_drawdown']*100:>5.1f}% / BH {r['bh_max_dd']*100:>5.1f}%  "
              f"T {r['total_trades']:>2d}")

    print(f"\n{'─'*80}")
    print(f"  WORST 8 BY UPSIDE CAPTURE")
    print(f"{'─'*80}")
    for _, r in bot_capture.iterrows():
        print(f"  {r['symbol']:>5s}  Cap {r['capture_pct']:>5.0f}%  "
              f"Str {r['total_return']*100:>+7.2f}%  "
              f"BH {r['bh_return']*100:>+7.2f}%  "
              f"DD {r['max_drawdown']*100:>5.1f}% / BH {r['bh_max_dd']*100:>5.1f}%  "
              f"T {r['total_trades']:>2d}")

    # Distribution of upside capture
    print(f"\n{'─'*80}")
    print(f"  UPSIDE CAPTURE DISTRIBUTION")
    print(f"{'─'*80}")
    for lo, hi, lbl in [(-999, 0, 'Lost money'), (0, 25, '0-25%'), (25, 50, '25-50%'), 
                         (50, 75, '50-75%'), (75, 100, '75-100%'), (100, 150, '100-150%'), 
                         (150, 999, '150%+ (beat BH)')]:
        cnt = ((dfr['capture_pct'] >= lo) & (dfr['capture_pct'] < hi)).sum()
        if cnt:
            print(f"    {lbl:>16s}: {cnt:>4d} tickers")

    # --- CHAND ON WEEKLY with detailed comparison ---
    print(f"\n{'='*80}")
    print(f"  CHAND ON WEEKLY vs EMA/SMA ON WEEKLY (same 3 ETFs)")
    print(f"  Both vs Buy & Hold")
    print(f"{'='*80}")

    chand_params = {
        'QQQ': {'period': 18, 'mult': 3.5, 'entry_mult': 1.5,
                'reg_window': 3, 'reg_threshold': -2.0, 'reg_type': 'slope_atr'},
        'VTI': {'period': 18, 'mult': 3.5, 'entry_mult': 1.5},
        'VTV': {'period': 18, 'mult': 2.5, 'entry_mult': 2.0,
                'reg_window': 3, 'reg_threshold': -2.0, 'reg_type': 'slope_atr'},
    }

    for sym in ['QQQ', 'VTI', 'VTV']:
        df_etf = fetch_weekly_alpaca(sym)
        nbars = len(df_etf) if df_etf is not None else 0
        print(f"\n  {sym} ({nbars} weekly bars, 2020-07 → present):")
        if df_etf is None:
            print("    No data available")
            continue

        # BH
        bh_start = float(df_etf['open'].iloc[SLOW])
        bh_end = float(df_etf['close'].iloc[-1])
        bh_ret = (bh_end - bh_start) / bh_start
        print(f"    {'BUY & HOLD':20s}  Ret {bh_ret*100:>+7.2f}%")

        e = backtest_ema_sma(df_etf, detailed=True)
        if e:
            cap = e['total_return'] / bh_ret * 100 if abs(bh_ret) > 0.01 else 0
            print(f"    {'EMA(10)/SMA(40)':20s}  Sharpe {e['sharpe_ratio']:.3f}  "
                  f"Ret {e['total_return']*100:>+7.2f}%  "
                  f"Win {e['win_rate']*100:>5.1f}%  Trades {e['total_trades']}  "
                  f"DD {e['max_drawdown']*100:>5.1f}%  Cap {cap:>4.0f}%")
        else:
            print(f"    {'EMA(10)/SMA(40)':20s}  No trades")

        cp = chand_params[sym]
        c = backtest_chand_weekly(df_etf, cp)
        if c:
            cap = c['total_return'] / bh_ret * 100 if abs(bh_ret) > 0.01 else 0
            print(f"    {'CHAND+REG':20s}  Sharpe {c['sharpe_ratio']:.3f}  "
                  f"Ret {c['total_return']*100:>+7.2f}%  "
                  f"Win {c['win_rate']*100:>5.1f}%  Trades {c['total_trades']}  "
                  f"DD {c['max_drawdown']*100:>5.1f}%  Cap {cap:>4.0f}%")
        else:
            print(f"    {'CHAND+REG':20s}  No trades")

        # Combined: CHAND entry + EMA/SMA crossunder exit (no trend filter)
        combo1 = backtest_chand_entry_cross_exit(df_etf, {'period': cp['period'], 'entry_mult': cp.get('entry_mult', 1.5), 'trend_filter': False})
        if combo1 and combo1['total_trades'] > 0:
            cap = combo1['total_return'] / bh_ret * 100 if abs(bh_ret) > 0.01 else 0
            print(f"    {'CHAND(in)+CROSS(ex)':20s}  Sharpe {combo1['sharpe_ratio']:.3f}  "
                  f"Ret {combo1['total_return']*100:>+7.2f}%  "
                  f"Win {combo1['win_rate']*100:>5.1f}%  Trades {combo1['total_trades']}  "
                  f"DD {combo1['max_drawdown']*100:>5.1f}%  Cap {cap:>4.0f}%")
        else:
            print(f"    {'CHAND(in)+CROSS(ex)':20s}  No trades")

        # Combined: CHAND entry + EMA/SMA crossunder exit (WITH trend filter EMA > SMA)
        combo2 = backtest_chand_entry_cross_exit(df_etf, {'period': cp['period'], 'entry_mult': cp.get('entry_mult', 1.5), 'trend_filter': True})
        if combo2 and combo2['total_trades'] > 0:
            cap = combo2['total_return'] / bh_ret * 100 if abs(bh_ret) > 0.01 else 0
            print(f"    {'CHAND(in)+CROSS(ex)+F':20s}  Sharpe {combo2['sharpe_ratio']:.3f}  "
                  f"Ret {combo2['total_return']*100:>+7.2f}%  "
                  f"Win {combo2['win_rate']*100:>5.1f}%  Trades {combo2['total_trades']}  "
                  f"DD {combo2['max_drawdown']*100:>5.1f}%  Cap {cap:>4.0f}%")
        else:
            print(f"    {'CHAND(in)+CROSS(ex)+F':20s}  No trades")

        # Combined: EMA/SMA crossover entry + CHAND trailing stop exit
        combo = backtest_ema_chand(df_etf, cp)
        if combo and combo['total_trades'] > 0:
            cap = combo['total_return'] / bh_ret * 100 if abs(bh_ret) > 0.01 else 0
            print(f"    {'EMA/SMA+CHAND(exit)':20s}  Sharpe {combo['sharpe_ratio']:.3f}  "
                  f"Ret {combo['total_return']*100:>+7.2f}%  "
                  f"Win {combo['win_rate']*100:>5.1f}%  Trades {combo['total_trades']}  "
                  f"DD {combo['max_drawdown']*100:>5.1f}%  Cap {cap:>4.0f}%")
        else:
            print(f"    {'EMA/SMA+CHAND(exit)':20s}  No trades")

    # 2022 bear market check for the 3 ETFs
    print(f"\n{'─'*80}")
    print(f"  2022 BEAR MARKET CHECK (Jan-Jun 2022)")
    print(f"{'─'*80}")
    for sym in ['QQQ', 'VTI', 'VTV']:
        df_etf = fetch_weekly_alpaca(sym)
        if df_etf is None:
            continue
        bear = df_etf.loc['2022-01-01':'2022-06-30']
        if len(bear) < SLOW:
            print(f"  {sym}: insufficient data in period")
            continue
        e = backtest_ema_sma(bear, detailed=False)
        bh_bear = (float(bear['close'].iloc[-1]) - float(bear['open'].iloc[0])) / float(bear['open'].iloc[0])
        if e and e['total_trades'] > 0:
            sd = 'in cash' if e['total_return'] > 0 else 'in position (lost)'
            print(f"  {sym}: BH {bh_bear*100:>+6.2f}%  "
                  f"Strategy {e['total_return']*100:>+6.2f}%  "
                  f"{e['total_trades']} trades  {sd}")
        else:
            print(f"  {sym}: BH {bh_bear*100:>+6.2f}%  No trades (was in cash all period)")

    # 2022 full year
    print(f"\n{'─'*80}")
    print(f"  2022 FULL YEAR CHECK")
    print(f"{'─'*80}")
    for sym in ['QQQ', 'VTI', 'VTV']:
        df_etf = fetch_weekly_alpaca(sym)
        if df_etf is None:
            continue
        yr22 = df_etf.loc['2022-01-01':'2022-12-31']
        if len(yr22) < SLOW:
            print(f"  {sym}: insufficient data in period")
            continue
        e = backtest_ema_sma(yr22, detailed=False)
        bh22 = (float(yr22['close'].iloc[-1]) - float(yr22['open'].iloc[0])) / float(yr22['open'].iloc[0])
        if e and e['total_trades'] > 0:
            sd = 'in cash' if e['total_return'] > 0 else 'in position (lost)'
            print(f"  {sym}: BH {bh22*100:>+6.2f}%  "
                  f"Strategy {e['total_return']*100:>+6.2f}%  "
                  f"{e['total_trades']} trades  {sd}")
        else:
            print(f"  {sym}: BH {bh22*100:>+6.2f}%  No trades (was in cash all period)")

    print(f"\n  Completed: {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"\n  Completed: {datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    main()
