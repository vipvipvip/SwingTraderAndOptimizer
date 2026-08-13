import os
from dotenv import load_dotenv

load_dotenv()

TOP_N = 10
SECTOR_ETFS = ['XLB', 'XLE', 'XLF', 'XLRE', 'XLV', 'XLI', 'XLK', 'XLP', 'XLU', 'XLY', 'XLC']
EXPECTED_STOCKS = 1435
EXPECTED_ETFS = 28
EMA_PERIOD = 10
SMA_PERIOD = 40
COST_PER_TRADE = 0.0005
INITIAL_CAPITAL = 100000.0
WARMUP_BARS = 60
TS_START = '2023-06-30'

# Ratchet-ATR exit (matches backtest --exit ratchet-atr): exit a held position
# when its close < (highest close since entry) - RATCHET_ATR_MULT x ATR, where
# ATR comes from the hourly table (atr_stop = close - 2*ATR on hourly bars).
# Peak-anchored, so the stop never floats down with a crash (the old
# close-anchored atr_stop could not trigger during selloffs by construction).
# Applies to the stock leg only; the ETF leg is a weekly EMA/SMA rotation.
RATCHET_EXIT = True
RATCHET_ATR_MULT = 2.0

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')

ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
ALPACA_ETF_API_KEY = os.getenv('ALPACA_ETF_API_KEY')
ALPACA_ETF_SECRET_KEY = os.getenv('ALPACA_ETF_SECRET_KEY')
ALPACA_BASE_URL = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
