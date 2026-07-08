import os
from dotenv import load_dotenv

load_dotenv()

TICKERS = ['QQQ', 'VTI', 'VTV']

DETREND_PERIOD = 30
SMOOTHING = 5

WARMUP_BARS = 60

POLL_INTERVAL_SEC = 1800

DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'database': os.getenv('DB_DATABASE', 'swingtrader'),
    'user': os.getenv('DB_USERNAME', 'swingtrader'),
    'password': os.getenv('DB_PASSWORD', 'swingtrader_dev_password'),
}

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
ALPACA_BASE_URL = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

MARKET_OPEN = (9, 30)
MARKET_CLOSE = (16, 0)
