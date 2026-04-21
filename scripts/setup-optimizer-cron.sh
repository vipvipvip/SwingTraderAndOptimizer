#!/usr/bin/env bash
# Setup Nightly Optimizer on Linux via cron
# Run once to schedule the nightly optimizer

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OPTIMIZER_DIR="$PROJECT_ROOT/optimizer"
RUN_SCRIPT="$OPTIMIZER_DIR/run_nightly.sh"

echo "Setting up nightly optimizer cron job..."
echo "Project root: $PROJECT_ROOT"
echo "Optimizer dir: $OPTIMIZER_DIR"
echo "Run script: $RUN_SCRIPT"
echo ""

# Verify script exists
if [ ! -f "$RUN_SCRIPT" ]; then
    echo "ERROR: $RUN_SCRIPT not found!"
    exit 1
fi

# Make executable
chmod +x "$RUN_SCRIPT"
echo "✓ Made $RUN_SCRIPT executable"

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -q "run_nightly.sh"; then
    echo "✓ Cron entry already exists"
    echo ""
    echo "Current cron entry:"
    crontab -l | grep run_nightly.sh
else
    # Add cron entry: run at 2:00 AM daily
    CRON_ENTRY="0 2 * * * $RUN_SCRIPT"
    (crontab -l 2>/dev/null || true; echo "$CRON_ENTRY") | crontab -

    echo "✓ Added cron entry"
    echo ""
    echo "Cron entry added:"
    crontab -l | grep run_nightly.sh
fi

echo ""
echo "Setup complete!"
echo ""
echo "Manual trigger (anytime): $RUN_SCRIPT"
echo "View logs: tail -f $OPTIMIZER_DIR/logs/nightly.log"
echo "List cron jobs: crontab -l"
echo "Edit cron jobs: crontab -e"
echo "Remove: crontab -e  (and delete the run_nightly.sh line)"
