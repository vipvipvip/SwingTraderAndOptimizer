# SwingTraderAndOptimizer

A full-stack algorithmic swing trading system that automatically optimizes trading parameters nightly, executes trades during market hours with per-ticker allocation weights, and displays live performance on a web dashboard.

**Status:** Production-ready (paper trading). Runs live trades automatically every 30 minutes during market hours (9:30 AM - 4:00 PM ET, weekdays only, when market is open). Nightly optimizer runs via OS scheduler (Windows Task Scheduler / cron) at 2:00 AM UTC.

---

## What It Does

1. **Nightly Parameter Optimization** (2:00 AM UTC via OS Scheduler)
   - Runs Python backtester against 2 years of hourly market data
   - Tests ~2,200 MACD/SMA/Bollinger Band parameter combinations per ticker
   - Generates backtest trades with allocation-aware position sizing
   - Saves best-performing parameters (by Sharpe ratio) to SQLite database
   - ~87 minute runtime for 3 tickers (SPY, QQQ, IWM) — uses native OS scheduler to bypass PHP timeout

2. **Dynamic Allocation Weights** (Per-ticker capital allocation)
   - Configure how much portfolio capital is allocated to each ticker (default 33.33% per ticker for 3-way split)
   - Trade sizing automatically scales: `(account_equity × allocation_weight%) / entry_price`
   - Backtest trades use the same allocation formula for realistic P&L
   - Update via API: `PUT /api/v1/tickers/{symbol}/allocation`

3. **Scheduled Trade Execution** (Every 30 minutes, market hours)
   - Fetches latest hourly bars from Alpaca
   - Computes MACD, SMA, and Bollinger Band signals using optimized parameters
   - Places market orders with allocation-weighted position sizing
   - Tracks entry/exit prices, P&L, and allocation weight per trade
   - Records all trades to database with complete metrics

4. **Web Dashboard** (Real-time)
   - View account equity, buying power, and cash
   - See strategy parameters and performance metrics (win rate, Sharpe ratio, allocation weight)
   - Chart equity curves (backtest vs. live overlay)
   - Monitor open positions and recent trades with allocation details
   - Inspect backtest trades from nightly optimizer runs
   - **Manual trigger buttons** — Run optimizer or trade executor on-demand (for testing/emergencies)

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
cd optimizer
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt

# Laravel backend
cd ../backend
composer install --ignore-platform-req=ext-fileinfo
cp .env.example .env  # Already exists with correct config

# Svelte frontend
cd ../frontend
npm install  # Ensure Node 18 is active
```

### 3. Set Up OS Scheduler (Trade Executor + Nightly Optimizer)

**Option A: Windows (Task Scheduler)**

```powershell
# Terminal 1 — Trade Executor (runs Laravel scheduler every minute)
# Run as Administrator in PowerShell:
$phpPath = "C:\path\to\php.exe"  # e.g., C:\tools\php82\php.exe
$projectRoot = "C:\path\to\SwingTraderAndOptimizer"
$artisanPath = "$projectRoot\backend\artisan"

$action = New-ScheduledTaskAction -Execute $phpPath -Argument "$artisanPath schedule:run"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserID "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "SwingTrader-LaravelScheduler" -Action $action -Trigger $trigger -Principal $principal

# Terminal 2 — Nightly Optimizer (runs at 2 AM UTC, bypasses Laravel timeout)
# Run as Administrator in PowerShell:
cd C:\path\to\SwingTraderAndOptimizer\scripts
.\setup-optimizer-wts.ps1
```

**Option B: Linux (cron)**

```bash
# Trade Executor (runs Laravel scheduler every minute)
# Add to /etc/crontab or via `crontab -e`:
* * * * * /path/to/php /path/to/SwingTraderAndOptimizer/backend/artisan schedule:run >> /dev/null 2>&1

