#!/usr/bin/env bash
# CoreEW intraday rebalance — manual run helper.
#
# Usage:
#   ./coreew_rebalance.sh                # live run (default drift 0.5%)
#   ./coreew_rebalance.sh --dry-run      # preview, no orders
#   ./coreew_rebalance.sh --override     # force exact rebalance now (drift 0)
#   ./coreew_rebalance.sh --drift=1.0    # custom drift threshold %
#   ./coreew_rebalance.sh --dry-run --drift=0.8
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ARTISAN="$PROJECT_ROOT/swingtrader/backend/artisan"
PHP_BIN="/usr/bin/php"

if [ ! -f "$ARTISAN" ]; then
    echo "artisan not found at $ARTISAN" >&2
    exit 1
fi

cd "$PROJECT_ROOT/swingtrader/backend"
$PHP_BIN "$ARTISAN" trades:execute-EW-ETF "$@"
