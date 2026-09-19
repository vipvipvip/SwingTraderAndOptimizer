import os
from dotenv import load_dotenv

load_dotenv()  # own dir .env if present
_MTF_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mtf', '.env')
if os.path.exists(_MTF_ENV):
    load_dotenv(_MTF_ENV, override=False)  # reuse shared DB/DB/ALPACA/Slack creds

EMA_PERIOD = 10
SMA_PERIOD = 40
TOP_N = 25
MAX_SINCE_CROSS_WEEKS = 12
MIN_HISTORY_BARS = 45

DB_HOST = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT = int(os.getenv('DB_PORT', '5432'))
DB_NAME = os.getenv('DB_DATABASE', 'swingtrader')
DB_USER = os.getenv('DB_USERNAME', 'swingtrader')
DB_PASS = os.getenv('DB_PASSWORD', 'swingtrader_dev_password')

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

# Feature weights (derived from weekly hindsight AUCs across 5,832 crosses:
# parabola = EMA10>SMA40 cross followed by +50% within 12wk, base rate 2.1%).
WEIGHTS = {
    'std20': 1.7,      # weekly-return stdev 20wk  (AUC 0.87)
    'maxrange8': 1.65, # widest weekly range 8wk   (0.85)
    'low52': 1.65,     # close vs prior 52wk low   (0.85)
    'atr': 1.65,       # avg weekly range 20wk/close (0.85)
    'expcount': 1.6,   # 10%+ range weeks last 4   (0.84)
    'dip8': 1.5,       # dip depth into cross, 8wk (0.80)
    'rng_c': 1.5,      # cross-week range          (0.80)
    'c2s': 1.3,        # close/SMA40 at cross      (0.74)
    'ret20': 1.1,      # momentum 20wk into cross  (0.66)
}