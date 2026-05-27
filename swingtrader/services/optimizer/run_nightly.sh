#!/usr/bin/env bash
# Nightly Optimizer wrapper — called by cron
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/nightly.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nightly optimizer starting..." >> "$LOG"

# Wait for PostgreSQL to be ready (Docker container may still be starting)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for PostgreSQL..." >> "$LOG"
for i in $(seq 1 30); do
    if (echo > /dev/tcp/127.0.0.1/5432) 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] PostgreSQL ready." >> "$LOG"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: PostgreSQL not ready after 150s, aborting." >> "$LOG"
        exit 1
    fi
    sleep 5
done

# Use explicit path to venv's python (cron doesn't inherit shell aliases/functions)
PYTHON="$SCRIPT_DIR/venv/bin/python"
"$PYTHON" nightly_optimizer.py --timeframe 1Day --tickers QQQ VTI VTV >> "$LOG" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Optimizer finished (exit: $EXIT_CODE)" >> "$LOG"
