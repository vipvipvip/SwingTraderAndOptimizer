"""Fetch OHLCV data from Alpaca using modern alpaca-py SDK"""
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import pandas as pd

# Load .env from backend directory
env_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
load_dotenv(env_path)

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')
db_path = os.path.join(os.path.dirname(__file__), 'optimized_params', 'strategy_params.db')


def fetch_historical_data(symbol, timeframe='1Day', years=2):
    """
    Fetch historical OHLCV data from Alpaca using /v2/stocks/bars API

    Args:
        symbol: Stock symbol (e.g., 'SPY')
        timeframe: '1Day', '1Hour', '4Hour', '1Week', etc.
        years: Number of years of historical data to fetch

    Returns:
        DataFrame with OHLCV data, indexed by timestamp
    """

    end_date = datetime.now(ZoneInfo('America/New_York'))
    start_date = end_date - timedelta(days=365 * years)

    print(f"Fetching {symbol} data from {start_date.date()} to {end_date.date()}")

    try:
        # Map timeframe string to TimeFrame enum
        tf_map = {
            '1Hour': TimeFrame.Hour,
            '1Day': TimeFrame.Day,
            '1Week': TimeFrame.Week,
            '1Month': TimeFrame.Month,
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)

        # Use modern alpaca-py SDK
        client = StockHistoricalDataClient(api_key, secret_key)
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_date,
            end=end_date,
            feed='iex',  # Free tier with IEX data
            limit=10000
        )

        bars_dict = client.get_stock_bars(request_params)

        if not bars_dict or symbol not in bars_dict.data:
            print(f"No data returned for {symbol}")
            return None

        # Paginate through results if needed
        all_bars = list(bars_dict.data[symbol])
        page_token = getattr(bars_dict, 'next_page_token', None)

        while page_token:
            request_params = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start_date,
                end=end_date,
                feed='iex',
                limit=10000,
                page_token=page_token
            )
            bars_dict = client.get_stock_bars(request_params)
            if symbol in bars_dict.data:
                all_bars.extend(bars_dict.data[symbol])
            page_token = getattr(bars_dict, 'next_page_token', None)

        # Convert to DataFrame
        data = []
        for bar in all_bars:
            data.append({
                'timestamp': bar.timestamp,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            })

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()

        print(f"Fetched {len(df)} bars for {symbol}")
        return df

    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return None


def save_data(df, symbol, timeframe='1Day'):
    """Save data to CSV for offline analysis"""
    if not os.path.exists('data'):
        os.makedirs('data')

    filename = f"data/{symbol}_{timeframe}_{datetime.now(ZoneInfo('America/New_York')).strftime('%Y%m%d')}.csv"
    df.to_csv(filename)
    print(f"Data saved to {filename}")
    return filename


def load_data(symbol, timeframe='1Day'):
    """Load data from most recent CSV file"""
    if not os.path.exists('data'):
        return None

    files = [f for f in os.listdir('data') if f.startswith(f"{symbol}_{timeframe}")]
    if not files:
        return None

    latest_file = max(files)  # Get most recent file
    df = pd.read_csv(f"data/{latest_file}", index_col=0, parse_dates=True)
    print(f"Loaded {len(df)} bars from {latest_file}")

    return df


def load_data_from_db(symbol):
    """Load OHLCV data for a symbol from bars table"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get ticker_id
        cursor.execute('SELECT id FROM tickers WHERE symbol = ?', (symbol,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        ticker_id = row[0]

        # Load all bars
        cursor.execute('''
            SELECT timestamp, open, high, low, close, volume
            FROM bars
            WHERE ticker_id = ?
            ORDER BY timestamp
        ''', (ticker_id,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        # Convert to DataFrame
        data = []
        for row in rows:
            data.append({
                'timestamp': row[0],
                'open': row[1],
                'high': row[2],
                'low': row[3],
                'close': row[4],
                'volume': row[5]
            })

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        df = df.sort_index()

        print(f"Loaded {len(df)} bars for {symbol} from database")
        return df
    except Exception as e:
        print(f"Error loading data from database: {e}")
        return None


def append_bars_to_db(symbol, new_bars):
    """Append new bars to the database (called after fetching fresh data)"""
    if new_bars is None or len(new_bars) == 0:
        return 0

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get ticker_id
        cursor.execute('SELECT id FROM tickers WHERE symbol = ?', (symbol,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return 0

        ticker_id = row[0]

        # Get last timestamp in database
        cursor.execute(
            'SELECT MAX(timestamp) FROM bars WHERE ticker_id = ?',
            (ticker_id,)
        )
        row = cursor.fetchone()
        last_timestamp = row[0] if row and row[0] else None
        last_ts = pd.to_datetime(last_timestamp) if last_timestamp else None

        # Append only new bars (after last_timestamp)
        inserted = 0
        now = datetime.now(ZoneInfo('America/New_York')).isoformat()

        for timestamp, row_data in new_bars.iterrows():
            if last_ts is None or timestamp > last_ts:
                cursor.execute('''
                    INSERT INTO bars
                    (ticker_id, timestamp, open, high, low, close, volume, source, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ticker_id,
                    timestamp.isoformat(),
                    float(row_data['open']),
                    float(row_data['high']),
                    float(row_data['low']),
                    float(row_data['close']),
                    int(row_data['volume']),
                    'alpaca',
                    now
                ))
                inserted += 1

        conn.commit()
        conn.close()

        if inserted > 0:
            print(f"Appended {inserted} new bars for {symbol} to database")

        return inserted
    except Exception as e:
        print(f"Error appending bars to database: {e}")
        return 0
