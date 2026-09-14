# Handoff — CHAND → CoreEW rename (session resume)

**Date:** 2026-09-12 (updated 2026-09-14 for intraday drift-gated rebalancing)
**Owner of record:** AGENTS.md (repo root) — read it first; this doc is the *live-state* resume guide.

## What the strategy IS now
CoreEW = an **equal-weight trio book** on QQQ/VTI/VTV (no chandelier exit, no
signals, no optimizer, no regression). Rebalances intraday: every 5-min cron tick
while the market is open, a leg is trimmed/topped-up back toward `equity/3` only
when its deviation exceeds `COREEW_DRIFT_PCT` (0.5% of equity). Historically this
was "CHAND" (chandelier exit); the chandelier machinery is retired and the name is
gone from the live path. Weekly day-gating (COREEW_REBALANCE_DAYS + once-per-day
marker) was **replaced by intraday drift-gated rebalancing on 2026-09-14**.

## Live account
- Alpaca paper **#PA3GKZYLVO68**, **$100,000** initial, **0 positions** (reset 2026-09-12).
- Keys: `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` in `swingtrader/backend/.env` (gitignored).
- Do NOT reuse the old paper accounts (#PA31Z71315NM/#PA3EHVX93SJT/#PA3NCXU4O2CN) — stopped/orphaned.

## Command + scheduling
- Command: **`trades:execute-EW-ETF`** — class `ExecuteEWETF` at
  `swingtrader/backend/app/Console/Commands/ExecuteEWETF.php`.
- Flags: `--dry-run` (preview w/o orders), `--override` (force exact rebalance,
  threshold 0), `--drift=PCT` (per-run threshold override), `--force-test` (round-trip filled test).
- Drift gate: **`COREEW_DRIFT_PCT`** in `swingtrader/backend/.env` (default `0.5` %).
- **Old gate `COREEW_REBALANCE_DAYS` was REMOVED 2026-09-14** — do not reference it;
  the intraday command no longer day-gates or writes the once-per-day marker
  `chand_last_rebalance.txt` (that file was deleted; it was the old weekly marker).
- Cron (live): `*/5 * * * * /usr/bin/php .../artisan trades:execute-EW-ETF >> /dev/null 2>&1`
  — reads `.env` per invocation (no restart needed). Market-open check is the only gate.
- Manual wrapper: `swingtrader/services/scripts/coreew_rebalance.sh` (passthrough args).
- Slack tag `[CoreEW]` fires only when a run actually trades (drift crossed), not every 5-min tick.

## Slack / report branding
- Prefix tag: **`[CoreEW]`** (was `[CHAND]`). Stock/ETF not differentiated; single message.
- `swingtrader/services/scripts/alpaca_report.py` ACCOUNTS map uses
  `coreew` → acct `#PA3GKZYLVO68` (also used by the trio EW backtest validation).
- Explore Dashboard column header now **CoreEW** (scanner backend +
  `explorer.blade.php`); Explorer JSON key `chand` → `coreew`.

## What was deleted (verify on resume if unsure)
- DB (PostgreSQL, all CHAND-only data):
  - `live_trades` (21), `strategy_parameters` (7), `optimization_history` (507),
    `backtest_trades` (180), `positions_cache` (1), `equity_snapshots` (6744).
- Files: `swingtrader/services/optimizer/data/*.csv`, `optimizer/logs/nightly.log`,
  optimizer systemd unit (DISABLED banner), EMAC runner/backfill files.
- All rows omitted so `strategy_parameters` for QQQ/VTI/VTV trio empty → the
  dashboard StrategyCard renders the **CoreEW** branch (no chandelier params).

## NOT removed (intended legacy / still-needed)
- **Chandelier backtest engine / optimizer code** in `swingtrader/services/optimizer/` +
  the shared `TA-Lib` chandelier helpers in `TradeExecutorService`/`StrategyService`
  (lines prefixed `chandelier_*`) — used by scanner/other backtests. **Leave alone.**
- Scaffold/migration files re `chandelier_*` columns (DB schema history). **Leave.**
- Historical docs (TRADING_STRATEGIES.md §1 header / How_System_Works "CHAND+REG
  (historical)" asides / perf_explanations "CHAND was already correct") — intentional
  historical record of the prior strategy. **Leave.**

## Verify checklist (intraday mode, post-2026-09-14)
1. `grep COREEW_DRIFT_PCT swingtrader/backend/.env` → `0.5`.
2. Confirm cron line for `trades:execute-EW-ETF` exists (5-min).
3. Expect: quiet ticks → no trades, no Slack. On drift cross → trim/top-up +
   single Slack `[CoreEW]`. Marker file is no longer written (deleted).
4. Freshness monitoring: `swingtrader/backend/storage/trades_last_run.txt` mtime
   is stamped every 5-min run (market open or closed); the unified
   `common/scripts/health-check.sh` "CoreEW Intraday Rebalance" section fails if
   it goes stale (>15 min).
5. Optionally `swingtrader/services/scripts/coreew_rebalance.sh --dry-run` any time
   for a preview; plain run = live trigger at will.
6. Verify no `[CHAND]` Slack tag / `COREEW_REBALANCE_DAYS` references remain in live path.

## Known open items (from AGENTS.md + this session)
- **`sudo systemctl disable --now swingtrader-optimizer.timer`** — **DONE**
  (2026-09-13, confirmed by user + verified `inactive (dead)`, `Loaded: ...disabled`).
  Timer can no longer fire; no stale CHAND/optimizer Slack path remains.
- Frontend Svelte rebuild needed if you changed any `.svelte` — rebuild
  `swingtrader/frontend` bundle and republish so dashboard shows CoreEW column
  (StrategyCard.svelte only needed if you want to strip the chandelier `{#if}` dead
  branch at lines 148–171; cosmetic only, live branch renders correctly without it).
- Intraday drift-gated rebalance is the live driver (2026-09-14). If the weekly
  cadence is ever wanted again, restore `COREEW_REBALANCE_DAYS` day-gating + the
  once-per-day marker — the drift-threshold logic in `rebalanceEqualWeightWeekly`
  is orthogonal and keeps working either way.

## Quick commands
```bash
# env check
grep COREEW_DRIFT_PCT swingtrader/backend/.env

# dry-run preview (no orders)
cd swingtrader/backend && php artisan trades:execute-EW-ETF --dry-run

# force exact rebalance now (threshold 0)
cd swingtrader/backend && php artisan trades:execute-EW-ETF --override

# manual wrapper (same flags, passthrough)
swingtrader/services/scripts/coreew_rebalance.sh --dry-run

# find any leftover live-path CHAND (should be empty in app code)
grep -rn 'CHAND\|chand' swingtrader/backend/app --include=*.php | grep -vi 'chandelier\|vendor'
```
