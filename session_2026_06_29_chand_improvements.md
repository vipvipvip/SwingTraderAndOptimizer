# CHAND+REG Improvements — Session Summary (Jun 29, 2026)
####### Load the CHAND improvements session and continue
## State Before

Live CHAND+REG system had been deployed ~1 month (since late May). The system was running but fragile:

- **Manual DB resets required regularly** — Alpaca positions would drift from DB state, requiring `DELETE FROM live_trades` to re-sync
- **`entry_price` was wrong** — stored pre-order `getCurrentPrice()` instead of actual fill price from Alpaca
- **Increment path never recalculated entry_price** — adding to a position kept the old entry_price, making P&L tracking incorrect
- **`positions:sync` silently failed** — `PositionCache` model had wrong table name (`position_caches` vs actual `positions_cache`), so the command appeared to succeed but wrote to the wrong table
- **Alpaca API changes** — `unrealized_pl` renamed to `unrealized_pnl`, and `side` key was removed for long positions
- **`qty <= 1` filter** blocked small/force-test trades from reconciliation
- **Orphaned open trades** — reconciliation left old open entries in DB, causing duplicate positions on next reconcile

## What Was Done

### Bug Fixes (Live System)

| File | Fix |
|------|-----|
| `swingtrader/backend/app/Services/TradeExecutorService.php:356-420` | Use `filled_avg_price` from Alpaca order response; weighted-average entry_price on increment; call `syncLiveTradesFromAlpaca()` at start of every cycle |
| `swingtrader/backend/app/Services/EquityService.php:131-260` | Full reconciliation: create missing DB entries from Alpaca positions, close stale open trades, remove `qty<=1` filter, use correct field names |
| `swingtrader/backend/app/Models/PositionCache.php:7` | Added `protected $table = 'positions_cache'` |
| `swingtrader/backend/app/Console/Commands/SyncPositions.php:30-31` | Use `unrealized_pnl` with fallback to `unrealized_pl`; handle missing `side` key |
| `swingtrader/backend/app/Console/Commands/ExecuteDailyTrades.php:51` | Call `positions:sync` after every trade cycle |

### Architecture

**Auto-Reconciliation** — Every 5-min trading cycle:
1. Fetch all filled orders from Alpaca order history
2. Create/update `live_trades` with actual `filled_avg_price`
3. Match sell orders → close corresponding open buys
4. Fetch Alpaca positions, update `positions_cache`
5. Create DB entries for Alpaca-only positions (e.g., manual trades)
6. Close stale open DB entries that don't match Alpaca

**Alpaca is the source of truth.** The DB is a cache that self-heals every 5 minutes.

### Documentation

| File | Changes |
|------|---------|
| `common/docs/How_System_Works.md` | Added Self-Healing Reconciliation section, updated live flow diagram, updated `live_trades` schema with all `strategy_signal` values, updated safety mechanisms, last updated date |
| `common/docs/MONITORING.md` | Trade executor: every 5 min (not 1 min), added reconciliation checks, added `positions_cache` section with mismatch detection, fixed all path references (`backend/` → `swingtrader/backend/`) |
| `common/docs/services_doc/emac-runner.service` | Added missing systemd unit to match installed services |

### Code Cleanup

- Deleted `swingtrader/services/optimizer/analyze_gaps.py` (one-off research)
- Deleted `swingtrader/services/optimizer/compare_entry.py` (one-off research)

### Statistical Analysis

**CHAND+REG vs Buy-and-Hold** — 503 stocks (QQQ universe), Feb 1 – Jun 26, 2026:
- Avg excess return: **+422%** (paired t-test, p=0.00002)
- **96.6%** of stocks beat BH (485/502, binomial p≈0)
- Sharpe: **1.286** (95% CI [1.254, 1.318], p≈0)
- Small effect size (Cohen's d=0.19) but overwhelming consistency
- Full reference doc: `common/docs/stats-helper.md`

## Key Decisions

- **Alpaca is source of truth** — DB is a reconcilable cache. No more manual DB resets.
- `entry_price` stored after fill confirmation via `filled_avg_price`
- Weighted-average price on position increments
- `positions:sync` runs automatically after every trade cycle
- Cron: `trades:execute-daily` every 5 min via crontab (not Laravel scheduler alone)
- Three services: CHAND+REG (5-min, QQQ/VTI/VTV), EMACrossover+MACD (30-min, separate Alpaca paper), Scanner (daily)

## Current System State

- **Open positions (Jun 29):** QQQ 65 shares (−$1,106), VTI 61 shares (−$362), VTV 137 shares (+$560)
- **Equity:** $100,738 → $99,043 (−1.7% since May 11)
- **Optimizer:** Runs nightly at 02:00 EDT via systemd timer
- **Reconciliation:** Runs every 5 min — no manual intervention needed

## Remaining Ideas / Future Work

1. **Velocity/Acceleration as confirmatory filter** — Research on `feature/Velocity-Acceleration` branch (unmerged). Add momentum confirmation to CHAND entry/exits. Summary in `common/docs/VA_vs_CHAND_comparison.md`.
2. **Time stop-loss for extended holds** — Close trades that exceed X days regardless of signal (protect against flat/dead positions).
3. **Bracket orders** — Use Alpaca's take-profit/stop-loss order types for automatic exits.
4. **Progress/learning dashboard** — Track how CHAND+REG is beating BH over time live, show win streaks, etc.
5. **EMACrossover+MACD performance review** — Check if the 30-min service is profitable or needs tuning.

## Verification

To verify the system is healthy after changes:
```bash
# Check reconciliation is running
sudo journalctl -u swingtrader-backend -n 50 | grep -i "reconcile\|sync\|RECONCILED"

# Verify positions_cache matches Alpaca
php swingtrader/backend/artisan positions:sync
php swingtrader/backend/artisan tinker --execute="print_r(\DB::table('positions_cache')->get()->toArray());"

# Check for stale open trades (should be 1 per symbol max)
psql -U swingtrader -d swingtrader -c "SELECT symbol, COUNT(*) FROM live_trades WHERE status='open' GROUP BY symbol HAVING COUNT(*) > 1;"
```

## Relevant Files

- `swingtrader/backend/app/Services/TradeExecutorService.php` — live CHAND execution + reconciliation trigger
- `swingtrader/backend/app/Services/EquityService.php` — core reconciliation engine (`syncLiveTradesFromAlpaca`)
- `swingtrader/backend/app/Models/PositionCache.php` — positions cache model
- `swingtrader/backend/app/Console/Commands/SyncPositions.php` — positions sync command
- `swingtrader/backend/app/Console/Commands/ExecuteDailyTrades.php` — trade execution command
- `common/docs/How_System_Works.md` — system architecture
- `common/docs/MONITORING.md` — operations checklist
- `common/docs/stats-helper.md` — stats test reference
- `common/docs/VA_vs_CHAND_comparison.md` — VA analysis (on feature/Velocity-Acceleration branch)
- `swingtrader/services/optimizer/parameter_optimizer.py` — backtest engine
- `swingtrader/services/ema_sma_crossover/` — 30-min EMACrossover service (separate account)