# Nightly Optimizer (runs at 2 AM UTC, direct Python execution)
cd /path/to/SwingTraderAndOptimizer/scripts
chmod +x setup-optimizer-cron.sh
./setup-optimizer-cron.sh
```

**Why separate schedulers?**
- Trade executor needs quick iteration (every 30 min, market hours) — Laravel scheduler handles this
- Nightly optimizer takes ~87 minutes — OS scheduler bypasses PHP's 60s timeout limit

### 3.1 Verify Nightly Optimizer Setup

**Windows (Task Scheduler):**

```powershell
# Verify task exists and is ready
schtasks query /tn "SwingTrader-NightlyOptimizer"
# Should show State: Ready

# Manually trigger to test (optional)
schtasks run /tn "SwingTrader-NightlyOptimizer"

# Check logs after run completes
Get-Content "C:\path\to\SwingTraderAndOptimizer\optimizer\logs\nightly.log" -Tail 20
```

**Linux/WSL (cron):**

```bash
# Verify cron job exists
crontab -l | grep run_nightly

# Check logs after it runs (2 AM daily)
tail -f /path/to/SwingTraderAndOptimizer/optimizer/logs/nightly.log
```

**What to look for in logs:**
```
[2026-04-23 02:00:00] Nightly optimizer starting...
[2026-04-23 02:01:15] Optimizing SPY [1Hour]...
[2026-04-23 02:45:30] Optimizer finished (exit: 0)
```

Exit code 0 = success. Non-zero = check Python package imports and Alpaca API key.

### 4. Run the Application

```bash
# Terminal 1: Laravel backend (port 9000)
cd backend
php artisan serve --host=127.0.0.1 --port=9000

# Terminal 2: Svelte frontend (port 5173) — must use Node 18
cd frontend
npm run dev
# If Node 18 is not your default, activate it first via nvm or path prefix

