# Handoff — CHAND → CoreEW rename (session resume)

**Date:** 2026-09-12
**Owner of record:** AGENTS.md (repo root) — read it first; this doc is the *live-state* resume guide.

## What the strategy IS now
CoreEW = a pure **weekly equal-weight trio book** on QQQ/VTI/VTV (no chandelier
exit, no signals, no optimizer, no regression). Each rebalance trims overweights
and tops-up underweights back to `equity/3` per legholism, once per eligible
weekday (marker-gated). Historically this was "CHAND" (chandelier exit); the
chandelier machinery is retired and the name is gone from the live path.

## Live account
- Alpaca paper **#PA3GKZYLVO68**, **$100,000** initial, **0 positions** (reset 2026-09-12).
- Keys: `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` in `swingtrader/backend/.env` (gitignored).
- Do NOT reuse the old paper accounts (#PA31Z71315NM/#PA3EHVX93SJT/#PA3NCXU4O2CN) — stopped/orphaned.

## Command + scheduling
- Command: **`trades:execute-EW-ETF`** — class `ExecuteEWETF` at
  `swingtrader/backend/app/Console/Commands/ExecuteEWETF.php`.
- Flags: `--dry-run` (preview w/o orders), `--override` (force any-day),
  `--force-test` (round-trip filled test).
- Day gate: **`COREEW_REBALANCE_DAYS`** in `swingtrader/backend/.env`
  (Mon=1..Sun=7, comma list; **currently `1` = Monday**, plan `5` = Friday later).
- **Essential old var name `CHAND_REBALANCE_DAYS` must NOT be used** — cmd reads `COREEW_REBALANCE_DAYS`.
- Marker (once/day): `storage_path('chand_last_rebalance.txt')` — legacy filename
  retained (harmless; only needs a rename if you're pedantic). Renaming it would
  require deleting the file once on the switchover day.
- Cron (live): `*/5 * * * * /usr/bin/php .../artisan trades:execute-EW-ETF >> /dev/null 2>&1`
  — reads `.env` per invocation (no restart needed).
- Marker file content check in `ExecuteEWETF.php:54-56`; Slack tag `[CoreEW]`.

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

## Verify checklist before/after the Monday 2026-09-14 run
1. `grep -rn 'COREEW_REBALANCE_DAYS' swingtrader/backend/.env` → `1` (Monday now).
2. Confirm cron line for `trades:execute-EW-ETF` exists (5-min).
3. Expect on Mon 2026-09-14 10:25: **one** EW rebalance — buy QQQ/VTI/VTV at
   ~$33.3K each, zero sells. Marker file written exactly once + single Slack `[CoreEW]`.
4. Optionally `php artisan trades:execute-EW-ETF --dry-run` Monday morning for full
   preview before the real run fires.
5. Verify no `[CHAND]` Slack tag / `CHAND_REBALANCE_DAYS` references remain in live path.

## Known open items (from AGENTS.md + this session)
- **`sudo systemctl disable --now swingtrader-optimizer.timer`** — **DONE**
  (2026-09-13, confirmed by user + verified `inactive (dead)`, `Loaded: ...disabled`).
  Timer can no longer fire; no stale CHAND/optimizer Slack path remains.
- Frontend Svelte rebuild needed if you changed any `.svelte` — rebuild
  `swingtrader/frontend` bundle and republish so dashboard shows CoreEW column
  (StrategyCard.svelte only needed if you want to strip the chandelier `{#if}` dead
  branch at lines 148–171; cosmetic only, live branch renders correctly without it).
- Friday plan (future): set `COREEW_REBALANCE_DAYS=5` in `.env` (no code change).

## Quick commands
```bash
# env check
grep COREEW_REBALANCE_DAYS swingtrader/backend/.env

# dry-run preview (Monday morning, before market-triggered run)
cd swingtrader/backend && php artisan trades:execute-EW-ETF --dry-run

# find any leftover live-path CHAND (should be empty in app code)
grep -rn 'CHAND\|chand' swingtrader/backend/app --include=*.php | grep -vi 'chandelier\|vendor'
```
