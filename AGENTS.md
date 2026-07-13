# Anchored Summary — SwingTraderAndOptimizer

## Goal
Find and trade the best entry among ALL strategies through systematic backtesting and live automated execution.

## Strategy Map
| # | Name | Universe | Signals | Status |
|---|------|----------|---------|--------|
| 1 | **CHAND** (Chandelier Exit) | QQQ/VTI/IWM | Optimized trailing stop | ✅ Live (Laravel) |
| 2 | **EMAC** (EMA/SMA 30-min) | QQQ/VTI/VTV | EMA10 > SMA40 cross | ✅ Live (systemd) |
| 3 | **MTCS** (Hilbert sine/lead) | QQQ/VTI/VTV | Sine wave crossover | ✅ Live — **slated for replacement** |
| 4 | **MTF Top-N** (Multi-TF rotation) | S&P 500 (503 stocks) | gap_w + atr_dist + freshness → top 10 daily | 🚧 Phase 1 (paper) |
| 5 | **Daily Signal** (Multi-TF alerts) | S&P 500 | 1-hour fresh cross + score | ✅ Slack @ 4:30 PM |

## Constraints & Preferences
- EMAC live runner must remain untouched
- MTCS (Alpaca paper acct #PA3NCXU4O2CN) is the candidate for replacement by MTF Top-N
- Daily Signal Service (Mon–Fri 4:30 PM ET, Slack tagged `[DAILY]`) is separate and stays
- Backtests use scanner DB tables (`tbl_scanner_tickers*`)

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
- Added `--infancy` flag to `backtest_multitf.py` — filters entries to `days_since_weekly < 60`; run backtest with `--exit daily-ema --infancy`
- **Found Multi-TF scoring massively outperforms Long scanner for rotation** — Multi-TF daily rebalance: +5,299% (22.2% DD, 68% win rate); Long scanner daily: -6.26% (50% win rate, noisy 8.3 buys/day)
- **MTCS upgraded to real Alpaca trading** — created `executor.py` with `buy_position()`/`sell_position()`, wired into `runner.py` (BUY pools cash, SELL liquidates)
- **MTCS given dedicated Alpaca account** — key `PKQK45DA2ERAXX6XKPUDORIWSH`, acct #PA3NCXU4O2CN, $1M paper (same pool as CHAND/EMAC)
- **MTCS chart utility** — `chart.py` for matplotlib Hilbert sine/lead visualization
- **MTCS health check updated** — checks Alpaca account balance + real positions
- **MTCS startup bug fixed** — `last_bar_dates[tid] = None` so signals process first bar
- **MTCS SIGTERM responsiveness fixed** — broke `time.sleep()` into 5s chunks
- **Stale MTCS virtual positions cleared** — deleted old `mtcs_positions` and `mtcs_trades` rows
- **EMAC roundtrip closed** — VTI -$3,487, VTV -$3,702; no open positions remain
- **Weekly Crossover removed from scanner** — redundant with Long mode
- **Created `backtest_topn_multitf.py`** — Top-N rotation backtest using Multi-TF score (gap_w/20 + atr_dist/1.5 + freshness)
- **Created `backtest_topn.py`** — Top-N rotation using Long scanner score (MACD/PPO zero-line crosses)

### Fixed Bugs
- **Duplicate live_trades entries** — `syncLiveTradesFromAlpaca()` Step 1 in EquityService.php re-opened closed trades via `status => 'open'` (fixed: skip if `status !== 'open'`)
- **Orphaned order IDs** — `handlePooledEntries()` in TradeExecutorService.php overwrote `alpaca_order_id` on scale-in, causing reconciliation to create duplicate entries for orphaned orders (fixed: removed `alpaca_order_id` from update)
- **Duplicate entry creation** — Step 1 created new entries for buy orders whose symbol already had an open trade (fixed: check `exists()` by symbol before creating)
- **Alpaca API keys** — Both CHAND (`PKBMUPEMGYQAKNZDQPDD4KI6O7`) and EMAC (`PKZQGO72QD3G4XDOL5HDV5IARX`) were invalid/expired (replaced with new keys)
- **Reset fallout** — Full DB transaction reset required `backfill.py` + `backfill_daily.py` to restore candle data for signal computation
- **Weekend stale-bar false alarms** — MTCS health check and unified health-check.sh both flagged Friday bars as stale on Monday; fixed both to count trading days (Mon-Fri) instead of raw calendar/hours
- **MTF runner zero candidates with incomplete daily data** — daily index lookup used exact `.get(sig_date)`, failed when scanner daily table had only 1 row for today; fixed to use `_nearest_date_idx` fallback like weekly/hourly already did

### In Progress
- **Phase 1 — MTF Top-N paper trading** (`swingtrader/services/mtf/runner.py`): Daily one-shot script scoring all 503 S&P stocks, logging top-10 picks + paper portfolio to CSV, sending Slack alert with picks, changes, and simulated P&L. MTCS continues running alongside.

### Blocked
- (none)

### Findings
- **Infancy as a hard filter degrades returns** — `--infancy` backtest with `--exit daily-ema`: top 25 avg +101% (vs unfiltered +356%); bottom 25 avg -11.2% (vs unfiltered -13.5%). 18 of 50 stocks had zero trades because their weekly cross predates the hourly data window (Jul 2023).
- **CIEN outperformed** with infancy (+633% vs +588%) — clean early entries captured the full trend. But APP (+741% → zero), SNDK (+400% → zero), HWM (+28% → zero) had all entries filtered out.
- **Infancy is better as a score component (0-2 pts) than a hard filter** — keeps explosive stocks in play while giving priority to fresh weekly crosses. The daily signal service already implements this correctly.
- **Multi-TF score crushes Long scanner for rotation** — Multi-TF weekly+daily bullish filter eliminates weak stocks; Long scanner's MACD/PPO zero-line crosses are noise (50% win rate = coin flip).
- **Multi-TF daily rebalance beats weekly** (+5,299% vs +698%) — scores are stable so daily doesn't churn (0.44 buys/day vs Long scanner's 8.3 buys/day).