# Terminal 3 (optional): Watch optimizer logs
cd backend
tail -f storage/logs/laravel.log
```

**Dashboard:** http://localhost:5173

---

## Project Structure

```
SwingTraderAndOptimizer/
├── optimizer/                    # Python backtester + parameter optimizer
│   ├── venv/                     # Virtual environment (gitignored)
│   ├── logs/                     # Nightly optimizer logs (created at runtime)
│   ├── nightly_optimizer.py      # Main optimizer — grid search + allocation-aware backtesting
│   ├── parameter_optimizer.py    # Strategy logic (MACD/SMA/BB signals + allocation sizing)
│   ├── data_fetcher.py           # Alpaca API data loading
│   ├── db.py                     # SQLite helper (reads allocation weights from Laravel DB)
│   ├── gen_equity_curves.py      # Generate equity snapshots from trades
│   ├── requirements.txt          # Python dependencies
│   ├── run_nightly.ps1           # Windows wrapper — called by Task Scheduler
│   ├── run_nightly.sh            # Linux wrapper — called by cron
│   ├── .env                      # API credentials + TRADING_TIMEFRAME
│   └── optimized_params/
│       └── strategy_params.db    # Shared SQLite database (shared with Laravel)
│
├── backend/                      # Laravel 12 REST API + scheduling
│   ├── app/
│   │   ├── Console/
│   │   │   ├── Commands/
│   │   │   │   ├── ExecuteDailyTrades.php     # Runs every 30 min, places allocation-weighted orders
│   │   │   │   └── RunNightlyOptimizer.php    # Manual trigger only (not auto-scheduled)
│   │   │   └── Kernel.php                     # Schedule definition (trade execution + equity snapshots)
│   │   ├── Http/Controllers/
│   │   │   ├── TickerController.php           # GET /api/v1/tickers, PUT /api/v1/tickers/{symbol}/allocation
│   │   │   ├── AccountController.php          # GET /api/v1/account
│   │   │   ├── EquityController.php           # GET /api/v1/equity/{ticker}
│   │   │   ├── TradesController.php           # GET /api/v1/trades/pnl, GET /api/v1/trades/backtest
│   │   │   └── AdminController.php            # POST /api/v1/admin/optimize/trigger, POST /api/v1/admin/trades/trigger
│   │   ├── Services/
│   │   │   ├── AlpacaService.php              # Alpaca API wrapper
│   │   │   ├── TradeExecutorService.php       # Signal computation + allocation-weighted order placement
│   │   │   └── EquityService.php              # Account equity snapshots
│   │   └── Models/
│   │       ├── Ticker.php, StrategyParameter.php, LiveTrade.php, BacktestTrade.php, etc.
│   ├── storage/logs/laravel.log               # Task execution logs
│   ├── .env                                   # Configuration (API keys, DB path, TRADING_TIMEFRAME, PYTHON_PATH, NIGHTLY_SCRIPT)
│   └── database/                              # Migrations (allocations, backtest trades, etc.)
│
├── frontend/                     # Svelte 4 dashboard
│   ├── src/
│   │   ├── lib/components/
│   │   │   ├── StrategyCard.svelte            # Strategy parameters + metrics display + allocation widget
│   │   │   ├── EquityCurveChart.svelte        # Chart.js equity visualization
│   │   │   ├── PositionsList.svelte           # Open positions table with allocation details
│   │   │   └── TradesTable.svelte             # Backtest trades + live trades combined
│   │   ├── api.js                             # Axios wrapper for /api/v1/* endpoints
│   │   └── App.svelte                         # Main dashboard
│   ├── package.json
│   └── vite.config.js                         # Requires Node 18 for base64url
│
├── scripts/                      # OS scheduler setup scripts
│   ├── setup-optimizer-wts.ps1   # Register nightly optimizer with Windows Task Scheduler
│   └── setup-optimizer-cron.sh   # Register nightly optimizer with Linux cron
│
├── BEST_PRACTICES.md             # Learnings from implementation (configuration, migrations, etc.)
└── .gitignore                    # Excludes .env, venv/, vendor/, node_modules/, *.db
```

---

## Configuration

All configuration lives in `.env` files. Key variables:

### `optimizer/.env`

```bash
# Alpaca API (paper trading)
ALPACA_API_KEY=PKGT6G6VWVQHWIYZAZIH6H6TQA
ALPACA_SECRET_KEY=EXWwpUnfkGYjdWp8w5Q1ijddkRjSvnBwHyJXvpyoJmie
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Optimizer timeframe (controls parameter grid scaling)
# Change to "1Day" for daily bars (slower but more data per bar)
TRADING_TIMEFRAME=1Hour
```

### `backend/.env`

```bash
# Alpaca API (paper trading)
ALPACA_API_KEY=PKGT6G6VWVQHWIYZAZIH6H6TQA
ALPACA_SECRET_KEY=EXWwpUnfkGYjdWp8w5Q1ijddkRjSvnBwHyJXvpyoJmie
ALPACA_BASE_URL=https://paper-api.alpaca.markets
FRONTEND_URL=http://localhost:5173

# Database (shared between Python and Laravel) — use relative paths for portability
DB_DATABASE="../optimizer/optimized_params/strategy_params.db"

# Optimizer timeframe (must match optimizer/.env)
TRADING_TIMEFRAME=1Hour

# Python interpreter path (for manual artisan optimize:nightly trigger)
PYTHON_PATH="../optimizer/venv/Scripts/python.exe"
NIGHTLY_SCRIPT="../optimizer/nightly_optimizer.py"
```

### Allocation Weights

Each ticker has a configurable allocation weight (percentage of portfolio to allocate):
```bash
# Via API:
curl -X PUT http://localhost:9000/api/v1/tickers/SPY/allocation \
  -H "Content-Type: application/json" \
  -d '{"allocation_weight": 50}'

# Defaults to 33.33% per ticker for even 3-way split
# Trade sizing: (account_equity × allocation_weight%) / entry_price
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

### Nightly Optimization (2:00 AM UTC — OS Scheduler)

