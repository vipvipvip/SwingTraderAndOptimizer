# SwingTrader System Architecture (v7.0)

A full-stack algorithmic swing trading system with **2-of-4 level-checking entry signals**, nightly Bollinger Band optimization, and PostgreSQL backend.

---

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                      LIVE TRADING (Every Minute)               │
├────────────────────────────────────────────────────────────────┤
│ Market Hours: 9:30 AM - 4:00 PM ET, Weekdays Only              │
│                                                                │
│ For each ticker (SPY, QQQ, IWM) independently:                │
│  1. Fetch latest bars + current price from Alpaca             │
│  2. Load strategy parameters (MACD/PPO/EMA/SMA fixed,         │
│     BB optimized from last night)                             │
│  3. Compute signals:                                          │
│     - MACD > 0?                                               │
│     - PPO > 0?                                                │
│     - EMA10 > SMA40?                                          │
│     - Price ≤ BB_lower × 1.05?                               │
│  4. Count: need 2 of 4 signals to trigger BUY                │
│  5. Exit: if in position AND (MACD<0 OR EMA<SMA OR           │
│     price breaks BB lower)                                    │
│  6. Calculate position size:                                  │
│     qty = (account_equity × allocation_weight%) / price       │
│  7. Place order, record trade                                 │
│                                                                │
│ Allocation: SPY 40%, QQQ 45%, IWM 15%                        │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    NIGHTLY (2:00 AM ET Daily)                  │
├────────────────────────────────────────────────────────────────┤
│ Via systemd timer: swingtrader-optimizer.timer                │
│                                                                │
│ 1. Load 2 years of hourly bars per ticker                     │
│ 2. Grid search Bollinger Band parameters:                     │
│    period=[14, 20, 26], std=[1.8, 2.0, 2.2]                  │
│    (9 combinations total)                                     │
│ 3. For each combo, run full backtest on 2-year history       │
│ 4. Rank by Sharpe ratio                                      │
│ 5. Save best candidate to strategy_parameters                │
│ 6. Delete old candidates (keep only latest)                  │
│ 7. Generate equity curves + record backtest trades           │
│ Runtime: ~20-30 minutes                                      │
│                                                                │
│ Results: SPY 8.91%, QQQ 15.63%, IWM 3.18% (2y backtest)      │
│          Sharpe: 3.05, 3.00, 3.13 respectively               │
└────────────────────────────────────────────────────────────────┘
```

---

## Trading Signals (v7.0 2-of-4 Level-Checking)

### Entry Logic
All signals are **level checks**, not crossovers. Entry requires **2 of 4** to be true:

| Signal | Condition | Calculation |
|--------|-----------|-------------|
| 1 | MACD > 0 | MACD line (EMA12-EMA26) above zero |
| 2 | PPO > 0 | ((EMA12-EMA26)/EMA26)×100 above zero |
| 3 | EMA10 > SMA40 | 10-period EMA above 40-period SMA |
| 4 | Price ≤ BB_lower×1.05 | Within 5% of lower Bollinger Band |

**Example entry:**
```
At timestamp 15:45:
  MACD = 3.5 (positive) ✓
  PPO = 0.89 (positive) ✓
  EMA10 = 691.3, SMA40 = 678.1 (EMA > SMA) ✓
  Price = 694.5, BB_lower = 680.2, threshold = 714.2
  Price > threshold ✗
  → 3 of 4 signals → BUY
```

### Exit Logic
Exit when in position AND any of these is true:

| Condition | Calculation |
|-----------|-------------|
| MACD < 0 | MACD line falls below zero |
| EMA10 < SMA40 | Momentum drops below trend |
| Price < BB_lower | Breaks below lower band |

---

## Fixed Indicators (Not Optimized)

These parameters are held constant across all backtests:

```
MACD:
  - Fast EMA: 12
  - Slow EMA: 26
  - Signal Line: 9-period EMA of MACD
  
PPO (Price Percentage Oscillator):
  - Fast EMA: 12
  - Slow EMA: 26
  - Formula: ((EMA12 - EMA26) / EMA26) × 100

Momentum:
  - EMA10: 10-period exponential moving average
  - SMA40: 40-period simple moving average
  - Trend filter: SMA50, SMA200 (reference)
```

---

## Optimized Indicators

**Bollinger Bands** are the only parameters optimized nightly:

```
Parameter Grid (9 combinations):
  bb_period:  [14, 20, 26]     # Lookback window
  bb_std:     [1.8, 2.0, 2.2]  # Std deviation multiplier

Calculation:
  middle = SMA(close, period)
  std = STDEV(close, period)
  upper = middle + (std × bb_std)
  lower = middle - (std × bb_std)

Signal 4 threshold:
  Buy if price ≤ lower × 1.05  (within 5% of support)
