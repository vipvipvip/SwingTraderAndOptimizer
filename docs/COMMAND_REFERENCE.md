# SwingTrader Command Reference

Complete documentation of all commands executed during the PostgreSQL migration and optimization setup.

---

## 1. Database Setup & Migrations

### Laravel Artisan Migrations
```bash
# Run all pending migrations
php artisan migrate --force

# Rollback and re-run all migrations
php artisan migrate:refresh --force
```

**Purpose:** Initialize database schema with Laravel migrations for tickers, bars, strategy_parameters, backtest_trades, optimization_history, and equity_snapshots tables.

---

## 2. Docker Operations

### Docker Compose Lifecycle
```bash
# Start PostgreSQL container
docker-compose up -d

# Stop and remove containers, prune volumes
docker-compose down
docker volume prune -f

# View running containers
docker ps
docker ps | grep postgres

# Copy data from Docker container to host
docker cp swingtrader-db:/var/lib/postgresql/data /path/to/backend/postgres_data
```

**Purpose:** Manage PostgreSQL Docker container, verify health, and persist data to host filesystem.

### Docker PostgreSQL Access
```bash
# Execute psql commands in running container
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "COMMAND"

# Execute multi-line SQL with heredoc
docker exec swingtrader-db psql -U swingtrader -d swingtrader << 'EOF'
  SQL_STATEMENTS
EOF
```

**Purpose:** Execute SQL queries against PostgreSQL database running in Docker container.

---

## 3. Data Fetching & Optimization

### Python Optimizer Execution
```bash
# Run nightly optimizer (blocks until complete)
python3 optimizer/nightly_optimizer.py 2>&1

# Run in background
python3 optimizer/nightly_optimizer.py 2>&1 &

# Run with Python interpreter
cd optimizer && python3 -c "from nightly_optimizer import run_nightly_optimization; run_nightly_optimization()"
```

**Purpose:** Execute parameter optimization and equity curve calculation for all tickers.

### Process Management
```bash
# Check running processes
pgrep -f "python3 optimizer/nightly_optimizer.py"
ps aux | grep -E "python|joblib" | grep -v grep

# Kill running optimizer
pkill -f "python3 optimizer/nightly_optimizer.py"
pkill -9 -f "python3 optimizer/nightly_optimizer.py"  # Force kill

# Monitor CPU usage of running processes
ps aux | grep "LokyProcess" | head -3 | awk '{print $3}' | paste -sd+ | bc
top -bn1 | grep -E "^%Cpu|python"
```

**Purpose:** Monitor and control background optimization processes.

---

## 4. Database Schema & Data Management

### Table Truncation & Cleanup
```bash
# Truncate specific tables
TRUNCATE strategy_parameters;
TRUNCATE backtest_trades;
TRUNCATE optimization_history;
TRUNCATE equity_snapshots CASCADE;
TRUNCATE intra_day_prices CASCADE;

# Delete specific records
DELETE FROM equity_snapshots WHERE snapshot_type = 'backtest';
DELETE FROM equity_snapshots WHERE ticker_id IS NULL;
```

**Purpose:** Clear old data to start fresh optimization runs with clean state.

### Sequence Management
```bash
# Reset sequences to start at 1
ALTER SEQUENCE strategy_parameters_id_seq RESTART WITH 1;
ALTER SEQUENCE backtest_trades_id_seq RESTART WITH 1;
ALTER SEQUENCE optimization_history_id_seq RESTART WITH 1;
ALTER SEQUENCE equity_snapshots_id_seq RESTART WITH 1;

# Reset tickers sequence to continue from 4 (after 3 existing tickers)
ALTER SEQUENCE tickers_id_seq RESTART WITH 4;

# View all sequences
SELECT * FROM pg_sequences WHERE schemaname = 'public';
```

**Purpose:** Ensure auto-increment IDs start at correct values after data truncation.

---

## 5. Data Inspection & Verification

