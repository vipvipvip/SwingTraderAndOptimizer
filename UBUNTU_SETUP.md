# Ubuntu/Linux Setup Guide - SwingTraderAndOptimizer

Complete guide for setting up the trading system on **native Ubuntu/Linux** (not WSL or Windows).

**Status:** Production-ready on Ubuntu 22.04+ | Tested on native Linux

---

## Prerequisites

Before starting, ensure you have:

```bash
# System requirements
- Ubuntu 20.04+ (or any modern Linux distro)
- 4GB RAM minimum (8GB+ recommended)
- 2GB disk space for code + data
- Active internet connection
```

**Check your system:**
```bash
lsb_release -a      # Show Ubuntu version
uname -m            # Show architecture (x86_64 or ARM)
```

---

## Part 1: System Dependencies

### 1.1 Update System Packages

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### 1.2 Install PHP 8.4 + SQLite

```bash
sudo apt-get install -y \
  php-cli \
  php-sqlite3 \
  php-xml \
  php-dom \
  php-mbstring \
  php-curl \
  php-json \
  php-fileinfo

# Verify PHP
php -v
php -m | grep sqlite3  # Should show sqlite3
```

### 1.3 Install Node.js 18+

```bash
# Option A: Using NodeSource repo (recommended)
sudo curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Option B: Using nvm (if you prefer version management)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install 18

# Verify
node -v    # Should be 18.x or higher
npm -v
```

### 1.4 Install Python 3.9+

```bash
sudo apt-get install -y \
  python3 \
  python3-venv \
  python3-pip

# Verify
python3 --version  # Should be 3.9+
```

### 1.5 Install Composer

```bash
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x /usr/local/bin/composer

# Verify
composer --version
```

### 1.6 Install Git

```bash
sudo apt-get install -y git

# Configure git
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

---

## Part 2: Clone and Setup Project

### 2.1 Clone Repository

```bash
cd ~
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer
git checkout STO-Ubuntu-v1  # Use Ubuntu-specific branch
```

### 2.2 Backend Setup (Laravel)

```bash
cd backend

# Copy environment
cp .env.example .env

# Install dependencies
composer install

# Generate app key
php artisan key:generate

# Set database path (use absolute path for cron compatibility)
PROJECT_ROOT=$(cd ../.. && pwd)
sed -i "s|DB_DATABASE=.*|DB_DATABASE=$PROJECT_ROOT/optimizer/optimized_params/strategy_params.db|" .env
```

### 2.3 Frontend Setup (Svelte)

```bash
cd ../frontend

# Install dependencies
npm install

# Verify build
npm run build  # Takes ~30 seconds
```

### 2.4 Python Optimizer Setup

```bash
cd ../optimizer

# Create virtual environment
python3 -m venv venv

# Activate venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify imports
python3 -c "from alpaca.data.historical import StockHistoricalDataClient; print('✓ Alpaca SDK OK')"

deactivate
```

---

## Part 3: Configure Alpaca Credentials

### 3.1 Get Your Alpaca API Keys

1. Go to https://app.alpaca.markets/
2. Log in or create account
3. Navigate to **Settings → API Keys**
4. Copy your **API Key** and **Secret Key** (for paper trading)

### 3.2 Update .env Files

**Backend:**
```bash
# backend/.env
ALPACA_API_KEY=PKxxxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxx
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

**Optimizer:**
```bash
# optimizer/.env
ALPACA_API_KEY=PKxxxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxx
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_TIMEFRAME=1Hour
```

### 3.3 Test Connection

```bash
# From backend directory
php artisan tinker
>>> $alpaca = app('App\Services\AlpacaService');
>>> $alpaca->getAccount();
# Should return account info, not "unauthorized"
>>> exit
```

---

## Part 4: Scheduler Setup (Native Crontab)

### 4.1 The Two Key Jobs

The system needs two scheduled jobs on Linux:

| Job | Schedule | Command |
|-----|----------|---------|
| **Nightly Optimizer** | 2:00 AM daily | `run_nightly.sh` (Python) |
| **Trade Executor** | Every minute | `php artisan schedule:run` (Laravel checks every 30 min) |

### 4.2 Setup Nightly Optimizer Cron

```bash
cd /path/to/SwingTraderAndOptimizer/scripts

# Run setup script (automatically adds cron job)
bash setup-optimizer-cron.sh

# Verify it was added
crontab -l | grep run_nightly
# Should show: 0 2 * * * /path/to/optimizer/run_nightly.sh
```

### 4.3 Setup Trade Executor Cron

```bash
# Add to your crontab
crontab -e

# Add this line:
* * * * * /usr/bin/php /path/to/backend/artisan schedule:run >> /dev/null 2>&1

# Save and exit (Ctrl+X in nano, :wq in vim)
```

### 4.4 Verify Cron Jobs

```bash
# List all cron jobs
crontab -l

# Should show both:
# 0 2 * * * /path/to/optimizer/run_nightly.sh
# * * * * * /usr/bin/php /path/to/backend/artisan schedule:run >> /dev/null 2>&1

# Monitor cron execution (Linux)
grep CRON /var/log/syslog | tail -10

# Or on systemd systems:
journalctl -u cron | tail -20
```

---

## Part 5: Run the Application

### 5.1 Start All Services

**Option A: Using the startup script (recommended)**
```bash
bash scripts/start-all.sh
```

