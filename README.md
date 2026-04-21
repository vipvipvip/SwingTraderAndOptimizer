# SwingTraderAndOptimizer

A full-stack algorithmic swing trading system that automatically optimizes trading parameters nightly, executes trades during market hours, and displays live performance on a web dashboard.

**Status:** Production-ready (paper trading). Runs live trades automatically every 30 minutes during market hours (9:30 AM - 4:00 PM ET, weekdays only, when market is open).

---

## What It Does

1. **Nightly Parameter Optimization** (2:00 AM UTC)
   - Runs Python backtester against 2 years of hourly market data
   - Tests ~2,200 MACD/SMA/Bollinger Band parameter combinations per ticker
   - Saves best-performing parameters (by Sharpe ratio) to SQLite database
   - ~87 minute runtime for 3 tickers (SPY, QQQ, IWM)

2. **Scheduled Trade Execution** (Every 30 minutes, market hours)
   - Fetches latest hourly bars from Alpaca
   - Computes MACD, SMA, and Bollinger Band signals using optimized parameters
   - Places market orders automatically when signal fires
   - Tracks entry/exit prices and P&L

3. **Web Dashboard** (Real-time)
   - View account equity, buying power, and cash
   - See strategy parameters and performance metrics (win rate, Sharpe ratio)
   - Chart equity curves (backtest vs. live overlay)
   - Monitor open positions and recent trades

---

## Quick Start

### 1. Prerequisites

- **Windows 11** (or Linux with systemd/cron)
- **PHP 8.2+** with SQLite extension
- **Node.js 18.x** (older versions lack base64url encoding for Vite 4.5)
  - If you have system default older Node, use nvm path prefix: `PATH="/c/Users/dikes/AppData/Roaming/nvm/v18.20.8:$PATH"`
- **Python 3.9+** with venv
- **Git** (optional, for version control)

### 2. Install Dependencies

```bash
# Python optimizer
cd "C:/data/Program Files/SwingTraderAndOptimizer/optimizer"
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt

# Laravel backend
cd "C:/data/Program Files/SwingTraderAndOptimizer/backend"
composer install --ignore-platform-req=ext-fileinfo
cp .env.example .env  # Already exists with correct config

# Svelte frontend
cd "C:/data/Program Files/SwingTraderAndOptimizer/frontend"
npm install  # Ensure Node 18 is active
```

### 3. Set Up Windows Task Scheduler (for automated trading)

```bash
# Run as Administrator in PowerShell:
$ErrorActionPreference = "Stop"
$taskName = "SwingTrader-LaravelScheduler"
$taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($taskExists) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }

$action = New-ScheduledTaskAction -Execute "C:\path\to\php.exe" `
  -Argument "C:\path\to\backend\artisan schedule:run"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserID "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal
```

### 4. Run the Application

```bash
# Terminal 1: Laravel backend (port 8000)
cd "C:/data/Program Files/SwingTraderAndOptimizer/backend"
php artisan serve --host=127.0.0.1 --port=8000

# Terminal 2: Svelte frontend (port 5173) — must use Node 18
cd "C:/data/Program Files/SwingTraderAndOptimizer/frontend"
PATH="/c/Users/dikes/AppData/Roaming/nvm/v18.20.8:$PATH" npm run dev

