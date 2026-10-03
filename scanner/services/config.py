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

ATR_PERIOD = 14
ATR_MULT = 2.0

TABLE = 'tbl_prices_weekly'


def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)
