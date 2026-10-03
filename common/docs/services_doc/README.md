# Services Index — single source of truth for what's actually deployed

Every row below was cross-checked against live `systemctl list-timers --all`,
`systemctl is-enabled`, and `crontab -l` on **2026-09-28**. If this table and a unit
file in this directory ever disagree, re-run those commands — this file (and the
`.service`/`.timer` files next to it) should always mirror `/etc/systemd/system/`
and the box's crontab, not the other way around. The per-service `systemd/`
directory next to each service's code (e.g. `swingtrader/services/mtf/systemd/`)
is the deploy source; the copies here are the documentation mirror.

## Trading (places orders)

| Driver | Mechanism | Schedule | Status |
|---|---|---|---|
| **CoreEW P20w** — "LegEMA" (`trades:execute-leg-ema --span=20`) | systemd `swingtrader-legema.{service,timer}` | Mon–Fri 10:05 ET (+0–60 s `RandomizedDelaySec`) | ✅ enabled/active — per-leg weekly EMA(20) crossover, acts once per new settled week |
| **MTF Top-N** (`swingtrader-mtf-executor --mode all`) | systemd `swingtrader-mtf-executor.{service,timer}` | Mon–Fri 10:25 ET | ✅ enabled/active — scores **and** executes both legs (stocks #PA368CPXNS13, ETFs #PA3U8GZ96PEN) |

Both order-placing drivers are systemd units in this directory. **The old CoreEG100 crontab
line is commented out** (`trades:execute-EW-gate100`, retired 2026-09-28) — the file and code
are kept for rollback, and uncommenting it is the rollback procedure. Strategy logic:
`AGENTS.md` / `OPERATING_RULES.md` and [../BUY_SELL_TRIGGERS.md](../BUY_SELL_TRIGGERS.md).
The `swingtrader-legema` deploy source lives in
`swingtrader/services/mtf/systemd/`; the copies here are the documentation mirror.

## Scanner data pipeline (no orders)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-scanner-update.timer` | Mon–Fri 09:00 | ✅ enabled/active | Pre-close weekly+daily bar populate + indicators |
| `swingtrader-scanner-hourly.timer` | — | ⛔ **disabled 2026-10-02** | Hourly latest-trade capture. No live consumer left (HCO removed from Daily Signal, MTF emasma never read it); kept for the `--strategy mtf` research path only |
| `swingtrader-scanner-backfill.timer` | Mon–Fri 16:30 | ✅ enabled/active | Post-close settle (weekly+daily final closes) + hourly backfill + indicators |

## Live strategies / signal services (Slack; the two trading drivers above are the only order-placers)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-mtf-executor.timer` | Mon–Fri 10:25 | ✅ enabled/active | MTF emasma score **+ execute** — places MTF stock/ETF orders. Runs `executor_retry.py` (added 2026-09-28): the score step is retried every 30m until it has all the tickers' data **or 16:00 ET**, then the execute step runs once and the unit exits. No attempt starts at/after the close, so the 16:45 recap and tomorrow's 10:25 trigger are never blocked; `TimeoutStartSec=6h` is the backstop (systemd won't re-trigger an active oneshot, so a stuck loop would skip the next day). Give-up posts a red Slack alert with the last `mtf_runs` status. |
| `swingtrader-mtf-scorer.timer` | Mon–Fri 16:45 | ✅ enabled/active | MTF evening recap — re-scores today's settled close, posts the **same** Slack summary the 10:25 run posts. **No orders**; `save_pending` is overwritten by tomorrow's inline score, so this can't double-execute. |
| `swingtrader-daily-signal.timer` | Mon–Fri 17:00 | ✅ enabled/active | Daily Signal all-3-CO Slack emit. **No orders.** |
| `swingtrader-weekly-takeoff.timer` | Fri 17:15 | ✅ enabled/active | Weekly EMA10/SMA40 take-off scanner, Slack post. **No orders.** |
| `swingtrader-earnings-screener.timer` | Mon–Fri, every 30 min 09:30–15:30 | ✅ enabled/active | Daily-MACD earnings-crossover screener, Slack post. **No orders.** |
| `swingtrader-earnings-refresh.timer` | Sun 06:00 | ✅ enabled/active | Refreshes the earnings-date cache the screener reads |

## Infra

| Unit | Schedule | Status | Purpose |
|---|---|---|---|
| `swingtrader-backend.service` | always-on | ✅ enabled/running | Laravel backend, port 9000 |
| `swingtrader-fe-dev.service` | always-on | ✅ enabled/running | Svelte/Vite dev server, port 5173 |
| `swingtrader-db.service` | always-on | ✅ enabled/exited (starts the Docker container, then exits — container itself stays up) | PostgreSQL container |
| `swingtrader-backup.timer` | daily 16:15 | ✅ enabled/active | PostgreSQL backup |

## Retired / not deployed

| Unit | Status | Notes |
|---|---|---|
| `swingtrader-optimizer.service` / `.timer` | ⛔ **disabled** (confirmed via `systemctl is-enabled`) | Legacy CHAND nightly param-grid search. Dead since CoreEW went pure equal-weight 2026-09-12 — no chandelier params left to tune. Unit files kept for reference only. |
| `sec-research.service` / `.timer` | ⚠️ **not installed** — no file exists under `/etc/systemd/system/`, no `systemctl` entry at all | These two files document what a systemd wrapper *would* look like around `scanner/services/sec_research.py`; nothing on this box actually runs it on a timer. Run it manually per `sec_research_guide.md` if you need it. |
| `swingtrader-mtf-preview.service` / `.timer` (in `swingtrader/services/mtf/systemd/`, not mirrored here) | ⚠️ **not installed** | Dry-run alternative to `swingtrader-mtf-scorer` (17:05 ET, `--dry-run` execute instead of the scorer's plain re-score). Code exists in the repo but was never `daemon-reload`/`enable`d — confirm with whoever wrote it whether it's superseded-by or meant-to-replace the live scorer before installing it, since running both would post the evening Slack summary twice. |

## Corrections made 2026-09-27

Audit against live `systemctl`/`crontab` found this directory had drifted:
- `swingtrader-scanner-hourly.{service,timer}` and `swingtrader-weekly-takeoff.{service,timer}` existed live but were **missing entirely** from this directory — added.
- `swingtrader-mtf-scorer.{service,timer}` here still said **DISABLED** ("scoring is done inline by the 10:25 executor... no OnCalendar set"). It has since been re-enabled live as a 16:45 ET evening-recap timer — file replaced with the live version.
- `swingtrader-scanner-backfill.service` here was missing the weekly+daily settle `ExecStart` lines (only had hourly backfill) and had stale worker counts — replaced with the live version.
- `swingtrader-scanner-update.service` here had `--workers 10`; live runs `--workers 3` — replaced with the live version.

## Corrections made 2026-09-28 (CoreEW P20w go-live)

- `swingtrader-legema.{service,timer}` are **enabled and active** (verified via
  `systemctl is-enabled` + `systemctl list-timers --all`) but were **missing entirely** from
  this directory — added (copies verified byte-identical to `/etc/systemd/system/` and to the
  deploy source in `swingtrader/services/mtf/systemd/`).
- CoreEG100's `trades:execute-EW-gate100` crontab line is now **commented out** (retired
  2026-09-28, replaced by P20w). The "user crontab, every 5 min" row in the Trading table was
  wrong after that date — rewritten to list both live order-placing drivers as systemd units.
