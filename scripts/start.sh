#!/usr/bin/env bash
# Swing Trader Application Startup
# Minimal script: just start the server
# Assumes: PHP installed, vendor/ exists, .env configured, database ready

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "Starting Swing Trader Backend..."
echo "API: http://localhost:9000"
echo "Docs: http://localhost:9000/api/documentation"
echo ""

# Ensure log directory exists
mkdir -p "$BACKEND_DIR/storage/logs"

# Start Laravel dev server
cd "$BACKEND_DIR"
exec php artisan serve --host=127.0.0.1 --port=9000
