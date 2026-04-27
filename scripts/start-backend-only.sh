#!/usr/bin/env bash
# Production Backend-Only Startup
# For automated trading without UI (backend + cron only)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "Swing Trader: Backend-Only (Production)"
echo "==========================================${NC}"
echo ""

# Kill existing processes
echo -e "${YELLOW}Cleaning up existing backend processes...${NC}"
pkill -9 -f "php artisan serve" 2>/dev/null || true
lsof -ti:9000 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Old processes killed${NC}"
echo ""

# Clear Laravel caches
echo -e "${YELLOW}Clearing Laravel caches...${NC}"
cd "$BACKEND_DIR"
rm -f bootstrap/cache/*.php 2>/dev/null || true
php artisan config:clear 2>/dev/null || true
php artisan cache:clear 2>/dev/null || true
mkdir -p storage/framework/views
echo -e "${GREEN}✓ Caches cleared${NC}"
echo ""

# Start Backend
echo -e "${BLUE}Starting Backend API on port 9000...${NC}"
mkdir -p "$BACKEND_DIR/storage/logs"
php artisan serve --host=0.0.0.0 --port=9000 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend PID: $BACKEND_PID${NC}"

# Wait for backend to be ready
sleep 3

# Verify backend is responding
if curl -s http://localhost:9000/api/v1/account >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Backend API responding${NC}"
else
    echo -e "${RED}✗ Backend API not responding (check /tmp/backend.log)${NC}"
fi
echo ""

# Display info
echo -e "${BLUE}=========================================="
echo "Swing Trader: Backend Running (Production Mode)"
echo "==========================================${NC}"
echo ""
echo -e "${GREEN}API Server:${NC}       ${YELLOW}http://localhost:9000${NC}"
echo -e "${GREEN}API Docs:${NC}         ${YELLOW}http://localhost:9000/api/documentation${NC}"
echo ""
echo -e "${YELLOW}Frontend:${NC}         Not running (trading only)"
echo ""
echo -e "${YELLOW}Setup Crontab Entries:${NC}"
echo ""
echo "  # Nightly optimizer (runs at 2:00 AM UTC daily)"
echo "  0 2 * * * $PROJECT_ROOT/optimizer/run_nightly.sh"
echo ""
echo "  # Trade executor (runs every minute, weekdays only during market hours)"
echo "  * * * * * /usr/bin/php $PROJECT_ROOT/backend/artisan trades:execute-daily >> /dev/null 2>&1"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  Backend: tail -f /tmp/backend.log"
echo "  Laravel: tail -f $BACKEND_DIR/storage/logs/laravel.log"
echo ""
echo -e "${YELLOW}To stop: kill $BACKEND_PID${NC}"
echo ""

# Keep script running
wait
