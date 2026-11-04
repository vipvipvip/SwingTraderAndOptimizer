import os
from dotenv import load_dotenv

load_dotenv()

# Equal-weight sizing (research impl 2026-09-12, flip along with TOP_N).
# CoreEW-style: trim every overweight held position and top up/re-buy every
# underweight in-play name each cycle, instead of sizing only NEW entries at
# cash/len(to_buy). Held winners stop drifting untrimmed. The stock leg now
# targets equity/TOP_N with a gross-exposure cap — see SIZE_BY_TOP_N below.
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

# Portfolio HWM stop + profit sweep (ETF live 2026-11-05; stock paper
# forward test 2026-11-04).
# Policy lives in portfolio_guard.py; the executor adapter is wired. Flip
# GUARD_ENABLED to activate. The first live run seeds HWM at that day's
# settled-close mark (no historical account peak is imported).
# A/B (ETF-28 top-3 emasma, 2021-09-21..2026-09-25,
# daily marks, 0.05% cost, --equal-weight to match the live ETF leg):
#   baseline EW                      +187.7% / 20.2% DD / 91% invested
#   25% sweep at weekly rebalance    +162.0% / 18.2% DD / reserve $40.8k
#   (legacy equity/N baseline        +176.5% / 21.3% DD)
#   HWM stop weekly close, 20%       no trigger (sweep already caps DD < 20%)
#   HWM stop weekly close, 15%       +124.9% / 21.4% DD (one stop) -- rejected
#   HWM stop weekly close, 6%         +82.5% / 23.6% DD (ten stops) -- rejected
# So: 25% sweep, weekly-close HWM stop at 20% as a disaster stop only.
# The reserve is never re-invested; the live adapter sizes the active book
# from equity - reserve and persists the actual swept amount after fills.
GUARD_ENABLED = True
# ETF: 25% sweep + 20% weekly-close disaster stop (live 2026-11-05).
# Stock: 15% weekly-close HWM stop only, no sweep (live paper forward test
# 2026-11-04). In-sample A/B: +346.9% / 19.1% DD vs +335.5% / 29.2% baseline.
# Post-A/B window (2026-09-26..2026-11-04): -5.72% both, no stop triggered.
# Review after the first live stop or 2026-12-31, whichever comes first.
GUARD_MODES = ('etf', 'stock')
GUARD_HWM_STOP_PCT = 20.0
GUARD_PROFIT_SWEEP_PCT = 25.0
GUARD_SWEEP_ON_REBALANCE = True
GUARD_STOP_CHECK = 'weekly'
GUARD_COOLDOWN_SESSIONS = 5
GUARD_MIN_SWEEP = 0.0
# Per-mode overrides (stock shares the ETF defaults only if an override is absent).
GUARD_STOCK_HWM_STOP_PCT = 15.0
GUARD_STOCK_PROFIT_SWEEP_PCT = 0.0
GUARD_STOCK_SWEEP_ON_REBALANCE = True
GUARD_STOCK_STOP_CHECK = 'weekly'
GUARD_STOCK_COOLDOWN_SESSIONS = 5
GUARD_STOCK_MIN_SWEEP = 0.0

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

# MACD cross-proximity entry gate (stock leg only, 2026-10-20).
# The weekly EMA10>SMA40 cross (CO) usually comes FIRST; the weekly MACD diff
# line (EMA10-EMA40) then turns +ve within a few bars. Require the two events to
# be in sync within +/- EMASMA_MACD_PROX weekly bars, else reject the entry.
# Event-level A/B: in-sync crosses +2.5%/59% win vs not-sync -0.4%/48% (K=5,
# weekly 8w fwd). PORTFOLIO-level A/B found NO DD/win improvement (DD 43.8->43.1,
# win 48->49) — this is a forward-test of an unvalidated signal, reversible by
# flipping EMASMA_MACD_GATE. Applies to the stock leg only; the ETF leg (frozen
# experiment) is unaffected. Implementation is shared: emasma_core.macd_gate_ok.
EMASMA_MACD_GATE = True
EMASMA_MACD_PROX = 5

