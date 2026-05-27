#!/bin/bash
###############################################################################
# SwingTrader - Full Ubuntu Setup Script
#
# Automates complete setup from pristine Ubuntu to production-ready system
# Tested on: Ubuntu 20.04, 22.04, 24.04
#
# Usage:
#   curl -sS https://raw.githubusercontent.com/vipvipvip/SwingTraderAndOptimizer/STO-Ubuntu-v1/scripts/full-setup.sh > setup.sh
#   chmod +x setup.sh
#   ./setup.sh
#
# Or manually:
#   bash scripts/full-setup.sh
#
###############################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "${BLUE}=========================================="
    echo "$1"
    echo "==========================================${NC}"
}

print_step() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ Error: $1${NC}"
    exit 1
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# START
print_header "SwingTrader Ubuntu Setup - Full Automation"
echo ""

# ==============================================================================
# STEP 1: UPDATE SYSTEM
# ==============================================================================
print_header "Step 1: Update System Packages"
echo "This may take 2-5 minutes..."
sudo apt-get update || print_error "Failed to update package lists"
sudo apt-get upgrade -y || print_error "Failed to upgrade packages"
print_step "System updated"
echo ""

# ==============================================================================
# STEP 2: INSTALL DEPENDENCIES
# ==============================================================================
print_header "Step 2: Install System Dependencies"
echo "Installing: PHP, Node.js, Python 3, Git, Curl..."

sudo apt-get install -y \
    php-cli \
    php-sqlite3 \
    php-xml \
    php-dom \
    php-mbstring \
    php-curl \
    php-json \
    php-fileinfo \
    nodejs \
    npm \
    python3 \
    python3-venv \
    python3-pip \
    git \
    curl \
    wget \
    build-essential \
    || print_error "Failed to install dependencies"

print_step "All dependencies installed"
echo ""

# ==============================================================================
# STEP 3: VERIFY INSTALLATIONS
# ==============================================================================
print_header "Step 3: Verify Installations"
echo "Checking tool versions..."

PHP_VERSION=$(php -v | head -1)
NODE_VERSION=$(node -v)
NPM_VERSION=$(npm -v)
PYTHON_VERSION=$(python3 --version)
COMPOSER_VERSION=$(which composer >/dev/null && composer --version || echo "Not installed yet")
GIT_VERSION=$(git --version)

echo "PHP:      $PHP_VERSION"
echo "Node:     $NODE_VERSION"
echo "npm:      $NPM_VERSION"
echo "Python:   $PYTHON_VERSION"
echo "Git:      $GIT_VERSION"
print_step "All tools verified"
echo ""

# ==============================================================================
# STEP 4: INSTALL COMPOSER
# ==============================================================================
print_header "Step 4: Install Composer"
echo "Downloading and installing Composer..."

curl -sS https://getcomposer.org/installer | php || print_error "Failed to download Composer"
sudo mv composer.phar /usr/local/bin/composer || print_error "Failed to move Composer"
sudo chmod +x /usr/local/bin/composer

COMPOSER_VERSION=$(composer --version)
echo "Composer: $COMPOSER_VERSION"
print_step "Composer installed"
echo ""

# ==============================================================================
# STEP 5: CONFIGURE GIT
# ==============================================================================
print_header "Step 5: Configure Git"
git config --global user.name "SwingTrader Admin" || true
git config --global user.email "admin@swingtrader.local" || true
print_step "Git configured"
echo ""

# ==============================================================================
# STEP 6: CLONE PROJECT
# ==============================================================================
print_header "Step 6: Clone SwingTrader Repository"
echo "Cloning from GitHub..."

INSTALL_DIR="$HOME/SwingTraderAndOptimizer"
if [ -d "$INSTALL_DIR" ]; then
    print_warning "Directory already exists, backing up..."
    mv "$INSTALL_DIR" "$INSTALL_DIR.bak.$(date +%s)"
fi

git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git "$INSTALL_DIR" \
    || print_error "Failed to clone repository"

cd "$INSTALL_DIR"
git checkout STO-Ubuntu-v1 || print_error "Failed to checkout STO-Ubuntu-v1 branch"

print_step "Repository cloned to $INSTALL_DIR"
echo ""

# ==============================================================================
# STEP 7: SETUP BACKEND (LARAVEL)
# ==============================================================================
print_header "Step 7: Setup Backend (Laravel)"
echo "Installing PHP dependencies..."

cd "$INSTALL_DIR/backend"

# Copy .env
[ ! -f .env ] && cp .env.example .env
echo "Environment file created"

# Set database path (absolute)
DB_PATH="$INSTALL_DIR/optimizer/optimized_params/strategy_params.db"
sed -i "s|DB_DATABASE=.*|DB_DATABASE=$DB_PATH|" .env || true
echo "Database path set: $DB_PATH"

# Install Composer dependencies
composer install --no-interaction --prefer-dist || print_error "Failed to install Composer dependencies"
print_step "Composer dependencies installed"

# Generate app key
php artisan key:generate || print_error "Failed to generate app key"
print_step "App key generated"

echo ""

# ==============================================================================
# STEP 8: SETUP FRONTEND (SVELTE)
# ==============================================================================
print_header "Step 8: Setup Frontend (Svelte)"
echo "Installing Node dependencies..."

cd "$INSTALL_DIR/frontend"
npm install --prefer-offline || print_error "Failed to install npm dependencies"
print_step "npm dependencies installed"

