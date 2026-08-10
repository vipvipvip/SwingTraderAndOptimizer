# Trading Strategies

## Overview

This project contains three distinct trading systems that operate independently:

| # | Name | Universe | Signals | Status |
|---|------|----------|---------|--------|
| 1 | **CHAND** (Chandelier Exit) | QQQ/VTI/VTV | Optimized trailing stop | ✅ Live (Laravel) |
| 2 | ~~**EMAC**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 3 | ~~**MTCS**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 4 | **MTF Top-N** (Multi-TF rotation) | VTI stocks + ETFs | gap_w + atr_dist + freshness → top 10 daily | ✅ Live (Phase 2) |
| 5 | **Daily Signal** (Multi-TF alerts) | S&P 500 | 1-hour fresh cross + score | ✅ Slack @ 5:00 PM |

All systems share the same database (`swingtrader`) and Alpaca data source, but their logic, parameters, and objectives are entirely separate.

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
   - `TradeExecutorService.computeChandelierSignal()` → fetch OHLC bars from `tbl_etf_tickers_1hour` table, compute ATR, check Chandelier stop.
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

---

# 3. MTCS — Hilbert Sine/Lead Crossover (STOPPED)

> ⚠️ **MTCS was stopped and replaced by MTF Top-N.** The `mtcs-runner.service` was removed from systemd, and the entire `swingtrader/services/mtcs/` directory was deleted (2026-08-10) along with the `mtcs_positions`/`mtcs_trades` DB tables. This section is historical only.

