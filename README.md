# SwingTraderAndOptimizer v7.5+

A full-stack algorithmic swing trading system using a **Chandelier Exit** strategy with nightly parameter optimization and live trading dashboard.

**Status:** Production-ready (paper trading). Live signals every minute during market hours (9:30 AM - 4:00 PM ET). Nightly optimizer runs daily at 2:00 AM ET via systemd timer.

---

## What It Does

### 1. **Live Trade Execution** (Every minute during market hours)
- Evaluates each ticker independently (SPY, QQQ, IWM)
- Generates buy/sell signals using **Chandelier Exit** (always-long, trailing stop)
- Places orders with per-ticker allocation weights (SPY 40%, QQQ 45%, IWM 15%)
- Records all trades with entry/exit prices, P&L, and allocation details

### 2. **Chandelier Exit Signal Logic**
**Entry (always re-enter when flat):**
- No open position → BUY on next bar
- Exception: skip re-entry if exited same day (matches daily backtest)

**Exit (trailing stop from highest high):**
- `stop_level = highest_high_since_entry - ATR(period) × multiplier`
- SELL when close < stop_level

### 3. **Nightly Parameter Optimization** (2:00 AM ET daily via systemd timer)
- Tests Chandelier parameters: period=[14,20,26], multiplier=[1.8,2.0,2.2]
- Grid search over 9 combinations per ticker
- Backtests against 2 years of hourly data
- Saves best candidate and promotes if return AND Sharpe improve
- Returns: +8-15% on SPY/QQQ, Sharpe 3.0+ across all tickers

### 4. **Web Dashboard** (Real-time)
- Account equity, buying power, cash
- Strategy parameters and metrics (win rate, Sharpe, total return)
- Live Positions table with profit summary and allocation %
- Equity curves (backtest vs. live overlay)
- Trade history (closed trades only)
- Manual trigger buttons for optimizer and trade executor

---

## Strategy Details (v7.5)

### Chandelier Exit Parameters (Optimized Nightly)
```
Period:     [14, 20, 26]    (ATR lookback window)
Multiplier: [1.8, 2.0, 2.2] (stop distance in ATR units)
9 combinations tested per nightly run
```

### Entry Logic
```
When flat for SPY:
  → BUY at next bar open (always re-enter, unless exited today)
```

### Exit Logic
```
In position for SPY:
  highest_high = max(high since entry)
  stop = highest_high - ATR(period) × multiplier
  if close < stop → SELL at next bar open
```

### Performance
- SPY: 8.91% return, 3.05 Sharpe, ~12 trades
- QQQ: 15.63% return, 3.00 Sharpe, ~8 trades  
- IWM: 3.18% return, 3.13 Sharpe, ~6 trades

---

## Quick Start

### 1. Prerequisites
- **Ubuntu 20.04+** or similar Linux
- **PHP 8.2+** (Laravel 12)
- **PostgreSQL 14+**
- **Python 3.9+** with venv
- **Node.js 18+** (frontend)
- **Git** (optional)

### 2. Clone & Install
```bash
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer

# Python optimizer
cd optimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Laravel backend
cd ../backend
composer install
cp .env.example .env
php artisan key:generate
php artisan migrate --force

# Svelte frontend
cd ../frontend
npm install
```

### 3. Configure .env Files
**optimizer/.env:**
```bash
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_TIMEFRAME=1Hour
DATABASE_URL=postgresql://swingtrader:password@127.0.0.1/swingtrader
```

**backend/.env:**
```bash
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
DB_CONNECTION=pgsql
DB_HOST=127.0.0.1
DB_DATABASE=swingtrader
DB_USERNAME=swingtrader
DB_PASSWORD=password
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...  # optional
```

### 4. Set Up Systemd Services

**Trade Executor (runs every minute):**
```bash
sudo tee /etc/systemd/system/swingtrader-backend.service > /dev/null << 'EOF'
[Unit]
Description=SwingTrader Laravel Backend
After=network.target

[Service]
Type=simple
User=dikesh
WorkingDirectory=/home/dikesh/data/dev/SwingTraderAndOptimizer/backend
ExecStart=/usr/bin/php artisan serve --host=0.0.0.0 --port=9000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable swingtrader-backend
sudo systemctl start swingtrader-backend
```