**Option B: Manual (3 terminals)**

Terminal 1 - Backend:
```bash
cd backend
php artisan serve --host=127.0.0.1 --port=9000
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
# Will be available on http://localhost:5173
```

Terminal 3 - Monitor logs:
```bash
tail -f backend/storage/logs/laravel.log
```

### 5.2 Access the Dashboard

Open your browser:
- **Dashboard:** http://localhost:5173
- **API Docs:** http://localhost:9000/api/documentation
- **API Server:** http://localhost:9000

---

## Part 6: Verify Everything Works

### 6.1 Test Backend API

```bash
# Check account
curl http://localhost:9000/api/v1/account | jq .

# Check tickers
curl http://localhost:9000/api/v1/tickers | jq .

# Manual trade executor trigger
curl -X POST http://localhost:9000/api/v1/admin/trades/trigger | jq .

# Manual optimizer trigger
curl -X POST http://localhost:9000/api/v1/admin/optimize/trigger | jq .
```

### 6.2 Test Optimizer

```bash
# Run optimizer manually (takes ~90 minutes for 3 tickers)
cd optimizer
source venv/bin/activate
python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM

# Watch progress
tail -f logs/nightly.log
```

### 6.3 Check Database

```bash
cd optimizer/optimized_params
sqlite3 strategy_params.db

# Inside sqlite3:
.mode column
.headers on
SELECT * FROM tickers LIMIT 1;
SELECT * FROM strategy_parameters LIMIT 1;
.quit
```

---

## Key Differences: Ubuntu vs Windows/WSL

| Aspect | Ubuntu (Linux) | Windows/WSL |
|--------|--------|---|
| **Scheduler** | Native `crontab` | Windows Task Scheduler |
| **Python Path** | `venv/bin/python` | `C:\...\python.exe` or WSL interop |
| **Alpaca SDK** | `alpaca-py` (modern) | `alpaca-trade-api` (legacy) |
| **Script Execution** | Bash + execution bits | PowerShell or Bash |
| **Database Path** | `/home/...` (absolute) | `C:\...` (Windows paths) |
| **Line Endings** | LF | CRLF (auto-converted by Git) |

---

## Troubleshooting

### Problem: "PHP not found"
```bash
which php
# If empty, install: sudo apt-get install php-cli
```

### Problem: "npm not found"
```bash
which npm
# If empty, install Node.js (see Part 1.3)
```

### Problem: "Market is closed" when it should be open
The trade executor checks Alpaca's market clock. Market only opens 9:30-16:00 ET on weekdays.
```bash
# To force test mode (ignore market hours):
php artisan trades:execute-daily --force-test
```

### Problem: Cron job not running
```bash
# Check cron logs
grep run_nightly /var/log/syslog | tail -5

# Check if cron daemon is running
sudo systemctl status cron

# Restart cron if needed
sudo systemctl restart cron

# Manually test the script
bash /path/to/optimizer/run_nightly.sh
tail -f optimizer/logs/nightly.log
```

### Problem: Database locked error
```bash
# Find process holding lock
lsof | grep strategy_params.db

# Or check if optimizer is running
ps aux | grep python | grep nightly_optimizer

# Wait for optimizer to finish, or kill it
pkill -f nightly_optimizer
```

### Problem: "No such file or directory" in cron logs
Cron jobs run in a minimal environment. Make sure:
1. Use **absolute paths** in cron jobs (not relative `../..`)
2. Activate venv in wrapper scripts
3. Redirect output to log files

---

## Daily Operations

### Start Services
```bash
bash scripts/start-all.sh
```

### Monitor Logs
```bash
# Backend
tail -f backend/storage/logs/laravel.log

# Optimizer
tail -f optimizer/logs/nightly.log

# Cron execution
journalctl -u cron -f
```

### Manual Triggers
```bash
# Execute trades immediately
curl -X POST http://localhost:9000/api/v1/admin/trades/trigger

# Run optimizer immediately
curl -X POST http://localhost:9000/api/v1/admin/optimize/trigger
```

### Stop Services
```bash
# From start-all.sh terminal:
Ctrl+C

# Or manually kill processes:
pkill -f "php artisan serve"
pkill -f "vite"
pkill -f "nightly_optimizer"
```

---

## Next Steps

1. **Setup complete** → Start the services and verify dashboard loads
2. **Add credentials** → Update .env with your Alpaca API keys
3. **Test trade executor** → Run manual trigger to verify orders work
4. **Monitor first run** → Watch the nightly optimizer on its first run
5. **Check logs daily** → Use MONITORING.md for daily checks

---

## Branch Information

This guide is for the **`STO-Ubuntu-v1`** branch, which contains Ubuntu/Linux-specific code.

- **Main branch** (`main`) = Windows/WSL code
- **Current branch** (`STO-Ubuntu-v1`) = Ubuntu/Linux code
- These branches will eventually merge when both are production-ready

---

## Additional Resources

- [README.md](README.md) - Full project overview
- [BEST_PRACTICES.md](BEST_PRACTICES.md) - Development learnings
- [MONITORING.md](MONITORING.md) - Daily monitoring guide
- [TESTING.md](TESTING.md) - Testing strategy

---

**Last Updated:** 2026-04-25  
**Status:** Production-ready on Ubuntu 22.04+  
**Tested:** ✅ Native Linux, ✅ Crontab scheduling, ✅ Alpaca integration
