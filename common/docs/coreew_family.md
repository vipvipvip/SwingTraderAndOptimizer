# CoreEW strategy family — full narrative

Deep-dive for the CoreEW trio (QQQ/VTI/VTV) strategies and their evolution. **AGENTS.md keeps only the operational essentials; this file is the source of truth for the "why" and the history.** Statuses mirror the live state.

## Current: Variant P — "LegEMA" P20w (LIVE 2026-09-28)

`runLegEma(dryRun, span, override)` + `replayLegEmaSeries()`/`legEmaTrail()`/`legEmaState()` in Laravel `TradeExecutorService`. Per-leg binary crossover QQQ/VTI/VTV, each long only while its OWN settled weekly close > its `ewm(span=20, adjust=False)` EMA (alpha 2/21, seeded at first close); OFF legs idle in cash, ON legs rebalanced to EQUAL WEIGHT every new settled week (variant A's weekly trim applied to the long set).

Settled weeks only (`d.date + 7 <= CURRENT_DATE`), so week-W's Friday close decides and is acted from the following Monday. Scheduled Mon–Fri 10:05 ET after the 30-min warm-up gate.

**Parity with the backtest is exact BY CONSTRUCTION:** `backtest_trio_ew.py --leg-ema N` shells out to `trades:coreew-leg-ema-series` and consumes its per-week state — the signal is never re-implemented (any new variant must be added in PHP where live and backtest share it). P20w parity to the prototype: 813d +79.26%/−9.4%, 2016+ +364.27%/−19.2% vs A +396.17%/−33.2% and EG100 +268.83%/−16.1% — exact to the hundredth (P10w 813d +54.05%/−12.2%; per-leg flips QQQ=45/VTI=41/VTV=63 over 2016+).

**Dedupe = atomic DB claim on `coreew_runs`** (unique `(strategy, span, week)`) — `insertOrIgnore` → PG `ON CONFLICT DO NOTHING` decides the single weekly actor cluster-safely (replaced the old `storage/coreew_leg_ema_last_week.txt` marker, which does not survive a multi-instance deployment; the DB is shared). Errors → claim released → retry next tick; dry-run never claims/writes; `--override` releases the week's claim to force a re-action.

Fill discipline: trim BEFORE top-up, exits via `rebalanceTrim` when a DB trade exists else direct market sell gated on `waitForOrderFill`, buys via `rebalanceTopUp`.

The DAILY-close per-leg CO (P{span}d) is a research dead end (whipsaw vs A) and is intentionally the only piece still computed in Python — it will never go live.

## Predecessor: EG100 (variant "CoreEG100") — RETIRED 2026-09-28

Shortest-lived strategy: live 2026-09-27 → replaced 09-28 by LegEMA P20w. `runEg100Gate(dryRun, span, override)` + `replayIndexEgGate()` + `indexEgGateState()`/`indexEgTrail()`: equal-weight (daily-rebalanced) QQQ/VTI/VTV index from settled daily closes (seeded 1.0, day-0 return 0) vs its own `ewm(span=100, adjust=False)` EMA (alpha 2/101, seeded at first index value) as a PURE crossover — no band. LONG = all 3 at equity/N, OFF = all flat; whole-book decision, not per-leg. Settled bars only (`date < CURRENT_DATE`) so a day-t decision acts in session t+1.

**Parity with the backtest was exact BY CONSTRUCTION (2026-09-28):** `backtest_trio_ew.py --ema-gate/--ema-band` shells out to `trades:coreew-eg-series` and consumes the `series` trail — the pandas EG re-implementation was deleted (any new trio-gate variant must be added in PHP `replayIndexEgGate`/`indexEgTrail`).

Backtest vs weekly EW rebalance (re-verified 2026-09-28 on the parity-exact signal, decide t / fill t+1 close / 0.05% side / weekly EW trim): PURE EG100 = 3y +75.5%/−8.5% DD, 5.5y +87.9%/−18.2% DD, holdout 2016-11→2021-04 +62.3%/−22.4% DD. **⚠ The earlier figure (+85.6%/−12.1%, "64% of DD removed, 70% of return kept") did NOT reproduce — its −12% DD matches the ±3% band variant instead (+106.1%/−12.9% on the same holdout), so the old holdout number was almost certainly a band-variant result mislabeled as pure.**

Cutover dedupe was the newest flip date (`storage/coreew_eg100_last_flip.txt`, deleted 2026-09-28). Exit = `rebalanceTrim` when a DB trade exists else direct market sell gated on `waitForOrderFill`. Shared the 30-min opening warm-up gate (09:30–10:00 ET). Rollback = uncomment the retired EG100 crontab line — the account books hand over cleanly to P20w because both target EW among the 3 legs.

## Predecessor: Variant S (monotone weekly ratchet) — RETIRED 2026-09-27

`runMonotoneGate`/`replayMonotoneGate`, `trades:execute-EW-gate`, `COREEW_GATE_MULT`. Monotone weekly ratchet (peak − 2·ATR), per leg. Replaced by CoreEG100; code retained off the cron.

## Benchmark: Variant A (plain weekly EW rebalance)

A's machinery — no indicators/crossover — is the engine under P20w and the official benchmark. Backtest A (813-d default window): +83.68%/−18.7% DD; full 2016+ +396.17%/−33.2% DD.

## Decision 2026-09-28 (EW review — historical)

Variant A preferred model/benchmark and beats the gate on return in-sample, but live stayed on EG100 at the time (elevated market; wanted to observe the gate rebalancing in that regime). Now moot: P20w replaced EG100 that same day, using A's weekly-EW machinery + per-leg crossover.

## Decision 2026-09-28 #2 (variant P, "LegEMA") — go-live

P{span}w = A's weekly-EW machinery + a PER-LEG binary crossover. **P20w is the pick** — full 2016→2026 (560 settled weeks): +364.27%/−19.2% DD vs A +396.17%/−33.2% and EG100 +268.83%/−16.1% (~92% of A's return at ~58% of A's DD; strongest weekly variant in every starts-sweep 2016→2022). Go-live executed 2026-09-28 (~14:07 ET) on #PA3GKZYLVO68: handover run trimmed the EG100-equal book to P20w EW targets in one shot (dedupe recorded week 2026-09-21), EG100 crontab line commented out, `swingtrader-legema.{service,timer}` created in `swingtrader/services/mtf/systemd/` (install into `/etc/systemd/system` needs sudo — single `systemctl enable --now` command). Slack `[CoreEW-LegEMA]`.