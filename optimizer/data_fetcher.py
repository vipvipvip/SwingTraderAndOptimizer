"""Fetch OHLCV data from Alpaca using modern alpaca-py SDK"""
import os
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
