#!/usr/bin/env bash
# Swing Trader: Start Backend + Frontend
# Starts both servers and displays access URLs

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "Swing Trader: Backend + Frontend"
echo "==========================================${NC}"
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
echo -e "${GREEN}Starting Backend API...${NC}"
mkdir -p "$BACKEND_DIR/storage/logs"
cd "$BACKEND_DIR"
php artisan serve --host=127.0.0.1 --port=9000 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}✓ Backend PID: $BACKEND_PID${NC}"

# Wait for backend to be ready
sleep 2

# Start Frontend
echo -e "${GREEN}Starting Frontend...${NC}"
cd "$FRONTEND_DIR"

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing frontend dependencies...${NC}"
    npm install --silent
fi

npm run dev > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend PID: $FRONTEND_PID${NC}"

# Display info
echo ""
echo -e "${BLUE}=========================================="
echo "Swing Trader Running"
echo "==========================================${NC}"
echo ""
echo -e "${GREEN}Dashboard UI:${NC}      ${YELLOW}http://localhost:5173${NC}"
echo -e "${GREEN}API Server:${NC}       ${YELLOW}http://localhost:9000${NC}"
echo -e "${GREEN}API Docs:${NC}         ${YELLOW}http://localhost:9000/api/documentation${NC}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  Backend:  tail -f /tmp/backend.log"
echo "  Frontend: tail -f /tmp/frontend.log"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo ""

# Keep script running
wait
