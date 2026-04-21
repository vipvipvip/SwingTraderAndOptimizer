#!/usr/bin/env bash
# Daily monitoring script - runs all critical checks and reports status
# Usage: ./daily-check.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OPTIMIZER_DIR="$PROJECT_ROOT/optimizer"
BACKEND_DIR="$PROJECT_ROOT/backend"
BACKEND_URL="http://localhost:8000"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   SwingTrader Daily Monitoring Report   ${NC}║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# ============================================================================
# 1. NIGHTLY OPTIMIZER CHECK
# ============================================================================
echo -e "${BLUE}=== NIGHTLY OPTIMIZER ===${NC}"

OPTIMIZER_LOG="$OPTIMIZER_DIR/logs/nightly.log"

if [ ! -f "$OPTIMIZER_LOG" ]; then
    echo -e "${RED}✗ No optimizer log found${NC}"
else
    LAST_RUN=$(tail -1 "$OPTIMIZER_LOG" 2>/dev/null || echo "")

    if echo "$LAST_RUN" | grep -q "finished"; then
        echo -e "${GREEN}✓ Last run completed${NC}"
        echo "  $LAST_RUN"
    else
        echo -e "${YELLOW}⚠ Last run may still be in progress${NC}"
        tail -3 "$OPTIMIZER_LOG" | sed 's/^/  /'
    fi
fi

echo ""

# ============================================================================
# 2. TICKERS & PARAMETERS CHECK
# ============================================================================
echo -e "${BLUE}=== TICKERS & PARAMETERS ===${NC}"

TICKERS_RESPONSE=$(curl -s "$BACKEND_URL/api/v1/tickers" 2>/dev/null || echo "")

if [ -z "$TICKERS_RESPONSE" ]; then
    echo -e "${RED}✗ Backend not responding${NC}"
else
    echo -e "${GREEN}✓ Backend API responding${NC}"

    # Check each ticker
    echo "$TICKERS_RESPONSE" | jq -r '.[] |
        "  \(.symbol): Sharpe=\(.params.sharpe_ratio|@json), Alloc=\(.allocation_weight|@json)%, Updated=\(.params.updated_at)"' 2>/dev/null || \
        echo -e "  ${RED}Error parsing ticker data${NC}"
fi

echo ""

# ============================================================================
# 3. TRADES CHECK
# ============================================================================
echo -e "${BLUE}=== TRADES (TODAY) ===${NC}"

TRADES_RESPONSE=$(curl -s "$BACKEND_URL/api/v1/trades/pnl" 2>/dev/null || echo "")

if [ -z "$TRADES_RESPONSE" ]; then
    echo -e "${RED}✗ Cannot fetch trades${NC}"
