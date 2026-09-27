import os
from dotenv import load_dotenv

load_dotenv()

# Phase 1 universe: narrow set for pattern-discovery before scaling to all ETFs.
TICKERS = ['VTI', 'QQQ', 'VTV']

# Rolling-window length for the slope calc, per timeframe. Kept independent
# since daily and weekly are expected to keep diverging as the method is tuned.
SLOPE_WINDOW = {
    'daily': 10,
    'weekly': 5,
}

TABLES = {
    'daily': 'tbl_scanner_tickers_daily',
    'weekly': 'tbl_scanner_tickers',
}

SLOPE_COLUMNS = ['slope_open', 'slope_high', 'slope_low', 'slope_close']

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')
