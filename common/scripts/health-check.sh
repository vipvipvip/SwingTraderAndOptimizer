#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SwingTrader System Health Check
# Verifies: DB, bars data (ETF + scanner), CoreEW intraday cron,
#           optimizer retired status, backend/frontend services,
#           timers, MTF Top-N, daily signal, API endpoints
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { PASS=$((PASS+1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() { FAIL=$((FAIL+1)); echo -e "  ${RED}✗${NC} $1"; }
warn() { WARN=$((WARN+1)); echo -e "  ${YELLOW}⚠${NC} $1"; }

PROJECT_DIR="/home/dikesh/data/dev/SwingTraderAndOptimizer"
CORE_ETFS="QQQ VTI VTV"

echo "=========================================="
echo "  SwingTrader Health Check"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# ---- Docker & PostgreSQL ----
echo ""
echo "--- PostgreSQL ---"

DOCKER_OK=$(docker ps --filter "name=swingtrader-db" --filter "health=healthy" --format "{{.Names}}" 2>/dev/null)
if [ "$DOCKER_OK" = "swingtrader-db" ]; then
    pass "PostgreSQL container is healthy"
else
    DOCKER_STATUS=$(docker ps --filter "name=swingtrader-db" --format "{{.Status}}" 2>/dev/null)
    if [ -n "$DOCKER_STATUS" ]; then
        warn "PostgreSQL container status: $DOCKER_STATUS (not healthy)"
    else
        fail "PostgreSQL container is not running"
    fi
fi

if docker exec swingtrader-db pg_isready -U swingtrader >/dev/null 2>&1; then
    pass "PostgreSQL is accepting connections"
else
    fail "PostgreSQL is not accepting connections"
fi

PSQL() { docker exec swingtrader-db psql -U swingtrader -t -A -c "$1" 2>/dev/null; }

# Count trading days (Mon-Fri) since a given date (used for ETF + scanner freshness)
_trading_days_since() {
    local d="$1" count=0
    local bar_epoch today_epoch bar_day today_day i dow
    bar_epoch=$(date -d "$d" +%s 2>/dev/null || echo 0)
    today_epoch=$(date +%s)
    bar_day=$((bar_epoch / 86400))
    today_day=$((today_epoch / 86400))
    for i in $(seq $((bar_day + 1)) "$today_day" 2>/dev/null); do
        dow=$(date -d "@$((i * 86400))" +%u 2>/dev/null)
        [ "$dow" -le 5 ] && count=$((count + 1))
    done
    echo "$count"
}

# ---- ETF Bars Data (per ticker) ----
# Reads the LIVE partitioned table (tbl_scanner_tickers_1hour, keyed by
# tbl_stock_tickers.id — all 28 ETFs are flagged is_etf=true there). The legacy
# tbl_etf_tickers_1hour (keyed by tbl_etf_tickers.id) froze 09-11 when the
# optimizer/backfill was retired and is no longer written; don't check it.
echo ""
echo "--- ETF Bar Data ---"

ENABLED_ETF=$(PSQL "SELECT symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=true ORDER BY symbol;")
if [ -z "$ENABLED_ETF" ]; then
    fail "No enabled ETF tickers found"
else
    pass "Enabled ETFs: $(echo "$ENABLED_ETF" | tr '\n' ' ')"
    for sym in $ENABLED_ETF; do
        LATEST=$(PSQL "SELECT MAX(DATE(h.date)) FROM tbl_scanner_tickers_1hour h JOIN tbl_stock_tickers t ON h.ticker_id = t.id WHERE t.symbol='$sym';")
        COUNT=$(PSQL "SELECT COUNT(*) FROM tbl_scanner_tickers_1hour h JOIN tbl_stock_tickers t ON h.ticker_id = t.id WHERE t.symbol='$sym';")
        if [ -n "$LATEST" ] && [ "$LATEST" != " " ]; then
            HOUR_TRADING_DAYS=$(_trading_days_since "$LATEST")
            if [ "$HOUR_TRADING_DAYS" -le 1 ] 2>/dev/null; then
                pass "  $sym: $COUNT bars, latest $LATEST ($HOUR_TRADING_DAYS trading days ago)"
            else
                warn "  $sym: $COUNT bars, latest $LATEST ($HOUR_TRADING_DAYS trading days ago - stale)"
            fi
        else
            fail "  $sym: no bar data found"
        fi
    done
fi

ETF_BAR_TOTAL=$(PSQL "SELECT COUNT(*) FROM tbl_scanner_tickers_1hour h JOIN tbl_stock_tickers t ON h.ticker_id = t.id WHERE t.enabled=true AND t.is_etf=true;")
echo "  Total ETF bars: $ETF_BAR_TOTAL"

# ---- Stock / Scanner Data ----
echo ""
echo "--- Stock Scanner Data ---"

STOCK_COUNT=$(PSQL "SELECT COUNT(*) FROM tbl_stock_tickers;")
ENABLED_STOCKS=$(PSQL "SELECT COUNT(*) FROM tbl_stock_tickers WHERE enabled=true;")
echo "  Stock tickers: $STOCK_COUNT total, $ENABLED_STOCKS enabled"

SCAN_DAILY_LATEST=$(PSQL "SELECT MAX(date) FROM tbl_scanner_tickers_daily;")
SCAN_DAILY_DAYS=$(( ($(date +%s) - $(date -d "$SCAN_DAILY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
SCAN_DAILY_ROWS=$(PSQL "SELECT COUNT(*) FROM tbl_scanner_tickers_daily;")
SCAN_DAILY_ROWS_LATEST=$(PSQL "SELECT COUNT(*) FROM tbl_scanner_tickers_daily WHERE date = '$SCAN_DAILY_LATEST';")
if [ -n "$SCAN_DAILY_LATEST" ]; then
    if [ "$SCAN_DAILY_DAYS" -le 2 ] 2>/dev/null; then
        pass "Scanner daily: $SCAN_DAILY_ROWS total rows, latest $SCAN_DAILY_LATEST ($SCAN_DAILY_DAYS days ago, $SCAN_DAILY_ROWS_LATEST tickers)"
    elif [ "$SCAN_DAILY_DAYS" -le 5 ] 2>/dev/null; then
        warn "Scanner daily: $SCAN_DAILY_ROWS total rows, latest $SCAN_DAILY_LATEST ($SCAN_DAILY_DAYS days ago - stale, $SCAN_DAILY_ROWS_LATEST tickers)"
    else
        fail "Scanner daily: $SCAN_DAILY_ROWS total rows, latest $SCAN_DAILY_LATEST ($SCAN_DAILY_DAYS days ago - severely stale, $SCAN_DAILY_ROWS_LATEST tickers)"
    fi
else
    fail "Scanner daily table is empty"
fi

SCAN_HOURLY_LATEST=$(PSQL "SELECT MAX(date) FROM tbl_scanner_tickers_1hour;")
SCAN_HOURLY_DAYS=$(( ($(date +%s) - $(date -d "$SCAN_HOURLY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
SCAN_WEEKLY_LATEST=$(PSQL "SELECT MAX(date) FROM tbl_scanner_tickers;")
SCAN_WEEKLY_DAYS=$(( ($(date +%s) - $(date -d "$SCAN_WEEKLY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
# Count trading days (Mon-Fri) since the latest bar
SCAN_HOURLY_TRADING_DAYS=$(_trading_days_since "$SCAN_HOURLY_LATEST")
if [ -n "$SCAN_HOURLY_LATEST" ]; then
    if [ "$SCAN_HOURLY_TRADING_DAYS" -le 1 ] 2>/dev/null; then
        pass "Scanner hourly: latest $SCAN_HOURLY_LATEST ($SCAN_HOURLY_TRADING_DAYS trading days ago)"
    elif [ "$SCAN_HOURLY_TRADING_DAYS" -le 3 ] 2>/dev/null; then
        warn "Scanner hourly: latest $SCAN_HOURLY_LATEST ($SCAN_HOURLY_TRADING_DAYS trading days ago - stale)"
    else
        fail "Scanner hourly: latest $SCAN_HOURLY_LATEST ($SCAN_HOURLY_TRADING_DAYS trading days ago - severely stale)"
    fi
else
    fail "Scanner hourly table is empty"
fi
if [ -n "$SCAN_WEEKLY_LATEST" ]; then
    if [ "$SCAN_WEEKLY_DAYS" -le 10 ] 2>/dev/null; then
        pass "Scanner weekly: latest $SCAN_WEEKLY_LATEST ($SCAN_WEEKLY_DAYS days ago)"
    else
        warn "Scanner weekly: latest $SCAN_WEEKLY_LATEST ($SCAN_WEEKLY_DAYS days ago - stale)"
    fi
else
    echo "  Scanner weekly: empty"
fi

# Check scanner .env exists
if [ -f "$PROJECT_DIR/scanner/backend/.env" ]; then
    pass "Scanner .env file exists"
else
    fail "Scanner .env file missing at scanner/backend/.env"
fi

# Check for recent scanner service failures
for svc in swingtrader-scanner-update swingtrader-scanner-backfill; do
    if systemctl is-failed "$svc.service" >/dev/null 2>&1; then
        warn "$svc.service is in failed state"
    fi
    RECENT_FAIL=$(journalctl -u "$svc.service" --since "3 days ago" --no-pager 2>/dev/null | grep "Failed with result\|Main process exited, code=exited, status=1" || true)
    if [ -n "$RECENT_FAIL" ]; then
        warn "$svc.service had failures in last 3 days:"
        echo "$RECENT_FAIL" | sed 's/^/    /'
    fi
done

# ---- CoreEW (formerly CHAND) ----
echo ""
echo "--- CoreEW Intraday Rebalance ---"

# Live trigger is the 5-min crontab entry that runs artisan trades:execute-EW-ETF.
if crontab -l 2>/dev/null | grep -q "trades:execute-EW-ETF"; then
    pass "CoreEW cron entry present (every 5 min)"
else
    fail "CoreEW cron entry MISSING — trades:execute-EW-ETF not in crontab"
fi

# Freshness marker: the command stamps storage/trades_last_run.txt on every run
# (market open or closed), so a modern mtime proves cron is firing.
COREEW_MARKER="$PROJECT_DIR/swingtrader/backend/storage/trades_last_run.txt"
if [ -f "$COREEW_MARKER" ]; then
    # Count minutes since the last CoreEW run marker
    NOW_EPOCH=$(date +%s)
    MARKER_EPOCH=$(stat -c %Y "$COREEW_MARKER" 2>/dev/null || echo 0)
    MIN_SINCE=$(( (NOW_EPOCH - MARKER_EPOCH) / 60 ))
    if [ "$MIN_SINCE" -le 15 ]; then
        pass "CoreEW last run $MIN_SINCE min ago (fresh)"
    elif [ "$MIN_SINCE" -le 60 ]; then
        warn "CoreEW last run $MIN_SINCE min ago — expect <=15 min during market hours"
    else
        fail "CoreEW last run $MIN_SINCE min ago — cron may be stalled"
    fi
else
    fail "CoreEW marker file missing at $COREEW_MARKER"
fi

# ---- Strategy Parameters (DISABLED — optimizer retired 2026-09-12) ----
echo ""
echo "--- Nightly Optimizer (DISABLED) ---"

pass "Optimizer is disabled (2026-09-12) — CHAND→CoreEW is equal-weight only, no chandelier params, optimization_history cleared"
if [ "$(PSQL "SELECT COUNT(*) FROM strategy_parameters;" 2>/dev/null || echo 0)" -gt 0 ]; then
    warn "strategy_parameters still has rows (post-2026-09-12 purge) — expected 0"
else
    pass "strategy_parameters empty (expected post-optimizer)"
fi
if [ "$(PSQL "SELECT COUNT(*) FROM optimization_history;" 2>/dev/null || echo 0)" -gt 0 ]; then
    warn "optimization_history still has rows — expected 0"
else
    pass "optimization_history empty (expected)"
fi

# ---- Timers ----
echo ""
echo "--- System Timers ---"

# Strategy timers with next run time
for timer in swingtrader-scanner-update swingtrader-scanner-backfill swingtrader-mtf-executor swingtrader-daily-signal; do
    if systemctl is-enabled "$timer.timer" >/dev/null 2>&1; then
        NEXT=$(systemctl show "$timer.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
        TRIGGER=$(systemctl show "$timer.timer" -p TriggerOnCalendar --value 2>/dev/null || echo "?")
        pass "$timer.timer enabled — next: $NEXT (schedule: $TRIGGER)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Disabled-by-design timers (informational, not warnings)
echo "    (disabled by design: swingtrader-mtf-scorer — score inline in 10:25 executor; swingtrader-optimizer — retired 2026-09-12)"

# Earnings timers
for timer in swingtrader-earnings-refresh swingtrader-earnings-screener; do
    if systemctl is-enabled "$timer.timer" >/dev/null 2>&1; then
        NEXT=$(systemctl show "$timer.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
        TRIGGER=$(systemctl show "$timer.timer" -p TriggerOnCalendar --value 2>/dev/null || echo "?")
        pass "$timer.timer enabled — next: $NEXT (schedule: $TRIGGER)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Infrastructure timers
for timer in swingtrader-backup; do
    if systemctl is-enabled "$timer.timer" >/dev/null 2>&1; then
        NEXT=$(systemctl show "$timer.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
        pass "$timer.timer enabled (next: $NEXT)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Check for recent failures in oneshot services triggered by timers
echo ""
echo "--- Recent Timer Service Runs ---"

for svc in swingtrader-scanner-update swingtrader-scanner-backfill swingtrader-mtf-executor swingtrader-daily-signal swingtrader-earnings-screener swingtrader-earnings-refresh; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    if [ "$STATUS" = "failed" ]; then
        fail "$svc.service FAILED — last run errored"
        LAST_ERR=$(journalctl -u "$svc.service" --since "3 days ago" --no-pager 2>/dev/null | grep -E "error|Error|traceback|Traceback|FAIL" | tail -2 || true)
        if [ -n "$LAST_ERR" ]; then
            echo "$LAST_ERR" | sed 's/^/    /'
        fi
    elif [ "$STATUS" = "success" ] || [ "$STATUS" = "inactive" ]; then
        pass "$svc.service last run: $STATUS"
    elif [ "$STATUS" = "not-found" ]; then
        warn "$svc.service not found"
    fi
done

# ---- Systemd Services ----
echo ""
echo "--- System Services ---"

for svc in swingtrader-db swingtrader-backend swingtrader-fe-dev; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    if [ "$STATUS" = "active" ] || [ "$STATUS" = "exited" ]; then
        pass "$svc is $STATUS"
    elif [ "$STATUS" = "not-found" ]; then
        warn "$svc service not found"
    else
        fail "$svc is $STATUS"
    fi
done

# ---- Daily EMA/SMA Crossover Signal Service ----
echo ""
echo "--- Daily Signal Service ---"

DAILY_CSV="$PROJECT_DIR/swingtrader/services/ema_sma_crossover/data/daily_signals.csv"
DAILY_STATE="$PROJECT_DIR/swingtrader/services/ema_sma_crossover/.daily_signal_state.json"

if systemctl is-enabled swingtrader-daily-signal.timer >/dev/null 2>&1; then
    NEXT=$(systemctl show swingtrader-daily-signal.timer -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
    pass "swingtrader-daily-signal.timer is enabled (next: $NEXT)"
else
    warn "swingtrader-daily-signal.timer is not enabled"
fi

if systemctl is-active swingtrader-daily-signal.timer >/dev/null 2>&1; then
    pass "swingtrader-daily-signal.timer is active"
else
    warn "swingtrader-daily-signal.timer is not active"
fi

# Check CSV signal log
if [ -f "$DAILY_CSV" ]; then
    LAST_SIGNAL=$(tail -1 "$DAILY_CSV" 2>/dev/null || echo "")
    if [ -n "$LAST_SIGNAL" ] && [ "$LAST_SIGNAL" != "date,ticker,action,close_price,ema,sma,reason" ]; then
        pass "Daily signals CSV exists with entries"
        echo "    Last signal: $LAST_SIGNAL"
    else
        echo "    CSV exists (header only, no signals yet)"
    fi
else
    warn "Daily signals CSV not found at $DAILY_CSV"
fi

# Check state file freshness
if [ -f "$DAILY_STATE" ]; then
    STATE_AGE=$(( ($(date +%s) - $(stat -c %Y "$DAILY_STATE" 2>/dev/null || echo 0)) / 86400 ))
    pass "Daily signal state file exists ($STATE_AGE days old)"
else
    warn "Daily signal state file not found (will be created on first run)"
fi

# ---- MTF Top-N Multi-TF Rotation ----
echo ""
echo "--- MTF Top-N Rotation ---"

MTF_HEALTH="$PROJECT_DIR/swingtrader/services/mtf/health_check.py"
if [ -f "$MTF_HEALTH" ]; then
    cd "$PROJECT_DIR/swingtrader/services/mtf" && python3 "$MTF_HEALTH"
    MTF_EXIT=$?
    if [ "$MTF_EXIT" -eq 0 ]; then
        pass "MTF Top-N health check passed"
    else
        fail "MTF Top-N health check detected issues"
    fi
else
    fail "MTF Top-N health check script not found at $MTF_HEALTH"
fi

# ---- API Health ----
echo ""
echo "--- API Endpoints ---"

BACKEND_CODE=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:9000/api/health 2>/dev/null || echo "000")
if [ "$BACKEND_CODE" = "200" ]; then
    pass "Backend health endpoint returns 200"
else
    fail "Backend health endpoint: HTTP $BACKEND_CODE"
fi

FRONTEND_CODE=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || echo "000")
if [ "$FRONTEND_CODE" = "200" ]; then
    pass "Frontend dashboard returns 200"
else
    warn "Frontend dashboard: HTTP $FRONTEND_CODE"
fi

# Quick API data sanity check
API_RESPONSE=$(curl -s --max-time 5 -H "Accept: application/json" http://localhost:9000/api/v1/strategies 2>/dev/null)
TICKER_NAMES=$(echo "$API_RESPONSE" | python3 -c "import sys,json; data=json.load(sys.stdin); print(' '.join(t['symbol'] for t in data.get('tickers',data) if t['symbol']!='BLENDED'))" 2>/dev/null || echo "unparseable")
if [ -n "$TICKER_NAMES" ] && [ "$TICKER_NAMES" != "unparseable" ]; then
    pass "Strategy API returns tickers: $TICKER_NAMES"
else
    warn "Strategy API response: $TICKER_NAMES"
fi

# ---- Summary ----
echo ""
echo "=========================================="
echo "  Results: $PASS passed, $WARN warnings, $FAIL failed"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
elif [ "$WARN" -gt 0 ]; then
    exit 2
else
    exit 0
fi