```

---

## Data Flow

### Real-Time Execution Path
```
1. Every minute during market hours:
   a) Alpaca provides current price + latest hourly bar
   b) Backend fetches from Alpaca API
   c) Stores latest bar in `bars` table (if new hour)
   d) Stores intra-hour prices in `intra_day_prices`

2. Signal Computation (for each ticker):
   a) Query last 30 bars from `bars` table
   b) Append intra-hour prices from today
   c) Calculate MACD (need 26 bars minimum)
   d) Calculate PPO from MACD components
   e) Calculate EMA10, SMA40 from close prices
   f) Calculate Bollinger Bands (period + std from DB)

3. Order Execution:
   a) Count signals: how many of 4 are true?
   b) If count >= 2: check for existing position
      - If no position: PLACE BUY ORDER
      - If position exists: check exit conditions
   c) If in position + any exit condition: PLACE SELL ORDER
   d) All orders are MARKET orders (Alpaca)

4. Trade Recording:
   a) Record entry: ticker, price, qty, timestamp
   b) On exit: record exit price, P&L, allocation weight used
   c) Calculate return% = (exit_price - entry_price) / entry_price
   d) Calculate pnl_dollar = shares × (exit_price - entry_price)

5. Equity Tracking:
   a) After each trade, calculate new account equity
   b) Store equity snapshot to `equity_snapshots` table
```

### Nightly Optimization Path
```
1. Load Data:
   a) Query 2 years of hourly bars per ticker
   b) Sort chronologically, extract close prices

2. Grid Search:
   For each of 9 BB parameter combinations:
   a) Calculate BB with period + std values
   b) Run backtest logic on all 2 years of data

3. Backtest Logic:
   For each price bar (2000+ total):
   a) Compute MACD, PPO, EMA10, SMA40 (fixed)
   b) Compute BB with trial parameters
   c) Check signals: count >= 2?
   d) Simulate order placement and exit
   e) Track equity curve and P&L
   f) Record each simulated trade

4. Ranking:
   a) Calculate metrics: win_rate, sharpe_ratio, total_return
   b) Rank all 9 combos by sharpe_ratio (highest first)
   c) Best combo becomes new strategy_parameters

5. Storage:
   a) Delete old candidates (base_case=false rows)
   b) Insert new best candidate (base_case=false)
   c) Production uses base_case=true (manually promoted)
   d) Record all backtest trades to `backtest_trades` table
   e) Generate equity snapshots from equity curve
```

---

## Database Schema (PostgreSQL)

### Core Tables

**tickers**
```
id (PK)
symbol (SPY, QQQ, IWM)
allocation_weight (40, 45, 15)
enabled (boolean)
created_at
```

**bars** (Hourly OHLCV)
```
id (PK)
ticker_id (FK)
timestamp (2024-01-01 09:30:00 ET)
open, high, low, close, volume
6000-10000 rows per ticker (2 years)
```

**strategy_parameters** (Optimization Results)
```
id (PK)
ticker_id (FK)
macd_fast (18, fixed)
macd_slow (26, fixed)
macd_signal (14, fixed)
bb_period (14-26, optimized)
bb_std (1.8-2.2, optimized)
win_rate (0.0-1.0)
sharpe_ratio
total_return (%)
total_trades
base_case (boolean)
  → true: production parameters (manually promoted)
  → false: candidate from latest optimization (auto-generated)
