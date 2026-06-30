# SwingTrader System Architecture

A full-stack algorithmic swing trading system using **Chandelier Exit + Linear Regression Exit** strategy with nightly parameter optimization via grid search + coordinate ascent, live trading via Alpaca, and a Svelte dashboard.

---

## System Components & Dependencies

```
┌─────────────────────────────────────────────────────────────────────┐
│                      LARAVEL BACKEND (port 9000)                     │
│  php artisan serve  │  systemd: swingtrader-backend.service          │
├─────────────────────────────────────────────────────────────────────┤
│  TradeExecutorService.php   — signal generation, order placement     │
│  AlpacaService.php          — Alpaca API wrapper                     │
│  StrategyService.php        — per-ticker active params + live metrics│
│  EquityService.php          — account equity snapshots               │
│                                                                     │
│  Scheduler (Laravel Kernel.php, runs inside backend process):       │
│    trades:execute-daily  → every 5 min, Mon–Fri 09:30–16:05 ET     │
│    positions:sync        → every 5 min, Mon–Fri 09:30–16:05 ET     │
│    equity:snapshot       → daily 16:05 ET                           │
│    logs:check-and-alert  → daily 09:15 ET + 16:10 ET weekdays      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      SVELTE FRONTEND (port 5173)                     │
│  npm run dev  │  systemd: swingtrader-fe-dev.service                 │
├─────────────────────────────────────────────────────────────────────┤
│  App.svelte              — dashboard: cards, trade history, charts   │
│  StrategyCard.svelte     — per-ticker card (params, entry/stop, PnL)│
│  TradesHistoryTable.svelte — live + backtest trade log              │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL (Docker, port 5432)                  │
│  systemd: swingtrader-db.service                                     │
├─────────────────────────────────────────────────────────────────────┤
│  tbl_etf_tickers_1hour   — hourly OHLCV for ETF tickers              │
│  strategy_parameters     — active (base_case=true) per-ticker params│
│  live_trades             — executed Alpaca trades                   │
│  backtest_trades         — optimizer simulated trades               │
│  optimization_history    — per-run results (sharpe, return, params) │
│  equity_snapshots        — daily equity tracking                    │
│  positions_cache         — Alpaca position sync                     │
│  tbl_stock_tickers       — 503 SP500 stock symbols (scanner)        │
│  tbl_scanner_tickers(_daily,_1hour) — OHLCV + MACD/PPO/SMA/ATR    │
│  tbl_stock_analyzer      — fundamental data (EPS, PE, revenue...)   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      TIMERS & CRON (systemd + cron)                  │
├─────────────────────────────────────────────────────────────────────┤
│  TIMER                    SCHEDULE          WHAT IT DOES             │
│  ─────────────────────────────────────────────────────────────────── │
│  swingtrader-optimizer   02:00 ET daily     Run optimizer (Python)   │
│  swingtrader-backup      16:15 ET daily     pg_dump backup           │
│  scanner-update          09:00 ET Mon–Fri   Populate weekly + daily  │
│  scanner-hourly          10–16 ET Mon–Fri   Capture hourly bars      │
│                                                                     │
│  Also: cron: trades:execute-daily every 5 min (during market hours) │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      SCANNER (Python, SP500 stocks)                  │
│  scanner/services/scripts/                                           │
├─────────────────────────────────────────────────────────────────────┤
│  populate_tickers.py     — fetch OHLCV from Alpaca (incremental)    │
│  compute_indicators.py   — MACD, PPO, SMA crossovers, ATR stop      │
│  capture_hourly.py       — hourly bar capture during market hours   │
│                                                                     │
│  Timer: scanner-update   → 09:00 ET weekdays (week + day timeframes)│
│  Timer: scanner-hourly   → 10–16 ET hourly (hour timeframe)         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      OPTIMIZER (Python, ETF tickers)                 │
│  swingtrader/services/optimizer/                                     │
├─────────────────────────────────────────────────────────────────────┤
│  nightly_optimizer.py    — 2-pass grid search + coordinate ascent   │
│  parameter_optimizer.py  — backtest engine with Chand+Reg exit      │
│  db.py                   — PostgreSQL persistence layer              │
│  run_nightly.sh          — bash wrapper called by systemd timer      │
│                                                                     │
│  Timer: swingtrader-optimizer → 02:00 ET daily                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### ETF Bars (Hourly, for CHAND+REG Trading)
```
Alpaca bars API (IEX) ──► nightly_optimizer.py (02:00 ET)
                              │
                              ├── fetch_prices.py → data_fetcher.py
                              │     ├── Checks MAX(timestamp) in tbl_etf_tickers_1hour
                              │     ├── Fetches new 1-hour bars from Alpaca incrementally
                              │     ├── Filters to regular hours (9:30 AM - 4:00 PM ET)
                              │     └── INSERT ON CONFLICT DO NOTHING
                              │
                              └── tbl_etf_tickers_1hour ──► optimizer backtest
                                                           ──► live trading (5 min)
                                                           ──► exit/entry signals
