#!/usr/bin/env bash
# Nightly Optimizer wrapper — called by cron
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/nightly.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nightly optimizer starting..." >> "$LOG"

# Use Windows Python via WSL interop (has all required packages)
/mnt/c/Python/Python3143/python.exe nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Optimizer finished (exit: $?)" >> "$LOG"
