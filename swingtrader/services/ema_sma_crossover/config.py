import os
from dotenv import load_dotenv

load_dotenv()

TICKERS = ['QQQ', 'VTI', 'VTV']

EMA_PERIOD = 10
SMA_PERIOD = 40

MACD_FAST = 10
MACD_SLOW = 40
MACD_SIGNAL = 400

POLL_INTERVAL_SEC = 120

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')

ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
ALPACA_BASE_URL = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

MARKET_OPEN = (9, 30)
MARKET_CLOSE = (16, 0)

COST_PER_TRADE = 0.0005
INITIAL_CAPITAL = 100000.0
