# Anchored Summary — SwingTraderAndOptimizer

## Goal
Build and identify the differentiators for a multi-timeframe EMA(10)/SMA(40) strategy that screens S&P 500 stocks across weekly → daily → 1-hour for explosive breakout candidates, with a signal-only daily service, scanner UI integration, and a live 30-min automated runner already in place.

## Constraints & Preferences
- 30-min EMAC live runner (QQQ/VTI/VTV, Alpaca paper) must remain untouched
- Daily Signal Service runs Mon–Fri 4:30 PM ET via systemd timer, sends Slack alerts tagged `[DAILY]`, logs to CSV — no trading
- Backtest scans S&P 500 scanner DB tables (`tbl_scanner_tickers*`), not EMAC ETF tables
- Backtest entry: weekly EMA(10) > SMA(40) AND daily EMA(10) > SMA(40) AND 1-hour fresh EMA cross above SMA(40)
- Exit variants tested: 1-hour EMA cross below (default), ATR trailing stop, daily EMA cross below
- Mid-session scope: locate explosive stocks before they explode with focus on infancy entries (weekly cross < 60 days)

## Progress
### Done
- Added `--exit daily-ema` to `backtest_multitf.py` — detects daily EMA cross below SMA on fresh daily bar; won big on explosive stocks (WDC +1,517%, APP +741%, MU +669%) with dramatically fewer trades
- Ran full 502-stock backtest with `--exit daily-ema` — strategy captures +360% avg on top 25 (vs BH +950%) but avoids catastrophic losers (KLAC +99% vs BH -50%)
- Wrote and later removed `analyze_explosives.py` — analyzed 4,967 entry signals across 503 stocks to find what differentiates explosive 90-day returns
- Discovered top 3 predictive features at entry: **weekly gap from SMA(40)** (30% vs 12.6%), **ATR distance %** (2.2% vs 1.3%), **freshness** (days since weekly cross < 60)
- Rewrote `daily_signal_service.py` as multi-TF scanner with momentum score + infancy buckets + Slack alert
- Added `indexMultiTfUptrend()` to `ScannerController.php` — Multi-TF filter mode with score/gap_w/atr_dist/infancy
- Updated `index.blade.php` — Multi-TF table, infancy toggle, row highlighting, AJAX timeframe switch
- Optimized chart endpoint — 1-hour 500 bars, daily 500, weekly 300
- Removed temp `analyze_explosives.py` after use
- Added market breadth computation to daily signal service — `pct_in_uptrend` with regime label (⚠️ Risk-off < 35%, ➖ Neutral 35-54%, ✅ Risk-on > 54%) in Slack alert
- Added market breadth badge to scanner UI — colored dot + regime label visible on all filter pages (computed via `getMarketBreadth()` in controller from latest crossover events)
- Added Copy Tickers button (📋 Copy) to scanner top bar — calls `/scanner/copy-tickers` endpoint, returns comma-delimited tickers matching current filter
- Added `getMultiTfUptrendTickers()` helper + `copyTickers()` public method + `/scanner/copy-tickers` route
- Fixed internal server error: `copyTickers()` Long-mode SQL was missing `atr_stop` in subquery SELECT clause
- Scanner up/down arrow navigation now scrolls active row to center of `.table-wrap` container via manual `scrollRowIntoView()` (was `scrollIntoView({block:'center'})` which scrolled wrong container)
- Chart header now shows `Company Name (TICKER)` centered above price panels, extracted from `row.children[1]` on click
- Active row highlight uses blue background (`#1a3a5c`) + 2px blue left border (`#58a6ff`) — overrides `new-row` green via combined `.new-row.active td` selector
- All 6 table modes now use same base styling — removed all per-mode `<colgroup>` width overrides

### Fixed Bugs
- **Duplicate live_trades entries** — `syncLiveTradesFromAlpaca()` Step 1 in EquityService.php re-opened closed trades via `status => 'open'` (fixed: skip if `status !== 'open'`)
- **Orphaned order IDs** — `handlePooledEntries()` in TradeExecutorService.php overwrote `alpaca_order_id` on scale-in, causing reconciliation to create duplicate entries for orphaned orders (fixed: removed `alpaca_order_id` from update)
- **Duplicate entry creation** — Step 1 created new entries for buy orders whose symbol already had an open trade (fixed: check `exists()` by symbol before creating)
- **Alpaca API keys** — Both CHAND (`PKBMUPEMGYQAKNZDQPDD4KI6O7`) and EMAC (`PKZQGO72QD3G4XDOL5HDV5IARX`) were invalid/expired (replaced with new keys)
- **Reset fallout** — Full DB transaction reset required `backfill.py` + `backfill_daily.py` to restore candle data for signal computation

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- **Daily EMA exit is the best exit mode for explosive stocks** — 1-hour exit whipsaws, ATR trailing is worse, daily cross below captures multi-week/month trends
- **Multi-timeframe filter (weekly+daily bullish) already always true** when 1-hour data starts (Jul 2023) — it doesn't identify explosive stocks before they pop; it's a trend confirmation, not a discovery tool
- **Replace trend-age with freshness bonus** — stocks with weekly cross < 60 days (SATS, DELL) had the biggest % gains; mature trends score lower now
- **Daily Signal Service now uses freshness-based scoring** over plain crossover count — entry signals sorted by momentum score, infancy entries highlighted separately
- **Chart data limited to last N bars** — 500 for 1-hour/daily, 300 for weekly; page-timeframe switch is AJAX-only when a chart is loaded
- **Market breadth thresholds** — risk-off < 35%, neutral 35-54%, risk-on > 54% (based on historical quartiles from 9-71% range)
- **Active row highlight** uses manual container scroll calculation (not `scrollIntoView`) because the `.table-wrap` overflow container isn't the nearest scrollable ancestor
- **Colgroups removed from all table modes** — all 6 scanner tables now auto-size columns consistently

