#!/bin/bash
# Setup nightly cron job for parameter optimization
# Run this once to schedule the nightly optimizer

# Get the absolute path to the project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create a wrapper script for cron
cat > "$PROJECT_DIR/nightly_optimizer_cron.sh" << 'EOF'
#!/bin/bash
# Cron wrapper for nightly optimizer

PROJECT_DIR="/c/data/Program Files/Alpaca-API-Trading"
cd "$PROJECT_DIR"

# Activate virtual environment and run optimizer
source venv/Scripts/activate
python nightly_optimizer.py >> "$PROJECT_DIR/logs/nightly_optimization.log" 2>&1

# Log the run
echo "Optimization run at $(date)" >> "$PROJECT_DIR/logs/nightly_runs.log"
EOF

chmod +x "$PROJECT_DIR/nightly_optimizer_cron.sh"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

echo "Cron setup complete!"
echo ""
echo "To schedule nightly runs at 4 AM, add this to your crontab:"
echo "0 4 * * * $PROJECT_DIR/nightly_optimizer_cron.sh"
echo ""
echo "To edit crontab, run: crontab -e"
echo ""
echo "Manual run (anytime): python $PROJECT_DIR/nightly_optimizer.py"