## Key Decisions
- **Daily EMA exit is the best exit mode for explosive stocks** — 1-hour exit whipsaws, ATR trailing is worse, daily cross below captures multi-week/month trends
- **Multi-timeframe filter (weekly+daily bullish) already always true** when 1-hour data starts (Jul 2023) — it doesn't identify explosive stocks before they pop; it's a trend confirmation, not a discovery tool
- **Replace trend-age with freshness bonus** — stocks with weekly cross < 60 days (SATS, DELL) had the biggest % gains; mature trends score lower now
- **Daily Signal Service now uses freshness-based scoring** over plain crossover count — entry signals sorted by momentum score, infancy entries highlighted separately
- **Chart data limited to last N bars** — 500 for 1-hour/daily, 300 for weekly; page-timeframe switch is AJAX-only when a chart is loaded
- **Market breadth thresholds** — risk-off < 35%, neutral 35-54%, risk-on > 54% (based on historical quartiles from 9-71% range)
- **Active row highlight** uses manual container scroll calculation (not `scrollIntoView`) because the `.table-wrap` overflow container isn't the nearest scrollable ancestor
- **Colgroups removed from all table modes** — all 6 scanner tables now auto-size columns consistently
- **Infancy as score beat infancy as filter** — hard filter removes too many explosive entries (APP, SNDK, HWM zero trades); using freshness as a 0-2 pt bonus preserves them while still favoring fresh entries
- **Multi-TF Top-N replaces MTCS as the primary rotation strategy** — Hilbert sine/lead on 3 ETFs underperforms; Multi-TF score on 503 stocks with daily rebalance captures explosive breakouts with 22% max DD
- **Phase 1 (paper only)** — validate live scoring matches backtest by logging picks alongside running MTCS; sends Slack alert daily with picks, changes, and paper P&L
- **Phase 2 (replace MTCS)** — stop Hilbert runner, point Alpaca executor at MTF top-N picks; start with `--top-n 5` then scale to 10
- **Phase 3 (scale)** — increase to `--top-n 10` once comfortable; optionally add stop-loss or trailing exit to protect gains