# Terminal 3 (optional): Watch optimizer logs
cd "C:/data/Program Files/SwingTraderAndOptimizer/backend"
tail -f storage/logs/laravel.log
```

**Dashboard:** http://localhost:5173

---

## Project Structure

```
SwingTraderAndOptimizer/
├── optimizer/                    # Python backtester + parameter optimizer
│   ├── venv/                     # Virtual environment (gitignored)
│   ├── nightly_optimizer.py      # Main optimizer — grid search on hourly data
│   ├── parameter_optimizer.py    # Strategy logic (MACD/SMA/BB signals)
│   ├── data_fetcher.py           # Alpaca API data loading
│   ├── db.py                     # SQLite helper for strategy_parameters table
│   ├── gen_equity_curves.py      # Generate equity snapshots from trades
│   ├── requirements.txt          # Python dependencies
│   ├── .env                      # API credentials + TRADING_TIMEFRAME
│   └── optimized_params/
│       └── strategy_params.db    # Shared SQLite database (shared with Laravel)
│
├── backend/                      # Laravel 12 REST API + scheduling
│   ├── app/
│   │   ├── Console/
│   │   │   ├── Commands/
│   │   │   │   ├── ExecuteDailyTrades.php     # Runs every 30 min, places orders
│   │   │   │   └── OptimizeNightly.php        # Runs nightly, calls Python
│   │   │   └── Kernel.php                     # Schedule definition
│   │   ├── Http/Controllers/
│   │   │   ├── TickerController.php           # GET /api/v1/tickers
│   │   │   ├── AccountController.php          # GET /api/v1/account
│   │   │   ├── EquityController.php           # GET /api/v1/equity/{ticker}
│   │   │   ├── TradesController.php           # GET /api/v1/trades/pnl
│   │   │   └── AdminController.php            # POST /api/v1/admin/optimize/trigger
│   │   ├── Services/
│   │   │   ├── AlpacaService.php              # Alpaca API wrapper
│   │   │   ├── TradeExecutorService.php       # Signal computation + order placement
│   │   │   └── EquityService.php              # Account equity snapshots
│   │   └── Models/
│   │       ├── Ticker.php, StrategyParameter.php, LiveTrade.php, etc.
│   ├── storage/logs/laravel.log               # Task execution logs
│   ├── .env                                   # Configuration (API keys, DB path, TRADING_TIMEFRAME)
│   └── database/                              # Migrations
│
├── frontend/                     # Svelte 4 dashboard
│   ├── src/
│   │   ├── lib/components/
│   │   │   ├── StrategyCard.svelte            # Strategy parameters + metrics display
│   │   │   ├── EquityCurveChart.svelte        # Chart.js equity visualization
│   │   │   └── PositionsList.svelte           # Open positions table
│   │   ├── api.js                             # Axios wrapper for /api/v1/* endpoints
│   │   └── App.svelte                         # Main dashboard
│   ├── package.json
│   └── vite.config.js                         # Requires Node 18 for base64url
│
└── .gitignore                    # Excludes .env, venv/, vendor/, node_modules/, *.db
```

---

## Configuration

All configuration lives in `.env` files. Key variables:

### `optimizer/.env` and `backend/.env`

```bash
# Alpaca API (paper trading)
ALPACA_API_KEY=PKGT6G6VWVQHWIYZAZIH6H6TQA
ALPACA_SECRET_KEY=EXWwpUnfkGYjdWp8w5Q1ijddkRjSvnBwHyJXvpyoJmie
ALPACA_BASE_URL=https://paper-api.alpaca.markets
FRONTEND_URL=http://localhost:5173

# Database (shared between Python and Laravel)
DB_DATABASE="C:/data/Program Files/SwingTraderAndOptimizer/optimizer/optimized_params/strategy_params.db"

# Optimizer timeframe (controls both Python and PHP)
# Change to "1Day" for daily bars (slower but more data per bar)
TRADING_TIMEFRAME=1Hour

