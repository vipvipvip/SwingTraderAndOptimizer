# Services Index — single source of truth for what's actually deployed

Cross-checked against live `systemctl list-timers --all`, `systemctl list-unit-files`,
and `crontab -l` on **2026-10-05**; pipeline/compute/earnings rows revised **2026-10-06**. If this table and `/etc/systemd/system/` ever
disagree, the OS wins and this file is wrong — re-run those commands and fix it here.

## Where the unit files live (changed 2026-10-05)

**This directory is documentation only. There are no `.service`/`.timer` files here
any more.** Each unit is owned by the component whose code it runs, and that
component's `systemd/` directory is the single deploy source:

| Component | Deploy source |
|---|---|
| Scanner (bar populate, backfill, earnings, prices) | `scanner/systemd/` |
| Laravel backend / DB / backup / frontend dev | `swingtrader/systemd/` |
| MTF, CoreEW P20w, prices-load | `swingtrader/services/mtf/systemd/` |
| Daily Signal | `swingtrader/services/ema_sma_crossover/systemd/` |
| Weekly take-off | `swingtrader/services/weekly_takeoff/systemd/` |

Deploy = copy the unit to `/etc/systemd/system/`, then `daemon-reload` (+ `enable` for
timers). Until 2026-10-05 this directory held a *second* copy of 24 units and had drifted:
it was missing `swingtrader-prices-load.*` (added the same day) while still carrying units
whose scripts and tables had been deleted. Two copies of a unit file is one copy too many —
edit the component's copy, then re-verify against the OS.

## Trading (places orders)