```

The CHAND+REG live trading system reads **resampled daily bars** from `tbl_etf_tickers_1hour`:
- PHP (`MarketDataTrait::getOhlcBars`): filters hourly bars to daily (UTC hour 4-5, minute 0)
- Python (`ParameterOptimizer._backtest_with_params`): same daily filter
- Live price (`TradeExecutorService::getCurrentPrice`): latest hourly close (no daily filter)
- Alpaca latest trade API used as fallback for current price

### EMAC Crossover System (Separate, 30-min Bars)
A separate EMA(10)/SMA(40) + MACD(10,40,400) crossover system using **30-min bars built from raw trade ticks**:

```
Alpaca trades API (IEX) ──► emac-runner.service (2-min poll loop)
                              │
                              ├── emac_raw_trades (every tick persisted)
                              │
                              ├── CandleBuilder (filters to regular hours 9:30-16:00 ET)
                              │     └── 30-min OHLCV bars → emac_candles
                              │
                              ├── Strategy (EMA/SMA crossover + MACD hist filter)
                              │     ├── BUY: EMA>SMA AND MACD hist>0 AND either just flipped
                              │     └── SELL: EMA<SMA AND MACD hist<0 AND either just flipped
                              │
                              └── Executor (Alpaca MARKET orders)
                                    ├── Pass 1: sell positions first
                                    └── Pass 2: split remaining cash equally among buy signals
```

Key differences from CHAND+REG:
- **Data source**: Raw trade ticks (not pre-computed bars)
- **Timeframe**: 30-min bars (not 1-hour/daily resampled)
- **Data pipeline**: Real-time via 2-min poll loop (not nightly batch)
- **Strategy**: EMA/SMA crossover + MACD filter (not Chandelier/Regression)
- **Scope**: QQQ, VTI, VTV (same tickers, independent system)
- **Account**: Separate Alpaca paper account, separate DB tables (`emac_*`)
- **Service**: `emac-runner.service` (systemd, long-running daemon, not timer-based)

### Stock Scanner Data (SP500, for Screening)
```
Alpaca ───┬── scanner-update (09:00 daily) ──► tbl_scanner_tickers (weekly)
           │                                     tbl_scanner_tickers_daily
           │                                     compute_indicators → MACD/PPO/SMA/ATR
           │
           └── scanner-hourly (hourly)       ──► tbl_scanner_tickers_1hour
                                                compute_indicators → same indicators
```

### Live Trading
```
cron (5 min) ──► trades:execute-daily ──► TradeExecutorService
                    │                           │
                    ├── RECONCILE:              ├── Pass 1: exits for each ticker
                    │   syncLiveTradesFromAlpaca│   (Chandelier + Regression check)
                    │   (self-heal DB from      ├── Pass 2: pooled cash entry
                    │    Alpaca order history)   │   (split equally among buy signals)
                    ├── getAccount() (Alpaca)   └── placeOrder() (Alpaca MARKET)
                    ├── getPositions() (Alpaca)
                    │                           └── positions:sync (after trades)
                    │                                 (populate positions_cache)
                    └── Slack webhook ──► report if trades occurred
