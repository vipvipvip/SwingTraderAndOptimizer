# SwingTrader System Architecture (v7.5)

A full-stack algorithmic swing trading system using a **Chandelier Exit** strategy with nightly parameter optimization and live trading dashboard.

---

## System Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    LIVE TRADING (Every Minute)                  │
├────────────────────────────────────────────────────────────────┤
│ Market Hours: 9:30 AM - 4:00 PM ET, Weekdays Only              │
│                                                                │
│ For each ticker (SPY, QQQ, IWM) independently:                │
│  1. Fetch latest bars + current price from Alpaca              │
│  2. Load strategy parameters (chandelier period + multiplier)  │
│     from strategy_parameters table                             │
│  3. If in position:                                            │
│     - Compute ATR(period)                                      │
│     - Track highest high since entry                           │
│     - stop_level = highest_high - ATR × multiplier            │
│     - If close < stop_level → SELL at next bar open           │
│  4. If flat → BUY at next bar open (always re-enter,          │
│     unless exited same day to match backtest)                  │
│  5. Calculate position size:                                   │
│     qty = (account_equity × allocation_weight%) / entry_price  │
│  6. Place order, record trade                                  │
│                                                                │
│ Allocation: SPY 40%, QQQ 45%, IWM 15%                         │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                   NIGHTLY (2:00 AM ET Daily)                    │
├────────────────────────────────────────────────────────────────┤
│ Via systemd timer: swingtrader-optimizer.timer                 │
│                                                                │
│ 1. Load 2 years of hourly bars per ticker                      │
│ 2. Grid search Chandelier parameters:                          │
│    period=[14, 20, 26], multiplier=[1.8, 2.0, 2.2]            │
│    (9 combinations total)                                      │
│ 3. For each combo, run full backtest on 2-year history         │
│ 4. Rank by Sharpe ratio                                        │
│ 5. Save best candidate, promote if return + Sharpe improve     │
│ 6. Portfolio coordinate ascent over tickers for blended Sharpe │
│ 7. Generate equity curves + record backtest trades             │
│ Runtime: ~20-30 minutes                                        │
│                                                                │
│ Results: SPY 8.91%, QQQ 15.63%, IWM 3.18% (2y backtest)       │
│          Sharpe: 3.05, 3.00, 3.13 respectively                 │
└────────────────────────────────────────────────────────────────┘
```

---

## Strategy Details (v7.5 Chandelier Exit)

### Entry Logic

```
When flat for [ticker]:
  → BUY at next bar open (always re-enter)
  Exception: skip re-entry if exited same day (matches daily backtest)
```

### Exit Logic

```
In position for [ticker]:
  highest_high = max(high since entry)
  stop = highest_high - ATR(period) × multiplier
  if close < stop → SELL at next bar open
```

### Parameters (Optimized Nightly)

| Parameter | Values | Description |
|-----------|--------|-------------|
| ATR Period | [14, 20, 26] | Lookback window for Average True Range |
| Multiplier | [1.8, 2.0, 2.2] | Stop distance in ATR units |

9 combinations tested per nightly run.

### Performance (2-Year Backtest)

| Ticker | Return | Sharpe | Win Rate | Trades | Allocation |
|--------|--------|--------|----------|--------|------------|
| SPY | 8.91% | 3.05 | 58.3% | ~12 | 40% |
| QQQ | 15.63% | 3.00 | 62.5% | ~8 | 45% |
| IWM | 3.18% | 3.13 | 66.7% | ~6 | 15% |

---

## Data Flow

### Real-Time Execution Path
```
1. Every minute during market hours:
   a) Alpaca provides current price + latest bar
   b) Backend fetches from Alpaca API
   c) Stores latest bar in `bars` table (if new hour)

2. Signal Computation (for each ticker):
   a) Query last 30 bars from `bars` table
   b) Calculate ATR(period) from highs, lows, closes
   c) Track highest high since entry
   d) Compute stop_level = highest_high - ATR × multiplier
   e) If in position + close < stop_level → SELL
   f) If flat → BUY (with same-day exit guard)

3. Order Execution:
   a) All orders are MARKET orders via Alpaca
   b) Position size = (equity × allocation_weight%) / entry_price

4. Trade Recording:
   a) Record entry: ticker, price, qty, timestamp
   b) On exit: record exit price, P&L, allocation weight used
   c) Calculate return% and pnl_dollar

5. Equity Tracking:
   a) After each trade, calculate new account equity
   b) Store equity snapshot to `equity_snapshots` table