**Service:** ~~`mtcs-runner.service`~~ (removed)  
**Location:** ~~`swingtrader/services/mtcs/`~~ (deleted)  
**Tickers:** QQQ, VTI, VTV  
**Account:** Alpaca paper (dedicated account #PA3NCXU4O2CN)

### Strategy
Uses Hilbert Transform spectral analysis to detect dominant market cycles
and generate BUY/SELL signals at cycle turning points.

- **Bars:** Daily OHLC from `tbl_etf_tickers_1hour`
- **Signal:** Hilbert Transform → sine/lead-sine crossover
  - BUY when sine crosses **above** lead (cycle trough)
  - SELL when sine crosses **below** lead (cycle peak)
- **Execution:** Real Alpaca orders — BUY pools cash equally across signals, SELL liquidates full position
- **Uncorrelated** from CHAND (daily return correlation: -0.017)

### Parameters
| Parameter | Value |
|-----------|-------|
| Detrend period | 30 |
| Smoothing | 5 |
| Warmup bars | 60 |
| Poll interval | 1800s (30 min) |

### Backtest Results (Blended QQQ/VTI/VTV)
| Metric | Value |
|--------|-------|
| Return | 68.5% |
| Sharpe | 1.14 |
| Win rate | 59% |
| Max DD | 15.6% |
| Trades | 147 |

# 4. MTF Top-N (Multi-TF Rotation) — Replaces MTCS

**Service:** `swingtrader-mtf-scorer.service` (systemd, oneshot — Phase 2 live)  
**Location:** `swingtrader/services/mtf/runner.py`  
**Universe:** VTI stocks + ETFs (Phase 2)  
**Account:** Alpaca paper (stocks #PA3PPZAZR76Z / ETFs #PA3U8GZ96PEN)

### Strategy
Daily rotation into top N S&P 500 stocks ranked by Multi-TF score:
- **Weekly filter:** EMA(10) > SMA(40) (bullish weekly trend)
- **Daily filter:** EMA(10) > SMA(40) (bullish daily trend)
- **Score:** `min(gap_w/20, 3) + min(atr_dist/1.5, 3) + max(0, 2 - days_since_weekly/60)`
- **Rebalance:** Daily — sell dropped, buy new entrants, equal weight
- **Exit:** Dropped from top N → sell at next day's open

### Backtest Results (Daily Rebalance, Jul 2023–Jul 2026)
| Metric | Value |
|--------|-------|
| Return | +5,299% ($100k → $5.4M) |
| Max DD | 22.2% |
| Win rate | 68% |
| Avg win | +16.24% |
| Avg loss | -5.31% |

### Phase Plan
| Phase | Action | Status |
|-------|--------|--------|
| 1 | Paper trading — log picks, CSV portfolio, Slack alerts. MTCS runs alongside. | 🚧 In Progress |
| 2 | Stop MTCS, wire MTF into Alpaca executor (--top-n 5) | ⏳ Pending |
| 3 | Scale to --top-n 10, add exit rules | ⏳ Pending |

# 5. Daily Signal Service (Signal-Only)

**Service:** `swingtrader-daily-signal.timer` (systemd, Mon–Fri 5:00 PM ET)  
**Location:** `swingtrader/services/ema_sma_crossover/daily_signal_service.py`  
**Universe:** S&P 500 (stocks from scanner DB)

### Purpose
Multi-timeframe EMA(10)/SMA(40) scanner that detects fresh 1-hour entry signals within weekly+daily uptrend. **Does not trade** — sends Slack alerts only.

### Strategy
- **Bars:** Weekly + daily + 1-hour from `tbl_scanner_tickers*` tables
- **Entry filter:** Weekly EMA(10) > SMA(40) AND daily EMA(10) > SMA(40) AND fresh 1-hour EMA cross above SMA(40)
- **Scoring:** Freshness-based momentum score with infancy buckets
- **Output:** Slack alert with top signals sorted by score, infancy-highlighted entries, market breadth regime

### Output
- **Slack:** Tagged `[DAILY]` prefix (distinct from `[MTF-TopN]` live runner messages)
- **CSV:** Columns: `date,ticker,action,close_price,ema,sma,reason`

# 6. Key Differences

| Aspect | CHAND | Scanner | MTF Top-N | Daily Signal |
|--------|-------|---------|-----------|--------------|
| **Goal** | Automated live trading | Market screening | Rotation trading | Signal alerts |
| **Strategy** | Chandelier Exit (always-in) | 3-way crossover convergence | Multi-TF score top-N | Multi-TF fresh crosses |
| **Universe** | QQQ/VTI/VTV | S&P 500 | VTI stocks + ETFs | S&P 500 |
| **Data Frequency** | Daily bars | Weekly, Daily, 1-Hour | Weekly, Daily, 1-Hour | Weekly, Daily, 1-Hour |
| **Execution** | Live Alpaca orders | Read-only | Live Alpaca orders (Phase 2) | Slack + CSV only |
| **Entry** | Always-in (no filter) | 3 aligned crossovers | Top-N by score | Fresh 1-hour cross |
| **Exit** | ATR trailing stop | N/A (scanner only) | Dropped from top N | N/A |
| **Parameters** | Optimized per ticker | Fixed | Fixed | Fixed |
| **Return (backtest)** | 97.8% | N/A | +5,469% (unfiltered) | N/A |
| **Max DD** | 10.0% | N/A | 22.2% | N/A |

---

# 7. Parameters Quick Reference

| Parameter | CHAND | Scanner | MTF Top-N | Daily Signal |
|-----------|-------|---------|-----------|--------------|
| Fast MA | `macd_fast` [14,18,22] | 24 | 10 (EMA) | 10 (EMA) |
| Slow MA | N/A (uses ATR) | 52 | 40 (SMA) | 40 (SMA) |
| Signal Line | N/A | 18 (MACD), 9 (PPO) | N/A | N/A |
| ATR Period | `macd_fast` (same as chandelier) | 14 | N/A | N/A |
| ATR Multiplier | `bb_std` [2.5, 3.0, 3.5] | 2.0 | N/A | N/A |
| Primary Metric | Sharpe Ratio | Crossover recency | Score (gap+atr+fresh) | Momentum score |
