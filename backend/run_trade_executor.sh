#!/usr/bin/env bash
# Trade Executor wrapper — called by cron
# Runs every 30 minutes during market hours (9:30 AM - 4 PM ET, weekdays)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/storage/logs"
LOG="$SCRIPT_DIR/storage/logs/trade_executor.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Trade executor starting..." >> "$LOG"

# Run Laravel command via PHP artisan (handles database bootstrapping properly)
/mnt/c/php/php.exe artisan trades:execute-daily >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Trade executor finished (exit: $?)" >> "$LOG"
