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

```bash
cd $PROJECT_DIR
docker-compose up -d
sleep 15  # Wait for PostgreSQL to initialize

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

Use systemd so services survive reboots and auto-restart on crash.

### Backend Service

```bash
PROJECT_DIR=$(pwd)  # Run from project root
sudo bash -c "cat > /etc/systemd/system/swingtrader-backend.service << 'EOF'
[Unit]
Description=SwingTrader Laravel Backend
After=network.target docker.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/backend
ExecStartPre=/usr/bin/php artisan config:clear
ExecStartPre=/usr/bin/php artisan cache:clear
ExecStart=/usr/bin/php artisan serve --host=0.0.0.0 --port=9000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-backend

[Install]
WantedBy=multi-user.target
EOF"
```

### Optimizer Service + Timer

```bash
PROJECT_DIR=$(pwd)  # Run from project root

# Optimizer service (oneshot)
sudo bash -c "cat > /etc/systemd/system/swingtrader-optimizer.service << 'EOF'
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

# Timer (2 AM daily)
sudo bash -c "cat > /etc/systemd/system/swingtrader-optimizer.timer << 'EOF'
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
sudo systemctl enable swingtrader-backend.service
sudo systemctl enable swingtrader-optimizer.timer
sudo systemctl start swingtrader-backend.service
sudo systemctl start swingtrader-optimizer.timer
```

---

## Crontab Setup

Add ONE cron entry — Laravel Kernel.php handles the schedule internally (trades every 5 min, etc.):

```bash
PHP_PATH=$(which php)
PROJECT_DIR=~/SwingTraderAndOptimizer  # adjust if different path

(echo "* * * * * $PHP_PATH $PROJECT_DIR/backend/artisan schedule:run >> /dev/null 2>&1") | crontab -

# Verify
crontab -l
```

---

## Frontend

**Development mode (manual):**
```bash
cd $PROJECT_DIR/frontend
npm run dev
```

**Production mode (systemd + nginx):** See [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md)

---

## First Run After Setup

After everything is installed, populate the database by running the optimizer:

```bash
cd $PROJECT_DIR/optimizer
./venv/bin/python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
```

Takes 30-45 minutes. Progress logged to `optimizer/logs/nightly.log`.

---

## After Every Reboot

```bash
docker-compose up -d          # Start PostgreSQL (Docker Desktop starts automatically)
# Backend auto-starts via systemd
# Crontab auto-runs schedule:run every minute
cd frontend && npm run dev     # Start frontend (or use fe-dev service)
```

---

## Verify Everything Works

```bash
curl http://localhost:9000/api/health          # Should return: {"status":"ok"}
curl http://localhost:9000/api/v1/account      # Should show Alpaca account balance
curl http://localhost:9000/api/v1/tickers      # Should show SPY, QQQ, IWM
sudo systemctl status swingtrader-backend      # Should be active (running)
sudo systemctl list-timers swingtrader-optimizer.timer  # Shows next 2 AM run
crontab -l                                     # Shows schedule:run entry
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
php artisan config:clear                    # Clear cache
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
