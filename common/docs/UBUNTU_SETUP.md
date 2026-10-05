# SwingTrader — Ubuntu/WSL2 Setup & Systemd Services

Installing and running the trading system on **native Ubuntu/Linux** or **WSL2**.

> **Rewritten 2026-10-05.** The previous version of this file described a
> generic Laravel + nightly-optimizer app and was wrong about this codebase in ways
> that would break a fresh install. Specifically, all of the following were incorrect
> and have been corrected or removed below:
>
> - **Paths.** The app is `swingtrader/backend`, `swingtrader/frontend`, `scanner/` —
>   not `backend/`, `frontend/`, `optimizer/` at the repo root.
> - **The crontab section was dangerous.** It instructed you to add
>   `* * * * * php artisan schedule:run` and warned "never comment out this line — a
>   `#` prefix stops trade execution." **That is false.** There is no framework-level
>   schedule and no trade execution in crontab; all order placement is systemd. The
>   live crontab has **zero active entries** (only commented-out history for the
>   retired CoreEG100/variant-S strategies). Adding that line does nothing useful.
> - **`php artisan migrate --force` fails in this repo** (see [Migrations](#migrations)).
> - **`nightly_optimizer.py --timeframe 1Hour` does not exist.** The optimizer's
>   `run_nightly.sh` was deleted and the hourly timeframe was purged 2026-10-02. What
>   remains in `swingtrader/services/optimizer/` is just a `venv` + `requirements.txt`,
>   and that venv is still load-bearing — it runs the MTF units.
> - **`swingtrader-startup.service` and `swingtrader-frontend.service` were never real.**
>   The frontend unit is `swingtrader-fe-dev.service`; there is no startup orchestrator
>   unit, because `swingtrader-db.service` starts the database container.

**Start here too:** [`services_doc/README.md`](services_doc/README.md) is the live
inventory of every unit — status, schedule, purpose. This file covers installing the
box; that one covers what is currently deployed.

---

## Contents

1. [Prerequisites](#prerequisites)
2. [Project layout](#project-layout)
3. [Database (PostgreSQL via Docker)](#database)
4. [Migrations](#migrations)
5. [Backend (Laravel)](#backend-laravel)
6. [Frontend](#frontend)
7. [Python environments](#python-environments)
8. [Systemd services](#systemd-services)
9. [Crontab](#crontab)
10. [On-demand jobs](#on-demand-jobs)
11. [First run / reboot behavior](#first-run--reboot-behavior)
12. [Verify everything](#verify-everything)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Native Ubuntu

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y \
  php-cli php-pgsql php-xml php-dom php-mbstring php-curl php-json php-fileinfo \
  nodejs npm \
  python3 python3-venv python3-pip \
  docker.io docker-compose \
  git curl
```

Composer:

```bash
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x composer.phar
```

> **Ops tooling worth installing on this box:** `ethtool` (to arm Wake-on-LAN),
> `rtcwake` (already present — schedule RTC wake/power-on). See
> [`services_doc/README.md`](services_doc/README.md) for why morning boot time matters.

### WSL2 (not WSL1)

```bash
# From Windows PowerShell — must show VERSION 2
wsl --list --verbose
```

Enable systemd in `sudo nano /etc/wsl.conf`:

```ini
[boot]
systemd=true

[user]
default=YOUR_USERNAME
```

Restart WSL from an **admin** PowerShell: `wsl --shutdown`, then
`systemctl is-system-running` → `running`.

Install **Docker Desktop** → Settings → Resources → WSL Integration → enable the
distro. Verify: `docker --version && docker ps`.

Same apt packages as native, plus `php-sqlite3`. Keep the project inside the WSL
filesystem (`/home/$USER/...`), never `/mnt/c/`.

> **Disable Windows sleep while plugged in.** WSL suspension stops the trading timers
> mid-run. Note that on this box the morning is the fragile part regardless of host:
> the 09:00/09:05 timers fire on boot, not at their scheduled minute.

---

## Project layout

```
swingtrader/
  backend/            Laravel app (artisan) — port 9000
  frontend/           Svelte/Vite — port 5173
  systemd/            backend, db, backup, fe-dev units
  services/
    mtf/              MTF Top-N strategy + systemd/
    ema_sma_crossover/ Daily Signal + systemd/
    weekly_takeoff/   Weekly take-off scanner + systemd/
    optimizer/        venv only (no run_nightly.sh — retired)
scanner/              Python data pipeline + its own .venv + systemd/
common/docs/          operating rules, service inventory, handoffs
```

Each service's `systemd/` directory is the **single deploy source** for its units.
There are no unit files in `common/docs/services_doc/` — that directory is
documentation only.

---

## Database

PostgreSQL runs as the Docker container `swingtrader-db`. The named volume
(`postgres_data`) persists data across restarts — **never use a bind mount, never
`docker-compose down -v`**.

```bash
cd $PROJECT_DIR
docker compose up -d
until docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1" >/dev/null 2>&1; do sleep 2; done
```

`systemd` does this for you via `swingtrader-db.service` (enabled at boot).

Seed tickers:

```bash
cd $PROJECT_DIR/swingtrader/backend
php artisan tinker --execute="
App\Models\Ticker::firstOrCreate(['symbol'=>'SPY'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'QQQ'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'IWM'],['allocation_weight'=>33.34,'enabled'=>1]);
"
```

> **If a Python service reports `Connection refused` on `127.0.0.1:5432`, the database
> container is not up yet.** This is not a bug in the service. Order it after
> `swingtrader-db.service`, or wait for `SELECT 1` to succeed. It is exactly how
> `swingtrader-earnings-refresh` failed on every boot for three weeks before being
> removed on 2026-10-05.

---

## Migrations

**`php artisan migrate` FAILS in this repo.** The `migrations` table is stale relative
to the raw-SQL tables the Python pipeline owns. Apply a specific migration by path:

```bash
cd $PROJECT_DIR/swingtrader/backend
php artisan migrate --force --path=database/migrations/2026_08_05_000000_create_sec_research_analysis_table.php
```

Do not run a bare `migrate` and do not pass `--force` over the whole set without
knowing what it will touch.

---

## Backend (Laravel)

```bash
cd $PROJECT_DIR/swingtrader/backend
composer install --no-interaction --prefer-dist
mkdir -p storage/logs storage/app bootstrap/cache
chmod -R 775 storage bootstrap/cache
cp .env.example .env && nano .env
```

Key `.env` values:

```env
DB_CONNECTION=pgsql
DB_HOST=127.0.0.1
DB_PORT=5432
DB_DATABASE=swingtrader
DB_USERNAME=swingtrader
DB_PASSWORD=<password>

ALPACA_API_KEY=<paper key>
ALPACA_SECRET_KEY=<paper secret>
ALPACA_BASE_URL=https://paper-api.alpaca.markets

SLACK_WEBHOOK_URL=<webhook>
```

> **Alpaca keys are per-account and per-component.** The wrong `.env` produces a
> confusing failure rather than an obvious one — see
> [`ALPACA_KEYS.md`](ALPACA_KEYS.md) before rotating or debugging a 401/403. Never
> commit any `.env`.

Manual mode: `php artisan serve --host=0.0.0.0 --port=9000`

After editing any `.blade.php`, clear `swingtrader/backend/storage/framework/{cache,views}/`
— **not** `scanner/backend/`.

---

## Frontend

```bash
cd $PROJECT_DIR/swingtrader/frontend
npm install
npm run dev        # dev server, port 5173
# npm run build    # production bundle → dist/
```

`localhost:5173` in dev. The Explorer dashboard is at
`http://localhost:9000/scanner/explorer`.

---

## Python environments

Two venvs, both required:

| venv | Python | Used by |
|---|---|---|
| `scanner/.venv` | 3.14 | bar populate, indicators, data readiness, earnings screener |
| `swingtrader/services/optimizer/venv` | 3.13/3.14 | MTF runner / executor / daily signal |

```bash
# scanner
cd $PROJECT_DIR/scanner && python3 -m venv .venv
./.venv/bin/pip install --upgrade pip setuptools wheel
./.venv/bin/pip install -r services/requirements.txt   # if present
./.venv/bin/pip install psycopg2-binary alpaca-py pandas sqlalchemy

# MTF / services
cd $PROJECT_DIR/swingtrader/services/optimizer
python3 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install -r requirements.txt
```

> The `optimizer/venv` name is historical — the nightly optimizer that gave the
> directory its name is retired. The venv itself is **not** optional; deleting it
> breaks every MTF unit.

---

## Systemd services

Copy a unit in, then reload:

```bash
sudo cp <component>/systemd/<unit> /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now <unit>.timer
```

### Always-on (enable; they start at boot)

| Unit | Source | Purpose |
|---|---|---|
| `swingtrader-db.service` | `swingtrader/systemd/` | starts the PostgreSQL container, then exits |
| `swingtrader-backend.service` | `swingtrader/systemd/` | Laravel on port 9000 |
| `swingtrader-fe-dev.service` | `swingtrader/systemd/` | Vite dev server on port 5173 (not needed for trading — safe to disable) |

### Timers (enable the `.timer`; the paired `.service` stays disabled — that is normal)

| Timer | Source | Schedule (ET) | Purpose |
|---|---|---|---|
| `swingtrader-prices-load` | `mtf/systemd/` | Mon–Fri 09:05 | canonical `tbl_prices_*` load + ATR |
| `swingtrader-scanner-update` | `scanner/systemd/` | Mon–Fri 09:00 | pre-close legacy bar populate |
| `swingtrader-legema` | `mtf/systemd/` | Mon–Fri 10:05 | **CoreEW P20w — places orders** |
| `swingtrader-mtf-executor` | `mtf/systemd/` | Mon–Fri 10:25 | **MTF Top-N — scores and places orders** |
| `swingtrader-scanner-backfill` | `scanner/systemd/` | Mon–Fri 16:30 | post-close settle of the 16:00 close |
| `swingtrader-backup` | `swingtrader/systemd/` | daily 16:15 | PostgreSQL backup |
| `swingtrader-earnings-screener` | `scanner/systemd/` | Mon–Fri every 30 min, 09:30–15:30 | earnings-crossover scan → Slack |
| `swingtrader-mtf-scorer` | `mtf/systemd/` | Mon–Fri 16:45 | MTF evening recap → Slack, no orders |
| `swingtrader-daily-signal` | `ema_sma_crossover/systemd/` | Mon–Fri 17:00 | Daily Signal → Slack, no orders |
| `swingtrader-weekly-takeoff` | `weekly_takeoff/systemd/` | Fri 17:15 | take-off scan → Slack, no orders |

Enable them all:

```bash
sudo systemctl daemon-reload
sudo systemctl enable swingtrader-db.service swingtrader-backend.service
sudo systemctl enable \
  swingtrader-prices-load.timer swingtrader-scanner-update.timer \
  swingtrader-legema.timer swingtrader-mtf-executor.timer \
  swingtrader-scanner-backfill.timer swingtrader-backup.timer \
  swingtrader-earnings-screener.timer swingtrader-mtf-scorer.timer \
  swingtrader-daily-signal.timer swingtrader-weekly-takeoff.timer
```

> **Not installed, do not enable blind:** `swingtrader-mtf-preview.*` exists in
> `mtf/systemd/` but was never deployed; running it alongside the live scorer would
> post the evening Slack summary twice.
>
> **Every timer is `Persistent=true`.** A timer missed while the box was off fires at
> the next boot. That is what rescues a late morning — but it also means a unit can
> fire *before* `swingtrader-db.service` has the container listening, and fail. If you
> add a new timer that touches the database, order it after `swingtrader-db.service`.

---

## Crontab

**There are no active crontab entries, and there should not be.**

```bash
crontab -l    # shows only commented-out history
```

All order placement and scheduling is systemd. The commented lines are kept on purpose
as the documented rollback path for retired strategies (`trades:execute-EW-gate100`,
retired 2026-09-28 in favour of CoreEW P20w). Uncommenting one re-enables that retired
strategy — do not do it casually.

**Do not add `* * * * * php artisan schedule:run`.** There is no framework-level trade
execution on this box; that line is a leftover from an earlier architecture and an
older version of this doc told you otherwise.

---

## On-demand jobs

Run these by hand when you want them — they are deliberately not scheduled:

```bash
cd $PROJECT_DIR/scanner

# Refresh the earnings-date cache (28-day / 4-week lookahead) — run this
# BEFORE an undervalued scan. Feeds tbl_earnings_calendar, which the
# earnings-screener timer reads.
./.venv/bin/python3 services/earnings_screener.py --refresh

# Scan now. Prints locally; add --slack to also post to Slack.
./.venv/bin/python3 services/earnings_screener.py --days 14 --all
./.venv/bin/python3 services/earnings_screener.py --stats    # cache freshness

# Data readiness gate — run this before assuming a bad signal is a strategy problem
./.venv/bin/python services/scripts/data_readiness.py --check --tf week,day --mode all
```

> The earnings cache is only as fresh as your last manual `--refresh`. The removed
> Sunday timer used to do this weekly and had been failing on every boot since
> 2026-09-13, so the cache had silently gone three weeks stale. If you rely on the
> weekday `earnings-screener` timer, refresh before you scan.

---

## First run / reboot behavior

**After a reboot there is nothing to do.** `swingtrader-db`, `-backend` and `-fe-dev`
start at boot; the timers catch up anything missed.

Two things to know on a fresh or wiped database:

1. Bars must exist before any strategy can score. Load the canonical pair:
   ```bash
   cd $PROJECT_DIR/scanner
   ./.venv/bin/python services/scripts/load_prices.py --resume --timeframe day
   ./.venv/bin/python services/scripts/load_prices.py --resume --timeframe week
   ./.venv/bin/python services/scripts/compute_indicators.py --timeframe prices-daily
   ./.venv/bin/python services/scripts/compute_indicators.py --timeframe prices-weekly
   ```
   Or just wait for `swingtrader-prices-load.timer` at 09:05.
2. `strategy_parameters` must be populated for CoreEW, or the entry-multiple override
   is bypassed. The CoreEW signal is canonical in PHP (`trades:execute-leg-ema`) — do
   not reimplement it in Python.

---

## Verify everything

```bash
sudo systemctl is-active swingtrader-db swingtrader-backend swingtrader-fe-dev
sudo systemctl list-timers --all | grep swingtrader     # 10 timers expected
curl -s http://localhost:9000/api/health
curl -s http://localhost:5173/

docker exec swingtrader-db psql -U swingtrader -d swingtrader \
  -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public';"

# data side
cd $PROJECT_DIR/scanner
./.venv/bin/python services/scripts/data_readiness.py --check --tf week,day --mode all
```

---

## Troubleshooting

**Python service: `Connection refused` on `127.0.0.1:5432`** — the DB container is
not up. This is the single most common failure on this box:

```bash
sudo systemctl status swingtrader-db
docker ps | grep swingtrader-db
until docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1"; do sleep 2; done
```

**A timer "fired" but nothing happened** — check the result, not the timer:

```bash
systemctl show <unit>.service -p Result -p ExecMainStatus
sudo journalctl -u <unit> -n 50 --no-pager
```

`Result=exit-code` with the timer still counted as "fired" is the signature of a unit
whose `ExecStart` referenced something that no longer exists. `ExecStartPre` is the
nasty version: it gates every sibling `ExecStart`, so one stale line silently disables
the entire unit.

**Strategy unit ran but placed no orders** — usually the data gate, not the strategy:

```bash
sudo journalctl -u swingtrader-mtf-executor -n 80 --no-pager | grep -iE 'readiness|freshness|blocked'
```

`data_readiness.py` is authoritative. A skipped run is the gate working correctly.

**Alpaca 401** — keys rotated, or the wrong component's `.env`. See
[`ALPACA_KEYS.md`](ALPACA_KEYS.md).

**Laravel "relation cache does not exist"** — cache after a config change:

```bash
cd $PROJECT_DIR/swingtrader/backend
php artisan config:clear && php artisan cache:clear
sudo systemctl restart swingtrader-backend
```

**Port conflict:**

```bash
lsof -i :9000; lsof -i :5173
```

**Roll back / disable something:**

```bash
sudo systemctl disable --now <unit>.timer
sudo rm /etc/systemd/system/<unit>.{service,timer}
sudo systemctl daemon-reload
```

Removing the unit file from `/etc/systemd/system/` does **not** remove it from the
repo — the deploy source stays in the component's `systemd/` dir. Delete it there too,
or the next deploy resurrects it.

---

## See Also

- [`services_doc/README.md`](services_doc/README.md) — **live service inventory** (status, schedule, purpose)
- [`OPERATING_RULES.md`](OPERATING_RULES.md) — operating rules and current system state
- [`ALPACA_KEYS.md`](ALPACA_KEYS.md) — which keys belong to which account/component
- [`COMMAND_REFERENCE.md`](COMMAND_REFERENCE.md) — command reference ⚠️ **also pre-restructure**
- [`AGENTS.md`](../../AGENTS.md) — repo entry point and safety rails