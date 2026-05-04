# WSL2 Setup Guide - SwingTraderAndOptimizer

Complete guide for setting up the trading system on **Windows Subsystem for Linux 2 (WSL2)**.

**Status:** Fully compatible with WSL2 | Tested on Windows 11 with WSL2 Ubuntu-24.04

---

## Prerequisites

### 1. WSL2 (Not WSL1)

```bash
# Check your WSL version from Windows PowerShell
wsl --list --verbose

# Must show VERSION 2. If version 1, upgrade:
wsl --set-version Ubuntu-24.04 2
```

### 2. Enable Systemd

```bash
sudo nano /etc/wsl.conf
```

Add:
```ini
[boot]
systemd=true

[user]
default=YOUR_USERNAME
```

Restart WSL from Windows PowerShell (as Administrator):
```powershell
wsl --shutdown
```

Reopen WSL and verify:
```bash
systemctl is-system-running  # Should return: running
```

### 3. Docker Desktop for Windows

- Install Docker Desktop for Windows
- Settings → Resources → WSL Integration → Enable your Ubuntu distro
- Verify from WSL:
```bash
docker --version
docker ps
```

---

## Installation Steps

### Step 1: Install System Dependencies

```bash
sudo apt-get update && sudo apt-get install -y \
  php-cli php-pgsql php-xml php-dom php-mbstring php-curl php-json php-fileinfo php-sqlite3 \
  php-xdebug \
  nodejs npm \
  python3 python3-venv python3-pip \
  git curl
```

Install Composer:
```bash
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x /usr/local/bin/composer
```

Install Node.js 20 (if npm not available):
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### Step 2: Clone Repository

```bash
cd ~
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer
PROJECT_DIR=$(pwd)
echo "Project at: $PROJECT_DIR"
```

> **Note:** You can clone to any path. All scripts use relative or auto-detected paths.

### Step 3: Configure Environment

```bash
cd $PROJECT_DIR/backend
cp .env.example .env
nano .env
```

Set these values:
```env
DB_CONNECTION=pgsql
DB_HOST=127.0.0.1
DB_PORT=5432
DB_DATABASE=swingtrader
DB_USERNAME=swingtrader
DB_PASSWORD=swingtrader_dev_password

ALPACA_API_KEY=<your_paper_trading_key>
ALPACA_SECRET_KEY=<your_paper_trading_secret>
ALPACA_BASE_URL=https://paper-api.alpaca.markets

PYTHON_PATH=python3
```

