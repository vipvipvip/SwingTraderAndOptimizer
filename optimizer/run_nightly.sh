#!/usr/bin/env bash
# Nightly Optimizer wrapper — called by cron
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/nightly.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nightly optimizer starting..." >> "$LOG"

# Use explicit path to venv's python (cron doesn't inherit shell aliases/functions)
PYTHON="$SCRIPT_DIR/venv/bin/python"
"$PYTHON" nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM >> "$LOG" 2>&1
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Optimizer finished (exit: $EXIT_CODE)" >> "$LOG"