```
Every night at 2 AM UTC (via Windows Task Scheduler / cron):
┌─────────────────────────────────────┐
│ OS scheduler triggers run_nightly.* │
│ (PowerShell script on Windows,      │
│  bash script on Linux)              │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ Directly calls Python nightly_opt:  │
│ For each ticker (SPY, QQQ, IWM):    │
│  1. Fetch 2 years of hourly data    │
│  2. Grid search ~2,200 param combos │
│  3. Backtest each against 2y data   │
│  4. Save best params (by Sharpe)    │
│  5. ~87 minutes total runtime       │
│ (No PHP timeout — native execution) │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│ Updated params saved to:            │
│ strategy_parameters table           │
│ (used by trade executor next run)   │
└─────────────────────────────────────┘
```

**Why OS scheduler?** The optimizer takes ~87 minutes but PHP has a 60-second execution limit. Bypass it entirely with direct OS scheduling.

---

## Components

### Python Optimizer (`optimizer/nightly_optimizer.py`)

**Purpose:** Grid-search parameter optimization on hourly historical data with allocation-aware backtesting.

**How it works:**
1. Loads 2 years of hourly bars from Alpaca for each ticker
2. Reads each ticker's allocation weight from Laravel database
3. Tests all combinations from `PARAM_GRIDS` dict:
   - MACD: fast=[3,5,8], slow=[13,21,34], signal=[3,5,8]
   - SMA: short=[20,30,50], long=[100,150,200]
   - Bollinger Bands: period=[14,20,26], std=[1.8,2.0,2.2]
4. For each combo, runs full backtest on 2 years of data with **allocation-weighted position sizing**:
   - Trade quantity = `(initial_capital × allocation_weight%) / entry_price`
   - Generates realistic P&L reflecting actual capital deployment
5. Ranks by Sharpe ratio
6. Saves winner to `strategy_parameters` table (one row per ticker)
7. Records all backtest trades (including allocation details) to `backtest_trades` table

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
- `GET /api/v1/tickers` → All strategy parameters + allocation weights
- `PUT /api/v1/tickers/{symbol}/allocation` → Update allocation weight for a ticker
- `GET /api/v1/account` → Account balance, buying power (from Alpaca)
- `GET /api/v1/equity/{ticker}` → Backtest + live equity curves
- `GET /api/v1/trades/pnl` → Win rate, total return, Sharpe (live trades)
- `GET /api/v1/trades/backtest` → Backtest trades from nightly optimizer (with allocation details)
- `POST /api/v1/admin/optimize/trigger` → Run optimizer now (manual trigger, also available via UI button)
- `POST /api/v1/admin/trades/trigger` → Run trade executor now (manual trigger, also available via UI button)

**Scheduled commands** (defined in `app/Console/Kernel.php`):
1. `trades:execute-daily` → Every 30 min, 9:30-16:00 ET (calls TradeExecutorService)
2. `equity:snapshot` → Daily at 16:05 ET (records end-of-day equity)
3. `positions:sync` → Every 5 min during market hours (updates position cache)

**Note:** `optimize:nightly` is no longer in Laravel's schedule — it's now managed by OS scheduler (see Step 3 setup). Manual trigger still available: `php artisan optimize:nightly`

**TradeExecutorService.php** — Core logic:
- Loads per-ticker allocation weight from database
- Computes allocation-aware position size: `(account_equity × allocation_weight%) / entry_price`
- Computes EMA for smoothing
- Detects MACD histogram crosses (entry/exit signals)
- Filters by SMA uptrend (price > SMA50 > SMA200)
- Checks Bollinger Bands for volatility
- Places allocation-weighted orders via Alpaca API
- Records trades to `live_trades` table with allocation details

---

### Svelte Dashboard (`frontend/`)

**Purpose:** Real-time performance visualization and monitoring.

