import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

WEEKLY_PPO_FAST = 60
WEEKLY_PPO_SLOW = 130
DAILY_PPO_FAST = 12
DAILY_PPO_SLOW = 26
PPO_SIGNAL_PERIOD = 9

COST_PER_TRADE = 0.0005
INITIAL_CAPITAL = 100000.0
WARMUP = 130

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')
