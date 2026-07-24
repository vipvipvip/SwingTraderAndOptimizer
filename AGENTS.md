# Anchored Summary — SwingTraderAndOptimizer

## Goal
Find and trade the best entry among ALL strategies through systematic backtesting, scanner UI integration, and live automated execution — Explorer Dashboard unifies signals from all strategies (CHAND/EMAC/MTCS/MTF/Daily) with Early breakout column.

## Strategy Map
| # | Name | Universe | Signals | Status |
|---|------|----------|---------|--------|
| 1 | **CHAND** (Chandelier Exit) | QQQ/VTI/VTV | Optimized trailing stop | ✅ Live (Laravel) |
| 2 | **EMAC** (EMA/SMA 30-min) | QQQ/VTI/VTV | EMA10 > SMA40 cross | ✅ Live (systemd) |
| 3 | **MTCS** (Hilbert sine/lead) | QQQ/VTI/VTV | Sine wave crossover | ✅ Live — **slated for replacement** |
| 4 | **MTF Top-N** (Multi-TF rotation) | S&P 500 (503 stocks) + 22 ETFs | gap_w + atr_dist + freshness → top 10 daily | 🚧 Phase 1 (paper) |
| 5 | **Daily Signal** (Multi-TF alerts) | S&P 500 | 1-hour fresh cross + score | ✅ Slack @ 4:30 PM |