**Features:**
- Account equity and buying power (real-time from Alpaca)
- Strategy cards showing optimized parameters and metrics
  - Win rate (from live trades)
  - Sharpe ratio, total return, allocation weight
  - MACD, SMA, BB parameter values
  - **Allocation weight editor** — update per-ticker capital allocation in real-time
- Equity curves with Chart.js
  - Grey dashed line: backtest equity (from nightly optimizer)
  - Green solid line: live trading equity
  - Instant switching between tickers (cached)
- **Backtest trades** — all trades from nightly optimizer runs
  - Shows entry/exit prices, P&L, allocation weight used
  - Filterable by ticker and date range
- **Live trades** — all executed orders from trade executor
  - Shows entry/exit prices, P&L, actual allocation weight executed
  - Real-time P&L tracking

**Auto-refresh:** Every 60 seconds via `setInterval`

---

## Database

**Location:** `optimizer/optimized_params/strategy_params.db` (SQLite)

**Tables:**

| Table | Columns | Purpose |
|-------|---------|---------|
| `tickers` | id, symbol, allocation_weight, created_at | Trading symbols (SPY, QQQ, IWM) + capital allocation per ticker |
| `strategy_parameters` | id, ticker_id, macd_fast, macd_slow, macd_signal, sma_short, sma_long, bb_period, bb_std, win_rate, sharpe_ratio, total_return, total_trades, updated_at | Optimized params (one per ticker) |
| `equity_snapshots` | id, ticker_id, snapshot_date, equity_value, snapshot_type (backtest\|live), created_at | Daily equity curves |
| `live_trades` | id, ticker_id, entry_date, entry_price, qty, exit_date, exit_price, return, pnl_dollar, allocation_weight, created_at | Executed trades with allocation details |
| `backtest_trades` | id, ticker_id, entry_date, entry_price, qty, exit_date, exit_price, return, pnl_dollar, allocation_weight, optimization_run_id, created_at | Trades from nightly optimizer backtests (with allocation-aware sizing) |
| `positions_cache` | id, ticker_id, qty, entry_price, market_value, unrealized_pnl, updated_at | Current open positions |
| `optimization_history` | id, ticker_id, run_date, sharpe_ratio, win_rate, num_trades, num_combos_tested, runtime_seconds | Audit trail of optimization runs |

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

1. Check Laravel is running: `cd backend && php artisan tinker` (should start REPL)
2. Verify database exists: `ls ../optimizer/optimized_params/strategy_params.db`
3. Check database has data: `sqlite3 ../optimizer/optimized_params/strategy_params.db "SELECT * FROM strategy_parameters LIMIT 1;"`
4. Verify API endpoint: `curl http://localhost:9000/api/v1/tickers`

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
| `optimizer/nightly_optimizer.py` | Grid search + allocation-aware backtesting |
| `optimizer/parameter_optimizer.py` | Strategy indicators (MACD/SMA/BB) + allocation sizing |
| `optimizer/data_fetcher.py` | Alpaca API data fetching |
| `optimizer/db.py` | SQLite helper + reads allocation weights from Laravel |
| `optimizer/run_nightly.ps1` | Windows wrapper (called by Task Scheduler) |
| `optimizer/run_nightly.sh` | Linux wrapper (called by cron) |
| `backend/app/Console/Kernel.php` | Schedule definition (trade execution, equity snapshots, position sync) |
| `backend/app/Console/Commands/ExecuteDailyTrades.php` | Trade execution with allocation weighting |
| `backend/app/Console/Commands/RunNightlyOptimizer.php` | Manual optimizer trigger (artisan command) |
| `backend/app/Services/TradeExecutorService.php` | Signal generation + allocation-weighted order placement |
| `backend/app/Services/AlpacaService.php` | Alpaca API wrapper |
| `backend/app/Http/Controllers/TickerController.php` | GET /api/v1/tickers, PUT /api/v1/tickers/{symbol}/allocation |
| `backend/app/Http/Controllers/TradesController.php` | GET /api/v1/trades/pnl, GET /api/v1/trades/backtest |
| `scripts/setup-optimizer-wts.ps1` | Register nightly optimizer with Windows Task Scheduler |
| `scripts/setup-optimizer-cron.sh` | Register nightly optimizer with Linux cron |
| `frontend/src/App.svelte` | Dashboard main page + allocation controls |
| `frontend/src/api.js` | Axios wrapper for API calls |

