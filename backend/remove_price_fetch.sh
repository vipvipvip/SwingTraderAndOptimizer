#!/usr/bin/env bash
# Manually remove price fetch entries from crontab

(crontab -l 2>/dev/null | grep -v "run_price_fetch.sh" | grep -v "^# Price fetch") | crontab -

echo "✓ Price fetch entries removed"
echo ""
echo "Remaining cron entries:"
crontab -l
