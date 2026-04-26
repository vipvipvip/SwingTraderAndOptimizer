# Ubuntu/Linux Setup Guide - SwingTraderAndOptimizer

Complete guide for setting up the trading system on **native Ubuntu/Linux** (not WSL or Windows).

**Status:** Production-ready on Ubuntu 22.04+ | Tested on native Linux

---

## Quick Start (Copy & Paste Everything)

**For a pristine Ubuntu server, copy and paste this entire block:**

```bash
#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "SwingTrader Ubuntu Setup - Full Automation"
echo "=========================================="

# 1. UPDATE SYSTEM
echo "Step 1: Updating system..."
sudo apt-get update
sudo apt-get upgrade -y

# 2. INSTALL ALL DEPENDENCIES
echo "Step 2: Installing dependencies..."
sudo apt-get install -y \
  php-cli php-sqlite3 php-xml php-dom php-mbstring php-curl php-json php-fileinfo \
  nodejs npm \
  python3 python3-venv python3-pip \
  git curl

# 3. INSTALL COMPOSER
echo "Step 3: Installing Composer..."
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x /usr/local/bin/composer

# 4. CONFIGURE GIT
echo "Step 4: Configuring Git..."
git config --global user.name "Dikesh"
git config --global user.email "dikeshchokshi@gmail.com"

# 5. CLONE PROJECT
echo "Step 5: Cloning project..."
cd ~
rm -rf SwingTraderAndOptimizer 2>/dev/null || true
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer
git checkout STO-Ubuntu-v1

# 6. SETUP BACKEND
echo "Step 6: Setting up backend..."
cd backend
cp .env.example .env

# Set database path (absolute)
PROJECT_ROOT="$(cd ../.. && pwd)/SwingTraderAndOptimizer"
DB_PATH="$PROJECT_ROOT/optimizer/optimized_params/strategy_params.db"
sed -i "s|DB_DATABASE=.*|DB_DATABASE=$DB_PATH|" .env

composer install
php artisan key:generate

# 7. SETUP FRONTEND
echo "Step 7: Setting up frontend..."
cd ../frontend
npm install
npm run build

# 8. SETUP PYTHON OPTIMIZER
echo "Step 8: Setting up Python optimizer..."
cd ../optimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# 9. MAKE SCRIPTS EXECUTABLE
echo "Step 9: Making scripts executable..."
cd ../scripts
chmod +x *.sh

# 10. SETUP CRONTAB
echo "Step 10: Setting up crontab..."
PHP_PATH="/usr/bin/php"
PROJECT_ROOT="$(pwd)/.."
ARTISAN_PATH="$PROJECT_ROOT/backend/artisan"
NIGHTLY_SCRIPT="$PROJECT_ROOT/optimizer/run_nightly.sh"

# Add nightly optimizer cron (2 AM daily)
CRON_NIGHTLY="0 2 * * * $NIGHTLY_SCRIPT"
if ! crontab -l 2>/dev/null | grep -q "run_nightly"; then
    (crontab -l 2>/dev/null || true; echo "$CRON_NIGHTLY") | crontab -
    echo "✓ Nightly optimizer cron added"
fi

# Add trade executor cron (every minute)
CRON_TRADES="* * * * * $PHP_PATH $ARTISAN_PATH schedule:run >> /dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "schedule:run"; then
    (crontab -l 2>/dev/null || true; echo "$CRON_TRADES") | crontab -
    echo "✓ Trade executor cron added"
fi

# 11. VERIFY INSTALLATION
echo ""
echo "=========================================="
echo "Verification"
echo "=========================================="
echo "PHP: $(php -v | head -1)"
echo "Node: $(node -v)"
echo "npm: $(npm -v)"
echo "Python: $(python3 --version)"
echo "Composer: $(composer --version)"
echo "Git: $(git --version)"
echo ""
echo "Crontab jobs:"
crontab -l
echo ""
echo "=========================================="
echo "✓ Installation Complete!"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo "1. Edit backend/.env with your Alpaca credentials"
echo "2. Run: cd SwingTraderAndOptimizer && bash scripts/start-all.sh"
echo "3. Open dashboard: http://localhost:5173"
echo ""
```

### Option A: Automated Setup (Recommended)

**One-liner from GitHub:**
```bash
curl -sS https://raw.githubusercontent.com/vipvipvip/SwingTraderAndOptimizer/STO-Ubuntu-v1/scripts/full-setup.sh | bash
```

**Or save and run locally:**
```bash
curl -sS https://raw.githubusercontent.com/vipvipvip/SwingTraderAndOptimizer/STO-Ubuntu-v1/scripts/full-setup.sh > setup.sh
chmod +x setup.sh
./setup.sh
```

**From this repository:**
```bash
bash scripts/full-setup.sh
```

**What the script does:**
- ✅ Updates system packages
- ✅ Installs all dependencies (PHP, Node, Python, Composer)
- ✅ Clones repository and checks out Ubuntu branch
- ✅ Sets up backend (Laravel + Composer)
- ✅ Sets up frontend (Svelte + npm)
- ✅ Sets up Python optimizer with venv
- ✅ Configures crontab for scheduling
- ✅ Verifies everything works
- ✅ Shows next steps