# Python interpreter path (for Laravel to call optimizer)
PYTHON_PATH="C:/data/Program Files/SwingTraderAndOptimizer/optimizer/venv/Scripts/python.exe"
NIGHTLY_SCRIPT="C:/data/Program Files/SwingTraderAndOptimizer/optimizer/nightly_optimizer.py"
```

---

## How It Works

### The Trading Loop

```
Every 30 minutes (during market hours):
┌─────────────────────────────────────┐
│ 1. Windows Task Scheduler fires      │
│    → Calls: php artisan schedule:run │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ 2. Laravel Scheduler checks due      │
│    commands (every minute check)     │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ 3. ExecuteDailyTrades command runs   │
│    (every 30 min, 9:30-16:00 ET)    │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ 4. For each ticker (SPY, QQQ, IWM): │
│    a) Fetch latest hourly bars      │
│    b) Load optimized parameters     │
│    c) Compute MACD/SMA/BB signals   │
│    d) Place order if signal fires   │
│    e) Record trade to database      │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ 5. Dashboard refreshes (every 60s)  │
│    Shows updated equity + trades    │
└─────────────────────────────────────┘
```

### Nightly Optimization (2:00 AM UTC)

```
Every night at 2 AM UTC:
┌─────────────────────────────────────┐
│ OptimizeNightly command runs         │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ Calls Python nightly_optimizer.py:  │
│ For each ticker (SPY, QQQ, IWM):    │
│  1. Fetch 2 years of hourly data    │
│  2. Grid search ~2,200 param combos │
│  3. Backtest each against 2y data   │
│  4. Save best params (by Sharpe)    │
│  5. ~87 minutes total runtime       │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ Updated params saved to:            │
│ strategy_parameters table           │
│ (used by trade executor next run)   │
└─────────────────────────────────────┘
```

---

## Components

### Python Optimizer (`optimizer/nightly_optimizer.py`)

**Purpose:** Grid-search parameter optimization on hourly historical data.

**How it works:**
1. Loads 2 years of hourly bars from Alpaca for each ticker
2. Tests all combinations from `PARAM_GRIDS` dict:
   - MACD: fast=[3,5,8], slow=[13,21,34], signal=[3,5,8]
   - SMA: short=[20,30,50], long=[100,150,200]
   - Bollinger Bands: period=[14,20,26], std=[1.8,2.0,2.2]
3. For each combo, runs full backtest on 2 years of data
4. Ranks by Sharpe ratio
5. Saves winner to `strategy_parameters` table (one row per ticker)

**Run manually:**
```bash
cd optimizer
source venv/Scripts/activate
python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM
```

**Config:** `TRADING_TIMEFRAME` env var controls timeframe (1Hour or 1Day). Param grids auto-scale per timeframe.

---

### Laravel Backend (`backend/`)

**Purpose:** REST API, trade execution, scheduling, database.

**Key endpoints:**
- `GET /api/v1/tickers` → All strategy parameters
- `GET /api/v1/account` → Account balance, buying power
- `GET /api/v1/equity/{ticker}` → Backtest + live equity curves
- `GET /api/v1/trades/pnl` → Win rate, total return, Sharpe
- `POST /api/v1/admin/optimize/trigger` → Run optimizer now

**Scheduled commands** (defined in `app/Console/Kernel.php`):
1. `optimize:nightly` → Daily at 2:00 AM UTC (calls Python)
2. `trades:execute-daily` → Every 30 min, 9:30-16:00 ET (calls TradeExecutorService)
3. `positions:sync` → Every 5 min during market hours (updates position cache)

**TradeExecutorService.php** — Core logic:
- Computes EMA for smoothing
- Detects MACD histogram crosses (entry/exit signals)
- Filters by SMA uptrend (price > SMA50 > SMA200)
- Checks Bollinger Bands for volatility
- Places orders via Alpaca API
- Records trades to `live_trades` table

---

### Svelte Dashboard (`frontend/`)

**Purpose:** Real-time performance visualization and monitoring.

**Features:**
- Account equity and buying power (real-time from Alpaca)
- Strategy cards showing optimized parameters and metrics
  - Win rate (live backtest data)
  - Sharpe ratio, total return
  - MACD, SMA, BB parameter values
- Equity curves with Chart.js
  - Grey dashed line: backtest equity
  - Green solid line: live trading equity
  - Instant switching between tickers (cached)
- Recent trades list with entry/exit prices and P&L

**Auto-refresh:** Every 60 seconds via `setInterval`

---

## Database

**Location:** `optimizer/optimized_params/strategy_params.db` (SQLite)

**Tables:**

| Table | Columns | Purpose |
|-------|---------|---------|
| `tickers` | id, symbol, created_at | Trading symbols (SPY, QQQ, IWM) |
| `strategy_parameters` | id, ticker_id, macd_fast, macd_slow, ... (11 columns), updated_at | Optimized params (one per ticker) |
| `equity_snapshots` | id, ticker_id, snapshot_date, equity_value, snapshot_type | Daily equity (backtest + live) |
| `live_trades` | id, ticker_id, entry_date, entry_price, exit_date, exit_price, return, pnl_dollar | Executed trades |
| `positions_cache` | id, ticker_id, qty, entry_price, market_value, unrealized_pnl | Current open positions |
| `optimization_history` | id, ticker_id, run_date, sharpe_ratio, win_rate, num_trades | Audit trail |

---

## Market Protection

The system has **two layers** of protection to avoid after-hours or holiday trading:

1. **Laravel Kernel.php** — `->weekdays()` constraint
   - Prevents any commands from running on weekends
   - Trades cannot execute Saturday/Sunday

2. **ExecuteDailyTrades.php** — Alpaca `$clock['is_open']` check
   - Verifies market is actually open before placing orders
   - Handles holidays automatically (Alpaca API tells us if market is closed)
   - Double-checks during market hours (9:30-16:00 ET)

**Result:** Trades only execute weekdays during actual market hours.

---

## Troubleshooting

### Scheduler Not Running Trades

**Check:**
1. Is it market hours? (9:30-16:00 ET, weekdays only)
2. Is the Windows Task Scheduler task running?
   ```bash
   schtasks query /tn "SwingTrader-LaravelScheduler"
   # Should show State: Ready
   ```
3. Check Laravel logs:
   ```bash
   tail -f backend/storage/logs/laravel.log | grep -i "execute\|optimize"
   ```

**Common issues:**
- Task Scheduler not running → Run as Administrator and re-register task
- PHP not in PATH → Use absolute path in task action
- Alpaca credentials expired → Update `.env` with fresh API key/secret

### Dashboard Shows "Failed to load strategies"

1. Check Laravel is running: `php artisan tinker` (should start REPL)
2. Verify database exists: `ls optimizer/optimized_params/strategy_params.db`
3. Check database has data: `sqlite3 optimizer/optimized_params/strategy_params.db "SELECT * FROM strategy_parameters LIMIT 1;"`
4. Verify API endpoint: `curl http://localhost:8000/api/v1/tickers`

