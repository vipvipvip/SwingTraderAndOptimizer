import os
from dotenv import load_dotenv

load_dotenv()

TOP_N = 10
V2_FRESH_BARS = 18     # 1-2 trading days x ~9 hourly bars/day freshness window (v2 strategy)
# MACD histogram momentum guard: exclude an entry (incl. re-buy) when the
# histogram has faded below V2_HIST_PEAK_FLOOR of its peak over the trailing
# V2_HIST_PEAK_LOOKBACK hourly bars.  Catches "shorter MACD histogram bars"
# (decelerating drive) even while EMA/SMA CO is still +ve — this is what made
# TEAM a bad re-buy after its ratchet stop.
V2_HIST_PEAK_LOOKBACK = 24
V2_HIST_PEAK_FLOOR = 0.7
SECTOR_ETFS = ['XLB', 'XLE', 'XLF', 'XLRE', 'XLV', 'XLI', 'XLK', 'XLP', 'XLU', 'XLY', 'XLC']
EXPECTED_STOCKS = 1434
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

# Hourly-bearish deep pullback filter: block entry when hourly EMA10 < SMA40
# AND daily close is more than this % below daily EMA10.  Bearish hourly
# entries with shallow daily pullback (>-5%) include big winners (AGL +326%,
# CIEN +181%); deep pullbacks (<=-5%) have 0% win rate in paper trading.
HOURLY_BEARISH_DAILY_GAP_LIMIT = -5.0

# Chase-guard: block re-entry when a symbol's price rises more than a
# toleranced % above the last SELL (fine-grained against buying back a name
# right after taking a loss).   It aggressively blocks top-N names the sandbox
# recently sold at a loss, causing the executor to silently backfill rank-11+
# names instead of the reported top-10.  NULLED for the v2 sandbox run
# (set to True to re-enable).
ENABLE_CHASE_GUARD = False

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
