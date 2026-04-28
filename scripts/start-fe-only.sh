#!/usr/bin/env bash
# Frontend-Only Startup
# Runs Svelte/Vite dev server on port 5173

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo "Swing Trader: Frontend-Only (Dev)"
echo "==========================================${NC}"
echo ""

# Kill existing processes
echo -e "${YELLOW}Cleaning up existing frontend processes...${NC}"
pkill -9 -f "vite" 2>/dev/null || true
pkill -9 -f "npm run dev" 2>/dev/null || true
lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Old processes killed${NC}"
echo ""

# Clean up frontend caches
echo -e "${YELLOW}Cleaning up frontend caches and build artifacts...${NC}"
cd "$FRONTEND_DIR"
rm -rf dist node_modules/.vite 2>/dev/null || true
rm -rf .svelte-kit 2>/dev/null || true
echo -e "${GREEN}✓ Caches cleared${NC}"
echo ""

# Start Frontend
echo -e "${BLUE}Starting Frontend on port 5173...${NC}"
npm run dev > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}✓ Frontend PID: $FRONTEND_PID${NC}"

# Wait for frontend to be ready
sleep 5

# Verify frontend is responding
if curl -s http://localhost:5173/ >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Frontend responding${NC}"
else
    echo -e "${YELLOW}⚠ Frontend may still be starting (check /tmp/frontend.log)${NC}"
fi
echo ""

# Display info
echo -e "${BLUE}=========================================="
echo "Swing Trader: Frontend Running (Dev Mode)"
echo "==========================================${NC}"
echo ""
echo -e "${GREEN}Frontend Dev Server:${NC} ${YELLOW}http://localhost:5173${NC}"
echo -e "${GREEN}Backend API:${NC}       ${YELLOW}http://localhost:9000${NC}"
echo ""
echo -e "${YELLOW}Logs:${NC}"
echo "  Frontend: tail -f /tmp/frontend.log"
echo ""
echo -e "${YELLOW}To stop: kill $FRONTEND_PID${NC}"
echo ""

# Keep script running
wait
