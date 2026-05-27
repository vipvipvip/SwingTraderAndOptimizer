#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SwingTrader System Health Check
# Verifies: DB, bars data, optimizer runs, strategy params,
#           backend/frontend services, market status
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

# Check PostgreSQL accepts connections
if docker exec swingtrader-db pg_isready -U swingtrader >/dev/null 2>&1; then
    pass "PostgreSQL is accepting connections"
else
    fail "PostgreSQL is not accepting connections"
fi

# ---- Bars Data ----
echo ""
echo "--- Market Data ---"

TICKER_COUNT=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT COUNT(*) FROM tickers WHERE enabled=true AND symbol != 'BLENDED';" 2>/dev/null || echo "0")
BAR_COUNT=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT COUNT(*) FROM bars b JOIN tickers t ON b.ticker_id = t.id WHERE t.enabled=true AND t.symbol != 'BLENDED';" 2>/dev/null || echo "0")

if [ "$BAR_COUNT" -gt 0 ] 2>/dev/null; then
    pass "Bars table has $BAR_COUNT rows across $TICKER_COUNT enabled tickers"
else
    fail "Bars table is empty - data has not been downloaded"
fi

# Check for bars with unexpected hours.
# Daily bars (midnight ET) store as hour 4-5 UTC (depending on DST).
# Hourly market hours (9:30 AM - 4:00 PM ET) store as hour 14-20 UTC.
BAD_BARS=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "
  SELECT COUNT(*) FROM bars 
  WHERE EXTRACT(HOUR FROM timestamp)::INT NOT IN (4, 5, 14, 15, 16, 17, 18, 19, 20);" 2>/dev/null || echo "error")
DAILY_BARS=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "
  SELECT COUNT(*) FROM bars WHERE EXTRACT(HOUR FROM timestamp)::INT IN (4, 5);" 2>/dev/null || echo "0")
HOURLY_BARS=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "
  SELECT COUNT(*) FROM bars WHERE EXTRACT(HOUR FROM timestamp)::INT IN (14, 15, 16, 17, 18, 19, 20);" 2>/dev/null || echo "0")
if [ "$BAD_BARS" = "0" ] 2>/dev/null; then
    pass "All $((DAILY_BARS + HOURLY_BARS)) bars have valid timestamps ($DAILY_BARS daily, $HOURLY_BARS hourly market hours)"
else
    warn "Found $BAD_BARS bars with unexpected hours"
fi

# Check data recency
RECENT_BAR=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT MAX(timestamp)::date FROM bars;" 2>/dev/null || echo "never")
DAYS_SINCE=$(( ($(date +%s) - $(date -d "$RECENT_BAR" +%s 2>/dev/null || echo 0)) / 86400 ))
if [ "$DAYS_SINCE" -le 7 ] 2>/dev/null; then
    pass "Most recent bar: $RECENT_BAR ($DAYS_SINCE days ago)"
else
    warn "Most recent bar: $RECENT_BAR ($DAYS_SINCE days ago - may be stale)"
fi

# ---- Strategy Parameters ----
echo ""
echo "--- Strategy Parameters ---"

PARAM_ROWS=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT COUNT(*) FROM strategy_parameters sp JOIN tickers t ON sp.ticker_id = t.id WHERE t.enabled=true AND sp.base_case=true AND t.symbol != 'BLENDED';" 2>/dev/null || echo "0")
if [ "$PARAM_ROWS" -ge "$TICKER_COUNT" ] 2>/dev/null; then
    pass "All $TICKER_COUNT enabled tickers have base_case=true parameters"
else
    fail "Expected $TICKER_COUNT tickers with base_case=true, found $PARAM_ROWS"
fi

# Check parameters are recent
LAST_PARAM_UPDATE=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT MAX(updated_at)::date FROM strategy_parameters sp JOIN tickers t ON sp.ticker_id = t.id WHERE t.enabled=true AND sp.base_case=true AND t.symbol != 'BLENDED';" 2>/dev/null || echo "never")
echo "  Parameters last updated: $LAST_PARAM_UPDATE"

# ---- Optimization History ----
echo ""
echo "--- Nightly Optimizer ---"

OPT_RUNS=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT COUNT(*) FROM optimization_history oh JOIN tickers t ON oh.ticker_id = t.id WHERE t.enabled=true AND t.symbol != 'BLENDED';" 2>/dev/null || echo "0")
if [ "$OPT_RUNS" -gt 0 ] 2>/dev/null; then
    pass "Optimization history has $OPT_RUNS recorded runs"
else
    warn "No optimization history found - optimizer may not have run"
fi

LAST_OPT=$(docker exec swingtrader-db psql -U swingtrader -t -A -c "SELECT MAX(run_date)::date FROM optimization_history;" 2>/dev/null || echo "never")
echo "  Last optimizer run: $LAST_OPT"

# Also check the nightly log
if [ -f "$PROJECT_DIR/swingtrader/services/optimizer/logs/nightly.log" ]; then
    LAST_LOG=$(tail -1 "$PROJECT_DIR/swingtrader/services/optimizer/logs/nightly.log" 2>/dev/null || echo "unreadable")
    echo "  Last optimizer log entry: $LAST_LOG"
else
    warn "Optimizer log file not found at swingtrader/services/optimizer/logs/nightly.log"
fi

# Check if optimizer timer is enabled
if systemctl is-enabled swingtrader-optimizer.timer >/dev/null 2>&1; then
    pass "Optimizer systemd timer is enabled"
else
    warn "Optimizer systemd timer is not enabled"
fi

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

# ---- API Health ----
echo ""
echo "--- API Endpoints ---"

BACKEND_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9000/api/health 2>/dev/null || echo "000")
if [ "$BACKEND_CODE" = "200" ]; then
    pass "Backend health endpoint returns 200"
else
    fail "Backend health endpoint: HTTP $BACKEND_CODE"
fi

STRATEGIES_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5173 2>/dev/null || echo "000")
if [ "$STRATEGIES_CODE" = "200" ]; then
    pass "Frontend dashboard returns 200"
else
    warn "Frontend dashboard: HTTP $STRATEGIES_CODE"
fi

# Quick API data sanity check
API_RESPONSE=$(curl -s http://localhost:9000/api/v1/strategies 2>/dev/null)
TICKER_NAMES=$(echo "$API_RESPONSE" | python3 -c "import sys,json; data=json.load(sys.stdin); print(' '.join(t['symbol'] for t in data.get('tickers',[]) if t['symbol']!='BLENDED'))" 2>/dev/null || echo "unparseable")
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
