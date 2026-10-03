import os
from dotenv import load_dotenv

load_dotenv()

# Equal-weight sizing (research impl 2026-09-12, flip along with TOP_N).
# CoreEW-style: trim every overweight held position and top up/re-buy every
# underweight in-play name to equity/len(in_play) each cycle, instead of sizing
# only NEW entries at cash/len(to_buy). Held winners stop drifting untrimmed.
# Backtest top-25 EW (--exit ratchet-atr --ratchet-atr-src daily --equal-weight
# --cost 0): +2,114,701% / -20.3% DD / 86% win vs new-entry-only top-25
# +1,153,856% / -20.1% DD. Returns are fantasy (survivorship), but 25 equal
# slots keeps the book demonstrably unconcentrated.
# NOTE (2026-09-25): these stock-leg backtests ran on the pre-fix engine, which read
# the decision-day Monday weekly row (= that week's FRIDAY close, a 4-day lookahead).
# Re-run lookahead-free (same flags, 2021-09-20 -> 2026-09-25, cost 0): +952% / -32.9% DD /
# 45% win / Sharpe 1.6 (SPY +89% / -24.5% / 0.83) - not +2.1M% / -20.3% / 86%. Still NOT an
# expected return: the 1,412-name universe is today's list (equal-weighted it returned ~+139%
# vs +40-49% for IJR/IJH/IWM), the top ~50 names carry ~99% of the profit, and without them
# the strategy is +132% / -36.8% DD vs +115% for the equal-weighted rest.
EQUAL_WEIGHT = True
TOP_N = 25
# ETF-leg pilot (2026-09-08): chosen because ETF-28 top-3 beat top-10 in backtests
# (+1,122.7% / 15.7% DD vs +422.6% / 20.3% DD). WARNING (2026-09-25): those runs used
# the pre-fix engine, which read the decision-day Monday weekly row = that week's
# FRIDAY close (4-day lookahead). Lookahead-free (last completed week, like live),
# 2021-09-21 -> 2026-09-25, 0.05% cost: top-3 +106% / -31.7% DD / Sharpe 0.78;
# top-10 +98% / -19.6% / 0.85; top-3 without SMH +54% / -27.2%. SPY: +89% / -24.5% /
# 0.83. So concentration was NOT the edge. Kept at 3 for the paper pilot by owner
# decision (2026-09-25). Stocks stay at TOP_N. Set ETF_TOP_N equal to TOP_N to revert.
ETF_TOP_N = 3
# The v2 freshest-crossover strategy (V2_FRESH_BARS, V2_HIST_PEAK_LOOKBACK,
# V2_HIST_PEAK_FLOOR) was retired 2026-09-26 — it required stored MACD columns,
# which are dropped. Use --strategy mtf or emasma.
SECTOR_ETFS = ['XLB', 'XLE', 'XLF', 'XLRE', 'XLV', 'XLI', 'XLK', 'XLP', 'XLU', 'XLY', 'XLC']
EMA_PERIOD = 10
SMA_PERIOD = 40
COST_PER_TRADE = 0.0005
INITIAL_CAPITAL = 100000.0
WARMUP_BARS = 60
TS_START = '2023-06-30'

# Ratchet-ATR exit (matches backtest --exit ratchet-atr --ratchet-atr-src
# daily): exit a held position when its close < (highest daily close since
# entry) - RATCHET_ATR_MULT x DAILY ATR, where ATR comes from the daily table
# (atr_stop = close - 2*ATR on daily bars). Both the ATR and the comparison
# close come from settled daily bars only (today's in-progress bar excluded),
# so live == backtest (signals on day D's close, fills at day D+1's open).
# Peak-anchored, so the stop never floats down with a crash (the old
# close-anchored atr_stop could not trigger during selloffs by construction).
# Applies to the stock leg only; the ETF leg is a weekly EMA/SMA rotation.
RATCHET_EXIT = True
RATCHET_ATR_MULT = 2.0

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