## Next Steps
1. Test infancy-filtered variant of the strategy — only take entries where `days_since_weekly < 60`
2. Consider adding volume confirmation or RS relative-strength as additional filter for infancy entries

## Critical Context
- PostgreSQL `swingtrader-db` on `127.0.0.1:5432`
- Scanner tables (`tbl_stock_tickers`, `tbl_scanner_tickers`, `tbl_scanner_tickers_daily`, `tbl_scanner_tickers_1hour`): all 503 S&P 500 stocks, OHLCV + pre-computed MACD/PPO/SMA/ATR indicators
- EMA periods: 10, SMA periods: 40 (config), COST = 0.0005, CAPITAL = 100000
- Market breadth computed from cross-over events: `SELECT DISTINCT ON (ticker_id)` from `tbl_scanner_tickers` and `tbl_scanner_tickers_daily`
- Copy-tickers endpoint mirrors all filter logic: Long, Short, Weekly Crossover, Multi-TF (+infancy), Undervalued
- **CHAND Alpaca** (key `PK7DIID4NUY5N7HODFQRDTWMJC`): $1M paper, active, 0 positions
- **EMAC Alpaca** (key `PK6IRYP5QWRVRVYJJYH5Q22RZS`, acct #PA3EHVX93SJT): $1M paper, active, 0 positions
- systemd timer fires Mon–Fri 16:30 ET, already enabled and active

## Relevant Files
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py`: Multi-TF scanner with scoring + infancy buckets + market breadth → Slack alert
- `swingtrader/services/ema_sma_crossover/backtest_multitf.py`: Multi-timeframe backtest, supports `--exit daily-ema` mode
- `scanner/backend/Controllers/ScannerController.php`: `indexMultiTfUptrend()`, `getMarketBreadth()`, `copyTickers()`, `getMultiTfUptrendTickers()`; optimized `chart()` with bar limits
- `scanner/backend/views/scanner/index.blade.php`: Multi-TF table, infancy toggle, AJAX timeframe switch, breadth badge, copy button, scroll-to-center, chart header, active-row highlight, unified colgroup-free table styling
- `swingtrader/backend/routes/web.php`: `/scanner/copy-tickers` route
- `swingtrader/services/ema_sma_crossover/market_breadth.py`: Historical market breadth analysis script
- `swingtrader/services/ema_sma_crossover/runner.py`: Live EMAC runner
- `swingtrader/services/ema_sma_crossover/executor.py`: EMAC order placement and rebalance logic
- `swingtrader/services/ema_sma_crossover/backfill.py`: Backfill 30-min candles from Alpaca
- `swingtrader/services/ema_sma_crossover/backfill_daily.py`: Backfill daily candles from Alpaca
- `swingtrader/services/ema_sma_crossover/systemd/daily-signal.{service,timer}`: systemd oneshot + timer (Mon–Fri 16:30 ET)
- `swingtrader/backend/app/Services/EquityService.php`: `syncLiveTradesFromAlpaca()` — CHAND reconciliation (Fixed: don't re-open closed trades, skip duplicate entry creation)
- `swingtrader/backend/app/Services/TradeExecutorService.php`: CHAND trade execution (Fixed: don't overwrite `alpaca_order_id` on scale-in)
- `common/scripts/health-check.sh`: Daily Signal Service monitoring section
- `common/docs/TRADING_STRATEGIES.md`: EMAC + Daily Signal strategies overview
- `common/docs/How_System_Works.md`: EMAC pipeline + Daily Signal Service
- `swingtrader/services/ema_sma_crossover/data/daily_signals.csv`: CSV log
- `swingtrader/services/ema_sma_crossover/.daily_signal_state.json`: Dedup state file
- `.env` files across: `swingtrader/backend/`, `scanner/backend/`, `swingtrader/services/optimizer/`, `swingtrader/services/ema_sma_crossover/`, `swingtrader/services/mtcs/`