# CoreEW P20w market gate (stock leg only, 2026-11-03).
# Borrows CoreEW's cash discipline as a risk-on/risk-off switch: QQQ/VTI/VTV
# must have enough legs above their own weekly EMA20 for the stock book to be
# invested. The state is read from the live PHP-canonical
# `trades:coreew-leg-ema-series` command, never re-implemented in Python.
#   any      = at least 1 leg ON (loosest; off only when all 3 are below)
#   majority = at least 2 legs ON
#   all      = 3/3 legs ON
#   qqq      = QQQ's leg only
# flat mode: when OFF, sell the whole stock book at the next run and hold cash
# until the gate turns back ON. ETF leg unaffected (frozen experiment).
# Lookahead-free A/B (top-25 emasma EW, daily-ATR ratchet, MACD gate, cost 0):
#   2021-09-20..2026-09-16: no gate +729.4% / DD 32.6% / win 46%;
#     weekly P20 any flat +618.6% / DD 26.0% / win 47%;
#     weekly P20 qqq flat +461.6% / DD 24.6% / win 46%.
#   2017-02-27..2026-10-07: no gate +4,892.5% / DD 35.4% / win 46%;
#     weekly P20 any flat +4,068.1% / DD 26.0% / win 47%.
# Daily EMA variants did not beat weekly (daily20: 44% win, 1,050 whipsaws).
# Set MARKET_GATE_ENABLED=False to revert to the prior always-invested book.
MARKET_GATE_ENABLED = True
MARKET_GATE_MODE = 'any'
MARKET_GATE_SPAN = 20
MARKET_GATE_LEGS = ('QQQ', 'VTI', 'VTV')

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

# Fixed stop-loss (stock leg, 2026-11-02): in ADDITION to the ATR ratchet, exit
# any held name whose last SETTLED daily close is at/below
# entry_price * (1 - FIXED_STOP_PCT/100). Anchored to the recorded entry fill
# (not the peak), matching backtest_topn_multitf.py --stop-loss N.
#
# DEFAULT OFF: the A/B (top-25 emasma EW, daily-ATR ratchet, cost 0) rejects it.
#   2021-09-20..2026-09-16: 5% stop +900.4% vs +951.0% baseline; max DD 36.2% both;
#                           706 stop exits (vs 360 ratchet-only).
#   2026-08-01..2026-11-02: 5% stop  -7.1% vs  -6.0% baseline; max DD 12.7% both;
#                           41 stop exits.
# It cuts names that later recover and the book's drawdowns are correlated
# gap-downs, so it lowers return without reducing DD. Set to 5.0 to enable.
FIXED_STOP_PCT = 0.0

# Ratchet re-entry cool-off (stock leg, 2026-11-02). A ratchet sell used to be
# blocked only for the SAME calendar day, but the executor runs once/day, so
# that guard was a no-op: the name is still in the weekly top-N (the rank is
# static Mon-Fri because the score reads the last SETTLED weekly bar), so it was
# re-bought the very next morning. Live evidence: 95 sell->re-buy events within
# 5 days in 2026-09-09..11-02. Block re-entry for N TRADING days instead
# (default 5 = the rest of the weekly cycle + margin). Set to 0 to restore the
# old same-day-only behaviour.
RATCHET_COOLDOWN_TRADING_DAYS = 5

# Equal-weight sizing + churn controls (stock leg, 2026-11-02).
# SIZE_BY_TOP_N: size each in-play name at equity/TOP_N instead of
# equity/len(in_play). A thin book (few qualifying picks) used to concentrate
# the whole account (2026-09-10: 3 picks -> ~$31K each on $100K), so a single
# name could cost 0.8% of the account. This also removes the need for a
# separate ramp: a new name is always capped at 1/TOP_N.
# Preserved names (held but out of the top-N; whipsaw guard) still consume
# capital, so their market value is subtracted from the investable equity and
# gross exposure is capped at 100% (no margin / negative cash).
# REBALANCE_BAND_PCT: only trim/top-up when a position drifts more than this
# % of its target. MIN_TRADE_NOTIONAL: skip rebalance deltas below this dollar
# amount (2026-09/10 live: 201 of 535 fills were <$500, mostly 1-share noise).
# Revert with SIZE_BY_TOP_N=False, REBALANCE_BAND_PCT=0, MIN_TRADE_NOTIONAL=0.
SIZE_BY_TOP_N = True
REBALANCE_BAND_PCT = 20.0
MIN_TRADE_NOTIONAL = 500.0

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