### Optimizer Not Finding Data

1. Verify Alpaca credentials in `.env`
2. Test API: `curl -H "Authorization: Bearer YOUR_KEY" https://paper-api.alpaca.markets/v2/account`
3. Check log: `tail -f backend/storage/logs/laravel.log`

### Slow Dashboard / Equity Curve Takes Forever to Load

1. This is fixed in current version (cached per-symbol, in-place chart update)
2. If still slow, check browser network tab for slow API response
3. Verify backend isn't running optimizer (check `top` on Linux or Task Manager on Windows)

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `optimizer/nightly_optimizer.py` | Grid search + backtest |
| `optimizer/parameter_optimizer.py` | Strategy indicators (MACD/SMA/BB logic) |
| `optimizer/data_fetcher.py` | Alpaca API data fetching |
| `optimizer/db.py` | SQLite helper for saving params |
| `backend/app/Console/Kernel.php` | Schedule definition (times + frequencies) |
| `backend/app/Console/Commands/ExecuteDailyTrades.php` | Trade execution entry point |
| `backend/app/Services/TradeExecutorService.php` | Signal generation + order placement |
| `backend/app/Services/AlpacaService.php` | Alpaca API wrapper |
| `backend/app/Http/Controllers/TickerController.php` | GET /api/v1/tickers endpoint |
| `frontend/src/App.svelte` | Dashboard main page |
| `frontend/src/api.js` | Axios wrapper for API calls |

---

## Manual Commands

### Trigger Optimizer Now (Don't Wait for 2 AM)

```bash
cd backend
php artisan optimize:nightly
```

### Validate Trade Signals (Dry-Run)

```bash
php artisan trades:validate SPY
php artisan trades:validate QQQ
php artisan trades:validate IWM
```

### Inspect Database

```bash
sqlite3 "optimizer/optimized_params/strategy_params.db"
.mode column
.headers on

SELECT symbol, macd_fast, macd_slow, sma_short, sma_long, updated_at
FROM strategy_parameters sp
JOIN tickers t ON sp.ticker_id = t.id;
```

### Clear Cache (If Dashboard Acts Weird)

```bash
php artisan config:clear
php artisan cache:clear
```

---

## Alpaca Account Details

**Paper Trading Account** (no real money risk):
- **API Base URL:** https://paper-api.alpaca.markets
- **Account Equity:** $100,000 (starting)
- **Buying Power:** ~$200,000 (2x leverage)
- **Status:** Active, ready for trading

**To Switch to Live Trading:**
Change `.env`:
```bash
ALPACA_BASE_URL=https://api.alpaca.markets  # (WARNING: Real money!)
```

---

## Development

### Add a New Ticker

1. **Launch Laravel REPL** → `php artisan tinker`
   ```php
   Ticker::create(['symbol' => 'AAPL']);
   exit  # or Ctrl+D to quit tinker
   ```
   (`tinker` is Laravel's interactive shell where you can run PHP code directly)

2. **Verify Optimizer** can fetch data for it (test manually first)
   ```bash
   python optimizer.py --tickers AAPL
   ```

3. **Update Kernel.php** if you want a separate schedule trigger

4. **Dashboard** auto-detects all tickers from `/api/v1/tickers`

### Change Timeframe

Edit `.env`:
```bash
TRADING_TIMEFRAME=1Day    # or 1Hour, 15Min, 5Min, etc.
```

Optimizer will auto-scale param grid. No code changes needed.

### Deploy to Production

1. Change `.env`:
   ```bash
   ALPACA_BASE_URL=https://api.alpaca.markets  # Live trading
   APP_ENV=production
   ```

2. Register Task Scheduler as described in "Quick Start" section

3. Monitor logs daily: `tail -f backend/storage/logs/laravel.log`

---

## Support

For detailed scheduler setup (Linux systemd/cron), see: `SCHEDULER_SETUP.md` (supplementary guide)

For implementation details on specific components, see inline code comments in:
- `optimizer/nightly_optimizer.py`
- `backend/app/Services/TradeExecutorService.php`
- `frontend/src/api.js`

---

**Last updated:** 2026-04-20  
**Status:** Production-ready (paper trading)
