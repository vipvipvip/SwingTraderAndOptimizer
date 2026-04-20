"""Generate equity curve CSVs for all tickers using optimized params, then import via API."""
import argparse
import sys
import os
import csv
import json
import urllib.request
import urllib.error
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from data_fetcher import load_data, fetch_historical_data, save_data
from db import StrategyDB

INITIAL_CAPITAL = 100000
API_BASE = 'http://127.0.0.1:8000/api/v1'
DB_PATH = os.path.join(os.path.dirname(__file__), 'optimized_params', 'strategy_params.db')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'backtest_results')


def run_backtest_with_dates(symbol, params, df):
    """Run backtest with given params, return list of (date, equity) tuples."""
    ema_fast = df['close'].ewm(span=params['macd_fast']).mean()
    ema_slow = df['close'].ewm(span=params['macd_slow']).mean()
    macd_histogram = (ema_fast - ema_slow) - (ema_fast - ema_slow).ewm(span=params['macd_signal']).mean()

    sma_short = df['close'].rolling(window=params['sma_short']).mean()
    sma_long  = df['close'].rolling(window=params['sma_long']).mean()

    bb_middle = df['close'].rolling(window=params['bb_period']).mean()
    bb_lower  = bb_middle - df['close'].rolling(window=params['bb_period']).std() * params['bb_std']

    signals = pd.Series(0, index=df.index)
    warmup = max(params['sma_long'], params['macd_slow'], params['bb_period'])

    for i in range(warmup, len(df)):
        macd_bullish = macd_histogram.iloc[i-1] <= 0 and macd_histogram.iloc[i] > 0
        price = df['close'].iloc[i]
        uptrend = price > sma_short.iloc[i] and sma_short.iloc[i] > sma_long.iloc[i]
        bb_cond  = price <= bb_lower.iloc[i] * 1.05
        if macd_bullish and uptrend and bb_cond:
            signals.iloc[i] = 1
        if i > 0 and signals.iloc[i-1] == 1:
            macd_bearish = macd_histogram.iloc[i-1] >= 0 and macd_histogram.iloc[i] < 0
            bb_break = price < bb_lower.iloc[i]
            if macd_bearish or bb_break:
                signals.iloc[i] = -1

    equity = INITIAL_CAPITAL
    position_active = False
    entry_price = None
    equity_curve = []

    for i in range(len(signals)):
        sig = signals.iloc[i]
        price = df['close'].iloc[i]
        date  = df.index[i]

        if sig == 1 and not position_active:
            entry_price = price
            position_active = True

        if (sig == -1 or i == len(signals) - 1) and position_active:
            pnl = (price - entry_price) / entry_price
            equity = equity * (1 + pnl)
            equity_curve.append((date.strftime('%Y-%m-%d %H:%M'), equity))
            position_active = False

    return equity_curve


def write_csv(symbol, equity_curve):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f'{symbol}_equity_curve.csv')
    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'equity'])
        for date, eq in equity_curve:
            writer.writerow([date, round(eq, 8)])
    print(f'  Saved: {path}')
    return path


def import_csv(symbol, csv_path):
    payload = json.dumps({'symbol': symbol, 'csv_path': csv_path}).encode()
    req = urllib.request.Request(
        f'{API_BASE}/admin/import-backtest',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
            print(f'  Import OK: {body}')
            return True
    except urllib.error.HTTPError as e:
        print(f'  Import FAILED {e.code}: {e.read().decode()}')
        return False


def main():
    parser = argparse.ArgumentParser(description='Generate and import equity curves')
    parser.add_argument(
        '--timeframe',
        default=os.getenv('TRADING_TIMEFRAME', '1Hour'),
        help='Bar timeframe: 1Hour, 1Day, etc. (default: TRADING_TIMEFRAME env or 1Hour)'
    )
    parser.add_argument(
        '--tickers',
        nargs='+',
        default=['SPY', 'QQQ', 'IWM'],
        help='Symbols to process (default: SPY QQQ IWM)'
    )
    args = parser.parse_args()

    db = StrategyDB(DB_PATH)

    for symbol in args.tickers:
        print(f'\n=== {symbol} [{args.timeframe}] ===')

        params = db.get_best_params(symbol)
        if not params:
            print(f'  No optimized params found for {symbol}')
            continue

        print(f'  Params: MACD {params["macd_fast"]}/{params["macd_slow"]}/{params["macd_signal"]}, '
              f'SMA {params["sma_short"]}/{params["sma_long"]}, '
              f'BB {params["bb_period"]}/{params["bb_std"]}')

        df = load_data(symbol, args.timeframe)
        if df is None or len(df) == 0:
            print(f'  Fetching fresh data for {symbol}...')
            df = fetch_historical_data(symbol, timeframe=args.timeframe, years=2)
            if df is None:
                print(f'  Failed to fetch data for {symbol}')
                continue
            save_data(df, symbol, args.timeframe)
        print(f'  Data: {len(df)} bars ({df.index[0]} to {df.index[-1]})')

        equity_curve = run_backtest_with_dates(symbol, params, df)
        if not equity_curve:
            print(f'  No trades generated for {symbol}')
            continue

        print(f'  Trades: {len(equity_curve)}, Final equity: ${equity_curve[-1][1]:,.2f}')
        for date, eq in equity_curve:
            print(f'    {date}  ${eq:,.2f}')

        csv_path = write_csv(symbol, equity_curve)
        import_csv(symbol, csv_path)

    db.close()
    print('\nDone.')


if __name__ == '__main__':
    main()
