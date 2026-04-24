#!/usr/bin/env bash
# Setup WSL cron entries for hourly price fetches (9:30 AM, 10 AM - 4 PM ET, weekdays)

BACKEND_PATH="/mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend"
SCRIPT="$BACKEND_PATH/run_price_fetch.sh"

# Create temporary cron file with new entries
TEMP_CRON=$(mktemp)

# Export existing crontab
crontab -l > "$TEMP_CRON" 2>/dev/null || true

# Remove old price fetch entries if they exist
grep -v "run_price_fetch.sh" "$TEMP_CRON" > "$TEMP_CRON.new" || true
mv "$TEMP_CRON.new" "$TEMP_CRON"

# Add price fetch cron entries
cat >> "$TEMP_CRON" << 'EOF'
# Price fetch: market open (9:30 AM ET)
30 9 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh

# Price fetch: hourly 10 AM - 4 PM ET (weekdays)
0 10 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 11 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 12 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 13 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 14 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 15 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
0 16 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh
EOF

# Install updated crontab
crontab "$TEMP_CRON"
rm "$TEMP_CRON"

echo "✓ Price fetch cron entries installed"
echo ""
echo "Schedule:"
echo "  9:30 AM ET — Market open price fetch"
echo "  Hourly 10 AM - 4 PM ET — Intra-day price fetches (Mon-Fri)"
echo ""
echo "Verify with: crontab -l"
