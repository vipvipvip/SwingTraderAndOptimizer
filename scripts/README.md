# Swing Trader Scripts

Startup and utility scripts for the SwingTrader application.

## Quick Start

### First Time Setup
```bash
bash scripts/setup.sh
```
Installs dependencies, configures .env, runs migrations.

### Start Application
```bash
bash scripts/start.sh
```
Starts Laravel dev server on http://localhost:8000

## Scripts

### `setup.sh` — One-time initialization
Checks prerequisites and configures the application:
- Verifies PHP and Composer installed
- Creates required directories
- Runs `composer install`
- Sets up `.env` file
- Generates APP_KEY
- Runs database migrations

**Run once:**
```bash
bash scripts/setup.sh
```

### `start.sh` — Start the application
Minimal startup script. Assumes setup already complete.

**Run daily:**
```bash
bash scripts/start.sh
```

Starts Laravel development server on `http://localhost:8000`

## After Startup

**API Documentation (Swagger UI):**
```
http://localhost:8000/api/documentation
```

**Manual API Triggers:**
```bash
# Execute trades now
curl -X POST http://localhost:8000/api/v1/admin/trades/trigger

# Run optimizer now
curl -X POST http://localhost:8000/api/v1/admin/optimize/trigger

# Check market status
curl http://localhost:8000/api/v1/admin/market-status
```

**Monitor Logs:**
```bash
tail -f backend/storage/logs/laravel.log
tail -f backend/storage/logs/trade_executor.log
tail -f optimizer/logs/nightly.log
```

## Cron Setup

Cron jobs for automated trading are installed separately via:
- **WSL/Linux:** `crontab -e` (manually add entries from memory)
- **Windows Task Scheduler:** Use Windows built-in scheduler

Scheduled tasks:
- **8:18 AM ET daily:** Nightly optimizer
- **9:30 AM - 4:00 PM (every 30 min, weekdays):** Trade executor

## Requirements

- **PHP 8.1+** with CLI
- **Composer** (for setup only)
- **SQLite** (default, automatic)
- **Alpaca API credentials** (in .env)

## Troubleshooting

**PHP not found:**
```bash
# Install PHP
apt-get install php-cli php-sqlite3  # Ubuntu/Debian/WSL

# Verify
php -v
```

**Composer not found:**
```bash
# Install Composer
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer

# Verify
composer --version
```

**Port 8000 already in use:**
Edit `scripts/start.sh` and change `--port=8000` to another port.

**Database locked:**
```bash
# Reset database
rm backend/database/database.sqlite
bash scripts/setup.sh
```

## Environment

For Alpaca API access, set in `backend/.env`:
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
```

Get credentials from: https://app.alpaca.markets/

## Linux Compatibility

✓ Tested on:
- WSL2 (Windows Subsystem for Linux)
- Ubuntu 20.04+
- Debian 11+
- Any Linux with PHP 8.1+ and Composer

All paths use forward slashes. No Windows-specific code.