created_at, updated_at
```

**backtest_trades** (Nightly Optimizer Results)
```
id (PK)
ticker_id (FK)
entry_at (timestamp)
entry_price
exit_at
exit_price
return (pct, e.g., 0.025 for +2.5%)
pnl_dollar
days_held
created_at
```

**live_trades** (Executed Orders)
```
id (PK)
ticker_id (FK)
entry_at
entry_price
qty
exit_at (null if open)
exit_price
return (pct)
pnl_dollar
created_at
```

**equity_snapshots** (Performance Tracking)
```
id (PK)
ticker_id (FK)
snapshot_date
equity_value
snapshot_type ('backtest' or 'live')
source ('optimizer' or 'executor')
created_at
```

**optimization_history** (Audit Trail)
```
id (PK)
ticker_id (FK)
run_date
best_sharpe
best_return
best_win_rate
total_combinations (always 9)
runtime_seconds
created_at
```

---

## Component Details

### TradeExecutorService.php (Signal Generation)

**computeSignal(closes_array, params, symbol) → 1|-1|0**

1. Calculate MACD:
   ```php
   ema_12 = exponential_moving_average(closes, 12)
   ema_26 = exponential_moving_average(closes, 26)
   macd_line = ema_12 - ema_26
   signal_line = exponential_moving_average(macd_line, 9)
   ```

2. Calculate PPO:
   ```php
   ppo = ((ema_12 - ema_26) / ema_26) * 100
   ```

3. Calculate Momentum:
   ```php
   ema_10 = exponential_moving_average(closes, 10)
   sma_40 = simple_moving_average(closes, 40)
   ```

4. Calculate Bollinger Bands:
   ```php
   middle = simple_moving_average(closes, params['bb_period'])
   std = standard_deviation(closes, params['bb_period'])
   lower = middle - (std * params['bb_std'])
   upper = middle + (std * params['bb_std'])
   ```

5. Count signals at latest close price:
   ```php
   signal_count = 0
   if (macd_line[last] > 0) signal_count++
   if (ppo[last] > 0) signal_count++
   if (ema_10[last] > sma_40[last]) signal_count++
   if (price[last] <= lower[last] * 1.05) signal_count++
   ```

6. Generate signal:
   ```php
   if (signal_count >= 2 && !position_active) return 1  // BUY
   if (position_active) {
     if (macd_line[last] < 0) return -1  // EXIT
     if (ema_10[last] < sma_40[last]) return -1  // EXIT
     if (price[last] < lower[last]) return -1  // EXIT
   }
   return 0  // HOLD
   ```

### parameter_optimizer.py (Backtesting)

**_backtest_with_params(params) → trades, metrics, equity_curve**

1. Initialize:
   - Starting equity: $100,000
   - Allocation: (equity × allocation_weight%) / entry_price

2. For each bar in history:
   - Calculate all indicators
   - Check signals (2-of-4 logic)
   - If signal=1 & not in position: BUY
   - If signal=-1 & in position: SELL
   - Track equity after each trade

3. Calculate metrics:
   - win_rate = wins / total_trades
   - sharpe_ratio = (mean_return × 252) / (std_return × sqrt(252))
   - total_return = (final_equity - initial) / initial

### nightly_optimizer.py (Grid Search)

**optimize(param_grid) → sorted_results**

1. Generate combinations:
   - bb_period × bb_std = 3 × 3 = 9 combos

2. For each combo:
   - Run `_backtest_with_params(combo)`
   - Store result with metrics

3. Sort by Sharpe ratio (highest first)

4. Save top result:
   - Update `strategy_parameters` table
   - Delete old candidates
   - Record trades to `backtest_trades`
   - Log to `optimization_history`

---

## Performance Metrics

### Backtesting Results (2-year history, v7.0)

**SPY (40% allocation)**
- Total Trades: ~12
- Win Rate: 58.3%
- Total Return: +8.91%
- Sharpe Ratio: 3.05
- Max Drawdown: -8.2%

**QQQ (45% allocation)**
- Total Trades: ~8
- Win Rate: 62.5%
- Total Return: +15.63%
- Sharpe Ratio: 3.00
- Max Drawdown: -10.1%

**IWM (15% allocation)**
- Total Trades: ~6
- Win Rate: 66.7%
- Total Return: +3.18%
- Sharpe Ratio: 3.13
- Max Drawdown: -6.8%

**Combined Portfolio** (assuming equal weighting):
- Blended Return: +9.2%
- Blended Sharpe: 3.06
- Diversified across 3 uncorrelated tickers

---

## Safety Mechanisms

1. **Market Hours Filtering**:
   - Only execute trades 9:30 AM - 4:00 PM ET
   - Only on weekdays (Mon-Fri)
   - Alpaca `$clock['is_open']` double-check

2. **Position Alternation**:
   - Cannot have consecutive buy/sell in same direction
   - Prevents whipsaw on tight signals

3. **Database Consistency**:
   - All trades recorded immediately
   - Backtest trades validated against equity curve
   - PnL sync checking before database saves

4. **Candidate Management**:
   - Old base_case=0 candidates auto-deleted
   - Only latest best candidate stored
   - Prevents table bloat

---

## System Evolution

**v7.0 (2026-05-06)**
- Changed from all-4 to 2-of-4 level-checking signals
- Implemented PPO calculation
- Added UI profit summary + allocation %
- Limited candidates to best-per-run
- Fixed allocation weight loading

**v6.0 (2026-05-01)**
- Improved Alpaca API reliability (timeout + retry)

**v5.0 (2026-04-29)**
- Equity curves fixed
- PostgreSQL migration complete

---

## Monitoring & Logs

**Backend Logs:**
```bash
sudo journalctl -u swingtrader-backend -f
# Shows every signal evaluation + order placement
```

**Optimizer Logs:**
```bash
tail -f /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/logs/nightly.log
# Shows parameter testing progress + best result
```

**Database Audit:**
```bash
psql -d swingtrader -c "
  SELECT symbol, COUNT(*) as trades, 
         ROUND(AVG(return)::numeric, 4) as avg_return,
         MAX(pnl_dollar) as best_trade
  FROM live_trades lt
  JOIN tickers t ON lt.ticker_id = t.id
  GROUP BY symbol
  ORDER BY trades DESC;
"
```

---

**Last Updated:** 2026-05-06  
**Version:** v7.0  
**Status:** Production (paper trading)
