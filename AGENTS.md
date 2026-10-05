# Landing — SwingTraderAndOptimizer

> **Resume current work:** `common/docs/HANDOFF_DailySignal_All3CO.md` (⛔ SUPERSEDED — HCO removed 2026-10-02, Daily Signal is now 2-CO WCO∧DCO; live spec is `common/docs/BUY_SELL_TRIGGERS.md` §3) and **CoreEW LegEMA P20w go-live** 2026-09-28 (P20w LIVE on #PA3GKZYLVO68, replacing EG100). **Commercialization (retail): `common/docs/HANDOFF_commercialization.md` + `common/docs/commercial/`.** Prior: `common/docs/HANDOFF_CoreEW_rename.md`.

## Objective
Find/trade the best entry across all strategies via systematic backtesting, scanner UI, and live automated execution. Explorer Dashboard unifies signals from all strategies (CoreEW/MTF/Daily) with an Early breakout column.

## Context model — read the doc for your work, don't carry the repo
Concerns are decoupled; each area owns its detail in `common/docs/`. **Start a task by reading the section relevant to it** from `common/docs/OPERATING_RULES.md` (full operating rules + critical context + file index, grouped verbatim from the old AGENTS.md), plus the area's own doc below. AGENTS.md is now only the index + safety rails below.

| Work area | Read first |
|---|---|
| Any code / live-service change | `OPERATING_RULES.md` (all rules) + `services_doc/README.md` (live timers/services) |
| CoreEW code/backtests (P20w live) | `coreew_family.md` (full narrative/history/decisions) + `OPERATING_RULES.md` CoreEW bullets |
| MTF stocks/ETFs (emasma top-N) | `OPERATING_RULES.md` MTF bullets |
| Scanner / Explorer / dashboard | `OPERATING_RULES.md` Scanner files + `scanner/` code |
| Daily Signal | `OPERATING_RULES.md` Daily-Signal bullets + `HANDOFF_DailySignal_All3CO.md` |
| Commercialization | `HANDOFF_commercialization.md` + `commercial/` |
| Strategy history/decisions | `TRADING_STRATEGIES.md`, `coreew_family.md`, `perf_explanations.md`, git log |
| Key routing / accounts | `OPERATING_RULES.md` Critical Context + `ALPACA_KEYS.md` |

## Safety rails — never these, in any work
1. **Backtest returns are NOT trustworthy as returns** — relative signal quality + replicable-picks only; **A/B only**; settled-weekly rule (`OPERATING_RULES.md`). **Never change the live emasma path without user sign-off.**
2. **CoreEW signal is PHP-canonical**: `backtest_trio_ew.py --leg-ema`/`--ema-gate` consume the artisan series — never re-implement in Python; any new CoreEW variant must be added in PHP; P{span}d daily path is dead-end/never live.
3. **Live fill discipline:** never record a DB trade or Slack claim until `waitForOrderFill` confirms `status=filled`; `rebalanceTrim` returning 0 = not filled; no live orders during 09:30–10:00 ET warm-up.
4. **Dedupe/data integrity:** `save_pending` deletes all unconsumed for the mode before INSERT (never restore same-sig_date DELETE); CoreEW week claim on `coreew_runs` via `insertOrIgnore` (dry-run never claims; `--override` releases).
5. **Settled bars only:** validate DCO flips on `date < today`, never live/partial. (HCO removed 2026-10-02 — Daily Signal is WCO∧DCO only.) MTF is weekly-only by design.
6. **`php artisan migrate` FAILS in this repo** — apply new migrations with `--path=...` (stale migrations table vs raw-SQL tables).
7. **Uptime:** no box-enforced power window; mornings fragile (scanner-update fires on boot ~09:32; boot after 10:25 = **no MTF that day**, since `mtf-executor` is `Persistent=false` on purpose). Not all timers are `Persistent` — see the split table in `common/docs/services_doc/README.md`. Do not design schedules around 17:10.
8. **Engine constants:** EMA=10, SMA=40, COST=0.0005, CAPITAL=100000. Universe = 1,435 stocks + 28 ETFs.

## Critical context
- Laravel on port 9000; Explorer `http://localhost:9000/scanner/explorer` (data `/scanner/explorer-data?mode=stock|etf`); clear `swingtrader/backend/storage/framework/{cache,views}/` after blade changes (NOT `scanner/backend/`).
- **Live:** P20w `trades:execute-leg-ema --span=20` (systemd Mon–Fri 10:05 ET, Slack `[CoreEW-LegEMA]`); MTF top-N 10:25 (stocks+ETFs, Slack); Daily Signal 5 PM (Slack only, no orders). **Retired:** EG100 (09-28), variant S (09-27), EMAC/MTCS, PPO.
- **Accounts (all Alpaca paper):** CoreEW #PA3GKZYLVO68; MTF stocks #PA368CPXNS13; MTF ETFs #PA3U8GZ96PEN; live Slack = acts on each weekly action / daily recap.
- Engines, indexes, keys, fill details, known edges: → `OPERATING_RULES.md`.