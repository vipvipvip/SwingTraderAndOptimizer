import os
from dotenv import load_dotenv
import psycopg2

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

API_KEY = os.getenv('ALPACA_API_KEY')
SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 5432,
    'database': 'swingtrader',
    'user': 'swingtrader',
    'password': 'swingtrader_dev_password',
}

MACD_FAST = 24
MACD_SLOW = 52
MACD_LENGTH = 18
PPO_FAST = 12
PPO_SLOW = 26
PPO_SIGNAL = 9

TABLE = 'tbl_scanner_tickers'


def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)
