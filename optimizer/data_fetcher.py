"""Fetch OHLCV data from Alpaca"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi
import pandas as pd

load_dotenv()

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')
base_url = os.getenv('ALPACA_BASE_URL')

# Initialize SDK
api = tradeapi.REST(api_key, secret_key, base_url)


def fetch_historical_data(symbol, timeframe='1Day', years=2):
    """
    Fetch historical OHLCV data from Alpaca

    Args:
        symbol: Stock symbol (e.g., 'SPY')
        timeframe: '1Day', '1Hour', '4Hour', '1Week', etc.
        years: Number of years of historical data to fetch

    Returns:
        DataFrame with OHLCV data, indexed by timestamp
    """

    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)

    print(f"Fetching {symbol} data from {start_date.date()} to {end_date.date()}")

    try:
        # Use the REST API get_bars method with IEX feed (free tier)
        bars = api.get_bars(
            symbol,
            timeframe,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            adjustment='raw',  # Use raw data without dividends/splits
            feed='iex'  # Use IEX feed which is free tier
        )

        # Convert to DataFrame
        df = bars.df

        # Select only OHLCV columns
        if 'vwap' in df.columns:
            df = df[['open', 'high', 'low', 'close', 'volume']]
        else:
            # Rename if necessary
            df.columns = ['open', 'high', 'low', 'close', 'volume', 'trade_count', 'vwap'] if len(df.columns) > 5 else ['open', 'high', 'low', 'close', 'volume']
            df = df[['open', 'high', 'low', 'close', 'volume']]

        # Ensure index is datetime
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        print(f"Fetched {len(df)} bars for {symbol}")

        return df

    except Exception as e:
        print(f"Error fetching data: {e}")
        import traceback
        traceback.print_exc()
        return None


def save_data(df, symbol, timeframe='1Day'):
    """Save data to CSV for offline analysis"""
    if not os.path.exists('data'):
        os.makedirs('data')

    filename = f"data/{symbol}_{timeframe}_{datetime.now().strftime('%Y%m%d')}.csv"
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
