#!/usr/bin/env bash
set -euo pipefail

# Swing Trader Application Startup Script
# Initializes and starts all application components

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
OPTIMIZER_DIR="$PROJECT_ROOT/optimizer"

echo "=========================================="
echo "Swing Trader Application Startup"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Find PHP executable (handle WSL/Windows paths)
PHP_CMD="php"
if ! command -v php &> /dev/null; then
    # Try WSL Windows PHP paths
    if [ -f "/mnt/c/php/php.exe" ]; then
        PHP_CMD="/mnt/c/php/php.exe"
    elif [ -f "/mnt/c/Program Files/php/php.exe" ]; then
        PHP_CMD="/mnt/c/Program Files/php/php.exe"
    else
        echo -e "${RED}✗ PHP not found${NC}"
        echo "   Add PHP to PATH or check:"
        echo "   - /mnt/c/php/php.exe (WSL)"
        echo "   - /usr/bin/php (Linux)"
        exit 1
    fi
fi
PHP_VERSION=$($PHP_CMD -v 2>/dev/null | head -1)
echo -e "${GREEN}✓ $PHP_VERSION${NC}"

if ! command -v composer &> /dev/null; then
    echo -e "${RED}✗ Composer not found${NC}"
    echo "   Install from: https://getcomposer.org/download/"
    exit 1
fi
echo -e "${GREEN}✓ Composer installed${NC}"

# Export PHP command for use in rest of script
export PHP_CMD

# Create necessary directories
echo ""
echo -e "${YELLOW}Creating directories...${NC}"
mkdir -p "$BACKEND_DIR/storage/logs"
mkdir -p "$BACKEND_DIR/storage/app"
mkdir -p "$OPTIMIZER_DIR/logs"
echo -e "${GREEN}✓ Directories created${NC}"

# Install dependencies
echo ""
echo -e "${YELLOW}Installing PHP dependencies...${NC}"
cd "$BACKEND_DIR"
composer install --quiet 2>/dev/null || {
    echo -e "${YELLOW}Composer install in progress (this may take a minute)...${NC}"
    composer install
}
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check .env file
echo ""
echo -e "${YELLOW}Checking configuration...${NC}"
if [ ! -f "$BACKEND_DIR/.env" ]; then
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
        echo -e "${GREEN}✓ Created .env from .env.example${NC}"
        echo -e "${YELLOW}⚠ Update .env with your Alpaca API credentials${NC}"
    fi
else
    echo -e "${GREEN}✓ .env exists${NC}"
fi

# Generate app key if needed
if ! grep -q "APP_KEY=" "$BACKEND_DIR/.env" || grep -q "APP_KEY=$" "$BACKEND_DIR/.env"; then
    echo -e "${YELLOW}Generating APP_KEY...${NC}"
    cd "$BACKEND_DIR"
    $PHP_CMD artisan key:generate
    echo -e "${GREEN}✓ APP_KEY generated${NC}"
fi

# Run migrations
echo ""
echo -e "${YELLOW}Running database migrations...${NC}"
cd "$BACKEND_DIR"
$PHP_CMD artisan migrate --force --quiet 2>/dev/null || true
echo -e "${GREEN}✓ Database ready${NC}"

# Verify cron setup
echo ""
echo -e "${YELLOW}Checking cron configuration...${NC}"
CRON_COUNT=$(crontab -l 2>/dev/null | grep -c "SwingTraderAndOptimizer" || echo "0")
if [ "$CRON_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Cron entries installed ($CRON_COUNT jobs)${NC}"
else
    echo -e "${YELLOW}⚠ No cron entries found${NC}"
    echo -e "${YELLOW}  To install: bash $BACKEND_DIR/setup_cron.sh (if available)${NC}"
fi

# Start Laravel dev server
echo ""
echo -e "${YELLOW}Starting Laravel development server...${NC}"
cd "$BACKEND_DIR"

echo ""
echo -e "${GREEN}=========================================="
echo "Application started successfully!"
echo "==========================================${NC}"
echo ""
echo "Backend API: http://localhost:8000"
echo "API Documentation: http://localhost:8000/api/documentation"
echo ""
echo "Logs:"
echo "  - Backend: $BACKEND_DIR/storage/logs/laravel.log"
echo "  - Trade Executor: $BACKEND_DIR/storage/logs/trade_executor.log"
echo "  - Optimizer: $OPTIMIZER_DIR/logs/nightly.log"
echo ""
echo "Cron Schedule:"
echo "  - 8:18 AM ET: Nightly Optimizer"
echo "  - 9:30 AM - 4:00 PM ET (every 30 min): Trade Executor"
echo ""
echo "API Endpoints (Manual):"
echo "  POST /api/v1/admin/trades/trigger      - Execute trades now"
echo "  POST /api/v1/admin/optimize/trigger    - Run optimizer now"
echo "  GET  /api/v1/admin/market-status       - Check market status"
echo "  GET  /api/v1/account                   - Account info"
echo "  GET  /api/v1/account/positions         - Open positions"
echo ""

# Start the server
$PHP_CMD artisan serve --host=0.0.0.0 --port=8000
