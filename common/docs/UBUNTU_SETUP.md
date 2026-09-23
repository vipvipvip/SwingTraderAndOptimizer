# SwingTrader — Ubuntu/WSL2 Setup & Systemd Services

Complete guide to installing the trading system on **native Ubuntu/Linux** or **Windows Subsystem for Linux 2 (WSL2)**, and running the Laravel backend + frontend + optimizer as auto-restarting systemd services.

**Status:** Production-ready on Ubuntu 22.04+ | Tested on Windows 11 with WSL2 Ubuntu-24.04

---
## Contents
1. [Prerequisites](#prerequisites)
2. [Project Setup](#project-setup)
3. [Database (PostgreSQL via Docker)](#database)
4. [Backend](#backend)
5. [Frontend / Python Optimizer](#frontend--python-optimizer)
6. [Systemd Services (backend, optimizer, frontend)](#systemd-services)
7. [Crontab](#crontab)
8. [First Run / Reboot Behavior](#first-run--reboot-behavior)
9. [Verify Everything](#verify-everything)
10. [Troubleshooting](#troubleshooting)
11. [See Also](#see-also)

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

Install Composer (Laravel dependency manager):
```bash
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x /usr/local/bin/composer
```

Configure Git:
```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

### WSL2 (not WSL1)

```bash
# Check version from Windows PowerShell — must show VERSION 2
wsl --list --verbose
wsl --set-version Ubuntu-24.04 2
```

Enable systemd (`sudo nano /etc/wsl.conf`):
```ini
[boot]
systemd=true

[user]
default=YOUR_USERNAME
```

Restart WSL (PowerShell, admin): `wsl --shutdown`, then verify `systemctl is-system-running` → `running`.

Install **Docker Desktop for Windows** → Settings → Resources → WSL Integration → enable your distro. Verify in WSL: `docker --version && docker ps`.

Install system deps (same apt packages as native, plus `php-sqlite3`) and Composer:
```bash
sudo apt-get update && sudo apt-get install -y \
  php-cli php-pgsql php-xml php-dom php-mbstring php-curl php-json php-fileinfo php-sqlite3 \
  php-xdebug nodejs npm python3 python3-venv python3-pip git curl
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer && sudo chmod +x /usr/local/bin/composer
# If npm not available:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

> **Performance:** keep the project in the WSL filesystem (`/home/$USER/...`), never `/mnt/c/`. Docker Desktop: 4GB+ RAM, 4+ CPUs. Disable Windows sleep while plugged in — WSL suspension stops trading.

---

## Project Setup

```bash
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer
PROJECT_DIR=$(pwd)
```

Configure backend env:
```bash
cd $PROJECT_DIR/backend
cp .env.example .env
nano .env
```

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

SLACK_WEBHOOK_URL=your_webhook_url
PYTHON_PATH=python3
```

> **Alpaca:** get keys at app.alpaca.markets → Paper Trading. Paper keys start with `PKS...`. If you get 401 errors, regenerate — old keys become invalid. Never commit `backend/.env`.

---

## Database

Named volume (`postgres_data`) persists data across restarts — never use a bind mount, never `docker-compose down -v`.

```bash
cd $PROJECT_DIR
docker-compose up -d
until docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1" > /dev/null 2>&1; do sleep 2; done
cd backend && php artisan key:generate && php artisan migrate --force
```

Seed initial tickers:
```bash
php artisan tinker --execute="
App\Models\Ticker::firstOrCreate(['symbol'=>'SPY'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'QQQ'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'IWM'],['allocation_weight'=>33.34,'enabled'=>1]);
"
```

Verify: `docker volume ls | grep swingtrader` and
`docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT COUNT(*) FROM tickers;"`.

---

## Backend

```bash
cd $PROJECT_DIR/backend
composer install --no-interaction --prefer-dist
mkdir -p storage/logs storage/app bootstrap/cache
chmod -R 775 storage bootstrap/cache
```

Dev/manual mode: `php artisan serve --host=0.0.0.0 --port=9000`

---

## Frontend / Python Optimizer

```bash
# Frontend
cd $PROJECT_DIR/frontend
npm install
npm run dev        # development (hot reload)
# npm run build    # production build → dist/

# Python optimizer
cd $PROJECT_DIR/optimizer
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install psycopg2-binary alpaca-py   # required for Postgres + new Alpaca SDK
deactivate
```

---

## Systemd Services

Services start in order on boot with no manual intervention:

```
swingtrader-startup   → Docker up → DB ready → Migrate → Seed tickers
       ↓ (depends)
swingtrader-backend   → php artisan serve :9000
swingtrader-frontend  → npm run dev :5173 (dev) | nginx (prod)
swingtrader-optimizer.timer → 2 AM nightly run
crontab               → schedule:run every minute
```

### Set project variables once

```bash
cd /path/to/SwingTraderAndOptimizer
PROJECT_DIR=$(pwd)
PHP_PATH=$(which php)
NPM_PATH=$(which npm)
echo "Project: $PROJECT_DIR | User: $USER"
```

### Startup orchestration (Docker → DB → migrate → seed)

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

StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-startup
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF"
```

### Backend service

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

> Change backend port: edit `ExecStart`; change optimizer schedule: edit the timer's `OnCalendar` (e.g. `Mon-Fri *-*-* 02:00:00` for weekdays-only).

### Optimizer service + timer (2 AM daily)

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

### Frontend — dev mode

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
Environment=\"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\"

[Install]
WantedBy=multi-user.target
EOF"
```

> If npm isn't found, add its bin dir to `PATH` (check with `which npm`) or use the absolute path in `ExecStart`.

### Frontend — production mode (nginx)

```bash
sudo apt-get install -y nginx
cd $PROJECT_DIR/frontend && npm run build
```

```bash
sudo bash -c 'cat > /etc/nginx/sites-available/swingtrader-fe' <<'EOF'
server {
    listen 5173;
    server_name _;
    root /path/to/SwingTraderAndOptimizer/frontend/dist;
    index index.html;

    gzip on;
    gzip_types text/plain text/css text/javascript application/json application/javascript;
    gzip_min_length 1000;

    location ~ ^/(assets|css|js|img)/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /api/ {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~ /\. { deny all; }
}
EOF

sudo ln -sf /etc/nginx/sites-available/swingtrader-fe /etc/nginx/sites-enabled/swingtrader-fe
sudo rm -f /etc/nginx/sites-enabled/default   # optional
sudo nginx -t && sudo systemctl restart nginx && sudo systemctl enable nginx
```

Run only ONE of dev/prod on port 5173 to avoid conflicts.

### Enable everything

```bash
sudo systemctl daemon-reload
sudo systemctl enable swingtrader-startup.service swingtrader-backend.service
sudo systemctl enable swingtrader-frontend.service   # dev mode (or nginx in prod)
sudo systemctl enable swingtrader-optimizer.timer
sudo systemctl start swingtrader-startup.service swingtrader-backend.service
sudo systemctl start swingtrader-frontend.service
sudo systemctl start swingtrader-optimizer.timer
```

---

## Crontab

ONE entry only — Laravel's Kernel.php handles the internal schedule (trades every 5 min, positions sync, alerts):

```bash
PHP_PATH=$(which php)
PROJECT_DIR=$(pwd)  # run from project root
(echo "* * * * * $PHP_PATH $PROJECT_DIR/backend/artisan schedule:run >> /dev/null 2>&1") | crontab -
crontab -l
```

> Never comment out this line — a `#` prefix stops trade execution.

---

## First Run / Reboot Behavior

Populate 2 years of bars + strategy params (30–45 min; must run after any DB wipe):
```bash
cd $PROJECT_DIR/optimizer
./venv/bin/python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
tail -f optimizer/logs/nightly.log
```

**After every reboot: nothing to do.** Systemd starts all services in order. Note: on WSL, Docker Desktop must be running on Windows before WSL starts, else `swingtrader-startup` waits (up to 2 min) for the Docker socket.

---

## Verify Everything

```bash
sudo systemctl is-active swingtrader-startup swingtrader-backend swingtrader-frontend swingtrader-optimizer.timer
curl http://localhost:9000/api/health
curl http://localhost:5173/                      # frontend + API proxy (nginx)
curl http://localhost:9000/api/v1/account        # Alpaca balance
sudo systemctl list-timers swingtrader-optimizer.timer
docker exec swingtrader-db psql -U swingtrader -d swingtrader \
  -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public';"
```

---

## Troubleshooting

**Backend fails: "relation cache does not exist"** — migrations didn't run before backend started:
```bash
sudo systemctl status swingtrader-startup --no-pager
cd backend && php artisan migrate --force
sudo systemctl restart swingtrader-backend
```

**Database empty after reboot** — named volume deleted or Docker reset:
```bash
docker volume ls | grep swingtrader
cd backend && php artisan migrate --force && php artisan tinker --execute="
App\Models\Ticker::firstOrCreate(['symbol'=>'SPY'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'QQQ'],['allocation_weight'=>33.33,'enabled'=>1]);
App\Models\Ticker::firstOrCreate(['symbol'=>'IWM'],['allocation_weight'=>33.34,'enabled'=>1]);
"
cd ../optimizer && ./venv/bin/python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
```

**Crontab commented out (trades not executing):**
```bash
crontab -l   # if line starts with #, re-add it (see Crontab section)
```

**Alpaca returns 401** — regenerate keys at app.alpaca.markets. Test:
```bash
curl -H "APCA-API-KEY-ID: YOUR_KEY" -H "APCA-API-SECRET-KEY: YOUR_SECRET" https://paper-api.alpaca.markets/v2/account
```

**Optimizer ModuleNotFoundError:**
```bash
cd optimizer && ./venv/bin/pip install psycopg2-binary alpaca-py
./venv/bin/python -c "import psycopg2; import alpaca; print('OK')"
```

**Service won't start / port conflicts:**
```bash
journalctl -u swingtrader-backend -n 50
sudo systemctl status swingtrader-startup --no-pager
lsof -i :9000; lsof -i :5173   # find conflicting process
sudo systemctl restart swingtrader-backend
```

**Frontend can't reach backend (nginx):** verify `curl http://localhost:9000/api/health`, `sudo nginx -t`, `sudo grep -A 5 "location /api" /etc/nginx/sites-enabled/swingtrader-fe`.

**Rollback / disable a service:**
```bash
sudo systemctl disable --now swingtrader-backend.service swingtrader-optimizer.timer
```

---

## See Also

- [How_System_Works.md](How_System_Works.md) — Architecture and data flow
- [MONITORING.md](MONITORING.md) — Daily health checks and troubleshooting
- [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) — All useful commands
- [Github-SSH-COMMANDS.md](Github-SSH-COMMANDS.md) — SSH key setup for GitHub