```

---

## Strategy

### Tickers
QQQ, VTI, VTV (enabled in `tbl_etf_tickers`). BLENDED is the portfolio composite.

### Exit — Chandelier Exit (always active)
```
highest_high = max(high since entry, ... , current high)
stop_level   = highest_high - ATR(period) × multiplier
if close < stop_level → SELL at next bar open
```

### Exit — Linear Regression Exit (optional, per ticker)
```
slope = linearRegSlope(close[-window:], window)  // $/day
normalized = slope / ATR  (or % of close, or raw $/day)
if normalized < threshold (negative slope = declining) → SELL
```

Runs AFTER Chandelier check. If either fires, the position exits.

### Entry — Chandelier Trigger (optional, per ticker)
```
entry_level = highest_high(period) - ATR × entry_mult
if close > entry_level → BUY signal
```
If `entry_mult` is null: always enter on next bar open.

### Cash Management — Pooled
Available cash is split equally among all tickers with buy signals. No per-ticker allocation weights.

### Self-Healing Reconciliation

Every trading cycle starts with `syncLiveTradesFromAlpaca()`, which:
1. Fetches ALL filled orders from Alpaca order history
2. Creates/updates `live_trades` rows with actual fill prices (`filled_avg_price`)
3. Matches sell orders to existing open buys and closes them
4. Fetches current Alpaca positions and reconciles entry_price + quantity
5. Creates DB entries for positions that exist on Alpaca but not in DB (e.g., manual trades)
6. Closes stale DB entries that don't match Alpaca positions

This makes **Alpaca the source of truth** — the DB is a cache that self-heals every 5 minutes. Even if:
- An order partially fills → reconciliation corrects qty/price
- A manual trade is placed on Alpaca → reconciliation picks it up
- The DB is wiped → reconciliation rebuilds from Alpaca order history
- Entry price was estimated → reconciliation overwrites with actual fill

### Signal Execution
All orders are Alpaca MARKET orders. Exit type (`chandelier`, `regression`, `force_close`) is tracked in `backtest_trades.exit_type`. Entry prices use `filled_avg_price` from the Alpaca order response (not pre-order price estimate).

### Scheduler
```
cron: */5 * * * * /usr/bin/php ... artisan trades:execute-daily >> /dev/null 2>&1
```
Runs every 5 min regardless of market hours. The command checks `alpacaService->getClock()['is_open']` and exits early if market is closed.

---

## Live Trading Flow (TradeExecutorService)

```
executeForAllTickers($override = false)
  │
  ├── RECONCILE: syncLiveTradesFromAlpaca()
  │     ├── Fetch all filled orders from Alpaca
  │     ├── Create/update live_trades with actual fill prices
  │     ├── Match sells → close open buys
  │     ├── Reconcile positions: update qty + entry_price
  │     ├── Create DB entries for Alpaca-only positions
  │     └── Close stale DB entries (no Alpaca match)
  │
  ├── getAccount() → $availableCash
  │
  ├── Pass 1: EXITS ──► for each ticker in position:
  │     ├── computeChandelierSignal(...)
  │     │     ├── calculateATR(period)
  │     │     ├── linearRegSlope() (if reg params set)
  │     │     └── return (buy|sell|hold)
  │     │
  │     └── if sell signal → handleSellSignal()
  │           └── placeOrder('sell') + record trade
  │
  ├── if $availableCash ≤ 0 → bail early (skip entry pass)
  │
  ├── Pass 2: ENTRIES ──► handlePooledEntries()
  │     ├── for each ticker NOT in position:
  │     │     └── check entry condition
  │     ├── for each buy signal:
  │     │     ├── placeOrder('buy')
  │     │     ├── store filled_avg_price as entry_price
  │     │     └── if adding to position: weighted avg price
  │     └── split cash equally among all qualifying tickers
  │
  └── Pass 3: OVERRIDE (only if --override flag)
        └── executeManualOverride()
              └── force-check entry for ALL tickers (even in-position)
                    deploy idle cash equally into qualifying ones
```

---

## Optimizer (nightly, 02:00 ET)

### Two-Pass Grid Search
```
Pass 1 — Chandelier-only:
  period  ∈ [14, 18, 22]
  mult    ∈ [2.0, 2.5, 3.0, 3.5, 4.0]
  entry   ∈ [1.0, 1.5, …]  (dependent on params)
  27+ combos per ticker

Pass 2 — Fix best Chandelier, grid Regression:
  reg_window     ∈ [3, 5, 8, 13]
  reg_threshold  ∈ [-0.5, -1.0, -2.0, -3.0]
  reg_type       ∈ [slope_atr, slope_pct, slope]
  32+ combos per ticker

Total: ~59 combos per ticker, ~2 seconds each
```

### Coordinate Ascent (Portfolio Level)
1. Run individual optimization for each ticker independently
2. Take top 5 candidates per ticker as coordinate ascent pool
3. Run portfolio backtest with **pooled cash** (all cash into highest-Sharpe trigger)
4. Promote params that improve blended Sharpe over baseline

### Output
- Per-ticker best params → `strategy_parameters` table (`base_case=true`)
- BLENDED portfolio record in `optimization_history` with nested JSON params
- All backtest trades in `backtest_trades` with `exit_type` tracking

---

## Scanner (09:00 daily + hourly market hours)

### populate_tickers.py (incremental)
```
For each ticker:
  1. Query MAX(date) FROM target table
  2. Fetch bars AFTER that date from Alpaca
  3. INSERT ON CONFLICT DO NOTHING
