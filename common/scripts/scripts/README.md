# Swing Trader Scripts

Startup and utility scripts for the SwingTrader application.

## Quick Start

### First Time Setup
```bash
bash scripts/setup.sh
```
Installs dependencies, configures .env, runs migrations.

### Start Everything (Recommended)
```bash
bash scripts/start-all.sh
```
Starts both backend API and frontend dashboard in one command.

### Or Start Separately

**Backend only:**
```bash
bash scripts/start.sh
```

**Frontend only (after backend is running):**
```bash
cd frontend
npm run dev
```

## Scripts

### `start-all.sh` — Start backend + frontend together
Convenient single command to start both servers.

**Run:**
```bash
bash scripts/start-all.sh
```

**Starts:**
- Backend API on http://localhost:9000
- Frontend dashboard on http://localhost:5173
- Auto-installs frontend dependencies if needed
- Handles cleanup on Ctrl+C

**Access:**
- Dashboard: http://localhost:5173
- API: http://localhost:9000
- API Docs: http://localhost:9000/api/documentation

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

Starts Laravel development server on `http://localhost:9000`

## After Startup

**API Documentation (Swagger UI):**
```
http://localhost:9000/api/documentation
```

**Manual API Triggers:**
```bash
# Execute trades now
curl -X POST http://localhost:9000/api/v1/admin/trades/trigger

# Run optimizer now
curl -X POST http://localhost:9000/api/v1/admin/optimize/trigger

# Check market status
curl http://localhost:9000/api/v1/admin/market-status
```

**Monitor Logs:**
```bash
tail -f backend/storage/logs/laravel.log
tail -f backend/storage/logs/trade_executor.log
tail -f optimizer/logs/nightly.log
```

## Systemd Services (Current)

Services are managed by systemd:

- **Backend:** `sudo systemctl start swingtrader-backend` (port 9000)
- **Frontend:** `sudo systemctl start swingtrader-fe-dev` (port 5173, Vite dev)
- **Optimizer Timer:** `sudo systemctl start swingtrader-optimizer.timer` (daily 2:00 AM)

## Requirements

- **PHP 8.2+** with CLI
- **Composer**
- **PostgreSQL 14+**
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

**Database connection error:**
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Run migrations
cd backend && php artisan migrate --force
```

**Port 9000 already in use:**
Edit the service file `ExecStart` line to change `--port=9000` to another port.

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
