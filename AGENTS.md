# Landing — SwingTraderAndOptimizer

> **Resume current work:** S1 full replace 2026-11-20 (MTF emasma ETF + MTF-stock/CMO Bounce40 replaced on the same 10:25 timers by `s1_live.py`). Daily Signal spec `common/docs/BUY_SELL_TRIGGERS.md` §3 (WCO∧DCO) and **CoreEW LegEMA P20w go-live** 2026-09-28 (P20w LIVE on #PA3GKZYLVO68, replacing EG100). **Commercialization (retail): `common/docs/HANDOFF_commercialization.md` + `common/docs/commercial/`.** **Explosion/jerk research (2026-11-07): `common/docs/EXPLOSION_SIGNAL.md`** — researched tool only, not live. Prior: `common/docs/HANDOFF_CoreEW_rename.md`.

## Objective
Find/trade the best entry across all strategies via systematic backtesting, scanner UI, and live automated execution. Explorer Dashboard unifies signals from all strategies (CoreEW/MTF/Daily) with an Early breakout column.

## Context model — read the doc for your work, don't carry the repo
Concerns are decoupled; each area owns its detail in `common/docs/`. **Start a task by reading the section relevant to it** from `common/docs/OPERATING_RULES.md` (full operating rules + critical context + file index, grouped verbatim from the old AGENTS.md), plus the area's own doc below. AGENTS.md is now only the index + safety rails below.

| Work area | Read first |
|---|---|
| Any code / live-service change | `OPERATING_RULES.md` (all rules) + `services_doc/README.md` (live timers/services) |
| CoreEW code/backtests (P20w live) | `coreew_family.md` (full narrative/history/decisions) + `OPERATING_RULES.md` CoreEW bullets |
| MTF ETFs (S1 daily-entry / settled-weekly-exit) | `OPERATING_RULES.md` S1/MTF bullets |
| MTF stocks (S1 daily-entry / settled-weekly-exit) | `OPERATING_RULES.md` S1/MTF bullets |
| Scanner / Explorer / dashboard | `OPERATING_RULES.md` Scanner files + `scanner/` code |
| Daily Signal | `OPERATING_RULES.md` Daily-Signal bullets + `BUY_SELL_TRIGGERS.md` §3 |
| Commercialization | `HANDOFF_commercialization.md` + `commercial/` |
| Explosion/jerk signal research (MRNA/QQQ/AGO; weekly+daily) | `EXPLOSION_SIGNAL.md` + `common/scripts/imminent_probability.py` |
| Strategy history/decisions | `TRADING_STRATEGIES.md`, `coreew_family.md`, `perf_explanations.md`, git log |
| Key routing / accounts | `OPERATING_RULES.md` Critical Context + `ALPACA_KEYS.md` |

## Safety rails — never these, in any work
1. **Backtest returns are NOT trustworthy as returns** — relative signal quality + replicable-picks only; **A/B only**; settled-weekly rule (`OPERATING_RULES.md`). **Never change the live S1 path without user sign-off.**
2. **CoreEW signal is PHP-canonical**: `backtest_trio_ew.py --leg-ema`/`--ema-gate` consume the artisan series — never re-implement in Python; any new CoreEW variant must be added in PHP; P{span}d daily path is dead-end/never live.
3. **Live fill discipline:** never record a DB trade or Slack claim until `waitForOrderFill` confirms `status=filled`; `rebalanceTrim` returning 0 = not filled; no live orders during 09:30–10:00 ET warm-up.
4. **Dedupe/data integrity:** `save_pending` deletes all unconsumed for the mode before INSERT (never restore same-sig_date DELETE); CoreEW week claim on `coreew_runs` via `insertOrIgnore` (dry-run never claims; `--override` releases).
5. **Settled bars only:** validate DCO flips on `date < today`, never live/partial; S1 weekly exit uses `bar_date + 7 <= sig_date`. Hourly data is never a live signal.
6. **`php artisan migrate` FAILS in this repo** — apply new migrations with `--path=...` (stale migrations table vs raw-SQL tables).
7. **Uptime:** no box-enforced power window; mornings fragile (scanner-update fires on boot ~09:32; boot after 10:25 = **no MTF/CMO that day**, since `mtf-executor` and `cmo-bounce` are `Persistent=false` on purpose). Not all timers are `Persistent` — see the split table in `common/docs/services_doc/README.md`. Do not design schedules around 17:10.
8. **Engine constants:** EMA=10, SMA=40, COST=0.0005, CAPITAL=100000. Universe = 1,422 stocks + 28 ETFs (1,450 enabled; count is dynamic: `tbl_stock_tickers WHERE enabled`).

## Critical context
- Laravel on port 9000; Explorer `http://localhost:9000/scanner/explorer` (data `/scanner/explorer-data?mode=stock|etf`); clear `swingtrader/backend/storage/framework/{cache,views}/` after blade changes (NOT `scanner/backend/`).
- **Live:** P20w `trades:execute-leg-ema --span=20` (systemd Mon–Fri 10:05 ET, Slack `[CoreEW-LegEMA]`); S1 daily-entry / settled-weekly-exit on both paper legs 10:25 ET via existing timer entrypoints (`s1_live.py`; Slack `[S1-ETF]` / `[S1-STOCK]`) — ETF handover was one-time and is complete (2026-11-20→11-24); auto-handover removed 2026-11-24, stock account expected flat; no auto-handover on either leg, explicit `--handover` only;
 Daily Signal 5 PM (Slack only, no orders); Trigger Levels report 10:00 + 17:05 (Slack only, `trigger_levels.py`). **Retired:** MTF emasma ETF and MTF-stock/CMO Bounce40 (replaced by S1 2026-11-20), EG100 (09-28), variant S (09-27), EMAC/MTCS, PPO.
- **Accounts (all Alpaca paper):** CoreEW #PA3GKZYLVO68; S1 stocks (formerly MTF/CMO stocks) #PA368CPXNS13; S1 ETFs #PA3U8GZ96PEN; live Slack = acts on each weekly action / daily recap.
- Engines, indexes, keys, fill details, known edges: → `OPERATING_RULES.md`.