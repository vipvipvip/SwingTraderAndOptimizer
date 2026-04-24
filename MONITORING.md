# Daily Monitoring Guide

Daily operations checklist to ensure the trading system runs smoothly and on schedule.

---

## Quick Daily Check (2 minutes)

Run this every morning to verify overnight optimizer run:

```bash
./scripts/daily-check.sh
```

Or manually:
```bash
tail -5 optimizer/logs/nightly.log
curl http://localhost:9000/api/v1/tickers | jq '.[0].params.updated_at'
curl http://localhost:9000/api/v1/trades/pnl | jq '{trades: (.recent_trades | length), return: .total_return}'
```

---

## Detailed Daily Schedule

### 🌙 Morning Check (After 2:00 AM UTC / 10:00 PM ET Previous Day)

**Nightly Optimizer Should Have Run**

```bash
# 1. Check optimizer completed successfully
tail -100 optimizer/logs/nightly.log | tail -5

# Expected output:
# [2026-04-21 02:26:12] Nightly optimizer starting...
# [2026-04-21 03:54:33] Optimizer finished (exit: 0)

# 2. Verify all 3 tickers updated
curl http://localhost:9000/api/v1/tickers | jq '.[].params | {symbol: input.symbol, updated_at, sharpe: sharpe_ratio}'

# 3. Check for errors in Laravel logs
tail -50 backend/storage/logs/laravel.log | grep -i "error\|exception" | head -10
```

**If optimizer didn't run:**
- Check WTS task status: `schtasks query /tn "SwingTrader-NightlyOptimizer"`
- Check cron logs (Linux): `grep CRON /var/log/syslog | tail -20`
- View full optimizer log: `tail -500 optimizer/logs/nightly.log`
- Common issues:
  - Python path incorrect in Task Scheduler
  - Virtual environment not activated
  - Alpaca API credentials invalid
  - Database locked

---

### 📈 During Market Hours (9:30-16:00 ET, Weekdays Only)

**Trade Executor Should Run Every 30 Minutes**

```bash
# 1. Check latest trade execution
tail -20 backend/storage/logs/laravel.log | grep "ExecuteDailyTrades"

# Expected: Every ~30 minutes during market hours

# 2. View current account equity
curl http://localhost:9000/api/v1/account | jq '{
  equity: .equity,
  buying_power: .buying_power,
  cash: .cash,
  timestamp: now | todate
}'

# 3. Check if positions are open
curl http://localhost:9000/api/v1/trades/pnl | jq '{
  recent_trades: (.recent_trades | length),
  open_positions: .positions | length,
  today_return: .total_return
}'

# 4. Verify positions are synced every 5 minutes
grep "PositionsSync" backend/storage/logs/laravel.log | tail -3
# Should see recent entries during market hours
```

**If no trades during market hours:**
- Is market actually open? Check: `curl -s https://paper-api.alpaca.markets/v2/clock | jq .is_open`
- Check trade signals: `curl http://localhost:9000/api/v1/equity/SPY | jq '.signal'`
- Verify Laravel scheduler is running: Check `SwingTrader-LaravelScheduler` WTS task
- Check for database locks: `tail -50 backend/storage/logs/laravel.log | grep -i "locked\|error"`

---

### 📊 End of Day (After 4:00 PM ET)

**Daily Snapshot & Trade Summary**

```bash
# 1. Check equity snapshot was recorded
curl http://localhost:9000/api/v1/equity/SPY | jq '.daily_snapshots[-1]'

# 2. Today's P&L summary
curl http://localhost:9000/api/v1/trades/pnl | jq '{
  total_return: .total_return,
  win_rate: .win_rate,
  sharpe: .sharpe_ratio,
  trades_today: (.recent_trades | map(select(.entry_date | startswith(now | todate))) | length)
}'

# 3. Check all tickers' current parameters
curl http://localhost:9000/api/v1/tickers | jq '.[] | {
  symbol,
  allocation_weight,
  sharpe: .params.sharpe_ratio,
  win_rate: .params.win_rate
}'
```

---

## Critical Alerts

### 🚨 IMMEDIATE ACTION REQUIRED

| Alert | Check Command | Likely Cause | Action |
|-------|---|---|---|
| **No trades executed** | `curl .../trades/pnl \| jq '.recent_trades \| length'` equals 0 | Market closed? Signals not firing? | Verify market open. Check Alpaca status. Inspect signal generation. |
| **Optimizer failed** | `tail optimizer/logs/nightly.log \| grep -i error` | Python crash, API timeout, DB locked | Check full log. Verify Alpaca credentials. Restart optimizer manually. |
| **Parameters not updated** | `curl .../tickers \| jq '.[0].params.updated_at'` older than 24h | Optimizer didn't complete | Check WTS/cron task. Run `php artisan optimize:nightly` manually. |
| **Negative equity** | `curl .../account \| jq '.equity'` less than $100k | Losses exceeded allocation | Review allocation weights. Check for stuck positions. Verify stop-loss logic. |
| **High error rate** | `grep ERROR backend/storage/logs/laravel.log \| wc -l` more than 10 | API timeouts, DB issues, race conditions | Check Alpaca API status. Restart services. Check database integrity. |
| **Scheduler stopped** | `schtasks query /tn "SwingTrader-LaravelScheduler" \| grep State` shows "Disabled" | Manual intervention, crash | Re-register task: `scripts/setup-optimizer-wts.ps1` |

---