## Constraints & Preferences
- EMAC 30-min runner (QQQ/VTI/VTV, Alpaca paper, Slack tag `[EMAC]`) must remain untouched
- MTCS (Alpaca paper acct #PA3NCXU4O2CN, Slack tag `[MTCS]`) runs alongside MTF Top-N during Phase 1 paper validation; slated for replacement by MTF Top-N
- Daily Signal Service (Mon–Fri 4:30 PM ET, Slack tagged `[DAILY]`) is separate and stays
- MTF Top-N Phase 1 is paper-only (Slack tag `[MTF-TopN]`) — no real Alpaca trading
- CHAND (Alpaca paper, Slack tag `[CHAND]`) runs via Laravel `ExecuteDailyTrades` command on same trio (QQQ/VTI/VTV)
- All backtests use scanner DB tables (`tbl_scanner_tickers*`), not strategy-specific ETF tables
- MTCS uses optimizer venv for Python execution; Hilbert chart script (`chart.py`) auto-detects this venv via `os.execv`
- Three Alpaca paper accounts: CHAND (#PA31Z71315NM), EMAC (#PA3EHVX93SJT), MTCS (#PA3NCXU4O2CN)
- Keep same Slack channel for all services — differentiate via prefix tags
- One combined Slack message per day for MTF (stocks + ETFs + sector info) via `--mode all`
- `--min-score 5` variant tracked separately with isolated state files / CSVs
- Laravel cache must be cleared in `swingtrader/backend/storage/framework/` (not `scanner/backend/`) — both data cache (`cache/explorer_*.json`) and compiled views (`views/*.php`) must be cleared after blade changes

## Progress
### Done
- Fixed MTF runner daily fallback: `_nearest_date_idx` replaces exact `.get(sig_date)` so picks still generate when scanner daily table hasn't finished updating
- Fixed weekend stale-bar false alarms in MTCS health check and unified health-check.sh: count trading days (Mon-Fri) instead of raw calendar/hours
- Merged `rnd/signal-processing` → `main` (22 commits, 58 files, ~8,900 additions)
- Created `feature/mtf-explorer-dashboard` branch
- Added `is_etf` boolean to `tbl_stock_tickers`, created/updated `tbl_etf_tickers` with 22 ETFs
- Updated `populate_tickers.py` to read all enabled tickers from `tbl_stock_tickers`
- Populated + computed all 22 ETFs: weekly (312 bars), daily (1,497 bars), hourly (~450 bars) with full indicators
- Updated MTF runner with `--mode stock|etf` flag, separate CSVs/state/Slack tags per mode, scoped market breadth
- Built MTF Explorer Dashboard: full scanner-style UI with checkboxes, keyboard navigation (arrow keys), ticker search/autocomplete, Copy button, 3-panel lightweight-charts (price + MACD + PPO), ETF/Stock mode toggle
- Fixed Explorer backend: optimized window function queries from 33s+ to **6s cold / 0.16s cached** using ROW_NUMBER + GROUP BY + FILTER pattern; fixed SMA40 frame to use ORDER BY ASC (PRECEDING); moved market breadth to PHP computation
- Fixed SQL bugs: `bt` CTE name (reserved keyword `both`), view path (`../../scanner/backend/views`), missing `close > sma40` filter conditions (caused 0 picks)
- Fixed EMAC overstated-position bug: `buy_position()` now reads `order['filled_qty']` instead of requested qty; `sell_position()` checks Alpaca position and caps qty; `_sync_alpaca_positions()` detects DB > Alpaca mismatches and corrects; all trade failures send `⚠️` Slack via `_send_slack_error()`
- Extended MTCS Hilbert chart to any ticker in DB: reads `tbl_stock_tickers` + `tbl_scanner_tickers_daily` (525 tickers); supports `--save=path.png` with auto-per-symbol filenames; auto-detects optimizer venv via `os.execv`
- Fixed AGENTS.md: CHAND universe is QQQ/VTI/VTV (was IWM)
- Explorer columns restructured: Ticker → Price → MTF Score → Daily Signal → EMAC → CHAND → MTCS → Combined → Early — all sortable by click, sorted by Combined descending by default
- Added CHAND/EMAC/Daily Signal/Combined/Early columns: CHAND = close > atr_stop on hourly; EMAC = daily EMA10 > SMA40; Daily Signal = fresh weekly SMA40 cross < 60 days; Combined = mtf_score + signal bonuses; Early = signal_count + fresh_pts - gap_pts
- Daily Signal fixed: uses infancy (fresh weekly cross < 60 days) instead of `sma_crossover` DB column
- Added `--etf` flag to `backtest_topn_multitf.py` for ETF universe backtesting
- Added `--score` flag to backtest (`mtf` or `early`) for alternate scoring strategies
- Backtest results confirmed: MTF scoring on stocks: +5,469% (22.2% DD); Early score: -40.77% (45.9% DD) — penalizing gap_w kills returns
- **SPOF hardening in runner.py**: crash alerting (global try/except → Slack `⚠️ CRASH`), stale data detection (>2d aborts, 1d warns), atomic state writes (tempfile+os.replace), DB connection retry (3 attempts, 5s delay)
- **Combined Slack message**: refactored runner to `--mode all` (runs both stock + ETF in one shot), single combined Slack alert per day, separate `_run_single_mode()` core logic
- **Systemd service updated**: single `ExecStart --mode all`, `TimeoutStopSec=300`
- **Deleted stale scanner-intraday.service + timer** (replaced by scanner-hourly)
- **Service docs updated**: `common/docs/services_doc/mtf-daily-runner.service` and `mtf_daily_runner.md` reflect `--mode all`, combined message, --user commands
- **Backtest fixed**: partial-date bug — excludes dates with <400 tickers so incomplete last trading day doesn't artifact -100% loss
- **Backtest `--min-score` + `--infancy` flags added** and confirmed: `--min-score 5` alone returns **+9,061%** (33.2% DD, 280 buys) vs unfiltered +5,469% (22.2% DD, 526 buys); adding infancy drops to +688% (59.2% DD, 93 buys) — infancy is the drag, not min-score
- **Adding `--min-score 5` variant to runner.py**: separate state files (`.mtf_state_min5_stock.json`), separate CSVs (`mtf_picks_min5_stock.csv`), isolated from default pipeline

### Fixed Bugs
- **Duplicate live_trades entries** — `syncLiveTradesFromAlpaca()` Step 1 in EquityService.php re-opened closed trades via `status => 'open'` (fixed: skip if `status !== 'open'`)
- **Orphaned order IDs** — `handlePooledEntries()` in TradeExecutorService.php overwrote `alpaca_order_id` on scale-in, causing reconciliation to create duplicate entries for orphaned orders (fixed: removed `alpaca_order_id` from update)
- **Duplicate entry creation** — Step 1 created new entries for buy orders whose symbol already had an open trade (fixed: check `exists()` by symbol before creating)
- **Alpaca API keys** — Both CHAND (`PKBMUPEMGYQAKNZDQPDD4KI6O7`) and EMAC (`PKZQGO72QD3G4XDOL5HDV5IARX`) were invalid/expired (replaced with new keys)
- **Reset fallout** — Full DB transaction reset required `backfill.py` + `backfill_daily.py` to restore candle data for signal computation
- **Weekend stale-bar false alarms** — MTCS health check and unified health-check.sh both flagged Friday bars as stale on Monday; fixed both to count trading days (Mon-Fri) instead of raw calendar/hours
- **MTF runner zero candidates with incomplete daily data** — daily index lookup used exact `.get(sig_date)`, failed when scanner daily table had only 1 row for today; fixed to use `_nearest_date_idx` fallback like weekly/hourly already did

### In Progress
- Integrating `--min-score` into runner.py (`--min-score` CLI arg, filtered candidates, isolated state/CSV suffix)

### Blocked
- (none)

### Findings
- **Infancy as a hard filter degrades returns** — `--infancy` backtest with `--exit daily-ema`: top 25 avg +101% (vs unfiltered +356%); bottom 25 avg -11.2% (vs unfiltered -13.5%). 18 of 50 stocks had zero trades because their weekly cross predates the hourly data window (Jul 2023).
- **CIEN outperformed** with infancy (+633% vs +588%) — clean early entries captured the full trend. But APP (+741% → zero), SNDK (+400% → zero), HWM (+28% → zero) had all entries filtered out.
- **Infancy is better as a score component (0-2 pts) than a hard filter** — keeps explosive stocks in play while giving priority to fresh weekly crosses. The daily signal service already implements this correctly.
- **Multi-TF score crushes Long scanner for rotation** — Multi-TF weekly+daily bullish filter eliminates weak stocks; Long scanner's MACD/PPO zero-line crosses are noise (50% win rate = coin flip).
- **Multi-TF daily rebalance beats weekly** (+5,299% vs +698%) — scores are stable so daily doesn't churn (0.44 buys/day vs Long scanner's 8.3 buys/day).
- **Sector ETF MTF underperforms B&H** — MTF rotation on 11 sector ETFs (TOP_N=5) returned +46.9% vs equal-weight B&H +127.9% over Jul 2023–Jul 2026. Scoring system designed for individual stock breakouts doesn't work on diversified ETF baskets. SPY/QQQ MTF = 0 trades (single ticker = buy-and-hold).

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
- **One combined Slack message** per day instead of separate stock+ETF messages — reduces noise, one view of both universes
- **`--mode all` refactored runner**: `_run_single_mode()` returns (success, lines, sig_date), `run_all()` merges both sections into one Slack send
- **`--min-score 5` isolated as separate pipeline** with its own state files / CSVs — tracks as an alternative paper portfolio alongside the default top-10, no interference
- **Partial-date fix for backtests**: filter out dates where <400 tickers have daily data (prevents incomplete-last-day artifacts)
- **Infancy filter drags performance** — `--min-score 5` alone crushes (+9,061% vs unfiltered +5,469%), but `+ --infancy` drops to +688% because it skips too many explosive entries

## Next Steps
1. ✅ Test infancy-filtered variant of the strategy — **done: infancy as hard filter degrades returns** (top 25 avg +101% vs unfiltered +356%)
2. ✅ Multi-TF daily beats weekly + crushes Long scanner — **shift strategy: MTF Top-N replaces MTCS**
3. 🚧 **Phase 1** — Finish `--min-score` integration in runner.py (CLI arg, filtered candidates, isolated suffix)
4. 🚧 Add health check for min-score state files
5. ⏳ After 1-week validation: Phase 2 — stop MTCS runner, wire MTF picks into real Alpaca executor (`--top-n 5`)
6. ⏳ Phase 3 — Optimize top-N size, add exit rules (stop-loss, trailing)

## Critical Context
- PostgreSQL `swingtrader-db` on `127.0.0.1:5432`, docker container healthy
- Scanner tables: 503 stocks + 22 ETFs with `is_etf` flag; `tbl_etf_tickers` has company names
- EMA=10, SMA=40, COST=0.0005, CAPITAL=100000
- MTF Top-N Phase 1: separate paper portfolios per mode (stock + ETF) + min-score variant, state in `.mtf_state_*.json`; sector ETFs shown in Slack as info-only scoring
- `mtf-daily-runner.timer` active at 5:30 PM ET weekdays — runs `--mode all` via systemd (single ExecStart)
- `ema10_sma40_crossover` and `sma_crossover` columns in scanner tables are never populated by the pipeline (all false) — must compute inline via window functions
- Laravel backend runs on port 9000 with `artisan serve` via systemd
- Three composite indexes: `idx_daily_tid_date_close`, `idx_wk_tid_date_close`, `idx_1h_tid_date_atr`
- Scanner daily data incomplete for current day — `populate_tickers.py --timeframe day` runs at 9 AM before market close
- Explorer page: `http://localhost:9000/scanner/explorer` (HTML), data: `/scanner/explorer-data?mode=stock|etf` (JSON, ~6s uncached / 0.16s cached)
- Backtest results: unfiltered MTF +5,469% (22.2% DD); `--min-score 5` +9,061% (33.2% DD); `--min-score 5 + --infancy` +688% (59.2% DD)
- **CHAND Alpaca** (key `PK7DIID4NUY5N7HODFQRDTWMJC`): $1M paper, active, 0 positions
- **EMAC Alpaca** (key `PK6IRYP5QWRVRVYJJYH5Q22RZS`, acct #PA3EHVX93SJT): $1M paper, active, 0 positions
- **MTCS Alpaca** (key `PKQK45DA2ERAXX6XKPUDORIWSH`, acct #PA3NCXU4O2CN): $1M paper, active, 0 positions

## Relevant Files
- `swingtrader/services/mtf/runner.py`: MTF Top-N Phase 1 — `--mode stock|etf|all` flag, `--min-score` (CLI arg + filtered candidates), separate CSVs/state per variant, crash alerting, stale data check, atomic writes, DB retry, sector info (info-only scoring in combined Slack)
- `swingtrader/services/mtf/db.py`: Market breadth queries — compute close>SMA40 inline, fixed `both`→`bt` CTE name
- `swingtrader/services/mtf/backtest_topn_multitf.py`: Top-N backtest with `--etf --score --min-score --infancy` flags, partial-date exclusion fix
- `swingtrader/services/mtf/config.py`: DB config, TOP_N=10, COST=0.0005, CAPITAL=100000
- `swingtrader/services/mtf/systemd/mtf-daily-runner.service`: Single ExecStart `--mode all`, `TimeoutStopSec=300`
- `swingtrader/services/mtf/health_check.py`: Checks timer, journal errors, data freshness, state file staleness
- `swingtrader/backend/storage/framework/cache/`: Explorer data cache (5-min TTL) — clear this + `views/` for blade changes
- `common/docs/services_doc/mtf-daily-runner.service`: Docs copy matching active service (`--mode all`, `TimeoutStopSec=300`)
- `common/docs/services_doc/mtf_daily_runner.md`: Updated with combined Slack message example, per-mode CSVs, `--mode all` CLI docs, `--user` systemd commands
- `scanner/backend/Controllers/ScannerController.php`: Explorer data endpoint with optimized window function queries
- `scanner/backend/views/scanner/explorer.blade.php`: Explorer Dashboard — 3-panel charts, all-strategy signal columns, sortable
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py`: Multi-TF scanner with scoring + infancy + market breadth → Slack
- `swingtrader/services/ema_sma_crossover/backtest_multitf.py`: Multi-timeframe backtest with `--exit daily-ema` mode