```

### Nightly Optimization Path
```
1. Load Data:
   a) Query 2 years of hourly bars per ticker
   b) Filter to market hours only (14:00-20:00 UTC)

2. Grid Search:
   For each of 9 Chandelier (period × multiplier) combos:
   a) Calculate ATR with trial period
   b) Run full backtest on all 2 years of data
   c) Simulate entry/exit with trailing stop logic

3. Ranking:
   a) Calculate metrics: win_rate, sharpe_ratio, total_return
   b) Rank all 9 combos by sharpe_ratio (highest first)
   c) Best combo saved as candidate

4. Portfolio Coordinate Ascent:
   a) Optimize each ticker independently
   b) Run portfolio-level backtest with allocation weights
   c) Promote candidate if both return AND Sharpe improve over baseline

5. Storage:
   a) Delete old candidates (base_case=false rows)
   b) Insert new best candidate
   c) Production uses base_case=true (manually promoted)
   d) Record all backtest trades to `backtest_trades` table
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
macd_fast (chandelier period: 14-26)
bb_std (chandelier multiplier: 1.8-2.2)
bb_period (ATR period, same as chandelier period)
win_rate (0.0-1.0)
sharpe_ratio
total_return (%)
total_trades
base_case (boolean)
  → true: production parameters (manually promoted)
  → false: candidate from latest optimization
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
return (pct)
pnl_dollar
days_held
symbol, source_symbol, allocation_weight, simulated_close
portfolio_value
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

**computeChandelierSignal(closes, highs, lows, params, inPosition, entryHigh) → 1|-1|0**

1. Calculate ATR:
   ```php
   true_range = max(high - low, |high - prev_close|, |low - prev_close|)
   atr = EMA(true_range, params['bb_period'])
   ```

2. Track highest high since entry:
   ```php
   highest_high = max(entry_high, ... , current_high)
   ```

3. Compute stop level:
   ```php
   stop_level = highest_high - atr * params['bb_std']
   ```

4. Generate signal:
   ```php
   if (!inPosition) return 1  // Always BUY when flat
   if (close < stop_level) return -1  // SELL (stop hit)
   return 0  // HOLD
   ```

### parameter_optimizer.py (Backtesting)

**_backtest_with_params(params) → trades, metrics, equity_curve**

1. Initialize:
   - Starting equity: $100,000
   - Allocation: (equity × allocation_weight%) / entry_price

2. For each bar in history:
   - Calculate ATR with trial period
   - Track highest high since entry
   - Compute stop = highest_high - ATR × multiplier
   - If in position & close < stop: SELL
   - If flat: BUY (with same-day exit guard)
   - Track equity after each trade

3. Calculate metrics:
   - win_rate = wins / total_trades
   - sharpe_ratio = (mean_return × 252) / (std_return × sqrt(252))
   - total_return = (final_equity - initial) / initial

### nightly_optimizer.py (Grid Search)

**optimize(param_grid) → sorted_results**

1. Generate combinations:
   - period × multiplier = 3 × 3 = 9 combos

2. For each combo:
   - Run `_backtest_with_params(combo)`
   - Store result with metrics

3. Sort by Sharpe ratio (highest first)

4. Portfolio coordinate ascent:
   - Run tickers independently
   - Blend results with allocation weights
   - Promote if improvement over baseline

5. Save results:
   - Update `strategy_parameters` table
   - Delete old candidates
   - Record trades to `backtest_trades`
   - Log to `optimization_history`

---

## Safety Mechanisms

1. **Market Hours Filtering**:
   - Only execute trades 9:30 AM - 4:00 PM ET
   - Only on weekdays (Mon-Fri)
   - Alpaca `$clock['is_open']` double-check

2. **Same-Day Exit Guard**:
   - Prevents re-entry on same day as exit
   - Matches daily backtest behavior

3. **Database Consistency**:
   - All trades recorded immediately
   - PnL sync checking before database saves

4. **Candidate Management**:
   - Old base_case=0 candidates auto-deleted
   - Only latest best candidate stored

5. **Graceful Degradation**:
   - API timeouts with retry logic
   - Fallback defaults for missing parameters

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

**Last Updated:** 2026-05-14  
**Version:** v7.5  
**Status:** Production (paper trading)  
**Scheduler:** systemd (backend service + optimizer timer)  
**Database:** PostgreSQL  
**Broker:** Alpaca (paper)