## Next Steps
1. ✅ Test infancy-filtered variant of the strategy — **done: infancy as hard filter degrades returns** (top 25 avg +101% vs unfiltered +356%)
2. ✅ Multi-TF daily beats weekly + crushes Long scanner — **shift strategy: MTF Top-N replaces MTCS**
3. 🚧 **Phase 1** — Build `mtf_daily_runner.py`: daily one-shot, scores 503 stocks, top-10 to CSV + Slack, paper portfolio tracking. MTCS runs alongside.
4. **Phase 2** — After 1 month of validation, stop MTCS, wire MTF picks into executor for real Alpaca trading
5. **Phase 3** — Optimize top-N size, add exit rules (stop-loss, trailing)

## Critical Context
- PostgreSQL `swingtrader-db` on `127.0.0.1:5432`
- Scanner tables (`tbl_stock_tickers`, `tbl_scanner_tickers`, `tbl_scanner_tickers_daily`, `tbl_scanner_tickers_1hour`): all 503 S&P 500 stocks, OHLCV + pre-computed MACD/PPO/SMA/ATR indicators
- EMA periods: 10, SMA periods: 40 (config), COST = 0.0005, CAPITAL = 100000
- Market breadth computed from cross-over events: `SELECT DISTINCT ON (ticker_id)` from `tbl_scanner_tickers` and `tbl_scanner_tickers_daily`
- Copy-tickers endpoint mirrors all filter logic: Long, Short, Weekly Crossover, Multi-TF (+infancy), Undervalued
- **CHAND Alpaca** (key `PK7DIID4NUY5N7HODFQRDTWMJC`): $1M paper, active, 0 positions
- **EMAC Alpaca** (key `PK6IRYP5QWRVRVYJJYH5Q22RZS`, acct #PA3EHVX93SJT): $1M paper, active, 0 positions
- **MTCS Alpaca** (key `PKQK45DA2ERAXX6XKPUDORIWSH`, acct #PA3NCXU4O2CN): $1M paper, active, 0 positions
- systemd timer fires Mon–Fri 16:30 ET, already enabled and active
- MTCS runner uses optimizer venv for Python execution
- Multi-TF backtest only active from July 2023 (when hourly atr_stop data starts)
- Multi-TF daily: 526 buys across ~1,200 days = 0.44 buys/day (stable rankings)
- Long scanner daily: 12,399 buys across ~1,493 days = 8.3 buys/day (noisy rankings)

## Relevant Files
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py`: Multi-TF scanner with scoring + infancy buckets + market breadth → Slack alert
- `swingtrader/services/ema_sma_crossover/backtest_multitf.py`: Multi-timeframe backtest, supports `--exit daily-ema` mode
- `swingtrader/services/ema_sma_crossover/backtest_topn.py`: Top-N rotation backtest (Long scanner score)
- `swingtrader/services/ema_sma_crossover/backtest_topn_multitf.py`: Top-N rotation backtest (Multi-TF score)
- `swingtrader/services/mtf/`: Phase 1 paper trading — runner, config, db, CSV logs
- `scanner/backend/Controllers/ScannerController.php`: `indexMultiTfUptrend()`, `getMarketBreadth()`, `copyTickers()`, `getMultiTfUptrendTickers()`; optimized `chart()` with bar limits
- `scanner/backend/views/scanner/index.blade.php`: Multi-TF table, infancy toggle, AJAX timeframe switch, breadth badge, copy button, scroll-to-center, chart header, active-row highlight, unified colgroup-free table styling
- `swingtrader/backend/routes/web.php`: `/scanner/copy-tickers` route
- `swingtrader/backend/app/Services/EquityService.php`: `syncLiveTradesFromAlpaca()` — CHAND reconciliation (Fixed: don't re-open closed trades, skip duplicate entry creation)
- `swingtrader/backend/app/Services/TradeExecutorService.php`: CHAND trade execution (Fixed: don't overwrite `alpaca_order_id` on scale-in)
- `common/scripts/health-check.sh`: Daily Signal Service monitoring section
- `common/docs/services_doc/mtcs_service.md`: MTCS service documentation
- `common/docs/services_doc/mtf_daily_runner.md`: MTF Top-N service documentation
- `common/docs/TRADING_STRATEGIES.md`: All strategies overview
- `common/docs/How_System_Works.md`: EMAC pipeline + Daily Signal Service
- `.env` files across: `swingtrader/backend/`, `scanner/backend/`, `swingtrader/services/optimizer/`, `swingtrader/services/ema_sma_crossover/`, `swingtrader/services/mtcs/`