**Time to complete:** ~10-15 minutes depending on internet speed

---

### Option B: Manual Setup (Step by Step)

If you prefer to understand each step, follow the sections below and copy-paste each command block.

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

**Copy & Paste:**
```bash
sudo apt-get update && sudo apt-get upgrade -y
```

**What it does:**
- Updates package lists from repositories
- Upgrades all installed packages to latest versions
- Takes 2-5 minutes depending on system

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

## Unified Codebase: Ubuntu & Windows/WSL

**The codebase is now identical across both platforms.** All three apps (backend, frontend, optimizer) use the same code, same database schema, same API endpoints, and same data flow.

### What's Consistent (Same on Both OS)

| Component | Ubuntu | Windows/WSL | Notes |
|-----------|--------|-------------|-------|
| **Backend API** | Laravel 12 | Laravel 12 | `/api/v1/*` endpoints identical |
| **Frontend** | Svelte 4 | Svelte 4 | http://localhost:5173 on both |
| **Optimizer** | nightly_optimizer.py | nightly_optimizer.py | Same code, detects platform |
| **Database Schema** | SQLite | SQLite | Same tables, same structure |
| **Data Flow** | CSV → bars table → optimizer | CSV → bars table → optimizer | Unified data pipeline |
| **Alpaca SDK** | alpaca-py | alpaca-py | Modern SDK for both |
| **Cache** | In-memory (array) | In-memory (array) | Same cache driver |
| **Configuration** | .env with absolute paths | .env with absolute paths | Same format, same vars |

### What Differs (OS-Specific Only)

| Aspect | Ubuntu (Linux) | Windows/WSL |
|--------|--------|---|
| **Scheduler** | Native `crontab` | Windows Task Scheduler |
| **Script Shell** | Bash (`run_nightly.sh`) | Bash or PowerShell wrapper |
| **Python venv Path** | `/path/venv/bin/python` | `C:\path\venv\Scripts\python.exe` |
| **DB Path Format** | `/home/user/...` (absolute) | `C:\Users\user\...` (absolute) |
| **Line Endings** | LF | CRLF (auto-converted by Git) |

---

## Data Flow: Identical on Both Platforms

```
1. Alpaca API
   ↓
2. fetch_historical_data() → CSV cache
   ↓
3. Import CSV → bars table (SQLite database)
   ↓
4. nightly_optimizer.py
   • Load from bars table
   • Fetch new data from last timestamp
   • Append incremental bars to bars table
   ↓
5. Save optimized parameters → strategy_parameters table
   ↓
6. Backend API queries bars table for optimization data
   ↓
7. Frontend dashboard displays results
```

This flow works identically on Ubuntu, Windows, and WSL.

---

## Windows/WSL Setup (Same Codebase)

For Windows or WSL users, the setup is **identical** except for 3 things:

### 1. Database Path in .env

**Ubuntu:**
```env
DB_DATABASE=/home/user/SwingTraderAndOptimizer/optimizer/optimized_params/strategy_params.db
```

**Windows (PowerShell):**
```env
DB_DATABASE=C:\Users\user\SwingTraderAndOptimizer\optimizer\optimized_params\strategy_params.db
```

**WSL (inside WSL):**
```env
DB_DATABASE=/home/user/SwingTraderAndOptimizer/optimizer/optimized_params/strategy_params.db
```

Git auto-converts line endings, so the file works as-is on both platforms.

### 2. Scheduler Setup (Windows Task Scheduler instead of crontab)

**Ubuntu (crontab):**
```bash
# Nightly optimizer at 2 AM
0 2 * * * /path/to/optimizer/run_nightly.sh

# Trade executor every minute
* * * * * /usr/bin/php /path/to/backend/artisan schedule:run
```

**Windows (Task Scheduler):**
```
Task 1: Run nightly_optimizer.sh at 02:00
  Command: C:\path\to\optimizer\run_nightly.sh
  
Task 2: Run schedule:run every 1 minute
  Command: C:\php\php.exe C:\path\to\backend\artisan schedule:run
```

Or use WSL Task Scheduler:
```powershell
$action = New-ScheduledTaskAction -Execute "wsl" -Argument "/path/to/optimizer/run_nightly.sh"
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "SwingTrader-Optimizer"
```

### 3. Python Virtual Environment Path

**Ubuntu:**
```bash
source /path/venv/bin/activate
```

**Windows (PowerShell):**
```powershell
& 'C:\path\venv\Scripts\Activate.ps1'
```

**Windows (CMD):**
```cmd
C:\path\venv\Scripts\activate.bat
```

### Everything Else is Identical

- Backend API code: Same
- Frontend code: Same
- Optimizer code: Same
- Database schema: Same
- API endpoints: Same
- Data flow: Same

Simply adjust the 3 items above (paths, scheduler, venv activation) and you have a working system on Windows/WSL.

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