## Weekly Review (Every Friday)

```bash
# 1. Win rate trend (should stay 70%+)
curl http://localhost:9000/api/v1/trades/pnl | jq '.win_rate'

# 2. Sharpe ratio per ticker (should be 15+)
curl http://localhost:9000/api/v1/tickers | jq '.[] | {symbol, sharpe: .params.sharpe_ratio}'

# 3. Cumulative P&L
curl http://localhost:9000/api/v1/trades/pnl | jq '.total_return'

# 4. Allocation weight review
curl http://localhost:9000/api/v1/tickers | jq '.[] | {symbol, allocation: .allocation_weight}'

# 5. Recent backtest trades quality
curl http://localhost:9000/api/v1/trades/backtest | jq '[limit(10; .[]) | {symbol, pnl_dollar, allocation_weight}]'
```

**If performance drops below thresholds:**
- Manually run optimizer: `cd backend && php artisan optimize:nightly`
- Review and adjust allocation weights
- Check for market regime changes (volatility spikes, trends)

---

## Automated Daily Summary Script

Instead of manual checks, run the automated script:

```bash
./scripts/daily-check.sh
```

This outputs:
```
=== NIGHTLY OPTIMIZER ===
Last run: 2026-04-21 02:26:12
Status: SUCCESS

=== TICKERS ===
SPY: Sharpe=21.97, Allocation=33.33%
QQQ: Sharpe=17.20, Allocation=33.33%
IWM: Sharpe=23.72, Allocation=33.33%

=== TRADES (TODAY) ===
Executed: 5 trades
Win Rate: 80%
Total Return: 2.45%

=== ACCOUNT ===
Equity: $102,450
Buying Power: $204,900
```

### Schedule the script via cron (Linux/Mac):

```bash
crontab -e

# Add this line (runs at 7 AM ET daily)
0 11 * * * /path/to/SwingTraderAndOptimizer/scripts/daily-check.sh >> /tmp/trading-check.log 2>&1
```

### Or Windows Task Scheduler:

```powershell
# Run as Administrator
$Action = New-ScheduledTaskAction -Execute "pwsh.exe" -Argument "-File C:\path\to\scripts\daily-check.ps1"
$Trigger = New-ScheduledTaskTrigger -Daily -At "07:00"
Register-ScheduledTask -TaskName "SwingTrader-DailyCheck" -Action $Action -Trigger $Trigger
```

---

## Log File Locations

| Log | Path | Purpose |
|-----|------|---------|
| **Optimizer** | `optimizer/logs/nightly.log` | Nightly parameter optimization (Python) |
| **Laravel** | `backend/storage/logs/laravel.log` | Trade executor, equity snapshots, position sync (PHP) |
| **Daily Check** | `/tmp/trading-check.log` (Linux) or `C:\Temp\trading-check.log` (Windows) | Daily monitoring script output |

---

## Troubleshooting Guide

### Optimizer Doesn't Run at 2 AM

**Windows (Task Scheduler):**
```powershell
# Check task is registered
schtasks query /tn "SwingTrader-NightlyOptimizer" /v

# Check for errors
Get-ScheduledTask -TaskName "SwingTrader-NightlyOptimizer" | Get-ScheduledTaskInfo

# Re-register if needed
cd C:\path\to\SwingTraderAndOptimizer\scripts
.\setup-optimizer-wts.ps1
```

**Linux (Cron):**
```bash
# Check cron entry
crontab -l | grep run_nightly

# Check cron logs
grep CRON /var/log/syslog | tail -20

# Re-register if needed
cd /path/to/SwingTraderAndOptimizer/scripts
./setup-optimizer-cron.sh
```

### Trades Not Executing During Market Hours

```bash
# 1. Verify market is open
curl -s https://paper-api.alpaca.markets/v2/clock | jq '{is_open, next_open, next_close}'

# 2. Check Laravel scheduler is running
schtasks query /tn "SwingTrader-LaravelScheduler" /v | grep State

# 3. Verify Alpaca credentials
curl -H "Authorization: Bearer $(grep ALPACA_API_KEY backend/.env | cut -d= -f2)" \
  https://paper-api.alpaca.markets/v2/account | jq '.status'

# 4. Check for database locks
fuser ../optimizer/optimized_params/strategy_params.db 2>/dev/null || echo "Database not locked"

# 5. Restart services
php artisan serve --port=9000 &
cd ../frontend && npm run dev &
```

### Optimizer Takes Too Long (>120 minutes)

```bash
# Check which ticker is slow
tail -100 optimizer/logs/nightly.log | grep "\[SPY\]\|\[QQQ\]\|\[IWM\]"

# Manual run with progress output
cd optimizer
source venv/Scripts/activate  # Windows
python nightly_optimizer.py --tickers SPY --timeframe 1Hour --verbose
```

### Dashboard Shows Stale Data

```bash
# Clear all caches
php artisan config:clear
php artisan cache:clear

# Restart backend
php artisan serve --port=9000

# Hard refresh frontend (Ctrl+Shift+R in browser)
```

---

## Contact Points

If something goes wrong:
1. **Check logs first** — 90% of issues are in the logs
2. **Run daily-check.sh** — Narrows down the problem quickly
3. **Verify market hours** — Many false alarms are weekends/holidays
4. **Check Alpaca status** — Sometimes API goes down, not your system
5. **Restart services** — Config caching causes 10% of issues

---

**Last updated:** 2026-04-21  
**Version:** 1.1.0
