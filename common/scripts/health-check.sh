#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SwingTrader System Health Check
# Verifies: DB, bars data (ETF + scanner), CoreEW LegEMA timer,
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

# ---- ETF universe ----
echo ""
echo "--- ETF Universe ---"

ENABLED_ETF=$(PSQL "SELECT symbol FROM tbl_stock_tickers WHERE enabled=true AND is_etf=true ORDER BY symbol;")
if [ -z "$ENABLED_ETF" ]; then
    fail "No enabled ETF tickers found"
else
    pass "Enabled ETFs: $(echo "$ENABLED_ETF" | tr '\n' ' ')"
fi

# ---- Stock / Scanner Data ----
echo ""
echo "--- Stock Scanner Data ---"

STOCK_COUNT=$(PSQL "SELECT COUNT(*) FROM tbl_stock_tickers;")
ENABLED_STOCKS=$(PSQL "SELECT COUNT(*) FROM tbl_stock_tickers WHERE enabled=true;")
echo "  Stock tickers: $STOCK_COUNT total, $ENABLED_STOCKS enabled"

SCAN_DAILY_LATEST=$(PSQL "SELECT MAX(date) FROM tbl_prices_daily;")
SCAN_DAILY_DAYS=$(( ($(date +%s) - $(date -d "$SCAN_DAILY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
SCAN_DAILY_ROWS=$(PSQL "SELECT COUNT(*) FROM tbl_prices_daily;")
SCAN_DAILY_ROWS_LATEST=$(PSQL "SELECT COUNT(*) FROM tbl_prices_daily WHERE date = '$SCAN_DAILY_LATEST';")
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

SCAN_WEEKLY_LATEST=$(PSQL "SELECT MAX(date) FROM tbl_prices_weekly;")
SCAN_WEEKLY_DAYS=$(( ($(date +%s) - $(date -d "$SCAN_WEEKLY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
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

# Summarize a timer's OnCalendar entries (this systemd exposes TimersCalendar,
# not the older TriggerOnCalendar). Multi-entry timers collapse to "first (+N)".
timer_schedule() {
    local entries first n
    entries=$(systemctl show "$1" -p TimersCalendar --value 2>/dev/null | grep -o 'OnCalendar=[^;]*' | sed 's/[[:space:]]*$//' || true)
    if [ -z "$entries" ]; then
        echo "?"
    else
        first=$(echo "$entries" | head -1)
        n=$(echo "$entries" | grep -c . || true)
        if [ "$n" -gt 1 ]; then
            echo "$first (+$((n - 1)) more)"
        else
            echo "$first"
        fi
    fi
}

# ---- CoreEW (formerly CHAND) — live path is the LegEMA P20w systemd timer ----
echo ""
echo "--- CoreEW LegEMA (P20w) ---"

if systemctl is-enabled swingtrader-legema.timer >/dev/null 2>&1; then
    NEXT=$(systemctl show swingtrader-legema.timer -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
    TRIGGER=$(timer_schedule swingtrader-legema.timer)
    pass "swingtrader-legema.timer enabled — next: $NEXT (schedule: $TRIGGER)"
else
    fail "swingtrader-legema.timer is NOT enabled — CoreEW P20w will not run"
fi

# Result of the last oneshot run: ExecMainStatus/Result are only meaningful after
# the service has run at least once (empty while never started).
COREEW_RESULT=$(systemctl show swingtrader-legema.service -p Result --value 2>/dev/null || echo "")
COREEW_EXIT=$(systemctl show swingtrader-legema.service -p ExecMainStatus --value 2>/dev/null || echo "")
COREEW_LAST=$(systemctl show swingtrader-legema.service -p ExecMainExitTimestamp --value 2>/dev/null || echo "")
case "$COREEW_RESULT" in
    "")
        fail "swingtrader-legema.service has never run"
        ;;
    success)
        if [ "$COREEW_EXIT" = "0" ]; then
            pass "swingtrader-legema.service last run: success (exit 0) — $COREEW_LAST"
        else
            warn "swingtrader-legema.service result=success but exit=$COREEW_EXIT — $COREEW_LAST"
        fi
        ;;
    *)
        fail "swingtrader-legema.service last run: $COREEW_RESULT (exit $COREEW_EXIT) — $COREEW_LAST"
        LAST_ERR=$(journalctl -u swingtrader-legema.service --since "3 days ago" --no-pager 2>/dev/null | grep -E "error|Error|FAIL|exception" | tail -3 || true)
        if [ -n "$LAST_ERR" ]; then
            echo "$LAST_ERR" | sed 's/^/    /'
        fi
        ;;
esac

# Freshness marker: the command stamps storage/trades_last_run.txt on every run
# (market open or closed), so its mtime must cover the most recent 10:05 ET
# Mon-Fri slot — not a rolling window like the old 5-min cron.
COREEW_MARKER="$PROJECT_DIR/swingtrader/backend/storage/trades_last_run.txt"
if [ ! -f "$COREEW_MARKER" ]; then
    fail "CoreEW marker file missing at $COREEW_MARKER"
else
    NOW_EPOCH=$(date +%s)
    MARKER_EPOCH=$(stat -c %Y "$COREEW_MARKER" 2>/dev/null || echo 0)
    DOW=$(date +%u)  # 1=Mon .. 7=Sun
    NOW_HM=$(date +%H%M)

    # Most recent scheduled 10:05 slot (weekdays only; holidays still stamp).
    if [ "$DOW" -le 5 ] && [ "$NOW_HM" -ge 1005 ]; then
        EXPECT_DAY=$(date +%Y-%m-%d)
    else
        EXPECT_DAY=$(date -d "$(date +%Y-%m-%d) -1 day" +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
        # walk back over the weekend
        while [ "$(date -d "$EXPECT_DAY" +%u)" -gt 5 ]; do
            EXPECT_DAY=$(date -d "$EXPECT_DAY -1 day" +%Y-%m-%d)
        done
    fi
    EXPECT_EPOCH=$(date -d "$EXPECT_DAY 10:05:00" +%s 2>/dev/null || echo 0)

    if [ "$MARKER_EPOCH" -ge "$EXPECT_EPOCH" ]; then
        MIN_SINCE=$(( (NOW_EPOCH - MARKER_EPOCH) / 60 ))
        pass "CoreEW last run $MIN_SINCE min ago (covers $EXPECT_DAY 10:05 slot)"
    elif [ "$MARKER_EPOCH" -ge $(( EXPECT_EPOCH - 300 )) ]; then
        pass "CoreEW last run marker within 5 min before the $EXPECT_DAY 10:05 slot"
    elif [ $(( NOW_EPOCH - MARKER_EPOCH )) -le 86400 ]; then
        warn "CoreEW marker predates the $EXPECT_DAY 10:05 slot — run may have been missed"
    else
        fail "CoreEW last run $(( (NOW_EPOCH - MARKER_EPOCH) / 3600 ))h ago — expected a run at $EXPECT_DAY 10:05"
    fi
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
        TRIGGER=$(timer_schedule "$timer.timer")
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
        TRIGGER=$(timer_schedule "$timer.timer")
        pass "$timer.timer enabled — next: $NEXT (schedule: $TRIGGER)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Infrastructure timers
for timer in swingtrader-backup swingtrader-legema; do
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

for svc in swingtrader-scanner-update swingtrader-scanner-backfill swingtrader-mtf-executor swingtrader-daily-signal swingtrader-earnings-screener swingtrader-earnings-refresh swingtrader-legema; do
    # NOTE: `systemctl is-active` exits non-zero for inactive oneshots, so a bare
    # `|| echo not-found` appends a bogus second line — capture the status only.
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || true)
    RESULT=$(systemctl show "$svc" -p Result --value 2>/dev/null || true)
    LAST=$(systemctl show "$svc" -p ExecMainExitTimestamp --value 2>/dev/null || true)
    if [ -z "$STATUS" ] || [ "$STATUS" = "unknown" ] || [ "$STATUS" = "not-found" ]; then
        warn "$svc.service not found"
    elif [ "$STATUS" = "failed" ] || { [ -n "$RESULT" ] && [ "$RESULT" != "success" ]; }; then
        fail "$svc.service last run: $STATUS/$RESULT — $LAST"
        LAST_ERR=$(journalctl -u "$svc" --since "3 days ago" --no-pager 2>/dev/null | grep -E "error|Error|traceback|Traceback|FAIL" | tail -2 || true)
        if [ -n "$LAST_ERR" ]; then
            echo "$LAST_ERR" | sed 's/^/    /'
        fi
    else
        pass "$svc.service last run: $STATUS (result: ${RESULT:-n/a}) — $LAST"
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
