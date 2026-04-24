#!/usr/bin/env bash
# Price Fetch wrapper — called by cron hourly during market hours
# Fetches latest prices and saves to intra_day_prices table
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/storage/logs"
LOG="$SCRIPT_DIR/storage/logs/price_fetch.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Price fetch starting..." >> "$LOG"

# Run Laravel command via PHP artisan
/mnt/c/php/php.exe artisan prices:fetch >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Price fetch finished (exit: $?)" >> "$LOG"
