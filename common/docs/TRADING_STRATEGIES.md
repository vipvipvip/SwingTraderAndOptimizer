# Trading Strategies

## Overview

This project contains three distinct trading systems that operate independently:

| # | Name | Universe | Signals | Status |
|---|------|----------|---------|--------|
| 1 | **CHAND** (trio EW book) | QQQ/VTI/VTV | Weekly equal-weight rebalance (weekday via `CHAND_REBALANCE_DAYS`; Mon now, Fri next) — NO signals | ✅ Live (Laravel) |
| 2 | ~~**EMAC**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 3 | ~~**MTCS**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 4 | **MTF Top-N** (Multi-TF rotation) | VTI stocks + ETFs | gap_w + atr_dist + freshness → top 10 daily | ✅ Live (Phase 2) |
| 5 | **Daily Signal** (Multi-TF alerts) | All enabled (VTI stocks + ETFs) | 1-hour fresh cross + score | ✅ Slack @ 5:00 PM |

All systems share the same database (`swingtrader`) and Alpaca data source, but their logic, parameters, and objectives are entirely separate.

---

# 1. CHAND — Weekly Equal-Weight Trio Book

**Service:** `TradeExecutorService` (execution), `StrategyService` (parameter management), `AlpacaService` (broker API)  
**Command:** `trades:execute-EW-ETF` (gated to `CHAND_REBALANCE_DAYS` in `.env`, one rebalance per week)

> **Status: converted 2026-09-12.** CHAND previously ran per-ticker Chandelier
> Exit (trailing ATR stop) tuned by a nightly brute-force grid-search optimizer.
> It is now a **pure equal-weight book**: long QQQ/VTI/VTV, each at `equity/3`,
> rebalanced ONCE per eligible weekday (`CHAND_REBALANCE_DAYS`, Mon=1..Sun=7;
> currently **Monday**, plan to switch to **Friday** — edit the `.env` value).
> No entry/exit signals, no stop-loss, no optimizer. The chandelier logic +
> `nightly_optimizer.py` remain in the repo as legacy (not called on the live
> path); the nightly optimizer timer/systemd unit is DISABLED.

### Strategy Type

**Always-In Equal-Weight Beta** — the trio is the whole-market regime book (the "what's CHAND for?" answer from the trio comparison).

Backtest comparison (`swingtrader/services/mtf/backtest_trio_ew.py`, 2023-06-30 → 2026-09-11, 803d, cost 0.05%):
A. EW weekly-rebalance **+81.67% / 18.7% DD / 58.4% weekly-up** — identical to B&H (+81.45%)
B. EW + weekly-ratchet gate +85.73% / 8.7% DD / 57.2% — the only variant that cuts drawdown
Decision: run **A** (pure EW). Rationale: it is sound, zero-parameter, no brute force, and the user's "winner" definition (highest win% + fewest trades) lands on "just hold the trio".

### Rebalance Rule

```
ON rebalance day (ET), once per day:
    equity_N = account_equity / 3
    for each of QQQ / VTI / VTV:
        if market_value > equity_N:  trim excess shares (REBALANCE_TRIM)
        if market_value < equity_N:  top up qty (weighted-avg entry merge / new leg)
```

- Trims never fully close a leg; top-ups re-establish a missing leg from scratch.
- Rebalance day(s): `CHAND_REBALANCE_DAYS` in `swingtrader/backend/.env` (Mon=1..Sun=7, comma-separated; currently `1`, plan `5` for Friday).
- Executor: `TradeExecutorService::rebalanceEqualWeightWeekly()`.
- Once-per-day marker file: `storage_path('chand_last_rebalance.txt')`.
- `trades:execute-EW-ETF --override` forces a manual run on any day (recovery/testing) and `--dry-run` previews the rebalance without orders.

### Parameters

None — the strategy has no tunable input. `strategy_parameters` rows for QQQ/VTI/VTV/BLENDED are legacy and unused on the live path.

### Capital Allocation

Fixed equal weight: every leg = `equity / 3`. Trimmed proceeds fund the top-ups.

### Backtest Cost Model

| Parameter | Value |
|-----------|-------|
| Round-trip cost | 0.05% |
| Initial capital | 100,000 |
| Window | Jul 2023 → now (settled bars) |

### Live Execution Flow (`TradeExecutorService`)

1. `ExecuteEWETF` (laravel) gates to the configured rebalance day(s) (ET), checks the once-per-day marker, then calls `rebalanceEqualWeightWeekly()`.
2. `syncLiveTradesFromAlpaca()` reconciles DB → Alpaca order history first (self-healing).
3. Fetch account equity + positions; compute `equity/3` per leg.
4. Trim overweights (partial sell, preserves/open-trade P&L), top-up underweights (weighted-avg entry merge via `rebalanceTopUp`).
5. Snapshot equity, sync positions cache, Slack `[CHAND]` summary when trades occurred.

### Risk Characteristics

- Full market beta: a 2022-style bear takes the book down with it (max DD ≈ trio B&H ≈ 18.7%).
- No stops, no timing, no whipsaws — highest win% / fewest-trades design.
- The weekly-ratchet gate (variant B, DD 8.7%) was the researched alternative but adds ~400-500 trades/3y and was **not adopted** (user prefers pure EW hold).