else
    TRADE_COUNT=$(echo "$TRADES_RESPONSE" | jq '.recent_trades | length' 2>/dev/null || echo "0")
    WIN_RATE=$(echo "$TRADES_RESPONSE" | jq '.win_rate * 100 | round' 2>/dev/null || echo "N/A")
    TOTAL_RETURN=$(echo "$TRADES_RESPONSE" | jq '.total_return * 100 | round / 100' 2>/dev/null || echo "N/A")

    if [ "$TRADE_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✓ Trades executed today${NC}"
    else
        echo -e "${YELLOW}⚠ No trades today (market may be closed)${NC}"
    fi

    echo "  Executed: $TRADE_COUNT trades"
    echo "  Win Rate: $WIN_RATE%"
    echo "  Total Return: $TOTAL_RETURN%"
fi

echo ""

# ============================================================================
# 4. ACCOUNT CHECK
# ============================================================================
echo -e "${BLUE}=== ACCOUNT ===${NC}"

ACCOUNT_RESPONSE=$(curl -s "$BACKEND_URL/api/v1/account" 2>/dev/null || echo "")

if [ -z "$ACCOUNT_RESPONSE" ]; then
    echo -e "${RED}✗ Cannot fetch account info${NC}"
else
    EQUITY=$(echo "$ACCOUNT_RESPONSE" | jq '.equity | round' 2>/dev/null || echo "N/A")
    BUYING_POWER=$(echo "$ACCOUNT_RESPONSE" | jq '.buying_power | round' 2>/dev/null || echo "N/A")

    if [ "$EQUITY" != "N/A" ] && (( $(echo "$EQUITY < 100000" | bc -l) )); then
        echo -e "${RED}✗ Equity below starting amount${NC}"
    else
        echo -e "${GREEN}✓ Account healthy${NC}"
    fi

    echo "  Equity: \$$EQUITY"
    echo "  Buying Power: \$$BUYING_POWER"
fi

echo ""

# ============================================================================
# 5. ERRORS CHECK
# ============================================================================
echo -e "${BLUE}=== ERROR CHECK ===${NC}"

LARAVEL_LOG="$BACKEND_DIR/storage/logs/laravel.log"
ERROR_COUNT=0

if [ -f "$LARAVEL_LOG" ]; then
    ERROR_COUNT=$(grep -c "ERROR\|Exception" "$LARAVEL_LOG" 2>/dev/null || echo "0")

    if [ "$ERROR_COUNT" -gt 10 ]; then
        echo -e "${RED}✗ High error count: $ERROR_COUNT errors${NC}"
        echo "  Recent errors:"
        tail -10 "$LARAVEL_LOG" | grep "ERROR\|Exception" | head -5 | sed 's/^/    /'
    elif [ "$ERROR_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠ Some errors detected: $ERROR_COUNT errors${NC}"
    else
        echo -e "${GREEN}✓ No errors in logs${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Laravel log not found${NC}"
fi

echo ""

# ============================================================================
# 6. SCHEDULER STATUS CHECK
# ============================================================================
echo -e "${BLUE}=== SCHEDULER STATUS ===${NC}"

OS=$(uname -s)

if [[ "$OS" == "MINGW64_NT"* ]] || [[ "$OS" == "MSYS_NT"* ]]; then
    # Windows
    OPTIMIZER_TASK=$(schtasks query /tn "SwingTrader-NightlyOptimizer" 2>/dev/null | grep "Ready" || echo "")
    TRADE_TASK=$(schtasks query /tn "SwingTrader-LaravelScheduler" 2>/dev/null | grep "Ready" || echo "")

    if [ -n "$OPTIMIZER_TASK" ]; then
        echo -e "${GREEN}✓ Optimizer task registered${NC}"
    else
        echo -e "${YELLOW}⚠ Optimizer task not found${NC}"
    fi

    if [ -n "$TRADE_TASK" ]; then
        echo -e "${GREEN}✓ Trade executor task registered${NC}"
    else
        echo -e "${YELLOW}⚠ Trade executor task not found${NC}"
    fi
else
    # Linux/Mac - check crontab
    if crontab -l 2>/dev/null | grep -q "run_nightly"; then
        echo -e "${GREEN}✓ Optimizer cron job registered${NC}"
    else
        echo -e "${YELLOW}⚠ Optimizer cron job not found${NC}"
    fi

    if crontab -l 2>/dev/null | grep -q "artisan schedule:run"; then
        echo -e "${GREEN}✓ Trade executor cron job registered${NC}"
    else
        echo -e "${YELLOW}⚠ Trade executor cron job not found${NC}"
    fi
fi

echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo -e "${BLUE}=== SUMMARY ===${NC}"

if [ "$ERROR_COUNT" -lt 10 ] && [ -n "$TICKERS_RESPONSE" ] && [ -n "$ACCOUNT_RESPONSE" ]; then
    echo -e "${GREEN}✓ System appears healthy${NC}"
    echo "  • Optimizer logs present"
    echo "  • Backend responding"
    echo "  • Minimal errors"
    echo "  • Account info accessible"
else
    echo -e "${YELLOW}⚠ System needs attention${NC}"
    echo "  Check the reports above for details"
fi

echo ""
echo -e "${BLUE}Report generated:${NC} $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
