# Trading Strategies

## Overview

This project contains two distinct trading systems that operate independently:

1. **Swing Trading System** (`optimizer/` + `TradeExecutorService`) — A live, fully-automated trend-following strategy using the Chandelier Exit method on daily data.
2. **Technical Scanner** (`scanner/` + `ScannerController`) — A multi-timeframe market scanner that detects convergence of MACD, PPO, and SMA crossovers.

Both systems share the same database (`swingtrader`) and Alpaca data source, but their logic, parameters, and objectives are entirely separate.

---

# 1. Swing Trading (Chandelier Exit)

**Service:** `TradeExecutorService` (execution), `StrategyService` (parameter management), `AlpacaService` (broker API)  
**Command:** `trades:execute-daily` (runs every 30 min via cron during market hours)  
**Optimizer:** `parameter_optimizer.py`, `nightly_optimizer.py` (runs daily at 8:18 AM ET via `optimize:nightly`)

### Strategy Type

**Always-In Trend Following with Chandelier Exit**

The strategy maintains a continuous long position in each ticker. There is no discretionary entry filter — it is always in the market. The only decision is when to exit via a trailing stop.

### Entry Rule

```
IF no open position AND not exited today:
    Enter at next bar open (market buy)
```

### Exit Rule (Chandelier Stop)

```
WHILE in position:
    highest_high = max(high of all bars since entry)
    stop_level   = highest_high - ATR(period) * multiplier
    IF close < stop_level:
        Exit at next bar open (market sell)
```

After exit, the strategy re-enters on the following bar (same-day re-entry is blocked).

### Parameters

Each ticker has its own optimized parameters stored in `strategy_parameters` (managed by `StrategyService`):

| Parameter | DB Column | Role | Grid Search Range |
|-----------|-----------|------|------------------|
| Chandelier Period | `macd_fast` | ATR lookback window | [14, 18, 22] |
| Multiplier | `bb_std` | Stop distance multiplier | [2.5, 3.0, 3.5] |
| ATR Period | `bb_period` | Set equal to `macd_fast` | (derived) |

**Optimization target:** Maximize Sharpe ratio (annualized, 252-day).

### Capital Allocation

- Each ticker has an `allocation_weight` (0–100%, default 33.33%) in the `tickers` table.
- Position size: `qty = floor(equity * allocation_weight / current_price)`
- Multi-ticker portfolio uses a shared capital pool; when cash runs out, entries wait for exits to free cash.

### Backtest Cost Model

| Parameter | Value |
|-----------|-------|
| Round-trip cost | 0.05% |
| Initial capital | 100,000 |
| Sharpe periods | 252 days |

### Live Execution Flow (`TradeExecutorService`)

1. `executeForAllTickers()` is triggered by `trades:execute-daily` via cron.
2. For each enabled ticker:
   - `AlpacaService.getAccount()` → check trading permissions.
   - `AlpacaService.getPositions()` → check current open positions.
   - `TradeExecutorService.computeChandelierSignal()` → fetch OHLC bars from `bars` table, compute ATR, check Chandelier stop.
   - On buy signal: calculate allocation, `AlpacaService.placeOrder(market, buy)`.
   - On sell signal: `AlpacaService.placeOrder(market, sell)`, calculate P&L, save to `live_trades`.

### Nightly Optimization Flow (`nightly_optimizer.py`)

1. Fetch incremental prices via `fetch_prices.py`.
2. Run grid search on [14,18,22] × [2.5,3.0,3.5] for each ticker (parallel via `joblib`).
3. Save top candidate per ticker.
4. **Portfolio Coordinate Ascent:**
   - For each ticker, test current vs top 5 candidates in a multi-ticker portfolio context.
   - Pick the parameter set that maximizes portfolio-level Sharpe ratio.
   - Update `base_case=true` row for each ticker.
   - Create/update BLENDED synthetic ticker with portfolio metrics.

### Risk Characteristics

- No take-profit level — purely trailing stop.
- No independent stop-loss; the Chandelier exit serves as both.
- Wider multiplier (`bb_std` = 3.5) → fewer exits, larger drawdowns.
- Tighter multiplier (`bb_std` = 2.5) → more exits, smaller drawdowns.
- Works best in trending markets; whipsaws in sideways/choppy markets.

### Console Commands

| Command | Description |
|---------|-------------|
| `trades:execute-daily` | Run trade signals for all tickers |
| `trades:execute-daily --force-test` | Place 1-share round-trips for testing |
| `trade:manual buy {symbol} --qty=` | Manual buy override |
| `trade:manual sell {symbol} --qty=` | Manual sell override |
| `optimize:nightly` | Run full optimizer pipeline |
| `equity:snapshot` | Snapshot current account equity to DB |
| `positions:sync` | Sync Alpaca positions to `positions_cache` |

---

# 2. Technical Scanner

**Service:** `compute_indicators.py` (indicator computation), `capture_hourly.py` (intraday price capture), `populate_tickers.py` (data ingestion)  
**Controller:** `ScannerController` (serves Blade UI at `/scanner`)  
**Schedule:** Hourly price capture during market hours via `capture_hourly.py`; indicator computation runs on demand.

### Purpose

Scan S&P 500 tickers across 3 timeframes (weekly, daily, 1-hour) for **aligned bullish crossover events** where MACD, PPO, and SMA all fire within close proximity. The convergence tightness is measured and used as a ranking signal.

### Timeframes and Tables

| Timeframe | DB Table | Date Column Type | Data Range |
|-----------|----------|-----------------|------------|
| Weekly | `tbl_scanner_tickers` | `date` | Since 2015 |
| Daily | `tbl_scanner_tickers_daily` | `date` | Since 2015 |
| 1-Hour | `tbl_scanner_tickers_1hour` | `timestamp` | 3-month rolling |