**Nightly Optimizer (runs at 2:00 AM):**
```bash
sudo tee /etc/systemd/system/swingtrader-optimizer.service > /dev/null << 'EOF'
[Unit]
Description=SwingTrader Nightly Optimizer
After=network.target

[Service]
Type=oneshot
User=dikesh
WorkingDirectory=/home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer
ExecStart=/bin/bash /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/run_nightly.sh

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/swingtrader-optimizer.timer > /dev/null << 'EOF'
[Unit]
Description=SwingTrader Nightly Optimizer Timer
Requires=swingtrader-optimizer.service

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable swingtrader-optimizer.timer
sudo systemctl start swingtrader-optimizer.timer
```

### 5. Run the Application

**Terminal 1 — Backend (already systemd):**
```bash
sudo systemctl status swingtrader-backend
sudo journalctl -u swingtrader-backend -f
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
# Runs on http://localhost:5173
```

**Terminal 3 (optional) — Monitor logs:**
```bash
tail -f /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/logs/nightly.log
```

---

## Architecture

### Trade Execution Loop (Every minute, market hours)
```
1. Executor fetches latest Alpaca bars + quotes
2. For each ticker independently:
   a) Load strategy parameters (chandelier period + multiplier)
   b) If in position: compute ATR, trailing stop from highest high
      If close < stop_level → SELL
   c) If flat → BUY (always re-enter, unless exited today)
   d) Calculate order size: (equity × allocation_weight%) / price
   e) Place market order via Alpaca
   f) Record trade to database
3. Dashboard refreshes every 60 seconds
```

### Nightly Optimization (2:00 AM daily)
```
1. Fetch 2 years of hourly bars for each ticker
2. Grid search: 9 Chandelier period × multiplier combinations
3. For each combo, backtest on full 2-year history
4. Rank by Sharpe ratio
5. Save best candidate, run portfolio coordinate ascent over tickers
6. Promote if both return AND Sharpe improve over baseline
```

---

## Database Schema (PostgreSQL)

```sql
tickers
├─ id, symbol, allocation_weight (40/45/15 for SPY/QQQ/IWM)
│  enabled, created_at

bars (hourly OHLCV from Alpaca)
├─ id, ticker_id, timestamp, open, high, low, close, volume
│  6000-10000 rows per ticker

strategy_parameters
├─ id, ticker_id
├─ macd_fast (chandelier period: 14-26), bb_std (chandelier mult: 1.8-2.2)
├─ bb_period (ATR period, same as chandelier period)
├─ win_rate, sharpe_ratio, total_return, total_trades
├─ base_case (true for production, false for candidates)
│  Only 1 row per ticker with base_case=true
│  Best candidate from nightly has base_case=false (updated nightly)

backtest_trades (from nightly optimization)
├─ id, ticker_id, entry_at, entry_price, exit_at, exit_price
├─ return (pct), pnl_dollar, days_held

live_trades (executed orders)
├─ id, ticker_id, entry_at, entry_price, qty
├─ exit_at (null if open), exit_price, return, pnl_dollar

equity_snapshots
├─ id, ticker_id, snapshot_date, equity_value
├─ snapshot_type ('backtest' or 'live')

optimization_history
├─ id, ticker_id, run_date, best_sharpe, best_return
├─ total_combinations, runtime_seconds
```

---

## Key Components

### Python Optimizer (`optimizer/nightly_optimizer.py`)
- Loads 2 years of hourly bars per ticker
- Tests 9 Chandelier (period × multiplier) combinations
- Runs full backtest with allocation-aware position sizing
- Portfolio coordinate ascent across tickers for blended Sharpe
- Saves best candidate, promotes if return + Sharpe improve
- ~20-30 minutes runtime total

### Laravel Backend (`backend/`)
**Trade Executor Service:**
- Runs every minute via `php artisan schedule:run`
- Computes Chandelier Exit signals independently per ticker
- Places orders with allocation-weighted position sizing
- Records trades with entry/exit prices, P&L