### Table Record Counts
```bash
# Count records in all tables
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT 'table_name' as table_name, COUNT(*) as count FROM bars
UNION ALL
SELECT 'strategy_parameters', COUNT(*) FROM strategy_parameters
UNION ALL
SELECT 'backtest_trades', COUNT(*) FROM backtest_trades
UNION ALL
SELECT 'optimization_history', COUNT(*) FROM optimization_history
UNION ALL
SELECT 'equity_snapshots', COUNT(*) FROM equity_snapshots
UNION ALL
SELECT 'tickers', COUNT(*) FROM tickers
ORDER BY table_name;"

# Count by category
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT 'equity_snapshots' as table_name, COUNT(*) FROM equity_snapshots
UNION ALL
SELECT 'intra_day_prices', COUNT(*) FROM intra_day_prices
UNION ALL
SELECT 'positions_cache', COUNT(*) FROM positions_cache;"
```

**Purpose:** Verify data has been properly inserted and persisted.

### Strategy Parameters Details
```bash
# View best parameters for each ticker
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT symbol, macd_fast, macd_slow, sma_short, sma_long, bb_period, win_rate, sharpe_ratio, total_return
FROM strategy_parameters sp
JOIN tickers t ON sp.ticker_id = t.id
ORDER BY t.symbol;"

# View optimization history by ticker
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT COUNT(*) as total, symbol FROM optimization_history oh
JOIN tickers t ON oh.ticker_id = t.id
GROUP BY symbol ORDER BY symbol;"
```

**Purpose:** Review optimization results and backtesting metrics.

### Equity Snapshots
```bash
# Count equity snapshots by type and ticker
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT COUNT(*) as total, symbol, snapshot_type 
FROM equity_snapshots es 
JOIN tickers t ON es.ticker_id = t.id 
GROUP BY symbol, snapshot_type 
ORDER BY symbol;"

# View first few equity snapshots
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT * FROM equity_snapshots LIMIT 5;"
```

**Purpose:** Verify equity curve data points are saved correctly.

### Backtest Trades
```bash
# Count trades by ticker
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
SELECT 'backtest_trades' as table_name, COUNT(*) as count, symbol
FROM backtest_trades
GROUP BY symbol;"
```

**Purpose:** Verify backtest trade records are saved from optimization.

---

## 6. Data Seeding

### Seed Tickers via Tinker
```bash
# Interactive PHP artisan shell
php artisan tinker

# Within tinker:
$symbols = ['SPY', 'QQQ', 'IWM'];
foreach ($symbols as $symbol) {
    Ticker::updateOrCreate(
        ['symbol' => $symbol],
        ['enabled' => true, 'allocation_weight' => 10]
    );
}
```

**Purpose:** Insert initial ticker records for trading symbols.

---

## 7. File System Operations

### Directory Management
```bash
# List directories
ls -la /path/to/directory | grep -E "^d.*data"

# Find files
find /path -name "*.py" -type f | head -20
find backend -name "EquityService*" -type f

# Search file contents
grep -r "equity" optimizer/ backend/ --include="*.py" --include="*.php"
grep -n "equity_curve" optimizer/parameter_optimizer.py

# Delete directories
rm -rf /home/dikesh/data/dev/SwingTraderAndOptimizer/backend/data
```

**Purpose:** Navigate filesystem, locate code, and clean up old data folders.

---

## 8. Code Debugging & Inspection

### Python Error Checking
```bash
# Run Python script and capture output
python3 optimizer/nightly_optimizer.py 2>&1 | head -200

# Check Python imports
python3 -c "from nightly_optimizer import run_nightly_optimization"

# Remove stale SQLite imports
grep -n "import sqlite3" optimizer/fetch_prices.py
```

**Purpose:** Debug script execution and identify errors.

### View Optimizer Output
```bash
# Read background task output
tail -50 /tmp/claude-1000/.../tasks/bejtyqq71.output
tail -20 /tmp/claude-1000/.../tasks/bejtyqq71.output

# Check line count
wc -l /tmp/claude-1000/.../tasks/bejtyqq71.output
```

**Purpose:** Monitor optimizer progress and debug issues.

---

## 9. Git Operations