### Indicator Parameters (`scanner/config.py`)

| Parameter | Value | Used In |
|-----------|-------|---------|
| `MACD_FAST` | 24 | SMA fast period |
| `MACD_SLOW` | 52 | SMA slow period |
| `MACD_LENGTH` | 18 | MACD signal line SMA period |
| `PPO_FAST` | 12 | PPO fast EMA period |
| `PPO_SLOW` | 26 | PPO slow EMA period |
| `PPO_SIGNAL` | 9 | PPO signal line EMA span |
| `ATR_PERIOD` | 14 | ATR lookback window |
| `ATR_MULT` | 2.0 | ATR stop multiplier |

### Computation Pipeline (`compute_indicators.py`)

**Phase 1 — Base Moving Averages:**
```
sma_fast = SMA(close, 24)
sma_slow = SMA(close, 52)
```

**Phase 2 — MACD (SMA-based, not EMA):**
```
macd_line       = sma_fast - sma_slow
macd_signal     = SMA(macd_line, 18)
macd_histogram  = macd_line - macd_signal
```

**Phase 3 — PPO:**
```
ppo_line       = ((sma_fast - sma_slow) / sma_slow) × 100
ppo_signal     = EMA(ppo_line, 9)
ppo_histogram  = ppo_line - ppo_signal
```

### Crossover Detection (6 signals)

| Signal | Condition | Direction |
|--------|-----------|-----------|
| `macd_crossover` | MACD line crosses above signal line | Bullish |
| `macd_cross_bearish` | MACD line crosses below signal line | Bearish |
| `ppo_crossover` | PPO line crosses above zero | Bullish |
| `ppo_cross_bearish` | PPO line crosses below zero | Bearish |
| `sma_crossover` | SMA(24) crosses above SMA(52) | Bullish |
| `sma_cross_bearish` | SMA(24) crosses below SMA(52) | Bearish |

**Note:** PPO crossing zero is mathematically equivalent to SMA(24) crossing SMA(52). Therefore `ppo_crossover` and `sma_crossover` always fire on the same bar, as do their bearish counterparts.

### ATR Stop (Scanner)

Separate from the Swing Trading Chandelier ATR:
```
tr    = max(high - low, |high - prev_close|, |low - prev_close|)
atr   = SMA(tr, 14)
atr_stop = close - atr × 2.0
```

Displayed as a reference column in the scanner UI and as a dashed line on the chart.

### Scanner UI (`ScannerController` → `scanner/index.blade.php`)

The scanner page at `/scanner` shows:
1. **Timeframe selector** (W / D / 1H).
2. **Results table** sorted by most recent crossover descending:
   - **Ticker** — colored green (bullish) or red (bearish) based on the most recent crossover direction of any of the 6 signals.
   - **Crossovers** — 3 colored dots with dates: blue (MACD), green (PPO), orange (SMA).
   - **ATR Stop** — trailing stop reference price (numeric).
   - **Close** — latest closing price.
3. **Interactive chart** (lightweight-charts) — click any ticker to see:
   - Price panel: candlesticks, EMA(10), SMA(40), SMA(200), ATR stop line (orange dashed), crossover markers.
   - MACD panel: MACD line, signal line, histogram with crossover markers.
   - PPO panel: PPO line, signal line, zero line with crossover markers.
   - SMA crossover markers (orange diamonds) on the price panel.

### Data Pipeline

**`populate_tickers.py`:**
- Fetches S&P 500 tickers from Alpaca.
- Gets OHLCV bars since 2015 for weekly/daily, 3 months for 1-hour.
- Stores in the 3 timeframe tables.
- Uses 10 parallel workers.

**`capture_hourly.py`:**
- Runs during market hours (9:30 AM — 4:00 PM ET, weekdays only).
- Fetches latest trade prices in batches of 200 via `StockLatestTradeRequest`.
- Upserts into `tbl_scanner_tickers_1hour`.
- On conflict: updates `high = GREATEST(current, new)`, `low = LEAST(current, new)`, `close = new value`.

### Convergence Logic (Controller)

The scanner filters for tickers that have experienced all three crossover types (MACD, PPO, SMA) at any point. Results are sorted by the most recent crossover date across all 3 signals, so the freshest signals appear first. The `cross_bullish` flag determines ticker color based on whether the most recent crossover event was bullish or bearish.

---

# 3. Key Differences

| Aspect | Swing Trading | Scanner |
|--------|---------------|---------|
| **Goal** | Automated live trading | Market analysis / signal discovery |
| **Strategy** | Chandelier Exit (always-in) | 3-way crossover convergence |
| **Data Frequency** | Daily bars | Weekly, Daily, 1-Hour |
| **Decision Maker** | `TradeExecutorService` | `ScannerController` (UI only) |
| **Optimizer** | Grid search + coordinate ascent | Not optimized |
| **Entry** | Always-in (no filter) | Requires 3 aligned crossovers |
| **Exit** | ATR trailing stop | N/A (scanner only, no trading) |
| **Parameters Per Ticker** | Yes (optimized individually) | No (global config values) |
| **Execution** | Live Alpaca orders | Read-only |
| **Target** | Sharpe ratio maximization | Crossover recency and convergence |

---

# 4. Parameters Quick Reference

| Parameter | Swing Trading | Scanner |
|-----------|---------------|---------|
| Fast MA | `macd_fast` [14,18,22] | 24 |
| Slow MA | N/A (uses ATR) | 52 |
| Signal Line | N/A | 18 (MACD), 9 (PPO) |
| ATR Period | `macd_fast` (same as chandelier) | 14 |
| ATR Multiplier | `bb_std` [2.5, 3.0, 3.5] | 2.0 |
| Primary Metric | Sharpe Ratio | Crossover recency |
