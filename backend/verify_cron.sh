#!/usr/bin/env bash
# Verify cron entries are correct

echo "=== Current Crontab ==="
crontab -l 2>/dev/null || echo "No crontab found"

echo ""
echo "=== Expected Price Fetch Entries ==="
echo "30 9 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh"
echo "0 10,11,12,13,14,15,16 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_price_fetch.sh"

echo ""
echo "=== Expected Trade Executor Entries (14 entries, every 30 min 9:30-16:00) ==="
echo "30,0 9-16 * * 1-5 /mnt/c/data/Program\ Files/SwingTraderAndOptimizer/backend/run_trade_executor.sh"

echo ""
echo "=== Count of Each Type ==="
echo "Price fetch entries: $(crontab -l 2>/dev/null | grep -c 'run_price_fetch.sh' || echo '0')"
echo "Trade executor entries: $(crontab -l 2>/dev/null | grep -c 'run_trade_executor.sh' || echo '0')"
