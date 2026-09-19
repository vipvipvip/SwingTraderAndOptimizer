# Landing — SwingTraderAndOptimizer

> **Resume current work:** `common/docs/HANDOFF_DailySignal_All3CO.md` (Daily Signal all-3-CO, 2026-09-16). Prior: `common/docs/HANDOFF_CoreEW_rename.md` (CoreEW intraday drift rebalance + gain-cap rake). Full history: git + `common/docs/{TRADING_STRATEGIES.md, How_System_Works.md, perf_explanations.md, COMMAND_REFERENCE.md, ALPACA_KEYS.md, MONITORING.md}`.

## Objective
Find/trade the best entry across all strategies via systematic backtesting, scanner UI, and live automated execution. Explorer Dashboard unifies signals from all strategies (CoreEW/MTF/Daily) with an Early breakout column.

## Live Strategies
| Strategy | Universe | Logic | Status |
|---|---|---|---|
| **CoreEW** (EW trio, ex-CHAND) | QQQ/VTI/VTV | Pure equal-weight book, `trades:execute-EW-ETF` every 5-min cron while market open; no signals/stop-loss | ✅ Live (Laravel), acct #PA3GKZYLVO68, Slack `[CoreEW]`, fires only when it actually trades |
| **MTF Top-N** (emasma v3) | 1,435 stocks + 28 ETFs | Stocks: weekly EMA10>SMA40 gap → top-10; ETFs top-3; once/day 10:25; stock leg exits on daily-ATR ratchet. Settled bars only. | ✅ Live, Slack `[MTF+EMA-SMA stocks+ETFs]` |
| **Daily Signal** | same universe | Emits only all-3-CO (WCO+DCO+HCO done) on settled, quality-gated bars → Slack; no orders | ✅ Slack 5:00 PM `[DAILY]` |
| EMAC / MTCS | — | Stopped, replaced by MTF; code deleted | ❌ |
| PPO | — | Closed experiment; do not revisit | ❌ |