**API Endpoints:**
- `GET /api/v1/account` — Account balance from Alpaca
- `GET /api/v1/account/positions` — Current open positions
- `GET /api/v1/strategies` — Strategy parameters + metrics (Chandelier period/mult)
- `GET /api/v1/trades/pnl` — Live trades with P&L
- `GET /api/v1/equity/{symbol}` — Equity curves
- `POST /api/v1/admin/trades/trigger` — Execute trades now
- `POST /api/v1/admin/optimize/trigger` — Optimize now

### Svelte Frontend (`frontend/`)
**Features:**
- Real-time account balance + buying power
- Strategy cards with parameters and metrics
- Live Positions table with:
  - Current P&L (in $ and %)
  - Allocation % per position
- Equity curves (backtest vs. live)
- Trade history (closed trades)
- Manual control buttons

---

## Allocation Weights

Each ticker has a fixed allocation weight (% of account equity to risk per trade):

```
SPY: 40%
QQQ: 45%
IWM: 15%
Total: 100%
```

**Order sizing formula:**
```
shares = (account_equity × allocation_weight%) / entry_price
```

Example: With $100k equity and SPY signal:
```
SPY allocation: 40% × $100k = $40k
At SPY $150/share: 40000 / 150 = ~266 shares
```

---

## Troubleshooting

### Executor not placing trades
```bash
# Check if backend is running
sudo systemctl status swingtrader-backend

# Check logs
sudo journalctl -u swingtrader-backend -f

# Is it market hours? (9:30-16:00 ET, weekdays)
# Is the market actually open?
curl https://paper-api.alpaca.markets/v2/clock -H "Authorization: Bearer $KEY"
```

### Optimizer failed to run
```bash
# Check timer is enabled
sudo systemctl list-timers swingtrader-optimizer.timer

# Check logs
tail -f /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/logs/nightly.log

# Manually test
cd optimizer
source venv/bin/activate
python nightly_optimizer.py --tickers SPY QQQ IWM
```

### Dashboard shows no positions
```bash
# Check Alpaca account has live positions
curl https://paper-api.alpaca.markets/v2/positions \
  -H "Authorization: Bearer $KEY"

# Check database has positions recorded
psql -U swingtrader -d swingtrader -c "SELECT * FROM backtest_trades LIMIT 5;"
```

---

## Performance Tips

1. **Check system resources during nightly run** (2:00 AM)
   - Optimizer uses all CPU cores (joblib parallel)
   - ~20-30 minutes total for 3 tickers

2. **Monitor Alpaca API rate limits**
   - Trade executor: 1 call/min per ticker
   - Nightly optimizer: ~100 calls during 2-hour window
   - Should be well under Alpaca's 200 calls/min limit

3. **PostgreSQL backups**
   - Daily equity snapshots accumulate
   - Clean old data if needed: 
     ```sql
     DELETE FROM equity_snapshots 
     WHERE snapshot_date < NOW() - INTERVAL '1 year';
     ```

---

## Version History

**v7.5 (2026-05-09)**
- Replaced 2-of-4 multi-indicator logic with pure Chandelier Exit strategy
- Updated README to reflect actual deployed strategy
- Fixed OrderController parameter swap bug
- Fixed days_held /7 divisor in optimizer (daily data)
- Aligned cost model between individual and portfolio backtests
- Skipped BLENDED ticker in trade execution
- Fixed EMA `adjust` inconsistency and BB std ddof

**v7.0 (2026-05-06)**
- Initial Chandelier Exit implementation
- Added profit summary to Live Positions title
- Added allocation % column to Live Positions table
- Limited strategy_parameters candidates (best per run only)
- Fixed allocation weight loading in backtest validation
- Trade executor generating ~12 trades per ticker, Sharpe 3.0+

**v6.0** — Fixed Alpaca API reliability (timeout + retry logic)

**v5.0** — Equity curves fixed, PostgreSQL migration complete

---

## Support & Documentation

- Signal logic details: See `backend/app/Services/TradeExecutorService.php:computeChandelierSignal()`
- Parameter optimization: See `optimizer/parameter_optimizer.py:optimize()`
- Database: See `backend/database/migrations/`
- Dashboard: See `frontend/src/App.svelte`

---

**Last Updated:** 2026-05-09  
**Current Version:** v7.5  
**Status:** Production (paper trading)  
**Scheduler:** systemd (backend service + optimizer timer)  
**Database:** PostgreSQL  
**Broker:** Alpaca (paper)
