#!/usr/bin/env bash
# Swing Trader: Start Backend + Frontend (Clean Restart)
# Kills existing processes, clears caches, starts fresh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "Swing Trader: Clean Restart"
echo "==========================================${NC}"
echo ""

# Kill existing processes
echo -e "${YELLOW}Cleaning up existing processes...${NC}"
pkill -9 -f "php artisan serve" 2>/dev/null || true
pkill -9 -f "npm run dev" 2>/dev/null || true
pkill -9 -f "vite" 2>/dev/null || true
lsof -ti:9000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Old processes killed${NC}"
echo ""

# Clear Laravel caches
echo -e "${YELLOW}Clearing Laravel caches...${NC}"
cd "$BACKEND_DIR"
rm -f bootstrap/cache/*.php 2>/dev/null || true
php artisan config:clear 2>/dev/null || true
php artisan cache:clear 2>/dev/null || true
echo -e "${GREEN}✓ Caches cleared${NC}"
echo ""

# Clear old logs
echo -e "${YELLOW}Clearing old logs...${NC}"
rm -f /tmp/backend.log /tmp/frontend.log 2>/dev/null || true
echo -e "${GREEN}✓ Logs cleared${NC}"
echo ""

# Cleanup on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait 2>/dev/null || true
    echo -e "${GREEN}Stopped${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start Backend
echo -e "${BLUE}Starting Backend API on port 9000...${NC}"
mkdir -p "$BACKEND_DIR/storage/logs"
cd "$BACKEND_DIR"
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

# Start Frontend
echo -e "${BLUE}Starting Frontend on port 5173...${NC}"
cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    npm install --silent
fi

npm run dev > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend PID: $FRONTEND_PID${NC}"

# Wait for frontend to be ready
sleep 4

# Verify frontend is responding
if curl -s http://localhost:5173 >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Frontend UI responding${NC}"
else
    echo -e "${RED}✗ Frontend UI not responding (check /tmp/frontend.log)${NC}"
fi
echo ""

# Display info
echo ""
echo -e "${BLUE}=========================================="
echo "Swing Trader Running"
echo "==========================================${NC}"
echo ""
echo -e "${GREEN}Dashboard UI:${NC}      ${YELLOW}http://localhost:5173${NC} (local)"
echo -e "${GREEN}                  ${YELLOW}http://192.168.1.232:5173${NC} (network)"
echo -e "${GREEN}API Server:${NC}       ${YELLOW}http://localhost:9000${NC} (local)"
echo -e "${GREEN}                  ${YELLOW}http://192.168.1.232:9000${NC} (network)"
echo -e "${GREEN}API Docs:${NC}         ${YELLOW}http://192.168.1.232:9000/api/documentation${NC}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  Backend:  tail -f /tmp/backend.log"
echo "  Frontend: tail -f /tmp/frontend.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo ""

# Keep script running
wait