## Operating Rules (apply every session)
- **Engine constants:** EMA=10, SMA=40, COST=0.0005, CAPITAL=100000. Universe = 1,435 stocks + 28 ETFs (`tbl_stock_tickers.is_etf`, `tbl_etf_tickers`). PostgreSQL `swingtrader-db` on `127.0.0.1:5432` (docker). Backtests read scanner tables only.
- **MTF state is DB-backed** (`mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades`); `mtf_positions` = source of truth; MTM in Slack = held qty × close. `get_pending`/`save_pending` cast JSONB `::text`. **`save_pending` deletes all unconsumed for the mode before INSERT — never restore same-sig_date DELETE** (crashes `idx_mtf_pending_unconsumed`).
- **emasma scoring reads settled bars only:** `sig_date` = last COMPLETE daily date (never live/partial), tie-break sort `(-score, -gap_w)` — live == backtest, reproducible. Ratchet uses settled daily bars + `latest_settled_daily_closes`; ratchet-sold names get same-day cool-off via `mtf_ratchet_cooldown` (stock leg only).
- **MTF is weekly-only by design** — hourly (`tbl_scanner_tickers_1hour`, 16 hash partitions) is unreliable. Daily Signal is the sole live hourly consumer; treat its signals as day-old/eyeball, never auto-execute.
- **CoreEW logic (Laravel `TradeExecutorService`):** `rebalanceEqualWeightWeekly(dryRun, minDriftPct, minProfitTrigger)` trims/tops-up a leg only when drift from equity/3 > `COREEW_DRIFT_PCT` (0.5%) OR any held leg has unrealized ≥ `COREEW_PROFIT_TRIGGER` ($100 → exact pass, FRACTIONAL shares, `numeric(12,5)`). **`COREEW_GAIN_CAP=150` is the live driver (2026-09-17):** when set, `rakeEqualWeight()` REPLACES the equalize path per cycle — any leg with unbanked uPnL > cap sells the excess above `COREEW_GAIN_BUFFER` ($25) to CASH and STOPS; a later rake-free cycle runs the EW rebalance, which redeploys the cash. Stateless (rake qty = bank/(price − avg_entry), can't re-fire on flat). `--override` forces exact, `--dry-run` previews.
- **Alpaca key routing (3 pairs + scanner)** — see `common/docs/ALPACA_KEYS.md`. CoreEW keys → `swingtrader/backend/.env` AND `scanner/backend/.env` (scanner is read-only IEX consumer on CoreEW keys; missing scanner update silently stalls hourly/ETF capture). MTF stock/ETF keys → `swingtrader/services/mtf/.env` (distinct var names).
- **Backtests:** **A/B only** — `current` vs new variant on BOTH legs (`--exit ratchet-atr --ratchet-atr-src daily`), head-to-head table + "keep current"/"switch" rec. Don't re-run settled variants (daily-bull, gap-reverse, close-200, fresh — keep as research flags). **Backtest returns are NOT trustworthy as returns** (survivorship bias, idealized fills, untrimmed winners; +17K%↔+20M% from tie-break alone) — use only for relative signal quality + replicable-picks validation. Baseline cache: `backtest_topn_multitf.py` + `backtest_baseline_cache.json` via `--cache-baseline` (stock 2021-09-20→2026-09-16, ETF 2020-03-02→2026-09-16); refresh baseline when comparing against new data. Never change the live emasma path without user sign-off.
- **Settled-bar rule (BAND/DOCN 09-16):** validate any DCO/HCO flip against the last settled bar (`date < today`), never the live/partial bar. Daily Signal hourly is quality-gated (`vol >= 1000`).
- **Server power window:** ON Mon–Fri **09:00→10:30 + 16:30→17:10 ET**, OFF all else. Timers `Persistent=true`. Executor at 10:25 depends on 09:00 scanner update (daily bars); boot before ~15:30 still trades, after 16:00 = safe no-trade day. mtf scorer + CHAND optimizer timers disabled.
- **Known code invariants:** `syncLiveTradesFromAlpaca` skips `status !== 'open'`; never overwrite `alpaca_order_id` in `handlePooledEntries`; executor buy path falls back to live Alpaca position qty; `reconcile_trades.py` rebuilds `mtf_trades` from Alpaca fills. `ema10_sma40_crossover`/`sma_crossover` DB columns are never populated — compute inline via window functions. `_nearest_date_idx` fallback for daily data.

## Critical Context
- Laravel on port 9000 (`artisan serve`, systemd). Explorer: `http://localhost:9000/scanner/explorer` (HTML); data `/scanner/explorer-data?mode=stock|etf` (6s cold / 0.16s cached). Clear `swingtrader/backend/storage/framework/{cache,views}/` after blade changes (NOT `scanner/backend/`).
- Indexes: `idx_daily_tid_date_close`, `idx_wk_tid_date_close`, `idx_1h_tid_date_atr`. Scanner daily data is incomplete for the current day (9 AM pre-close run).
- Accounts: CoreEW #PA3GKZYLVO68 ($100K, reset 09-12; ex-CHAND #PA31Z71315NM); MTF stocks #PA368CPXNS13 (fresh $100K 09-08; old #PA3H8RAWIS0C orphaned/401); MTF ETFs #PA3U8GZ96PEN; EMAC #PA3EHVX93SJT + MTCS #PA3NCXU4O2CN stopped. All $1M/paper unless noted.
- Known edge: same-day ratchet whipsaw (sell-and-rebuy) is mitigated by cool-off; old scan-side filters (hourly-bearish, chase-guard) exist but `ENABLE_CHASE_GUARD` is off.

## Relevant Files
- `swingtrader/services/mtf/runner.py` — score/execute, `--action score|execute`, `--mode stock|etf|all`, `--strategy emasma|v2|mtf`; settled-bar scoring, sector info, DB-backed state
- `swingtrader/services/mtf/{db,config,executor}.py` — DB state tables/JSONB helpers; config (TOP_N=10, ETF_TOP_N=3, RATCHET_ATR_MULT=2.0); Alpaca executor + `_compute_ratchet_stops` + `reconcile_trades()`
- `swingtrader/services/mtf/reconcile_trades.py` — idempotent `mtf_trades` rebuild from Alpaca fills; `--mode all|stock|etf`
- `swingtrader/services/mtf/systemd/swingtrader-mtf-executor.{service,timer}` — enabled, 10:25 Mon–Fri, score+execute `--strategy emasma --mode all`; `swingtrader-mtf-scorer.service` static/disabled
- `swingtrader/services/mtf/health_check.py`, `swingtrader/services/scripts/show_picks.py`, `coreew_rebalance.sh`
- `swingtrader/services/mtf/backtest_topn_multitf.py` — top-N backtest (`--etf --score emasma|mtf --min-score --infancy --exit daily-ema|ratchet-atr --ratchet-atr-src daily|hourly|weekly --daily-only`); includes baseline cache; validation source for live emasma
- `swingtrader/services/mtf/backtest_trio_ew.py` — CoreEW trio comparison backtest
- `swingtrader/backend/app/Services/TradeExecutorService.php` — `rebalanceEqualWeightWeekly(dryRun, minDriftPct, minProfitTrigger)` + `rakeEqualWeight(dryRun, gainCap, gainBuffer)` (rake replaces equalize path when `COREEW_GAIN_CAP`>0); legacy chandelier code retained, not called live
- `swingtrader/backend/app/Console/Commands/ExecuteEWETF.php` — 5-min intraday EW driver (`trades:execute-EW-ETF`); `COREEW_DRIFT_PCT`/`COREEW_PROFIT_TRIGGER`/`COREEW_GAIN_CAP`/`--override`/`--dry-run`
- `swingtrader/backend/app/Console/Commands/RunNightlyOptimizer.php` + `swingtrader/services/optimizer/` — disabled/legacy
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py` — Daily Signal, all-3-CO settled-bar emitter (dir holds only this + config.py/db.py)
- `scanner/backend/Controllers/ScannerController.php`, `scanner/backend/views/scanner/explorer.blade.php` — Explorer endpoint + dashboard
- `scanner/services/scripts/{compute_indicators.py, get_vti_universe.py, populate_tickers.py}` — partition-aware indicator worker, VTI universe fetcher, bar ingestion (+yfinance fallback)
- `common/docs/mtf-infra-refactor-plan.md` — archived infra plan