### Stage & Commit Changes
```bash
# Check git status
git status

# Stage migration files
git add backend/database/migrations/2026_04_17_000000_create_tickers_table.php
git add backend/database/migrations/2026_04_18_000000_create_bars_table.php
git add backend/database/migrations/2026_04_20_000000_create_strategy_parameters_table.php

# Create commit with message
git commit -m "fix: add missing database migrations for PostgreSQL setup"

# Push to remote
git push origin main
```

**Purpose:** Version control migrations and code changes.

---

## 10. Environment & Configuration

### View Configuration
```bash
# Check docker-compose.yml volume mounts
cat docker-compose.yml | grep -A5 "volumes:"

# Check Laravel database configuration
cat backend/config/database.php | grep -A10 "pgsql"

# Load environment variables
source backend/.env
cat backend/.env | grep ALPACA
```

**Purpose:** Verify configuration is correct for PostgreSQL and API keys.

---

## 11. Systemd Service Management

### Service Creation & Setup
```bash
# Create systemd service file (requires sudo)
sudo nano /etc/systemd/system/swingtrader-backend.service
sudo nano /etc/systemd/system/swingtrader-optimizer.service
sudo nano /etc/systemd/system/swingtrader-optimizer.timer

# Reload systemd daemon after creating/modifying services
sudo systemctl daemon-reload

# List all systemd services
sudo systemctl list-unit-files | grep swingtrader
systemctl list-timers
```

### Service Control
```bash
# Enable service (start on boot)
sudo systemctl enable swingtrader-backend
sudo systemctl enable swingtrader-optimizer.timer

# Disable service (don't start on boot)
sudo systemctl disable swingtrader-backend
sudo systemctl disable --now swingtrader-optimizer.timer

# Start service
sudo systemctl start swingtrader-backend
sudo systemctl start swingtrader-optimizer.service

# Stop service
sudo systemctl stop swingtrader-backend
sudo systemctl stop swingtrader-optimizer.timer

# Restart service
sudo systemctl restart swingtrader-backend

# Enable and start in one command
sudo systemctl enable --now swingtrader-backend
```

### Service Monitoring
```bash
# Check service status
sudo systemctl status swingtrader-backend
sudo systemctl status swingtrader-optimizer.timer
sudo systemctl status swingtrader-optimizer.service

# View service logs (last 50 lines)
journalctl -u swingtrader-backend -n 50

# Follow service logs in real-time
journalctl -u swingtrader-backend -f

# View logs with timestamps
journalctl -u swingtrader-backend --since "2 hours ago"

# List active timers
sudo systemctl list-timers --all

# Check if timer is active
sudo systemctl is-active swingtrader-optimizer.timer
```

### Service Troubleshooting
```bash
# Check if service is enabled
sudo systemctl is-enabled swingtrader-backend

# View service file
sudo cat /etc/systemd/system/swingtrader-backend.service
sudo cat /etc/systemd/system/swingtrader-optimizer.timer

# Show service dependencies
sudo systemctl list-dependencies swingtrader-backend

# Check for syntax errors in service file
sudo systemd-analyze verify /etc/systemd/system/swingtrader-backend.service
```

### Disabling Services
```bash
# Disable service without removing
sudo systemctl disable swingtrader-backend

# Stop triggered units (timer dependencies)
sudo systemctl stop swingtrader-optimizer.timer

# Check which services are triggering others
sudo systemctl list-units --all | grep swingtrader
```

**Purpose:** Manage system services for automatic startup and background operation of backend and optimizer.

---

## 12. Monitoring & Health Checks

### PostgreSQL Health
```bash
# Check container health
docker ps | grep postgres

# Verify connection
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT version();"

# List tables
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "\dt"
```

**Purpose:** Ensure database is running and accessible.

### Process Monitoring

#### Check if Process is Running
```bash
# Check if optimizer is running
pgrep -f "python3 optimizer/nightly_optimizer.py"

# Count processes
pgrep -f "nightly_optimizer" | wc -l

# List all Python processes
ps aux | grep "python3" | grep -v grep

# Find specific process by name
ps aux | grep "nightly_optimizer" | grep -v grep | awk '{print $2}' | head -1
```

