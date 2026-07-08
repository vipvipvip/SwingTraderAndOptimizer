import os
from dotenv import load_dotenv

load_dotenv()

TOP_N = 10
EMA_PERIOD = 10
SMA_PERIOD = 40
COST_PER_TRADE = 0.0005
INITIAL_CAPITAL = 100000.0
WARMUP_BARS = 60
TS_START = '2023-06-30'

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
