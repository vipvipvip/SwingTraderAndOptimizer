#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# SwingTrader System Health Check
# Verifies: DB, bars data (ETF + scanner), optimizer runs,
#           strategy params, backend/frontend services, market status
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

# ---- ETF Bars Data (per ticker) ----
echo ""
echo "--- ETF Bar Data ---"

ENABLED_ETF=$(PSQL "SELECT symbol FROM tbl_etf_tickers WHERE enabled=true AND symbol != 'BLENDED' ORDER BY symbol;")
if [ -z "$ENABLED_ETF" ]; then
    fail "No enabled ETF tickers found"
else
    pass "Enabled ETFs: $(echo "$ENABLED_ETF" | tr '\n' ' ')"
    for sym in $ENABLED_ETF; do
        LATEST=$(PSQL "SELECT MAX(DATE(b.timestamp)) FROM tbl_etf_tickers_1hour b JOIN tbl_etf_tickers t ON b.ticker_id = t.id WHERE t.symbol='$sym';")
        COUNT=$(PSQL "SELECT COUNT(*) FROM tbl_etf_tickers_1hour b JOIN tbl_etf_tickers t ON b.ticker_id = t.id WHERE t.symbol='$sym';")
        if [ -n "$LATEST" ] && [ "$LATEST" != " " ]; then
            DAYS_SINCE=$(( ($(date +%s) - $(date -d "$LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
            if [ "$DAYS_SINCE" -le 7 ] 2>/dev/null; then
                pass "  $sym: $COUNT bars, latest $LATEST ($DAYS_SINCE days ago)"
            else
                warn "  $sym: $COUNT bars, latest $LATEST ($DAYS_SINCE days ago - stale)"
            fi
        else
            fail "  $sym: no bar data found"
        fi
    done
fi

ETF_BAR_TOTAL=$(PSQL "SELECT COUNT(*) FROM tbl_etf_tickers_1hour b JOIN tbl_etf_tickers t ON b.ticker_id = t.id WHERE t.enabled=true AND t.symbol != 'BLENDED';")
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
_trading_days_since() {
    local d="$1" count=0
    local bar_epoch bar_day today_epoch today_day i dow
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
for sfx in update hourly; do
    if systemctl is-failed "scanner-${sfx}.service" >/dev/null 2>&1; then
        warn "scanner-${sfx}.service is in failed state"
    fi
    RECENT_FAIL=$(journalctl -u "scanner-${sfx}.service" --since "3 days ago" --no-pager 2>/dev/null | grep "Failed with result\|Main process exited, code=exited, status=1" || true)
    if [ -n "$RECENT_FAIL" ]; then
        warn "scanner-${sfx}.service had failures in last 3 days:"
        echo "$RECENT_FAIL" | sed 's/^/    /'
    fi
done

# ---- Strategy Parameters ----
echo ""
echo "--- Strategy Parameters ---"

PARAM_ROWS=$(PSQL "SELECT COUNT(*) FROM strategy_parameters sp JOIN tbl_etf_tickers t ON sp.ticker_id = t.id WHERE t.symbol IN ('QQQ','VTI','VTV') AND sp.base_case=true;")
CORE_COUNT=$(echo "$CORE_ETFS" | wc -w)
if [ "$PARAM_ROWS" -ge "$CORE_COUNT" ] 2>/dev/null; then
    pass "All $CORE_COUNT core ETFs (QQQ/VTI/VTV) have base_case=true parameters"
else
    fail "Expected $CORE_COUNT core ETFs with base_case=true, found $PARAM_ROWS"
fi

LAST_PARAM_UPDATE=$(PSQL "SELECT MAX(sp.updated_at)::date FROM strategy_parameters sp JOIN tbl_etf_tickers t ON sp.ticker_id = t.id WHERE t.enabled=true AND sp.base_case=true AND t.symbol != 'BLENDED';")
PARAM_DAYS=$(( ($(date +%s) - $(date -d "$LAST_PARAM_UPDATE" +%s 2>/dev/null || echo 0)) / 86400 ))
echo "  Parameters last updated: $LAST_PARAM_UPDATE ($PARAM_DAYS days ago)"

# Per-ticker active params (core ETFs only)
for sym in $CORE_ETFS; do
    PARAM_LINE=$(PSQL "
        SELECT CONCAT('period=', sp.chandelier_period, ' mult=', sp.chandelier_mult,
            CASE WHEN sp.chandelier_entry_mult IS NOT NULL THEN CONCAT(' entry=', sp.chandelier_entry_mult) ELSE '' END,
            CASE WHEN sp.reg_slope_window IS NOT NULL THEN CONCAT(' reg=', sp.reg_slope_type, ' ', sp.reg_slope_window, 'd th=', sp.reg_slope_threshold) ELSE '' END,
            ' sharpe=', ROUND(sp.sharpe_ratio::numeric, 2))
        FROM strategy_parameters sp JOIN tbl_etf_tickers t ON sp.ticker_id = t.id
        WHERE t.symbol='$sym' AND sp.base_case=true;
    ")
    if [ -n "$PARAM_LINE" ]; then
        echo "    $sym: $PARAM_LINE"
    fi
done

# ---- Optimization History (per ticker) ----
echo ""
echo "--- Nightly Optimizer ---"

OPT_RUNS=$(PSQL "SELECT COUNT(*) FROM optimization_history oh JOIN tbl_etf_tickers t ON oh.ticker_id = t.id WHERE t.enabled=true AND t.symbol != 'BLENDED';")
if [ "$OPT_RUNS" -gt 0 ] 2>/dev/null; then
    pass "Optimization history has $OPT_RUNS recorded runs for enabled tickers"
else
    warn "No optimization history found"
fi

LAST_OPT_GLOBAL=$(PSQL "SELECT MAX(run_date)::date FROM optimization_history;")
OPT_GLOBAL_DAYS=$(( ($(date +%s) - $(date -d "$LAST_OPT_GLOBAL" +%s 2>/dev/null || echo 0)) / 86400 ))
echo "  Last optimizer run (any ticker): $LAST_OPT_GLOBAL ($OPT_GLOBAL_DAYS days ago)"

# Per-ticker latest optimizer run details (core ETFs only)
for sym in BLENDED $CORE_ETFS; do
    OPT_LINE=$(PSQL "
        SELECT CONCAT(oh.run_date::date, ' sharpe=', ROUND(oh.best_sharpe::numeric, 2),
            ' return=', ROUND(oh.best_return::numeric, 2),
            ' win=', ROUND(oh.best_win_rate::numeric, 3),
            ' combos=', oh.total_combinations,
            ' promoted=', oh.promoted)
        FROM optimization_history oh JOIN tbl_etf_tickers t ON oh.ticker_id = t.id
        WHERE t.symbol='$sym'
        ORDER BY oh.run_date DESC LIMIT 1;
    ")
    if [ -n "$OPT_LINE" ]; then
        echo "    $sym: $OPT_LINE"
    else
        echo "    $sym: no optimization runs found"
    fi
done

# Also check the nightly log
if [ -f "$PROJECT_DIR/swingtrader/services/optimizer/logs/nightly.log" ]; then
    LAST_LOG=$(tail -1 "$PROJECT_DIR/swingtrader/services/optimizer/logs/nightly.log" 2>/dev/null || echo "unreadable")
    echo "  Last optimizer log entry: $LAST_LOG"
else
    warn "Optimizer log file not found at swingtrader/services/optimizer/logs/nightly.log"
fi

# ---- Timers ----
echo ""
echo "--- System Timers ---"

# Strategy timers with next run time
for timer in scanner-update scanner-hourly mtf-daily-runner daily-signal backfill-daily; do
    if systemctl is-enabled "$timer.timer" >/dev/null 2>&1; then
        NEXT=$(systemctl show "$timer.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
        TRIGGER=$(systemctl show "$timer.timer" -p TriggerOnCalendar --value 2>/dev/null || echo "?")
        pass "$timer.timer enabled — next: $NEXT (schedule: $TRIGGER)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Earnings timers
for timer in earnings-refresh earnings-screener; do
    if systemctl is-enabled "$timer.timer" >/dev/null 2>&1; then
        NEXT=$(systemctl show "$timer.timer" -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
        TRIGGER=$(systemctl show "$timer.timer" -p TriggerOnCalendar --value 2>/dev/null || echo "?")
        pass "$timer.timer enabled — next: $NEXT (schedule: $TRIGGER)"
    else
        warn "$timer.timer is not enabled"
    fi
done

# Infrastructure timers
for timer in swingtrader-optimizer swingtrader-backup; do
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

for svc in scanner-update scanner-hourly mtf-daily-runner daily-signal backfill-daily earnings-screener earnings-refresh; do
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

# ---- All Strategy Services (long-running) ----
echo ""
echo "--- Strategy Services ---"

for svc in emac-runner mtcs-runner; do
    STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
    if [ "$STATUS" = "active" ]; then
        STARTED=$(systemctl show "$svc" -p ActiveEnterTimestamp --value 2>/dev/null || echo "?")
        pass "$svc is running (since $STARTED)"
    elif [ "$STATUS" = "not-found" ]; then
        warn "$svc service not found"
    else
        fail "$svc is $STATUS"
    fi
    # Recent errors from log file
    LOG_FILE="/var/log/${svc}.log"
    if [ -f "$LOG_FILE" ]; then
        RECENT_ERRS=$(tail -200 "$LOG_FILE" 2>/dev/null | grep -iE "error|exception|traceback|fail" | tail -3 || true)
        if [ -n "$RECENT_ERRS" ]; then
            warn "  $svc recent errors:"
            echo "$RECENT_ERRS" | sed 's/^/    /'
        fi
    fi
done

# ---- EMAC EMA/SMA + MACD 30-min Crossover ----
echo ""
echo "--- EMAC Crossover ---"

EMAC_HEALTH="$PROJECT_DIR/swingtrader/services/ema_sma_crossover/health_check.py"
if [ -f "$EMAC_HEALTH" ]; then
    cd "$PROJECT_DIR/swingtrader/services/ema_sma_crossover" && python3 "$EMAC_HEALTH"
    EMAC_EXIT=$?
    if [ "$EMAC_EXIT" -eq 0 ]; then
        pass "EMAC health check passed"
    else
        fail "EMAC health check detected issues"
    fi
else
    fail "EMAC health check script not found at $EMAC_HEALTH"
fi

# ---- Daily EMA/SMA Crossover Signal Service ----
echo ""
echo "--- Daily Signal Service ---"

DAILY_CSV="$PROJECT_DIR/swingtrader/services/ema_sma_crossover/data/daily_signals.csv"
DAILY_STATE="$PROJECT_DIR/swingtrader/services/ema_sma_crossover/.daily_signal_state.json"

if systemctl is-enabled daily-signal.timer >/dev/null 2>&1; then
    NEXT=$(systemctl show daily-signal.timer -p NextElapseUSecRealtime --value 2>/dev/null || echo "?")
    pass "daily-signal.timer is enabled (next: $NEXT)"
else
    warn "daily-signal.timer is not enabled"
fi

if systemctl is-active daily-signal.timer >/dev/null 2>&1; then
    pass "daily-signal.timer is active"
else
    warn "daily-signal.timer is not active"
fi

# Check daily candle freshness for core ETFs only (emac_daily_candles table)
for sym in $CORE_ETFS; do
    DAILY_LATEST=$(PSQL "SELECT MAX(ts)::date FROM emac_daily_candles dc JOIN tbl_etf_tickers t ON dc.ticker_id = t.id WHERE t.symbol='$sym';")
    if [ -n "$DAILY_LATEST" ] && [ "$DAILY_LATEST" != " " ]; then
        DAILY_DAYS=$(( ($(date +%s) - $(date -d "$DAILY_LATEST" +%s 2>/dev/null || echo 0)) / 86400 ))
        if [ "$DAILY_DAYS" -le 7 ] 2>/dev/null; then
            pass "  $sym daily candles: latest $DAILY_LATEST ($DAILY_DAYS days ago)"
        else
            warn "  $sym daily candles: latest $DAILY_LATEST ($DAILY_DAYS days ago - stale)"
        fi
    else
        fail "  $sym: no daily candle data found"
    fi
done

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

# ---- MTCS Hilbert Transform Cycle Strategy ----
echo ""
echo "--- MTCS Cycle Strategy ---"

MTCS_HEALTH="$PROJECT_DIR/swingtrader/services/mtcs/health_check.py"
if [ -f "$MTCS_HEALTH" ]; then
    cd "$PROJECT_DIR/swingtrader/services/mtcs" && python3 "$MTCS_HEALTH"
    MTCS_EXIT=$?
    if [ "$MTCS_EXIT" -eq 0 ]; then
        pass "MTCS health check passed"
    else
        fail "MTCS health check detected issues"
    fi
else
    fail "MTCS health check script not found at $MTCS_HEALTH"
fi

# ---- MTF Top-N Multi-TF Rotation (Phase 1 Paper) ----
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
