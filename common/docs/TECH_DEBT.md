# Tech debt / TODO

Open items only. When one is done, delete it here (the fix belongs in git log and the
relevant doc). Add the date, where the problem lives, and what "done" looks like.
Live-path items (marked **LIVE**) need user sign-off before any change (AGENTS.md rail 1).

## Data integrity

### 1. Interior gaps in weekly/daily bars are invisible (added 2026-10-06) — **LIVE** (CoreEW)
- **Problem:** `replayLegEmaSeries` (`swingtrader/backend/app/Services/TradeExecutorService.php:1173`)
  keeps only weeks present for ALL of QQQ/VTI/VTV and drops the rest silently. A missing week
  in one ETF shifts every later EMA value and could flip a close-vs-EMA call (VTV 2026-09-28
  was a 0.3-cent miss). Nothing logs or blocks it.
- **Why undetected:** `load_prices.py` fetches from each ticker's newest bar, and
  `data_readiness.py` only checks the newest bar, so a hole in the middle is never found or
  repaired (only `load_prices.py --symbols X --full-refresh` fixes one).
- **State today:** checked 2026-10-06, QQQ/VTI/VTV each have 561 weekly bars, all exactly 7
  days apart. No gap exists now.
- **Done when:**
  - [ ] `data_readiness.py` reports interior gaps (weekly: step != 7 days; daily: missing
        NYSE sessions) for the three CoreEW ETFs, and held MTF positions.
  - [ ] `replayLegEmaSeries` returns an error (no trade, claim released, retried) if any
        symbol has fewer weeks than the aligned set, instead of dropping silently.

## Backtests / research

### 2. Backtests on the old tables — **mostly done 2026-10-07**
Repointed to `tbl_prices_*`: `backtest_topn_multitf.py`, `backtest_trio_ew.py`,
`backtest_ratchet_timing.py` (weekly+daily only), `tos_replicate.py`, `validate_prices.py`
(old-vs-new comparison now optional). Baseline cache re-cached on the new tables. Basis shifts
results (split/dividend adjusted): treat as A/B only; MTF stock top-10 moved ~28% vs the old basis.
**Deleted 2026-10-07 (dead; all recoverable from git history):** `backtest_regime_gate.py` and `audit/`
(both needed hourly bars, purged 2026-10-02), the whole `swingtrader/services/ppo/` dir + `ppo_zero_cross_study.py`
(PPO retired), `backfill_etf_daily_history.py` (superseded by `load_prices.py --symbols X --full-refresh`),
`populate_tickers.py` (wrote the dropped tables).

## Live MTF path (needs sign-off)

### 3. `runner.py::_backfill_daily` passes `--workers 10` — **LIVE**
SIP throttles above ~6 and `compute_indicators` documents <= 6. Lower to 4.

## Data

### 4. Split/dividend re-basing
Loader uses `adjustment=all`; an incremental pull cannot fix old bars re-based by a split or
dividend. Needs `load_prices.py --symbols X --full-refresh`; no automatic detection yet.

### 5. ~~Drop `zz_deprecated_scanner_tickers{,_daily}` (~2.2 GB)~~ **Done 2026-10-07**
Dropped (DB 5.1 GB -> 2.85 GB). Rollback only via the pre-drop backup the user moved out of the rotation folder.
`tbl_etf_tickers_1hour` also **dropped 2026-10-07** (its last-resort fallback was removed from
`TradeExecutorService::getDbPrice`). **Other tables still to decide:** empty `optimization_history`,
`backtest_trades`, `strategy_parameters` (code/routes still reference them).

## Cleanup

### 6. Leftovers
- Stale `Retry ... populate_tickers + compute_indicators` print in `runner.py` (~line 387).
- `backend/.env`, `.env.example` and old setup scripts still reference the removed `optimizer/` path.
- `dist/` was rebuilt for the removed optimizer button (frontend needs Node 18 via nvm).
- ~~Reinstall `swingtrader-mtf-scorer.service`~~ **Done 2026-10-07** (old `ExecStartPre` lines were harmless):
  `sudo cp swingtrader/services/mtf/systemd/swingtrader-mtf-scorer.service /etc/systemd/system/ && sudo systemctl daemon-reload`
- Hardcoded ticker counts in comments/docs drift (count is dynamic, `tbl_stock_tickers WHERE enabled`).