#### Monitor CPU & Memory Usage
```bash
# Real-time top (non-interactive, show once)
top -bn1 | head -20

# Watch specific process
top -bn1 | grep "python3"

# Show CPU usage for LokyProcess workers
ps aux | grep "LokyProcess" | head -5 | awk '{print $3}' | paste -sd+ | bc

# Monitor joblib workers
ps aux | grep -E "joblib|LokyProcess" | grep -v grep
```

#### Monitor File Output
```bash
# Watch output file grow
wc -l /path/to/output.txt

# Tail output in real-time
tail -f /tmp/optimizer_full_output.txt

# Show last N lines
tail -100 /tmp/optimizer_full_output.txt

# Check file size
du -h /tmp/optimizer_full_output.txt
```

#### Monitor Database Changes During Execution
```bash
# Watch table row counts update
watch -n 5 'docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "
  SELECT COUNT(*) as strategy_params FROM strategy_parameters
  UNION ALL
  SELECT COUNT(*) FROM backtest_trades;"'

# Check single table count
docker exec swingtrader-db psql -U swingtrader -d swingtrader -t -c "
  SELECT COUNT(*) FROM strategy_parameters;"

# Monitor in loop with sleep
for i in {1..20}; do 
  count=$(docker exec swingtrader-db psql -U swingtrader -d swingtrader -t -c "SELECT COUNT(*) FROM strategy_parameters;" 2>/dev/null | tr -d ' ')
  echo "$(date): params=$count"
  sleep 30
done
```

#### Monitor Network/API Calls
```bash
# Track open connections
lsof -p $(pgrep -f "nightly_optimizer" | head -1)

# Monitor network activity
netstat -an | grep ESTABLISHED | wc -l

# Check for stalled processes
ps aux | grep "python3" | grep -v grep | awk '{if ($8 ~ /S/) print $0}'
```

#### Comprehensive Process Status
```bash
# Full process info
ps -ef | grep "nightly_optimizer"

# With time running
ps -o pid,user,etime,cmd | grep "nightly_optimizer"

# Check parent/child relationships
pstree -p $(pgrep -f "nightly_optimizer" | head -1)

# Process state and memory
ps -aux | grep "nightly_optimizer" | grep -v grep | awk '{
  printf "PID=%s USER=%s CPU=%s MEM=%s TIME=%s CMD=%s\n", $2, $1, $3, $4, $9, $11
}'
```

**Purpose:** Track long-running optimization jobs and debug performance issues.

### Background Task Monitoring
```bash
# Monitor running processes
pgrep -f "nightly_optimizer" | wc -l

# Check CPU usage
top -bn1 | head -20
ps aux | grep "python3" | grep -v grep
```

**Purpose:** Track long-running optimization jobs.

---

## Summary

| Category | Command Count | Purpose |
|----------|---------------|---------|
| Database Setup | 3 | Migration and schema initialization |
| Docker Operations | 8 | Container lifecycle and SQL execution |
| Data Fetching | 4 | Optimizer execution and monitoring |
| Schema & Data | 10 | Table management and sequence resets |
| Inspection & Verification | 12 | Data validation and review |
| Seeding | 2 | Initial data population |
| File System | 6 | Directory and file management |
| Debugging | 4 | Error detection and troubleshooting |
| Git | 5 | Version control operations |
| Configuration | 3 | Environment and settings verification |
| Health Checks | 4 | Monitoring and validation |

**Total Commands: ~60+**

---

## Key Command Patterns

### Database Inspection Pattern
```bash
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "QUERY"
```

### File Search Pattern
```bash
grep -r "PATTERN" /path --include="*.EXT"
find /path -name "PATTERN" -type f
```

### Process Monitoring Pattern
```bash
pgrep -f "PROCESS_NAME"
ps aux | grep "PROCESS_NAME" | grep -v grep
```

### Data Truncation Pattern
```bash
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "TRUNCATE table_name;"
```

---

Last Updated: 2026-04-29
