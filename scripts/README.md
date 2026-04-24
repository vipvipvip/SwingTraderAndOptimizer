# Swing Trader Scripts

Startup and utility scripts for the SwingTrader application.

## Quick Start

### Linux/WSL/macOS
```bash
bash scripts/start.sh
```

### Windows
```cmd
scripts\start.bat
```

## What Each Script Does

### `start.sh` / `start.bat`
**Startup script for the application**

Checks prerequisites, installs dependencies, initializes database, and starts Laravel dev server.

**Automatically:**
- Checks for PHP and Composer
- Creates necessary directories
- Installs PHP dependencies
- Sets up `.env` if missing
- Generates APP_KEY
- Runs database migrations
- Displays API endpoints and log locations
- Starts Laravel server on `http://localhost:8000`

### `setup-optimizer-cron.sh`
**Install nightly optimizer on WSL/Linux**

Adds cron job for the nightly optimizer (8:18 AM ET daily).

```bash
bash scripts/setup-optimizer-cron.sh
```

### `setup-optimizer-wts.ps1`
**Install nightly optimizer on Windows Task Scheduler**

Adds Windows Task Scheduler job for the nightly optimizer.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-optimizer-wts.ps1
```

### `daily-check.sh` / `daily-check.ps1`
**Health check for the trading system**

Verifies optimizer and trade executor are running correctly.

```bash
bash scripts/daily-check.sh
```

## After Startup

Once the server is running:

1. **API Documentation:** http://localhost:8000/api/documentation (Swagger UI)
2. **Manual Triggers:**
   ```bash
   # Execute trades now
   curl -X POST http://localhost:8000/api/v1/admin/trades/trigger
   
   # Run optimizer now
   curl -X POST http://localhost:8000/api/v1/admin/optimize/trigger
   
   # Check market status
   curl http://localhost:8000/api/v1/admin/market-status
   ```

3. **Monitor Logs:**
   - Backend: `backend/storage/logs/laravel.log`
   - Trade Executor: `backend/storage/logs/trade_executor.log`
   - Optimizer: `optimizer/logs/nightly.log`

4. **Verify Cron (WSL/Linux):**
   ```bash
   crontab -l | grep SwingTrader
   ```

## Troubleshooting

**PHP not found:**
- Ensure PHP is installed and in PATH
- On Windows, check that PHP path is in system environment variables

**Composer not found:**
- Install from https://getcomposer.org/download/
- Or use `php -r "copy('https://getcomposer.org/installer', 'composer-setup.php'); php('composer-setup.php');")`

**Database errors:**
- Ensure `backend/storage/logs` directory is writable
- Check `.env` database configuration (defaults to SQLite at `database/database.sqlite`)

**Alpaca API errors:**
- Update `.env` with your Alpaca API credentials
- Verify `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are set

**Port 8000 already in use:**
- Change the port in the start script (modify `--port=8000`)
- Or stop the process using port 8000
