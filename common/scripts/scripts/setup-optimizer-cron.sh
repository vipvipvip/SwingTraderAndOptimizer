#!/usr/bin/env bash
# Setup cron job for nightly optimizer (Linux/WSL)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OPTIMIZER_SCRIPT="$PROJECT_ROOT/optimizer/run_nightly.sh"

# Make run_nightly.sh executable
chmod +x "$OPTIMIZER_SCRIPT"

# Check if cron entry already exists
CRON_JOB="0 2 * * * $OPTIMIZER_SCRIPT"
if crontab -l 2>/dev/null | grep -q "$OPTIMIZER_SCRIPT"; then
    echo "[OK] Cron job already exists for nightly optimizer"
    crontab -l | grep "$OPTIMIZER_SCRIPT" || true
else
    echo "[*] Adding cron job for nightly optimizer at 2:00 AM daily..."
    (crontab -l 2>/dev/null || true; echo "$CRON_JOB") | crontab -
    echo "[OK] Cron job installed:"
    crontab -l | grep "$OPTIMIZER_SCRIPT"
fi

echo ""
echo "To verify: crontab -l | grep run_nightly"
echo "To remove: crontab -e and delete the line"
