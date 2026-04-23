#!/usr/bin/env bash
# Nightly Optimizer wrapper — called by cron
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/nightly.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nightly optimizer starting..." >> "$LOG"

# Use venv python if it exists, otherwise fall back to system python3
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    "$SCRIPT_DIR/venv/bin/python" nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM >> "$LOG" 2>&1
else
    python3 nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM >> "$LOG" 2>&1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Optimizer finished (exit: $?)" >> "$LOG"
