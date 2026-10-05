# Services Index — single source of truth for what's actually deployed

Cross-checked against live `systemctl list-timers --all`, `systemctl list-unit-files`,
and `crontab -l` on **2026-10-05**. If this table and `/etc/systemd/system/` ever
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
| `swingtrader-prices-load.timer` | Mon–Fri 09:05 | ✅ enabled/active | **Canonical** `tbl_prices_daily`/`tbl_prices_weekly` load + ATR recompute. Added 2026-10-05 — `load_prices.py` is the only writer of those tables and nothing ran it, so they only advanced by hand. Runs after the open (Alpaca emits the current week's bar once that week has traded), ~80 min clear of the 10:25 executor. `Persistent=true`; deliberately no `RemainAfterExit` and no `Requires=` from the executor. |
| `swingtrader-scanner-update.timer` | Mon–Fri 09:00 | ✅ enabled/active | Pre-close weekly+daily **legacy** bar populate + indicators (`tbl_scanner_tickers*`, consumed by Explorer) |
| `swingtrader-scanner-backfill.timer` | Mon–Fri 16:30 | ✅ enabled/active | Post-close settle (weekly+daily final closes) + indicators. **This is the only thing that lands the 16:00 close** — `prices-load` at 09:05 runs before the bell and cannot settle it. |

Both legacy units still own `tbl_scanner_tickers*` (`compute_indicators --timeframe
week/day`). Those tables are *not* the trading path — see the canonical/legacy split in
`OPERATING_RULES.md`.

### `Persistent=true` vs `false` — do not normalise these

Changed 2026-10-05. `Persistent=true` means *"if this would have fired while the box was
off, fire it at the next boot."* With all ten timers `true`, an evening power-off — or any
reboot after the scheduled minute — made **every** timer of the missed day due at once,
including both order-placers. That ran `legema` and `mtf-executor` **pre-market at 08:45,
before `prices-load` had loaded a bar**, and hit Alpaca with ~10 concurrent units.

| `Persistent=true` — a missed run must still happen | `Persistent=false` — a missed run must be **skipped** |
|---|---|
| `prices-load` (09:05), `scanner-update` (09:00), `scanner-backfill` (16:30), `backup` (16:15) | `legema` (10:05), `mtf-executor` (10:25), `mtf-scorer` (16:45), `daily-signal` (17:00), `weekly-takeoff` (Fri 17:15), `earnings-screener` (09:30–15:30) |

The rule: **data refresh and backup catch up; anything that trades or posts a signal does
not.** A boot after 10:25 therefore skips the day's MTF run instead of replaying it at the
wrong time — the readiness gate is the backstop, not the schedule. This is what makes a
future nightly power-off safe. Both sides of the split are commented in the unit files so
the asymmetry does not get "corrected" away.

## Live strategies / signal services (Slack only; not order-placers)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-mtf-executor.timer` | Mon–Fri 10:25 | ✅ enabled/active | MTF emasma score **+ execute**. Runs `executor_retry.py` (2026-09-28): score retried every 30m until it has all tickers' data **or 16:00 ET**, then execute runs once and the unit exits. No attempt starts at/after the close, so the 16:45 recap and tomorrow's 10:25 trigger are never blocked; `TimeoutStartSec=6h` is the backstop. Give-up posts a red Slack alert with the last `mtf_runs` status. |
| `swingtrader-mtf-scorer.timer` | Mon–Fri 16:45 | ✅ enabled/active | MTF evening recap — re-scores today's settled close, posts the **same** Slack summary as 10:25. **No orders**; `save_pending` is overwritten by tomorrow's inline score, so it cannot double-execute. |
| `swingtrader-daily-signal.timer` | Mon–Fri 17:00 | ✅ enabled/active | Daily Signal two-CO (WCO∧DCO) Slack emit. **No orders.** |
| `swingtrader-weekly-takeoff.timer` | Fri 17:15 | ✅ enabled/active | Weekly EMA10/SMA40 take-off scanner, Slack post. **No orders.** |
| `swingtrader-earnings-screener.timer` | Mon–Fri, every 30 min 09:30–15:30 | ✅ enabled/active | Daily-MACD earnings-crossover screener, Slack post. **No orders.** Reads `tbl_earnings_calendar`. |
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