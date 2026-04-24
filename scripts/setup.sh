#!/usr/bin/env bash
# Swing Trader Application Setup
# One-time initialization: composer, .env, migrations, keys
# Run this once before first startup

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
OPTIMIZER_DIR="$PROJECT_ROOT/optimizer"

echo "=========================================="
echo "Swing Trader Application Setup"
echo "=========================================="
echo ""

# Check PHP
echo "Checking PHP..."
if ! command -v php &> /dev/null; then
    echo "✗ PHP not found. Install PHP and add to PATH."
    exit 1
fi
PHP_VERSION=$(php -v | head -1)
echo "✓ $PHP_VERSION"

# Check Composer
echo "Checking Composer..."
if ! command -v composer &> /dev/null; then
    echo "✗ Composer not found. Install from: https://getcomposer.org/download/"
    exit 1
fi
echo "✓ Composer installed"

# Create directories
echo ""
echo "Creating directories..."
mkdir -p "$BACKEND_DIR/storage/logs"
mkdir -p "$BACKEND_DIR/storage/app"
mkdir -p "$BACKEND_DIR/bootstrap/cache"
mkdir -p "$OPTIMIZER_DIR/logs"
echo "✓ Directories created"

# Install dependencies
echo ""
echo "Installing PHP dependencies..."
cd "$BACKEND_DIR"
composer install
echo "✓ Composer dependencies installed"

# Setup .env
echo ""
echo "Checking .env..."
if [ ! -f "$BACKEND_DIR/.env" ]; then
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
        echo "✓ Created .env from .env.example"
        echo "⚠ Update .env with your Alpaca credentials:"
        echo "   - ALPACA_API_KEY"
        echo "   - ALPACA_SECRET_KEY"
    fi
else
    echo "✓ .env exists"
fi

# Generate app key
echo ""
echo "Generating APP_KEY..."
if ! grep -q "APP_KEY=base64:" "$BACKEND_DIR/.env"; then
    php artisan key:generate
    echo "✓ APP_KEY generated"
else
    echo "✓ APP_KEY already set"
fi

# Run migrations
echo ""
echo "Running database migrations..."
php artisan migrate --force
echo "✓ Database ready"

# Summary
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Update .env with Alpaca API credentials"
echo "2. Run: bash scripts/start.sh"
echo ""
echo "Cron jobs (install separately):"
echo "  - 8:18 AM ET: Nightly Optimizer"
echo "  - 9:30 AM - 4:00 PM (every 30 min): Trade Executor"
echo ""
