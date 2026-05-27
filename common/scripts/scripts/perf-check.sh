#!/usr/bin/env bash
# Performance check: Backend startup time

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "Performance Check: Backend Startup Time"
echo "========================================"
echo ""
echo "Location: $BACKEND_DIR"
echo "Filesystem: $(df "$BACKEND_DIR" | tail -1 | awk '{print $1}')"
echo ""

# Kill any existing server
pkill -f "artisan serve" 2>/dev/null || true
sleep 1

# Time the startup
cd "$BACKEND_DIR"
echo "Starting server..."
START=$(date +%s%N)

# Start and wait for it to be ready
timeout 30 php artisan serve --host=0.0.0.0 --port=8000 > /tmp/perf-test.log 2>&1 &
SERVER_PID=$!

# Wait for server to be ready (max 20 seconds)
for i in {1..20}; do
    if curl -s http://localhost:9000/api/documentation > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

STOP=$(date +%s%N)
DURATION=$(( ($STOP - $START) / 1000000 ))  # Convert to milliseconds

if [ "${READY:-0}" -eq 1 ]; then
    echo "✓ Server ready in: ${DURATION}ms"
else
    echo "✗ Server failed to start"
    cat /tmp/perf-test.log
fi

# Cleanup
kill $SERVER_PID 2>/dev/null || true

echo ""
echo "Observations:"
if [ "$DURATION" -lt 2000 ]; then
    echo "  ✓ Fast startup (< 2s)"
elif [ "$DURATION" -lt 5000 ]; then
    echo "  ⚠ Moderate startup (2-5s)"
else
    echo "  ✗ Slow startup (> 5s)"
fi

echo ""
echo "Tips to improve performance:"
echo "  1. Move project to WSL native: /home/user/projects/"
echo "  2. Avoid /mnt/c/ (Windows filesystem)"
echo "  3. Use: cp -r /mnt/c/data/... /home/user/projects/"