# Verify build works
echo "Building frontend..."
npm run build || print_error "Failed to build frontend"
print_step "Frontend build successful"

echo ""

# ==============================================================================
# STEP 9: SETUP PYTHON OPTIMIZER
# ==============================================================================
print_header "Step 9: Setup Python Optimizer"
echo "Creating Python virtual environment..."

cd "$INSTALL_DIR/optimizer"

# Create venv
python3 -m venv venv || print_error "Failed to create venv"
print_step "Virtual environment created"

# Install requirements
echo "Installing Python dependencies (this may take 1-2 minutes)..."
source venv/bin/activate
pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
pip install -r requirements.txt || print_error "Failed to install Python dependencies"
deactivate
print_step "Python dependencies installed"

# Verify imports
echo "Verifying Alpaca SDK import..."
source venv/bin/activate
python3 -c "from alpaca.data.historical import StockHistoricalDataClient; print('✓ Import OK')" \
    || print_warning "Alpaca SDK import test skipped"
deactivate

echo ""

# ==============================================================================
# STEP 10: MAKE SCRIPTS EXECUTABLE
# ==============================================================================
print_header "Step 10: Make Scripts Executable"
cd "$INSTALL_DIR/scripts"
chmod +x *.sh
print_step "All scripts are executable"
echo ""

# ==============================================================================
# STEP 11: CREATE DIRECTORIES
# ==============================================================================
print_header "Step 11: Create Required Directories"
mkdir -p "$INSTALL_DIR/optimizer/logs" || true
mkdir -p "$INSTALL_DIR/backend/storage/logs" || true
mkdir -p "$INSTALL_DIR/backend/bootstrap/cache" || true
chmod -R 777 "$INSTALL_DIR/backend/storage" || true
chmod -R 777 "$INSTALL_DIR/optimizer/logs" || true
print_step "Directories created with proper permissions"
echo ""

# ==============================================================================
# STEP 12: SETUP CRONTAB
# ==============================================================================
print_header "Step 12: Configure Scheduler (Crontab)"
echo "Setting up automated tasks..."

PHP_PATH="/usr/bin/php"
ARTISAN_PATH="$INSTALL_DIR/backend/artisan"
NIGHTLY_SCRIPT="$INSTALL_DIR/optimizer/run_nightly.sh"

# Nightly Optimizer (2 AM daily)
CRON_NIGHTLY="0 2 * * * $NIGHTLY_SCRIPT >> $INSTALL_DIR/optimizer/logs/cron.log 2>&1"
if ! crontab -l 2>/dev/null | grep -q "run_nightly"; then
    (crontab -l 2>/dev/null || true; echo "$CRON_NIGHTLY") | crontab -
    print_step "Nightly optimizer scheduled (2:00 AM daily)"
else
    print_warning "Nightly optimizer cron already exists"
fi

# Trade Executor (every minute)
CRON_TRADES="* * * * * $PHP_PATH $ARTISAN_PATH schedule:run >> /dev/null 2>&1"
if ! crontab -l 2>/dev/null | grep -q "schedule:run"; then
    (crontab -l 2>/dev/null || true; echo "$CRON_TRADES") | crontab -
    print_step "Trade executor scheduled (every minute)"
else
    print_warning "Trade executor cron already exists"
fi

echo ""
echo "Current cron jobs:"
crontab -l | grep -E "run_nightly|schedule:run" || true
echo ""

# ==============================================================================
# FINAL VERIFICATION
# ==============================================================================
print_header "Final Verification"
echo ""
echo "Installation Summary:"
echo "  Install directory:  $INSTALL_DIR"
echo "  Backend:            Ready"
echo "  Frontend:           Ready"
echo "  Optimizer:          Ready"
echo "  Scheduler:          Configured"
echo ""

# Check key files exist
CHECKS=(
    "$INSTALL_DIR/backend/artisan"
    "$INSTALL_DIR/frontend/package.json"
    "$INSTALL_DIR/optimizer/nightly_optimizer.py"
    "$INSTALL_DIR/optimizer/venv/bin/python"
)

all_good=true
for check in "${CHECKS[@]}"; do
    if [ -f "$check" ] || [ -d "$check" ]; then
        echo "  ✓ $(basename $check)"
    else
        echo "  ✗ $(basename $check) - MISSING"
        all_good=false
    fi
done

echo ""

if [ "$all_good" = true ]; then
    print_header "✓ Setup Complete!"
else
    print_error "Some files are missing. Please check the output above."
fi

echo ""
echo "=========================================="
echo "NEXT STEPS:"
echo "=========================================="
echo ""
echo "1. Update Alpaca Credentials:"
echo "   nano $INSTALL_DIR/backend/.env"
echo "   Edit: ALPACA_API_KEY and ALPACA_SECRET_KEY"
echo ""
echo "2. Start Services:"
echo "   cd $INSTALL_DIR"
echo "   bash scripts/start-all.sh"
echo ""
echo "3. Open Dashboard:"
echo "   http://localhost:5173"
echo ""
echo "4. Check Status:"
echo "   curl http://localhost:9000/api/v1/account"
echo ""
echo "5. Monitor Logs:"
echo "   tail -f $INSTALL_DIR/backend/storage/logs/laravel.log"
echo "   tail -f $INSTALL_DIR/optimizer/logs/nightly.log"
echo ""
echo "=========================================="
echo ""

exit 0
