# Anchored Summary — SwingTraderAndOptimizer

## Goal
Find and trade the best entry among ALL strategies through systematic backtesting, scanner UI integration, and live automated execution — Explorer Dashboard unifies signals from all strategies (CHAND/EMAC/MTCS/MTF/Daily) with Early breakout column.

## Strategy Map
| # | Name | Universe | Signals | Status |
|---|------|----------|---------|--------|
| 1 | **CHAND** (Chandelier Exit) | QQQ/VTI/VTV | Optimized trailing stop | ✅ Live (Laravel) |
| 2 | ~~**EMAC**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 3 | ~~**MTCS**~~ (stopped) | — | — | ❌ Replaced by MTF |
| 4 | **MTF Top-N** (MTF stocks + EMA/SMA ETFs) | VTI stocks + ETFs | Stocks: gap_w + atr_dist + freshness; ETFs: weekly EMA10>SMA40 gap → top 10 | ✅ Live (#PA3PPZAZR76Z stocks / #PA3U8GZ96PEN ETFs) |
| 5 | **Daily Signal** (Multi-TF alerts) | S&P 500 | 1-hour fresh cross + score | ✅ Slack @ 5:00 PM |

## Constraints & Preferences
- EMAC (Alpaca paper acct #PA3EHVX93SJT, Slack tag `[EMAC]`) is **stopped** — replaced by MTF; all EMAC services/timers/scripts removed from systemd and repo (`backfill-daily`, `emac-runner`, `manageTicker.py`, `health_check.py`); remaining EMAC strategy code deleted from `ema_sma_crossover/` (2026-08-10) — dir now holds only the live Daily Signal service
- MTCS (Alpaca paper acct #PA3NCXU4O2CN, Slack tag `[MTCS]`) is **stopped** — service removed from systemd, replaced by MTF Top-N (Phase 2 live); entire `swingtrader/services/mtcs/` directory deleted (2026-08-10) + `mtcs_positions`/`mtcs_trades` DB tables dropped
- Daily Signal Service (Mon–Fri 5:00 PM ET, Slack tagged `[DAILY]`) is separate and stays
- MTF Top-N Phase 2 is live (Slack tag `[MTF-TopN stocks]` / `[EMA-SMA ETFs]`) — places real Alpaca orders
- CHAND (Alpaca paper, Slack tag `[CHAND]`) runs via Laravel `ExecuteDailyTrades` command on same trio (QQQ/VTI/VTV)
- All backtests use scanner DB tables (`tbl_scanner_tickers*`), not strategy-specific ETF tables
- MTCS uses optimizer venv for Python execution (code deleted 2026-08-10, dir removed from repo on merged branch `396aa07`)
- Three Alpaca paper accounts: CHAND (#PA31Z71315NM), EMAC (#PA3EHVX93SJT), MTCS (#PA3NCXU4O2CN, stopped)
- Two MTF Alpaca accounts: Stocks (#PA3PPZAZR76Z), ETFs (#PA3U8GZ96PEN)
- Keep same Slack channel for all services — differentiate via prefix tags
- One combined Slack message per day for MTF (stocks + ETFs + sector info) via `--mode all`
- **MTF state is DB-backed** (PostgreSQL), not files: `mtf_pending` (evening picks → morning executor), `mtf_runs` (ops/staleness log), `mtf_positions` (real Alpaca holdings = source of truth), `mtf_trades` (fill log). No `.mtf_state_*.json`, no portfolio/trades CSVs, no paper accounting — MTM in Slack is real positions × close
- `--min-score 5` variant **dropped** from production (research backtest only, +9,061% result retained in docs)
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
- **Deleted stale scanner-intraday.service + timer** (replaced by swingtrader-scanner-backfill, formerly scanner-hourly)
- **Service docs updated**: `common/docs/services_doc/swingtrader-mtf-scorer.service` and `mtf_daily_runner.md` reflect `--mode all`, combined message, --user commands
- **Backtest fixed**: partial-date bug — excludes dates with <400 tickers so incomplete last trading day doesn't artifact -100% loss
- **Backtest `--min-score` + `--infancy` flags added** and confirmed: `--min-score 5` alone returns **+9,061%** (33.2% DD, 280 buys) vs unfiltered +5,469% (22.2% DD, 526 buys); adding infancy drops to +688% (59.2% DD, 93 buys) — infancy is the drag, not min-score
- **Adding `--min-score 5` variant to runner.py**: separate state files (`.mtf_state_min5_stock.json`), separate CSVs (`mtf_picks_min5_stock.csv`), isolated from default pipeline
- **Updated MTF health_check.py**: now checks all state/CSV variants (stock/etf/min5) instead of old `.mtf_state.json` naming
- **LinkedIn posts for infra work**: created `LinkedIn-Posts/LINKEDIN_POSTS_INFRA.md` — 3 posts framing the infra refactor as "Vibe coding" (no Claude references, PGSQL instead of SQLite)
- **MTF state → PostgreSQL (2026-07-31)**: dropped all `.mtf_state_*.json` / `mtf_portfolio_*` / `mtf_trades_*` CSVs and the min-score 5 variant. Added `mtf_pending` (JSONB, unique partial index on unconsumed) + `mtf_runs` tables. Runner now: NEW/OUT vs real `mtf_positions` holdings, MTM = held qty × close, ETF P&L from real fills, idempotent pick CSVs (rewrites date rows). `health_check.py` + `show_picks.py` migrated to DB (`mtf_runs` staleness, `mtf_pending` status, real Alpaca equity).
- **yfinance fallback in `populate_tickers.py`**: when Alpaca IEX returns 0 bars for a ticker, fall back to `yf.download` (auto_adjust=False, `yf_interval` map for 1wk/1d/1h) via `fetch_yfinance_bars` + `_SimpleBar` Alpaca-compatible wrapper; status `'ok (yfinance fallback)'`. `--priority SYMS` CLI arg bypasses the "up to date" short-circuit so invested tickers always refetch. Fixed 4 gap tickers (CZFS/PDEX/SEB/UTMD) — 1435/1435 stocks now have 8/3 data.
- **Runner `--priority` wiring**: `_ensure_daily_data` retry gathers invested symbols from `get_all_positions(conn)` and passes them as `--priority` to the populate subprocess so exit signals can always be generated for held tickers
- **Earnings screener Slack dedupe**: identical 30-min scans now suppressed via `.earnings_screener_state.json` (signature = sorted [ticker, freshness, just_turned_positive]); sends only when the result set changes (new ticker or fresh cross)
- **Sector ETF Slack block deduped**: `_run_sector_info` try/except block was pasted twice in runner.py `main` assembly, posting the sector table twice; removed the second copy — one sector section per combined message

### Fixed Bugs
- **Duplicate live_trades entries** — `syncLiveTradesFromAlpaca()` Step 1 in EquityService.php re-opened closed trades via `status => 'open'` (fixed: skip if `status !== 'open'`)
- **Orphaned order IDs** — `handlePooledEntries()` in TradeExecutorService.php overwrote `alpaca_order_id` on scale-in, causing reconciliation to create duplicate entries for orphaned orders (fixed: removed `alpaca_order_id` from update)
- **Duplicate entry creation** — Step 1 created new entries for buy orders whose symbol already had an open trade (fixed: check `exists()` by symbol before creating)
- **Alpaca API keys** — Both CHAND and EMAC keys were invalid/expired (replaced with new keys, keys not stored in repo)
- **Reset fallout** — Full DB transaction reset required `backfill.py` + `backfill_daily.py` to restore candle data for signal computation
- **Weekend stale-bar false alarms** — MTCS health check and unified health-check.sh both flagged Friday bars as stale on Monday; fixed both to count trading days (Mon-Fri) instead of raw calendar/hours
- **MTF runner zero candidates with incomplete daily data** — daily index lookup used exact `.get(sig_date)`, failed when scanner daily table had only 1 row for today; fixed to use `_nearest_date_idx` fallback like weekly/hourly already did
- **MTF runner entry date column** — added `entry YYYY-MM-DD (Nxd)` to terminal + Slack output for all lists (stocks, ETFs, sectors, min-score variants)
- **MTF `get_sector_tickers` restored** — the `def` line was accidentally dropped during the pending-table refactor, silently killing sector ETF info in Slack; fixed orphaned body back into a working function
- **`get_pending` jsonb decode** — psycopg2 returns JSONB natively in some configs; cast to `::text` in SQL so `json.loads` is reliable regardless of adapter settings
- **`mtf_trades` fill log under-records** — partial-fill bug logged requested/partial qty (CBRL 95 vs 176, SEZL 23 vs 62, IJH 17 vs 129, RSP 9 vs 45) plus a phantom `VTV SELL 682` (0 sells ever placed on either account). Rebuilt the log from Alpaca's authoritative fill history via new `reconcile_trades.py` (idempotent delete+reinsert); hardened executor buy path to fall back to live Alpaca position qty; verified 21/21 trade rows exactly match `mtf_positions`
- **MTCS/EMAC journald pipe stall** — long-running processes with `StandardOutput=journal` go silent when journald pipe buffer fills; fixed by redirecting to `/var/log/emac-runner.log` and `/var/log/mtcs-runner.log`
- **compute_indicators.py lock contention** — 10 workers × 5,260 individual UPDATEs per ticker causes row-level lock contention (1h 47min runtime). Root cause identified: need partition-aware workers + COPY bulk writes (planned for refactor)
- **Duplicate sector ETF Slack message** — `_run_sector_info` try/except block was literally pasted twice in runner.py `main`, so the sector table posted twice in one message; removed the second copy (one sector section per combined message)
- **DNS failure on resume from suspend (2026-08-03)** — system slept S3 09:31→10:11 via GNOME battery-idle timeout (900s); `Persistent=true` timer fired at 10:11 before network came up → `NameResolutionError` for `paper-api.alpaca.markets` + `hooks.slack.com`, executor aborted (no trades, no Slack). Fixed by disabling battery-idle suspend: `gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'`
- **DNS failure on resume (2026-08-04, root cause was GDM login screen)** — laptop booted 09:09 on battery (external power switch off), sat at GDM login screen (only `gdm-greeter` session, no `dikesh` session until 10:22:56 after resume). Login screen idle-suspended 09:24:50 (its own dconf has default `sleep-inactive-battery-timeout=900`; user gsettings fix doesn't apply to greeter). Resume at 10:22:50 fired `swingtrader-mtf-executor.timer` (then `mtf-executor.timer`) before WiFi up → DNS fail, no trades. **Fixes**: (1) GDM greeter dconf override `/etc/dconf/db/gdm.d/99-power-suspend` (`sleep-inactive-battery-type/ac-type='nothing'`) + `/etc/dconf/profile/gdm` (`user-db:user` + `system-db:gdm`); (2) `_wait_for_network()` in executor.py polls `socket.gethostbyname` (8.8.8.8, paper-api.alpaca.markets) up to 30s before Alpaca calls; (3) both mtf services switched to `After=network-online.target` + `Wants=network-online.target`
- **Pending-overwrite bug** — `save_pending()` deleted ALL unconsumed pending by mode, so when executor failed (DNS) the unconsumed sig 8/3 picks were silently replaced by the next scorer run's sig 8/4 picks; morning executor then ran the wrong sig. Fixed: `save_pending` only replaces same mode+sig_date (idempotent); `clear_pending(mode, sig_date)` only marks that specific pending consumed (runner passes sig_date)

### MTF Infrastructure Refactor (Done)
- **Partitioned `tbl_scanner_tickers_1hour`** into 16 hash buckets (`ticker_id % 16`), migrated 2.8M rows, dropped 3 redundant indexes (saved 347 MB), old table backed up and dropped
- **Rewrote `compute_indicators.py`**: partition-aware workers (1 per partition = zero lock contention), COPY bulk UPDATEs instead of individual UPDATEs. Runtime: 1h 47min → **8.5 min** (12x speedup)
- **VTI universe**: 1,462 tickers fetched from Alpaca (Price > $50, non-OTC, non-ETF), added to `tbl_stock_tickers` → **1,435 enabled stocks** + 28 ETFs total (after removing 41 misclassified leveraged/commodity/currency/bitcoin/preferred funds, 2026-07-31)
- **Created `get_vti_universe.py`**: fetches all active US equities from Alpaca, filters by price/exchange/ETF, skips leveraged/inverse/commodity/currency/bitcoin/preferred funds (name classifier), inserts into DB
- **No changes needed** to `populate_tickers.py`, `runner.py`, `db.py` — PostgreSQL handles partition routing/pruning transparently

- **Universe cleanup (2026-07-31)**: removed 41 misclassified funds from `tbl_stock_tickers` — 15 no-data leveraged/currency/inverse ETFs (BKTI, EFO, FLYD, FNGO, FXA, FXC, IGHG, IWDL, NOCT, PFBC, QQUP, QQXL, UAN, USCI, UXI) + 26 leveraged/commodity/currency/preferred instruments (AGQ, ASA, BIB, DDM, DGP, FXE, FXF, FXY, GDXU, GLDM, IAU, MCHPP, QLD, ROM, SATA, SLV, SMCIP, SSO, STRC, STRD, STRF, STRK, URE, USD, UWM + GLD). None ever traded (0 rows in `mtf_positions`/`mtf_trades`/`mtf_pending`). Deleted 13,641 hourly + 28,504 daily + 6,212 weekly rows; `tbl_etf_tickers` dropped GLD (29 rows left). `EXPECTED_STOCKS`/`EXPECTED_ETFS` in `config.py` updated to 1435/28. Daily coverage now 100% of enabled universe.
- **Service naming + dead-unit cleanup (2026-08-10)**: renamed 7 timer pairs to `swingtrader-` prefix with schedules unchanged — `scanner-update`→`swingtrader-scanner-update`, `scanner-hourly`→`swingtrader-scanner-backfill`, `mtf-daily-runner`→`swingtrader-mtf-scorer`, `mtf-executor`→`swingtrader-mtf-executor`, `daily-signal`→`swingtrader-daily-signal`, `earnings-screener`→`swingtrader-earnings-screener`, `earnings-refresh`→`swingtrader-earnings-refresh`. Removed dead units `backfill-daily.*` + `emac-runner.service` (systemd) and `mtcs-runner.service` (repo). Deleted orphaned helpers (`ema_sma_crossover/health_check.py`, `manageTicker.py`, `mtcs/health_check.py`) and stale logs (`/var/log/emac-runner.log`, `/var/log/mtcs-runner.log`). Updated `health-check.sh`, `mtf/health_check.py`, `executor.py` comment, and unit copies in `scanner/systemd/`, `swingtrader/services/mtf/systemd/`, `swingtrader/services/ema_sma_crossover/systemd/`, `common/docs/services_doc/`. mtf scorer's `After=`/`Wants=` dependency re-pointed at `swingtrader-scanner-backfill.service`.
- **MTCS code fully deleted (2026-08-10)**: entire `swingtrader/services/mtcs/` directory removed (runner/executor/strategy/spectral/chart/backtest + `.env`); `mtcs_positions`/`mtcs_trades` DB tables dropped; MTCS launch configs removed from `.vscode/launch.json`; `TRADING_STRATEGIES.md` MTCS section marked as deleted historical.
- **Cleanup merged to main (2026-08-11)**: branch `task/Service-rename-cleanup` → main (fast-forward, commit `396aa07`). Push was initially blocked by GitHub secret-scanning (Slack webhook in `swingtrader-earnings-*.service` unit copies) — removed the redundant `Environment=SLACK_WEBHOOK_URL=` lines (scripts load `.env` themselves); Alpaca keys redacted in `AGENTS.md`/`TRADING.txt`. Paper-account secrets remain in older history, deliberately not scrubbed — revisit before going live.
- **EMAC strategy code deleted (2026-08-10)**: `ema_sma_crossover/` slimmed to live Daily Signal service only — deleted `runner.py`, `executor.py`, `strategy.py`, `backtest*.py`, `backfill*.py`, `candle_builder.py`, `price_collector.py`, `signal_trailing_stop.py`, `analyze_explosives.py`, `compare_all.py`, `market_breadth.py`, `requirements.txt`, `.emac_buffer.json`, `data/market_breadth.csv` (written but never read — MTF computes breadth itself), dead systemd copies (`emac-runner.service`, `backfill-daily.*`, old-name `daily-signal.*`). `.env` slimmed to DB + Slack webhook (dropped dormant EMAC Alpaca/Laravel keys). `launch.json` "EMAC Runner" config removed, "EMAC Signal" renamed "Daily Signal Service". `TRADING_STRATEGIES.md` overview + comparison tables updated (EMAC/MTCS dropped, MTF Phase 2, Daily 5:00 PM).

### In Progress
- (none)

### Blocked
- (none)

### Findings
- **Infancy as a hard filter degrades returns** — `--infancy` backtest with `--exit daily-ema`: top 25 avg +101% (vs unfiltered +356%); bottom 25 avg -11.2% (vs unfiltered -13.5%). 18 of 50 stocks had zero trades because their weekly cross predates the hourly data window (Jul 2023).
- **CIEN outperformed** with infancy (+633% vs +588%) — clean early entries captured the full trend. But APP (+741% → zero), SNDK (+400% → zero), HWM (+28% → zero) had all entries filtered out.
- **Infancy is better as a score component (0-2 pts) than a hard filter** — keeps explosive stocks in play while giving priority to fresh weekly crosses. The daily signal service already implements this correctly.
- **Multi-TF score crushes Long scanner for rotation** — Multi-TF weekly+daily bullish filter eliminates weak stocks; Long scanner's MACD/PPO zero-line crosses are noise (50% win rate = coin flip).
- **Multi-TF daily rebalance beats weekly** (+5,299% vs +698%) — scores are stable so daily doesn't churn (0.44 buys/day vs Long scanner's 8.3 buys/day).
- **Sector ETF MTF underperforms B&H** — MTF rotation on 11 sector ETFs (TOP_N=5) returned +46.9% vs equal-weight B&H +127.9% over Jul 2023–Jul 2026. Scoring system designed for individual stock breakouts doesn't work on diversified ETF baskets. SPY/QQQ MTF = 0 trades (single ticker = buy-and-hold).
- **S&P 500 is too late for explosive moves** — TSLA: +757% BEFORE S&P inclusion, only +35% AFTER; NVDA: +103% BEFORE inclusion. VTI (Total Market) catches stocks at ~$100M market cap, years before S&P 500. MTF's early-momentum signals work better on small/mid-cap growth stocks.

## Key Decisions
- **Daily EMA exit is the best exit mode for explosive stocks** — 1-hour exit whipsaws, ATR trailing is worse, daily cross below captures multi-week/month trends
- **Multi-timeframe filter (weekly+daily bullish) already always true** when 1-hour data starts (Jul 2023) — it doesn't identify explosive stocks before they pop; it's a trend confirmation, not a discovery tool
- **Replace trend-age with freshness bonus** — stocks with weekly cross < 60 days (SATS, DELL) had the biggest % gains; mature trends score lower now
- **Daily Signal Service now uses freshness-based scoring** over plain crossover count — entry signals sorted by momentum score, infancy entries highlighted separately
- **Chart data limited to last N bars** — 500 for 1-hour/daily, 300 for weekly; page-timeframe switch is AJAX-only when a chart is loaded
- **Market breadth thresholds** — risk-off < 35%, neutral 35-54%, risk-on > 54% (based on historical quartiles from 9-71% range)
- **VTI over S&P 500 for MTF universe** — S&P 500 is a lagging indicator (adds stocks after explosive growth); VTI (CRSP US Total Market) includes stocks from ~$100M market cap, years earlier. MTF's early-momentum signals need small/mid-cap growth stocks.
- **Active row highlight** uses manual container scroll calculation (not `scrollIntoView`) because the `.table-wrap` overflow container isn't the nearest scrollable ancestor
- **Colgroups removed from all table modes** — all 6 scanner tables now auto-size columns consistently
- **Infancy as score beat infancy as filter** — hard filter removes too many explosive entries (APP, SNDK, HWM zero trades); using freshness as a 0-2 pt bonus preserves them while still favoring fresh entries
- **Multi-TF Top-N replaces MTCS as the primary rotation strategy** — Hilbert sine/lead on 3 ETFs underperforms; Multi-TF score on 503 stocks with daily rebalance captures explosive breakouts with 22% max DD
- **Phase 1 (paper only)** — validate live scoring matches backtest by logging picks alongside running MTCS; sends Slack alert daily with picks, changes, and paper P&L ✅ done
- **Phase 2 (replace MTCS)** — stop Hilbert runner, point Alpaca executor at MTF top-N picks; started at `--top-n 10` ✅ live
- **Phase 3 (scale)** — increase to `--top-n 10` once comfortable; optionally add stop-loss or trailing exit to protect gains
- **One combined Slack message** per day instead of separate stock+ETF messages — reduces noise, one view of both universes
- **`--mode all` refactored runner**: `_run_single_mode()` returns (success, lines, sig_date), `run_all()` merges both sections into one Slack send
- **State in PostgreSQL, not files** — pending handoff via `mtf_pending`, ops log via `mtf_runs`, holdings via real `mtf_positions`; no paper portfolio simulation, no state JSONs (2026-07-31)
- **`--min-score 5` dropped from production** — research backtest only (+9,061% retained in docs); pipeline, state, and CSV variants removed
- **Partial-date fix for backtests**: filter out dates where <400 tickers have daily data (prevents incomplete-last-day artifacts)
- **Infancy filter drags performance** — `--min-score 5` alone crushes (+9,061% vs unfiltered +5,469%), but `+ --infancy` drops to +688% because it skips too many explosive entries
- **WeeklyAndDailyPPO experiment CLOSED (2026-08-01)** — TOS PPO (EMA60/130 wk + EMA12/26 dy, both scaled by weekly 130 EMA) tested as MTF alternative; **not adopted**. PPO top-10 stock rotation +611% vs MTF +9,031%; PPO filter on MTF halves return; PPO ETF +113% loses to SPY B&H +150%; PPO on SPY/VTI/QQQ = degenerate B&H. **Do not revisit.** Full writeup: `swingtrader/services/ppo/FINDINGS.md`
- **Ratchet-ATR exit replaces plain ATR stop (2026-08-12)** — the old `close − 2×ATR` stop is close-anchored and floats down with a crash (could not trigger by construction; ZBRA rode −52.7% never exiting). New peak-anchored ratchet: `exit when close < (highest close since entry) − 2×ATR`, stop only moves up. Backtest: +11,643% (20.8% DD) vs baseline +10,077% (21.1%). Wired into live executor (`config.RATCHET_EXIT`, `executor._compute_ratchet_stops`), stateless from DB, stock leg only. daily-EMA exit = null result at portfolio level (rotation subsumes it, 0 daily-ema sells); BH hypothesis refuted: rotation beats VTI/SPY/QQQ BH ~100x.
- **Server power window (2026-08-12)** — all timers `Persistent=true` (missed jobs fire at next boot, coalesced; executor has `_wait_for_market_open`). **Safe 3.5h/day uptime: ON Mon–Fri 09:00→10:15 + 16:30→17:10 ET, OFF all else.** Morning window is mandatory (10:00 executor must run during market hours); boot before ~15:30 still trades, boot after 16:00 = safe no-trade day. 16:45 scorer depends on 16:30 backfill (`After=`), so afternoon window must start at 16:30. Degradations: earnings-screener 13 runs → 1 catch-up; 02:00 optimizer catch-up collides at 09:00 boot (research-only, can disable); backup catches up at 16:30 boot.
- **Weekly-ratchet timing on core ETFs (2026-08-13, research only)** — "trade when close > peak−2×ATR on all three timeframes" tested on QQQ/VTI/VTV (`backtest_ratchet_timing.py`): all-3 → **−4.2%** (hourly stop whipsaws, ~60 exits/ETF), **weekly-only → +98.3% (7.1% DD)** vs B&H +82.8% (18.8%); robust across 1–3× mult. But it is a **timing** rule, not a **selection** rule, and it does **not** transfer: stock-leg weekly-ATR ratchet tested worse than hourly (+10,201% vs +11,643%, only 9 exits vs 187), and the live ETF leg (EMA/SMA top-10 rotation) beats weekly timing on the same window (+149.8% / 10.5% DD vs +99.2% / 8.6%). **No live strategy changed.** Full analysis: `common/docs/perf_explanations.md` §3.

## Next Steps
1. ✅ Test infancy-filtered variant of the strategy — **done: infancy as hard filter degrades returns** (top 25 avg +101% vs unfiltered +356%)
2. ✅ Multi-TF daily beats weekly + crushes Long scanner — **shift strategy: MTF Top-N replaces MTCS**
3. ✅ **Phase 1** — Finish `--min-score` integration in runner.py (CLI arg, filtered candidates, isolated suffix)
4. ✅ Add health check for min-score state files
5. ✅ **MTF Infrastructure Refactor** — Expand universe from 503 S&P 500 to ~1,463 VTI constituents (Price > $50), partition `tbl_scanner_tickers_1hour` (16 hash buckets), rewrite `compute_indicators.py` with partition-aware workers + COPY bulk writes. **Plan saved: `common/docs/mtf-infra-refactor-plan.md`**
6. ✅ **Phase 2** — MTCS runner stopped, MTF picks wired into real Alpaca executor (`--top-n 10`)
7. ⏳ Phase 3 — Optimize top-N size, add exit rules (stop-loss, trailing)
8. ⏳ **Regime overlay (saved for later)** — weekly-ratchet stop on SPY/QQQ as a whole-book market gate (long-all / cash / risk-off when the broad market breaks its weekly stop). Untested, speculative; the 7.1% DD weekly-timing result on the trio is the seed. Would need its own backtest before any live use.

## Critical Context
- PostgreSQL `swingtrader-db` on `127.0.0.1:5432`, docker container healthy
- Scanner tables: **1,435 enabled stocks + 28 enabled ETFs** with `is_etf` flag; `tbl_etf_tickers` (29 rows incl. BLENDED) has company names
- EMA=10, SMA=40, COST=0.0005, CAPITAL=100000
- MTF Top-N Phase 2 is live: `mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades` in PostgreSQL; sector ETFs shown in Slack as info-only scoring
- `swingtrader-mtf-scorer.timer` active at 4:45 PM ET weekdays — runs `--action score --mode all` via systemd; `swingtrader-mtf-executor.timer` at 10:00 AM ET runs `--action execute --mode all` (both `Persistent=yes`)
- `mtf_positions` is the source of truth for holdings; MTM in Slack = held qty × latest close; ETF P&L uses real Alpaca fill prices
- `get_pending`/`save_pending` cast JSONB to `::text` — psycopg2 jsonb handling varies by adapter config
- `ema10_sma40_crossover` and `sma_crossover` columns in scanner tables are never populated by the pipeline (all false) — must compute inline via window functions
- Laravel backend runs on port 9000 with `artisan serve` via systemd
- Three composite indexes: `idx_daily_tid_date_close`, `idx_wk_tid_date_close`, `idx_1h_tid_date_atr`
- Scanner daily data incomplete for current day — `populate_tickers.py --timeframe day` runs at 9 AM before market close
- Explorer page: `http://localhost:9000/scanner/explorer` (HTML), data: `/scanner/explorer-data?mode=stock|etf` (JSON, ~6s uncached / 0.16s cached)
- Backtest results: unfiltered MTF +5,469% (22.2% DD); `--min-score 5` +9,061% (33.2% DD); `--min-score 5 + --infancy` +688% (59.2% DD)
- **CHAND Alpaca** (key REDACTED): $1M paper, active, 0 positions
- **EMAC Alpaca** (key REDACTED, acct #PA3EHVX93SJT): $1M paper, stopped
- **MTCS Alpaca** (key REDACTED, acct #PA3NCXU4O2CN): $1M paper, stopped (code deleted 2026-08-10)

## Relevant Files
- `swingtrader/services/mtf/runner.py`: MTF Top-N Phase 2 — `--action score|execute` + `--mode stock|etf|all` flags, DB-backed state (`mtf_pending`/`mtf_runs`/`mtf_positions`), crash alerting, stale data check, DB retry, sector info, **entry date column in terminal + Slack**. Stocks scored with Multi-TF; ETF leg uses weekly EMA10>SMA40 rotation (`_compute_emasma_score`)
- `swingtrader/services/mtf/db.py`: Scanner DB access + `mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades` state tables, JSONB helpers (`save_pending`/`get_pending`/`clear_pending`, `log_run`/`get_last_run`)
- `swingtrader/services/mtf/config.py`: DB config, TOP_N=10, COST=0.0005, CAPITAL=100000
- `swingtrader/services/mtf/executor.py`: Alpaca order executor (mode keys); `_wait_for_fill` polls to full fill, buy path falls back to Alpaca position qty so fills never under-record; `reconcile_trades()` rebuilds `mtf_trades` from Alpaca order history
- `swingtrader/services/mtf/reconcile_trades.py`: CLI `--mode all|stock|etf` — idempotent fill-log rebuild (delete + re-insert from Alpaca's authoritative filled orders); use when `mtf_trades` disagrees with real fills
- `swingtrader/services/mtf/systemd/swingtrader-mtf-scorer.service`: Single ExecStart `--action score --mode all`, `TimeoutStopSec=300` (executor service runs `--action execute`)
- `swingtrader/services/mtf/health_check.py`: Checks timer, journal errors, data freshness, `mtf_runs` staleness, `mtf_pending` status — all DB-backed
- `swingtrader/services/scripts/show_picks.py`: Reads picks from `mtf_picks_*.csv` + holdings from `mtf_positions`, equity from real Alpaca accounts
- `swingtrader/backend/storage/framework/cache/`: Explorer data cache (5-min TTL) — clear this + `views/` for blade changes
- `common/docs/services_doc/swingtrader-mtf-scorer.service`: Docs copy matching active service (`--mode all`, `TimeoutStopSec=300`)
- `common/docs/services_doc/mtf_daily_runner.md`: Updated with combined Slack message example, per-mode CSVs, `--mode all` CLI docs, `--user` systemd commands
- `scanner/backend/Controllers/ScannerController.php`: Explorer data endpoint with optimized window function queries
- `scanner/backend/views/scanner/explorer.blade.php`: Explorer Dashboard — 3-panel charts, all-strategy signal columns, sortable
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py`: Multi-TF scanner with scoring + infancy + market breadth → Slack (dir holds only this live service + `config.py`/`db.py` deps; all EMAC code deleted)
- `swingtrader/services/mtf/backtest_topn_multitf.py`: Top-N backtest with `--etf --score --min-score --infancy --exit daily-ema` flags, partial-date exclusion fix
- `swingtrader/services/ppo/`: **CLOSED experiment** — TOS WeeklyAndDailyPPO backtests (`backtest.py` state machine, `backtest_topn.py` rotation, `FINDINGS.md`). Do not revisit.
- `common/docs/mtf-infra-refactor-plan.md`: **MTF Infrastructure Refactor Plan** — VTI universe, partitioning, worker scheduler, implementation tasks
- `scanner/services/scripts/compute_indicators.py`: **Rewritten** — partition-aware workers (1 per hash partition), COPY bulk UPDATEs, 12x speedup (1h 47min → 8.5min)
- `scanner/services/scripts/get_vti_universe.py`: **New** — fetches all active US equities from Alpaca, filters by price/exchange/ETF, inserts into `tbl_stock_tickers`
