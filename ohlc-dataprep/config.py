import os
from dotenv import load_dotenv

load_dotenv()

# Full 28-ETF universe (tbl_stock_tickers.is_etf = true), widened from the
# Phase 1 VTI/QQQ/VTV-only set once the divergence-pattern method was
# validated on those 3. Excludes 'BLENDED' (in tbl_etf_tickers but has no
# price rows in the scanner tables -- not a real tradeable ticker).
TICKERS = [
    'DIA', 'EEM', 'EFA', 'IJH', 'IJR', 'IWM', 'QQQ', 'RSP', 'SCHB', 'SCHD',
    'SMH', 'SPY', 'TLT', 'VGT', 'VTI', 'VTV', 'VUG', 'XLB', 'XLC', 'XLE',
    'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY',
]

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

# EG100 synthetic index (see utility_scripts/eg_index_calc.py): the same
# QQQ/VTI/VTV trio and EMA span as the live CoreEW gate
# (TradeExecutorService::runEg100Gate / ExecuteEWGate100.php).
EG_LEGS = ['QQQ', 'VTI', 'VTV']
EG_SPAN = 100

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')