> **Alpaca Keys:** Get from [app.alpaca.markets](https://app.alpaca.markets) → Paper Trading → API Keys
> **Important:** If you get 401 errors, regenerate the keys — old keys can become invalid

### Step 4: Backend Setup

```bash
cd $PROJECT_DIR/backend
composer install --no-interaction --prefer-dist
mkdir -p storage/logs storage/app bootstrap/cache
chmod -R 775 storage bootstrap/cache
```

### Step 5: Database Setup (PostgreSQL via Docker)

The `docker-compose.yml` uses a **named Docker volume** (`postgres_data`) for persistent storage. This ensures data survives Docker restarts and laptop reboots. Never use a bind mount (`./backend/postgres_data`) — it gets wiped.

```bash
cd $PROJECT_DIR
docker-compose up -d

# Wait for PostgreSQL to be ready
until docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1" > /dev/null 2>&1; do sleep 2; done
echo "PostgreSQL ready"

# Run migrations
cd backend
php artisan migrate --force

# Seed tickers
php artisan tinker --execute="
App\Models\Ticker::firstOrCreate(['symbol'=>'SPY'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'QQQ'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'IWM'],['allocation_weight'=>33.34,'enabled'=>1]);
echo 'Tickers seeded';
"
```

> **DB Persistence:** Data lives in Docker named volume `swingtraderandoptimizer_postgres_data`.
> Check with: `docker volume ls | grep swingtrader`

### Step 6: Python Optimizer Setup

```bash
cd $PROJECT_DIR/optimizer
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

# Install from requirements.txt
pip install -r requirements.txt

# Install additional packages required for PostgreSQL and Alpaca
pip install psycopg2-binary alpaca-py

deactivate
```

> **Why the extra packages?** The requirements.txt has alpaca-trade-api (old SDK) but the
> optimizer uses alpaca-py (new SDK). psycopg2-binary is needed for PostgreSQL connectivity.

### Step 7: Frontend Setup

```bash
cd $PROJECT_DIR/frontend
npm install
```

---

## Systemd Services (Auto-start on Boot)

Four services manage the full lifecycle. They start automatically in order on every WSL boot — no manual intervention needed.

```
swingtrader-startup   → Docker up → DB ready → Migrate → Seed tickers
       ↓ (depends)
swingtrader-backend   → php artisan serve :9000
swingtrader-frontend  → npm run dev :5173
swingtrader-optimizer.timer → 2 AM nightly run
crontab               → schedule:run every minute (trades every 5 min via Kernel.php)
```

### Step 0: Set Project Variables

Run from project root before creating any service:

```bash
cd /path/to/SwingTraderAndOptimizer
PROJECT_DIR=$(pwd)
PHP_PATH=$(which php)
NPM_PATH=$(which npm)
echo "Project: $PROJECT_DIR | User: $USER"
```

### Service 1: Startup Orchestration

Handles Docker → PostgreSQL → Migrations → Tickers in correct order:

```bash
sudo bash -c "cat > /etc/systemd/system/swingtrader-startup.service << EOF
[Unit]
Description=SwingTrader Startup Orchestration (Docker + DB + Migrate)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=$USER
WorkingDirectory=$PROJECT_DIR

ExecStartPre=/bin/bash -c 'until docker info > /dev/null 2>&1; do sleep 3; done'
ExecStart=/usr/bin/docker-compose up -d
ExecStartPost=/bin/bash -c 'until docker exec swingtrader-db psql -U swingtrader -d swingtrader -c \"SELECT 1\" > /dev/null 2>&1; do sleep 2; done'
ExecStartPost=$PHP_PATH $PROJECT_DIR/backend/artisan migrate --force
ExecStartPost=/bin/bash -c '$PHP_PATH $PROJECT_DIR/backend/artisan tinker --execute=\"App\\\\Models\\\\Ticker::firstOrCreate([\\\"symbol\\\"=>\\\"SPY\\\"],[\\\"allocation_weight\\\"=>33.33,\\\"enabled\\\"=>1]); App\\\\Models\\\\Ticker::firstOrCreate([\\\"symbol\\\"=>\\\"QQQ\\\"],[\\\"allocation_weight\\\"=>33.33,\\\"enabled\\\"=>1]); App\\\\Models\\\\Ticker::firstOrCreate([\\\"symbol\\\"=>\\\"IWM\\\"],[\\\"allocation_weight\\\"=>33.34,\\\"enabled\\\"=>1]);\" 2>/dev/null'

StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-startup
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF"
```

### Service 2: Backend

Depends on startup service being complete:

```bash
sudo bash -c "cat > /etc/systemd/system/swingtrader-backend.service << EOF
[Unit]
Description=SwingTrader Laravel Backend
After=swingtrader-startup.service
Requires=swingtrader-startup.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/backend
ExecStartPre=$PHP_PATH artisan config:clear
ExecStartPre=$PHP_PATH artisan cache:clear
ExecStart=$PHP_PATH artisan serve --host=0.0.0.0 --port=9000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-backend

[Install]
WantedBy=multi-user.target
EOF"
```

### Service 3: Frontend

```bash
sudo bash -c "cat > /etc/systemd/system/swingtrader-frontend.service << EOF
[Unit]
Description=SwingTrader Frontend (Vite Dev Server)
After=swingtrader-backend.service
Requires=swingtrader-startup.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/frontend
ExecStart=$NPM_PATH run dev
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-frontend
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
EOF"
```

### Service 4: Optimizer Timer (2 AM daily)

```bash
sudo bash -c "cat > /etc/systemd/system/swingtrader-optimizer.service << EOF
[Unit]
Description=SwingTrader Nightly Optimizer
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$PROJECT_DIR/optimizer
ExecStart=/bin/bash $PROJECT_DIR/optimizer/run_nightly.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-optimizer
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
EOF"

sudo bash -c "cat > /etc/systemd/system/swingtrader-optimizer.timer << EOF
[Unit]
Description=SwingTrader Nightly Optimizer Timer
Requires=swingtrader-optimizer.service

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF"
```

### Enable All Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable swingtrader-startup.service
sudo systemctl enable swingtrader-backend.service
sudo systemctl enable swingtrader-frontend.service
sudo systemctl enable swingtrader-optimizer.timer

sudo systemctl start swingtrader-startup.service
sudo systemctl start swingtrader-backend.service
sudo systemctl start swingtrader-frontend.service
sudo systemctl start swingtrader-optimizer.timer
```

---

## Crontab Setup

ONE entry only — Laravel Kernel.php handles the internal schedule (trades every 5 min, positions sync, alerts):

```bash
PHP_PATH=$(which php)
PROJECT_DIR=$(pwd)  # run from project root

(echo "* * * * * $PHP_PATH $PROJECT_DIR/backend/artisan schedule:run >> /dev/null 2>&1") | crontab -

# Verify — should show exactly one uncommented line
crontab -l
```

> **Important:** Never comment out this line. If it has a `#` prefix, trades will not execute.

---

## First Run After Setup

Populate the database with 2 years of historical bars and optimized strategy parameters:

```bash
cd $PROJECT_DIR/optimizer
./venv/bin/python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
```

Takes 30-45 minutes. Monitor: `tail -f optimizer/logs/nightly.log`

> **Must run this after any database wipe.** Without bars data the optimizer has nothing to backtest and strategy parameters will be empty.

---

## After Every Reboot

**Nothing to do.** All services start automatically:

```
Open WSL terminal → systemd starts all services in order:
  1. swingtrader-startup  → Docker + DB + Migrate + Seed
  2. swingtrader-backend  → API on :9000
  3. swingtrader-frontend → Dashboard on :5173
  4. swingtrader-optimizer.timer → scheduled for 2 AM
  5. crontab → schedule:run every minute
```

> **Docker Desktop must be running on Windows** before WSL starts, otherwise `swingtrader-startup` will wait (up to 2 minutes) for the Docker socket.

---

## Verify Everything Works

```bash
# Services
sudo systemctl is-active swingtrader-startup swingtrader-backend swingtrader-frontend swingtrader-optimizer.timer

# API
curl http://localhost:9000/api/health          # {"status":"ok"}
curl http://localhost:9000/api/v1/account      # Alpaca balance
curl http://localhost:9000/api/v1/tickers      # SPY, QQQ, IWM

# Crontab
crontab -l                                     # One uncommented line

# Timer
sudo systemctl list-timers swingtrader-optimizer.timer  # Next 2 AM run

# Bars data
docker exec swingtrader-db psql -U swingtrader -d swingtrader \
  -c "SELECT symbol, COUNT(*) FROM bars b JOIN tickers t ON b.ticker_id=t.id GROUP BY symbol;"
```

---

## Important Notes

### Sleep Mode Warning
When Windows goes to sleep, WSL is suspended — all trading stops.
- Disable sleep while plugged in: Control Panel → Power Options → Never sleep (plugged in)

### Alpaca API Keys
- Keys can become invalid — if you get 401 errors, regenerate from Alpaca dashboard
- Paper trading keys start with `PKS...`
- Keys stored in: `backend/.env` — never commit this file

### Performance Tips
1. Keep project in WSL filesystem (`/home/$USER/...`), NOT `/mnt/c/` — much faster
2. Allocate resources in Docker Desktop: Settings → Resources → 4GB+ RAM, 4+ CPUs
3. Windows Defender: Add WSL folder to exclusions for better performance

---

## Troubleshooting

### Backend fails: "relation cache does not exist"
The database has no tables — migrations haven't run yet. This happens when `swingtrader-startup` service didn't complete before `swingtrader-backend` started.

```bash
# Check startup service completed successfully
sudo systemctl status swingtrader-startup --no-pager

# Run migrations manually if needed
cd backend && php artisan migrate --force

# Restart backend
sudo systemctl restart swingtrader-backend
```

### Database is empty after reboot
PostgreSQL data is stored in a Docker named volume (`swingtraderandoptimizer_postgres_data`). If empty, the volume was deleted or Docker was reset.

```bash
# Verify volume exists
docker volume ls | grep swingtrader

# Check table count
docker exec swingtrader-db psql -U swingtrader -d swingtrader \
  -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public';"

# If empty: run migrations and reseed
cd backend && php artisan migrate --force
php artisan tinker --execute="
App\Models\Ticker::firstOrCreate(['symbol'=>'SPY'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'QQQ'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'IWM'],['allocation_weight'=>33.34,'enabled'=>1]);
"
# Then re-run the optimizer to repopulate bars + strategy params
cd ../optimizer && ./venv/bin/python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
```

> **Never use `docker-compose down -v`** — the `-v` flag deletes volumes including all data.

### Crontab commented out (trades not executing)
```bash
crontab -l   # If line starts with #, it's disabled

# Fix: reset with correct entry
PHP_PATH=$(which php)
PROJECT_DIR=/path/to/SwingTraderAndOptimizer
(echo "* * * * * $PHP_PATH $PROJECT_DIR/backend/artisan schedule:run >> /dev/null 2>&1") | crontab -
```

### Docker won't connect
```bash
docker --version          # If fails: enable WSL integration in Docker Desktop
docker-compose up -d      # Start PostgreSQL
docker ps                 # Verify swingtrader-db is running
```

### Alpaca returns 401
```bash
# Test directly:
curl -H "APCA-API-KEY-ID: YOUR_KEY" -H "APCA-API-SECRET-KEY: YOUR_SECRET" \
     https://paper-api.alpaca.markets/v2/account
# If still 401: regenerate keys at app.alpaca.markets
# See: docs/Github-SSH-COMMANDS.md for credential storage patterns
```

### Optimizer fails with ModuleNotFoundError
```bash
cd optimizer
./venv/bin/pip install psycopg2-binary alpaca-py
./venv/bin/python -c "import psycopg2; import alpaca; print('OK')"
```

### Backend won't start
```bash
journalctl -u swingtrader-backend -n 50    # Check logs
sudo systemctl status swingtrader-startup  # Confirm startup completed first
sudo systemctl restart swingtrader-backend
```

### Port conflicts
```bash
lsof -i :9000    # Find what's using backend port
lsof -i :5173    # Find what's using frontend port
kill -9 <PID>
```

---

## See Also

- [How_System_Works.md](How_System_Works.md) — Architecture and data flow
- [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) — Detailed systemd services
- [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md) — Frontend dev/prod modes
- [MONITORING.md](MONITORING.md) — Daily health checks
- [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) — All useful commands