---

## Manual Commands

### UI Trigger Buttons (Dashboard)

The dashboard includes two manual trigger buttons at the top for on-demand execution:

1. **⚙️ Trigger Optimizer** — Run nightly parameter optimization immediately
   - Displays "Running..." while executing
   - Shows success/error message below button
   - Auto-dismisses after 3 seconds
   - Calls `POST /api/v1/admin/optimize/trigger`

2. **📈 Execute Trades** — Run trade executor immediately
   - Displays "Executing..." while running
   - Shows success/error message below button
   - Auto-dismisses after 3 seconds
   - Calls `POST /api/v1/admin/trades/trigger`

**Use case:** Testing new parameters, manual trigger during emergencies, or verify system is working without waiting for scheduled times.

### Trigger Optimizer Now via CLI (Don't Wait for 2 AM)

```bash
cd backend
php artisan optimize:nightly
```

**View logs:**
```bash
tail -f ../optimizer/logs/nightly.log
```

### Update Ticker Allocation Weight

```bash
# Via API:
curl -X PUT http://localhost:9000/api/v1/tickers/SPY/allocation \
  -H "Content-Type: application/json" \
  -d '{"allocation_weight": 40}'

# Response: { "symbol": "SPY", "allocation_weight": 40, "message": "Allocation updated" }
```

### View Backtest Trades (from nightly optimizer)

```bash
curl http://localhost:9000/api/v1/trades/backtest
```

### View Live Trades (executed orders)

```bash
curl http://localhost:9000/api/v1/trades/pnl
```

### Inspect Database

```bash
sqlite3 "../optimizer/optimized_params/strategy_params.db"
.mode column
.headers on

-- View current strategy parameters with allocation weights
SELECT t.symbol, sp.macd_fast, sp.macd_slow, sp.sma_short, sp.sma_long, 
       sp.sharpe_ratio, t.allocation_weight, sp.updated_at
FROM strategy_parameters sp
JOIN tickers t ON sp.ticker_id = t.id;

-- View backtest trades with allocation details
SELECT t.symbol, bt.entry_date, bt.entry_price, bt.qty, bt.exit_price, 
       bt.pnl_dollar, bt.allocation_weight
FROM backtest_trades bt
JOIN tickers t ON bt.ticker_id = t.id
ORDER BY bt.entry_date DESC LIMIT 20;
```

### Clear Cache (If Dashboard Acts Weird)

```bash
php artisan config:clear
php artisan cache:clear
php artisan serve --host=127.0.0.1 --port=9000  # Restart backend
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

## Recent Updates (v1.1.0)

- **Allocation weights system** — Per-ticker capital allocation (default 33.33% for 3-way split)
- **OS-level scheduler** — Nightly optimizer runs via Windows Task Scheduler / cron, bypasses PHP 60s timeout
- **Backtest trades** — All optimizer-generated trades recorded with allocation details in database
- **Allocation API** — PUT `/api/v1/tickers/{symbol}/allocation` to update capital allocation
- **Dashboard enhancements** — View/edit allocation weights, inspect backtest trades side-by-side with live trades
- **Manual trigger buttons** — On-demand optimizer and trade executor execution from dashboard UI

---

**Last updated:** 2026-04-21  
**Version:** 1.1.0  
**Status:** Production-ready (paper trading)  
**Scheduler:** Windows Task Scheduler (WTS) or Linux cron  
**Broker:** Alpaca (paper trading)  
**Account Equity:** $100k (paper)