```
No delete-all-reinsert. Only fetches missing data.

### compute_indicators.py
Computes per-bar: MACD line/signal/histogram, MACD crossover (bull/bear), PPO line/signal/histogram, PPO crossover (bull/bear), SMA crossover (bull/bear), ATR stop level.

### Timeframes
| Table | Timeframe | Timer | Data Range |
|-------|-----------|-------|------------|
| tbl_scanner_tickers | Weekly | scanner-update (09:00 daily) | 2017–present |
| tbl_scanner_tickers_daily | Daily | scanner-update (09:00 daily) | 2017–present |
| tbl_scanner_tickers_1hour | Hourly | scanner-hourly (hourly 10–16) | 90-day lookback |

---

## Database Schema

### Core Tables

**tbl_etf_tickers** — ETF symbols for trading
```
id (PK), symbol (QQQ|VTI|VTV|BLENDED), enabled, allocation_weight
```

**tbl_etf_tickers_1hour** — Hourly OHLCV for ETF tickers
```
id (PK), ticker_id (FK), timestamp, open, high, low, close, volume
~1478 rows per ticker (2017–present)
```

**strategy_parameters** — Active optimized parameters per ticker
```
id (PK), ticker_id (FK), base_case (boolean)
chandelier_period, chandelier_mult, chandelier_entry_mult
reg_slope_window, reg_slope_threshold, reg_slope_type
sharpe_ratio, total_return, win_rate, max_drawdown, total_trades
```

**live_trades** — Executed Alpaca orders (reconciled every cycle)
```
id (PK), ticker_id (FK), symbol, side, quantity
entry_price, exit_price, entry_at, exit_at
pnl_dollar, pnl_pct, status (open|closed)
strategy_signal (CHANDELIER_ENTRY|CHANDELIER_EXIT|RECONCILED|MANUAL_BUY|FORCE_TEST)
alpaca_order_id
```

Entry prices are sourced from Alpaca's `filled_avg_price` (actual fill, not pre-order estimate).
When positions are incremented, `entry_price` is recalculated as weighted average.
Stale entries are automatically closed during reconciliation.

**backtest_trades** — Simulated trades from optimizer
```
id (PK), ticker_id (FK), entry_at, entry_price, exit_at, exit_price
return, pnl_dollar, days_held, exit_type (chandelier|regression|force_close)
portfolio_value
```

**optimization_history** — Per-run audit trail
```
id (PK), ticker_id (FK), run_date, best_sharpe, best_return, best_win_rate
total_combinations, runtime_seconds, params (JSONB), promoted
```

### Scanner Tables

**tbl_stock_tickers** — 503 SP500 stock symbols
**tbl_scanner_tickers** — Weekly OHLCV + MACD/PPO/SMA/ATR indicators
**tbl_scanner_tickers_daily** — Daily OHLCV + indicators
**tbl_scanner_tickers_1hour** — Hourly OHLCV + indicators (90-day)
**tbl_stock_analyzer** — Fundamental data (EPS, PE, revenue, dividends)

---

## Safety Mechanisms

1. **Auto-Reconciliation**: Every trading cycle starts with `syncLiveTradesFromAlpaca()`. The DB self-heals from Alpaca's actual positions — no manual DB resets needed if state diverges.
2. **Market Hours**: Alpaca clock check via `getClock()['is_open']`. Only executes 09:30–16:05 ET weekdays.
3. **Cash Gating**: If `$availableCash ≤ 0` after exit pass, entry pass is skipped entirely.
4. **Same-Day Exit Guard**: Prevents re-entry on same day as exit (matches backtest behavior).
5. **No Overlapping**: Scheduler uses `withoutOverlapping(10)` to prevent concurrent runs.
6. **Strategy Validation Gate**: Blocks trading if no `base_case=1` params exist or required params are missing.
7. **Graceful Degradation**: API timeouts with retry logic. Fallback defaults for missing params.
8. **Manual Override**: `--override` flag force-checks entry even for in-position tickers to deploy idle cash.
9. **Incremental Scanner**: `populate_tickers.py` only fetches bars after `MAX(date)` — no delete-all-reinsert.

---

## Monitoring

**Health Check:**
```bash
bash /home/dikesh/data/dev/SwingTraderAndOptimizer/common/scripts/health-check.sh
# Checks: DB, ETF bars per ticker, scanner recency, optimizer runs,
#         strategy params, systemd services, API endpoints
```

**Backend Logs:**
```bash
sudo journalctl -u swingtrader-backend -f
```

**Optimizer Logs:**
```bash
tail -f /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/optimizer/logs/nightly.log
```

**Trade Activity:**
Slack webhook reports sent when any trade (buy/sell) occurs via `SLACK_WEBHOOK_URL`.

---

**Last Updated:** 2026-06-29
**Tickers:** QQQ, VTI, VTV (+ BLENDED portfolio composite)
**Broker:** Alpaca (paper)
**Database:** PostgreSQL (Docker)
**Scheduler:** systemd timers + cron + Laravel Kernel schedule
**Frontend:** Svelte + Vite (port 5173)
**Backend:** Laravel 11 (port 9000)