| Driver | Mechanism | Schedule | Status |
|---|---|---|---|
| **CoreEW P20w** — "LegEMA" (`trades:execute-leg-ema --span=20`) | systemd `swingtrader-legema.{service,timer}` | Mon–Fri 10:05 ET (+0–60 s `RandomizedDelaySec`) | ✅ enabled/active — per-leg weekly EMA(20) crossover, acts once per new settled week |
| **MTF Top-N** (`swingtrader-mtf-executor --mode all`) | systemd `swingtrader-mtf-executor.{service,timer}` | Mon–Fri 10:25 ET | ✅ enabled/active — scores **and** executes both legs (stocks #PA368CPXNS13, ETFs #PA3U8GZ96PEN) |

These are the **only** order-placing drivers. The old CoreEG100 crontab line is commented
out (`trades:execute-EW-gate100`, retired 2026-09-28); uncommenting it is the rollback
procedure. Strategy logic: `AGENTS.md` / `OPERATING_RULES.md`, [../BUY_SELL_TRIGGERS.md](../BUY_SELL_TRIGGERS.md).

## Scanner data pipeline (no orders)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-prices-load.timer` | Mon–Fri 09:05 | ✅ enabled/active | **Canonical** `tbl_prices_daily`/`tbl_prices_weekly` catch-up: `load_prices.py --resume` → `compute_indicators.py` (week, day). Incremental per ticker, so on a normal day it is ~1 request per behind ticker and a seconds-long compute; weekly is skipped Mon–Thu (see below). `Persistent=true`; deliberately no `RemainAfterExit` and no `Requires=` from the executor. |
| `swingtrader-scanner-update.timer` | Mon–Fri 09:00 | ⛔ disabled 2026-10-06 | Redundant with `prices-load` (09:05): both ran the same load + `atr_stop`. The deprecated `tbl_scanner_tickers*` tables it once fed were renamed `zz_deprecated_*` on 2026-10-06 |
| `swingtrader-scanner-backfill.timer` | Mon–Fri 16:30 | ✅ enabled/active | Post-close settle: `load_prices.py --timeframe both --resume` → `compute_indicators` week → day, all on the canonical pair. **This is the only thing that lands the 16:00 close** (and, on Fridays, the week's final weekly bar). It no longer touches `tbl_scanner_tickers*`. |

The deprecated pair `tbl_scanner_tickers` / `tbl_scanner_tickers_daily` is **no longer written or
read by anything live**; both were renamed `zz_deprecated_scanner_tickers{,_daily}` on 2026-10-06
(**dropped 2026-10-07**, ~2.2 GB freed; there is no in-DB undo).

### Canonical price tables — how they are loaded (2026-10-06)

`tbl_prices_weekly` / `tbl_prices_daily` are **canonical**: CoreEW (`TradeExecutorService.php`),
MTF (`db.py`, `executor.py`, `runner.py`), the readiness gate, Daily Signal, `weekly_takeoff`,
the Explorer and `health-check.sh` all read them. Only `load_prices.py` writes bars; only
`compute_indicators.py` writes `atr_stop`.

- **Incremental per ticker, always.** `load_prices.py` fetches each ticker from its **own**
  last stored bar (daily: frontier + 1; weekly: the frontier bar itself, so a bar fetched
  early gets completed). Only a ticker with no rows pulls full history (2016+). Before this,
  any ticker with a gap re-pulled ~2,650 bars (the 2026-10-05 run: 6 min, SIP throttled
  12.7/s → 1.2/s). `--full-refresh` is the explicit, opt-in way to re-pull history — **needed
  after a split/dividend**, because `adjustment=all` re-bases *old* bars and an incremental
  pull cannot fix them. `--report-only` lists what is behind and fetches nothing.
- **Weekly is loaded once a week: Friday after the 16:05 ET settle.** Alpaca stamps each weekly
  bar on the ISO-week Monday. The newest *final* bar is therefore this Monday's stamp only
  from Fri 16:05, and **last** Monday's from Mon–Thu. `load_prices.settled_week_monday()` is
  the one definition; `resume_cutoff('week')` and `data_readiness._expected_session_date('week')`
  both call it, and the loader refuses to persist the still-forming week. Consequence: Mon–Thu
  the weekly load/compute are no-ops, and the Monday gate expects **last** week's stamp
  (e.g. 2026-09-28 holds Friday 10-02's close). `weekly_takeoff` (Fri 17:15) uses the same rule.
- **`compute_indicators.py` is incremental.** `load_prices.py` NULLs `atr_stop` on every row it
  upserts, so "NULL past the 14-bar warm-up" means "new or restated". The script finds each
  ticker's first such bar and recomputes only from there (14 bars of look-back). Normal day:
  seconds, vs ~7 min for the old full rewrite (verified identical to the full result: 0
  mismatches). Nothing pending → exits "already current". `--full` forces the old behaviour.
  `week`/`day` and `prices-weekly`/`prices-daily` are aliases for the same two tables. Exits
  non-zero on a worker error. Keep `--workers` ≤ 6 (64 MB `/dev/shm`).
- **Readiness gate (`data_readiness.py`)**: `atr_stop` is required only on tickers that have a
  bar **at the frontier** — a halted/delisted name (QRVO, PSKY, WBD) is reported as stale but
  no longer blocks the other ~1,400. **Held positions** (`mtf_positions`) are a hard
  requirement: each must have a frontier bar *and* a non-NULL `atr_stop`, or the gate fails.
  `executor.py` also logs a loud `⚠️ HELD … NULL/invalid atr_stop` instead of silently skipping
  the bar (no behaviour change to exits). Self-repair (`backfill_all_missing.py`) now just calls
  `load_prices` + `compute_indicators`; it used to fill the deprecated pair and left the real gap.

### `Persistent=true` vs `false` — do not normalise these

Changed 2026-10-05. `Persistent=true` means *"if this would have fired while the box was
off, fire it at the next boot."* With all ten timers `true`, an evening power-off — or any
reboot after the scheduled minute — made **every** timer of the missed day due at once,
including both order-placers. That ran `legema` and `mtf-executor` **pre-market at 08:45,
before `prices-load` had loaded a bar**, and hit Alpaca with ~10 concurrent units.

| `Persistent=true` — a missed run must still happen | `Persistent=false` — a missed run must be **skipped** |
|---|---|
| `prices-load` (09:05), `scanner-update` (09:00), `scanner-backfill` (16:30), `backup` (16:15) | `legema` (10:05), `mtf-executor` (10:25), `mtf-scorer` (16:45), `daily-signal` (17:00), `trigger-levels` (10:00, 17:05), `weekly-takeoff` (Fri 17:15), `earnings-screener` (09:30–15:30) |

The rule: **data refresh and backup catch up; anything that trades or posts a signal does
not.** A boot after 10:25 therefore skips the day's MTF run instead of replaying it at the
wrong time — the readiness gate is the backstop, not the schedule. This is what makes a
future nightly power-off safe. Both sides of the split are commented in the unit files so
the asymmetry does not get "corrected" away.

## Live strategies / signal services (Slack only; not order-placers)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-mtf-executor.timer` | Mon–Fri 10:25 | ✅ enabled/active | MTF emasma score **+ execute**. Runs `executor_retry.py` (2026-09-28): score retried every 30m until it has all tickers' data **or 16:00 ET**, then execute runs once and the unit exits. No attempt starts at/after the close, so the 16:45 recap and tomorrow's 10:25 trigger are never blocked; `TimeoutStartSec=6h` is the backstop. Give-up posts a red Slack alert with the last `mtf_runs` status. |
| `swingtrader-mtf-scorer.timer` | Mon–Fri 16:45 | ✅ enabled/active | MTF evening recap — re-scores today's settled close, posts the **same** Slack summary as 10:25. **No orders**; `save_pending` is overwritten by tomorrow's inline score, so it cannot double-execute. | **No data-refresh pre-steps** (removed 2026-10-06): the 16:30 backfill already loaded + computed, and the runner's gate runs `--ensure`, which self-repairs.
| `swingtrader-daily-signal.timer` | Mon–Fri 17:00 | ✅ enabled/active | Daily Signal two-CO (WCO∧DCO) Slack emit. **No orders.** |
| `swingtrader-trigger-levels.timer` | Mon–Fri 10:00 + 17:05 | ✅ enabled/active (installed 2026-10-07) | **Trigger Levels** Slack report: next buy/sell price per ticker for CoreEW P20w (QQQ/VTI/VTV) and MTF-ETF (top 3 + next 3). **No orders, no DB writes.** Runs `swingtrader/services/mtf/trigger_levels.py` (MTF-ETF Alpaca keys for live prices; CoreEW levels from the PHP series). `Persistent=false`. `--dry-run` prints, `--no-explainer` drops the HOW TO READ block. Spec: [../SPEC_trigger_levels.md](../SPEC_trigger_levels.md). |
| `swingtrader-weekly-takeoff.timer` | Fri 17:15 | ✅ enabled/active | Weekly EMA10/SMA40 take-off scanner, Slack post. **No orders.** |
| `swingtrader-earnings-screener.timer` | Mon–Fri, every 30 min 09:30–15:30 | ✅ enabled/active | Daily-MACD earnings-crossover screener, Slack post. **No orders.** Reads `tbl_earnings_calendar`. Scheduled run is `--days 7 --max-fresh 10 --all --slack`: earnings within the next **7 days** and a MACD cross at most **10 days** old (changed 2026-10-06; was 14 days / no freshness cap). Slack posts only when the list changes. |
| ~~`swingtrader-earnings-refresh.timer`~~ | ⛔ **REMOVED 2026-10-05** | Refreshes the earnings-date cache the screener reads. **On demand by design** — run `cd scanner && ./.venv/bin/python3 services/earnings_screener.py --refresh`. It was failing on *every* boot with `Connection refused` on 5432 (the Sunday 06:00 fire is always caught at boot by `Persistent=true`, before `swingtrader-db.service` has the container listening), so `tbl_earnings_calendar` had silently gone stale from **2026-09-13 to 2026-10-05** while the screener kept posting from it. The cache was refreshed on 10-05 (941 → 1380 rows, horizon 10-08 → 11-02). Refresh before you rely on the screener. |

## Infra

| Unit | Schedule | Status | Purpose |
|---|---|---|---|
| `swingtrader-backend.service` | always-on | ✅ enabled/running | Laravel backend, port 9000 |
| `swingtrader-fe-dev.service` | always-on | ✅ enabled/running | Svelte/Vite **dev** server, port 5173. Not needed for trading — left enabled deliberately; say the word and it goes. |
| `swingtrader-db.service` | always-on | ✅ enabled/exited (starts the Docker container, then exits — container stays up) | PostgreSQL container |
| `swingtrader-backup.timer` | daily 16:15 | ✅ enabled/active | PostgreSQL backup |

## Retired / not deployed

| Unit | Status | Notes |
|---|---|---|
| `swingtrader-scanner-hourly.{service,timer}` | ⛔ **REMOVED 2026-10-05** | Hourly latest-trade capture. HOURLY was purged 2026-10-02: `tbl_scanner_tickers_1hour` dropped, `capture_hourly.py` + `backfill_hourly.py` deleted. Units were still installed and disabled. Also killed `runner.py --fresh`, which read that table — now unrunnable, not merely disabled. |
| `swingtrader-optimizer.{service,timer}` | ⛔ **REMOVED 2026-10-05** | Legacy CHAND nightly param-grid search, disabled since CoreEW went pure equal-weight (2026-09-12). Its `ExecStart` script `swingtrader/services/optimizer/run_nightly.sh` **no longer exists**, so the unit could only ever fail. `README.md`, `COMMAND_REFERENCE.md`, `UBUNTU_SETUP.md` and `OPERATING_RULES.md` still reference it — stale, not yet swept. |
| `swingtrader-mtf-preview.{service,timer}` | ⚠️ **not installed** | Dry-run alternative to `swingtrader-mtf-scorer` (17:05 ET, `--dry-run` execute). Code exists in `swingtrader/services/mtf/systemd/` but was never enabled. Confirm whether it's superseded-by or meant-to-replace the live scorer before installing — running both posts the evening Slack summary twice. |
| `sec-research.{service,timer}` | ⚠️ **never installed** — wrapper files now **removed** from the repo | They only ever documented what a systemd wrapper *would* look like around `scanner/services/sec_research.py`, which does work (and has a DB cache table) — it just was never scheduled. `sec_research_guide.md` documents running it manually and no longer claims a timer exists. |

## Corrections made 2026-10-05

Audit of this directory against the OS found the drift had turned into a live fault.

- **CRITICAL — the 16:30 post-close settle was dead on arrival.** `swingtrader-scanner-backfill.service`
  kept an `ExecStartPre=populate_tickers.py --timeframe hour` plus two more hourly `ExecStart`
  lines from before the 10-02 purge. `'hour'` is no longer a key in
  `populate_tickers.TIMEFRAMES` or `compute_indicators.TABLES`, so argparse rejected it with
  exit 2 — and because **`ExecStartPre` runs before every `ExecStart`**, the unit aborted
  before the weekly+daily settle lines ever ran. Nothing had failed yet only because the last
  run was Fri 10-02, hours before the purge; the next fire (Mon 16:30) would have skipped
  settling Friday's close entirely, and taken Tuesday's MTF run down with it. Silent: the
  timer still "fires", just with `Result=exit-code`. Hourly lines removed from the unit (repo
  + `/etc/systemd/system/`).
- 24 duplicate unit files removed from this directory; the earnings units (whose only repo
  copy was here) moved to `scanner/systemd/`, the rest verified byte-identical to their
  canonical copy first. The stale `services_doc/swingtrader-mtf-executor.service` was the
  pre-09-28 version lacking `executor_retry.py` — canonical is newer, so nothing was lost.
- `swingtrader-earnings-{refresh,screener}.timer` carried `Timezone=America/New_York`, which
  is **not a valid systemd key** (`systemd-analyze verify` flagged it; the bare `OnCalendar`
  silently used the system TZ). Folded into `OnCalendar=… America/New_York`.
- `advanced_research.md` / `comprehensive_research.md` moved up to `common/docs/` — they
  document research modules, not services. Not deleted.
- `swingtrader-prices-load.*` added to the inventory (see the pipeline table above).

## Corrections made 2026-10-06

Follow-up to the 10-05 audit: the repo had switched the **readers** to the canonical price
tables but the **writers, the repair path and the unit files** still fed the old ones.

- **Writers/repair repointed.** `scanner-update`, `scanner-backfill` and the MTF scorer's
  pre-steps ran `populate_tickers.py` (deprecated tables); `backfill_all_missing.py` (the gate's
  self-heal) wrote them too, so a real gap on the canonical pair would never have healed. All now
  go through `load_prices.py` + `compute_indicators.py`. `backfill_prices_incremental.py` was
  folded into the loader and deleted (two callers for one job is how the original confusion
  started). `compute_indicators` `week`/`day` aliases now point at the canonical tables.
- **`scanner-update.timer` disabled** — identical work to `prices-load` 5 minutes later, and the
  two computes would overlap.
- **Weekly loads only on Friday after close** (see above); the 10-05 partial weekly row
  (1,452 rows stamped 2026-10-05) was deleted.
- **Gate scoping + held-position hard requirement** (see above).
- **Dead hourly references removed:** `TradeExecutorService::getDbPrice` queried the dropped
  hourly table (swallowed into a debug log, silently disabling the live-price deviation guard);
  now reads the latest `tbl_prices_daily` close. `ScannerController.php:544` still used the
  deleted `$latestHourlyDate`, so **`/scanner/explorer-data` returned 500 since the 10-02 purge**
  — fixed. `health-check.sh` hourly checks, `mtf/db.py` dead hourly loaders and the HCO
  backtest (`backtest_single_ticker.py`) removed. `weekly_takeoff` (was reading the deprecated
  weekly table) repointed to `tbl_prices_weekly` with a settled-week filter.
- **HCO is gone from the code and docs**, and `HANDOFF_DailySignal_All3CO.md` was deleted.
- **Optimizer removed:** the legacy `swingtrader/services/optimizer/*.py`, `RunNightlyOptimizer`,
  the `/admin/optimize/trigger` route and the dashboard "Trigger Optimizer" button. Only
  `optimizer/venv` + `requirements.txt` remain (the MTF units run on that venv).
- **Install steps needed after a unit changes** (repo → `/etc/systemd/system`, then
  `daemon-reload`): done 2026-10-06 for `scanner-backfill`, `scanner-update`, `prices-load`,
  `earnings-screener`; `mtf-scorer` (pre-steps removed) done 2026-10-07; `trigger-levels` installed 2026-10-07.
- **Known leftover:** `runner.py::_backfill_daily` (the MTF self-heal) still passes
  `--workers 10` to `load_prices` and `compute_indicators`; the SIP feed throttles above ~6 and
  `compute_indicators` documents ≤ 6. Not changed (live MTF path — needs sign-off).
