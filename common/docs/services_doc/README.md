# Services Index — single source of truth for what's actually deployed

Every row below was cross-checked against live `systemctl list-timers --all`,
`systemctl is-enabled`, and `crontab -l` on **2026-09-27**. If this table and a unit
file in this directory ever disagree, re-run those commands — this file (and the
`.service`/`.timer` files next to it) should always mirror `/etc/systemd/system/`
and the box's crontab, not the other way around. The per-service `systemd/`
directory next to each service's code (e.g. `swingtrader/services/mtf/systemd/`)
is the deploy source; the copies here are the documentation mirror.

## Trading (places orders)

| Driver | Mechanism | Schedule | Status |
|---|---|---|---|
| **CoreEG100** (`trades:execute-EW-gate100`) | user **crontab**, not systemd | every 5 min, market hours | ✅ live — the only driver that places orders |

CoreEG100 is *not* a systemd unit — it's a plain cron entry (`crontab -l`). See
`AGENTS.md` for the strategy logic; there is no unit file for it in this directory.

## Scanner data pipeline (no orders)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-scanner-update.timer` | Mon–Fri 09:00 | ✅ enabled/active | Pre-close weekly+daily bar populate + indicators |
| `swingtrader-scanner-hourly.timer` | Mon–Fri 09:10, 10:10, …, 15:10 (7 runs) | ✅ enabled/active | Intraday hourly capture + MACD/EMA recompute |
| `swingtrader-scanner-backfill.timer` | Mon–Fri 16:30 | ✅ enabled/active | Post-close settle (weekly+daily final closes) + hourly backfill + indicators |

## Live strategies / signal services (Slack; CoreEG100 above is the only order-placer)

| Unit | Schedule (ET) | Status | Purpose |
|---|---|---|---|
| `swingtrader-mtf-executor.timer` | Mon–Fri 10:25 | ✅ enabled/active | MTF emasma score **+ execute** — places MTF stock/ETF orders |
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