### Console Commands

| Command | Description |
|---------|-------------|
| `trades:execute-EW-ETF` | Weekly EW rebalance (Fridays only, once/day) |
| `trades:execute-EW-ETF --override` | Force a mid-week manual rebalance |
| `trades:execute-EW-ETF --force-test` | Place 1-share round-trips for testing |
| `equity:snapshot` | Snapshot current account equity to DB |
| `positions:sync` | Sync Alpaca positions to `positions_cache` |
| `optimize:nightly` | **LEGACY** chandelier optimizer — do not run (CHAND is EW-only) |

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
**Account:** Alpaca paper (stocks #PA368CPXNS13 / ETFs #PA3U8GZ96PEN — keys in `mtf/.env`)

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
**Universe:** All enabled tickers in `tbl_stock_tickers` — 1,435 VTI stocks + 28 ETFs (same universe as MTF Top-N). *NOT S&P 500; older docs that say "S&P 500" are outdated.*

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

### Relationship to MTF Top-N — same inputs, different trigger (IMPORTANT)

The Daily Signal and MTF Top-N share the **same universe**, the **same hard filters** (weekly+daily EMA10>SMA40, close above ATR stop), and the **same score formula** (`gap_w/20 + atr_dist/1.5 + freshness`). They are **not connected** — the Daily Signal does not feed into MTF, and neither consumes the other's output. The only difference is the **selection trigger**:

| | MTF Top-N | Daily Signal |
|---|---|---|
| **Trigger** | State-driven: highest current score → top 10 | Event-driven: fresh 1-hour EMA>SMA cross on the **last completed bar** |
| **Question** | "Which names are strongest right now?" | "Who just broke out today?" |
| **Typical score at listing** | ≥ ~5.0 (extended: big `gap_w`/`atr_dist`) | 1.0–3.5 (fresh cross = price near averages) |
| **Output** | Real Alpaca orders (stocks + ETFs) | Slack alert + CSV only |

**Why they almost never overlap:** a fresh 1-hour cross happens when a name is *near its averages* — `gap_w` and `atr_dist` are small by definition at that moment, so the score is low and it ranks far below the MTF top-10 cutoff. MTF's top-10 is filled with *extended* names (e.g. ZBRA at `gap_w` 52.9%) that crossed weeks/months ago and therefore don't produce "fresh cross today" events.

**The exception proves the rule:** PBF on 2026-08-10 — fresh hourly cross *and* already-extended (`gap_w` 67%) → score 5.1 → listed by the Daily Signal **and** in the MTF top-10, traded live (+2.9%). This only happens when the gap explodes before the hourly cross.

**Implication:** the Daily Signal is the *early/event* view (fresh triggers), MTF is the *extended/state* view (already-run). Making MTF prefer fresh-cross names is the `--score near`/`early` variant, which backtested decisively worse (−61.5% at scale) — the momentum terms (`gap_w`/`atr_dist`) are what capture the explosive moves.

# 6. Key Differences

| Aspect | CHAND | Scanner | MTF Top-N | Daily Signal |
|--------|-------|---------|-----------|--------------|
| **Goal** | Whole-market beta book | Market screening | Rotation trading | Signal alerts |
| **Strategy** | EW weekly rebalance (no signals) | 3-way crossover convergence | Multi-TF score top-N | Multi-TF fresh crosses |
| **Universe** | QQQ/VTI/VTV | S&P 500 | VTI stocks + ETFs | All enabled (VTI stocks + ETFs) |
| **Data Frequency** | Daily bars (weekly trigger) | Weekly, Daily, 1-Hour | Weekly, Daily, 1-Hour | Weekly, Daily, 1-Hour |
| **Execution** | Live Alpaca orders | Read-only | Live Alpaca orders (Phase 2) | Slack + CSV only |
| **Entry** | Always-in (all three, equity/3) | 3 aligned crossovers | Top-N by score | Fresh 1-hour cross |
| **Exit** | None (hold) | N/A (scanner only) | Dropped from top N | N/A |
| **Parameters** | None (fixed weights) | Fixed | Fixed | Fixed |
| **Return (backtest)** | +81.7% (EW weekly rebal) | N/A | +5,469% (unfiltered) | N/A |
| **Max DD** | 18.7% (≈ trio B&H) | N/A | 22.2% | N/A |

---

# 7. Parameters Quick Reference

| Parameter | CHAND | Scanner | MTF Top-N | Daily Signal |
|-----------|-------|---------|-----------|--------------|
| Fast MA | **none (EW-only since 2026-09-12)** | 24 | 10 (EMA) | 10 (EMA) |
| Slow MA | N/A | 52 | 40 (SMA) | 40 (SMA) |
| Signal Line | N/A | 18 (MACD), 9 (PPO) | N/A | N/A |
| ATR Period | legacy chandelier only | 14 | N/A | N/A |
| ATR Multiplier | legacy chandelier only | 2.0 | N/A | N/A |
| Primary Metric | **none — fixed equity/3 weights** | Crossover recency | Score (gap+atr+fresh) | Momentum score |
