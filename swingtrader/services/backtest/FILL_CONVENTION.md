# Fill convention — the pinned specification

**Why this document exists.** On an identical signal and identical price data,
two fill conventions produced total returns of **+530.76%** and **+696.82%** for
CoreEW P20w — a **165 percentage-point spread from a modelling choice alone**.
Neither reproduces the published baseline (`+364.27%` / `-19.2%` max drawdown).

A number that moves 165pp when an unstated assumption changes is not a
measurement. This file pins the assumptions so they stop being implicit, and
`regression_check.py` enforces them.

## Pinned convention

Defined once in `harness.py` as `Convention` / `CONVENTION`:

| Field | Value | Meaning |
|---|---|---|
| `rebalance_trigger` | `weekly` | Pull the book back to equal weight on **every** weekly bar — trim every overweight, top up every underweight in-play name. Matches live's stated sizing rule. |
| `price_point` | `next-close` | Fill at the **close of the first trading day strictly after** the decision date. |
| `order_counting` | `rebalance-orders` | One order per symbol per rebalance, buys and sells counted separately. |

Constants are **imported, never redefined**: `COST_PER_TRADE` (0.0005) and
`INITIAL_CAPITAL` (100000) come from `mtf/config.py`, `EMA_PERIOD`/`SMA_PERIOD`
from the same place, and the CoreEW span/EMA recursion lives in PHP
(`TradeExecutorService::replayLegEmaSeries`).

## Settled-bar rule (not negotiable)

- A decision may only use a weekly bar whose week has **fully passed**:
  `bar_date <= decision_date - 7 days`. Enforced by
  `emasma_core.settled_weekly_idx()`, shared with live.
- Never read a partial or in-progress weekly aggregate. This is the bug that
  previously produced `+636%` legacy vs `+106%` settled.
- Daily prices used for fills or signals must be `<= decision_date`.

## Signal / execution ownership

| Layer | Module | Used by |
|---|---|---|
| Strategy decisions (score, settled bar, ranking) | `mtf/emasma_core.py` | **live + backtest** |
| CoreEW crossover + trail | PHP `TradeExecutorService` | **live + backtest** |
| Portfolio mechanics (fills, sizing, cost, metrics) | `backtest/harness.py` | backtest only |

Live is **not** wired to the fill simulator, and should not be: live sends real
market orders and takes what the book gives. What must match between live and
backtest is *which names are picked and when* — and that is shared code, gated
by `parity_check.py`.

## Known-unreconciled item

**The published P20w figures cannot currently be reproduced.** Their convention
is not yet identified. Candidate differences, none confirmed:

1. Fill price (close vs open vs VWAP) — `next-open` is not yet implemented.
2. Rebalance trigger — the published sheet reports 747 buys / 687 sells, which
   sits *between* our two modes (108 and 560 rebalances). It may count
   round-trip trade legs rather than rebalance orders.
3. Cost/sizing application order.

**Consequence:** P20w absolute figures are excluded from the regression gate
until this is resolved. Publishing a new headline number before then would
replace a reconciled figure with an unreconciled one.

## What IS regression-gated

Two orthogonal anchors, both stable and both verified against the refresh:

| Anchor | Why it is trustworthy |
|---|---|
| **Signal flips** — QQQ 45 · VTI 41 · VTV 63 | Pure function of the PHP EMA series. Detects any price-data drift. Must match **exactly**. |
| **Buy-and-hold benchmark** — ~+392% / 16.1% CAGR | No signal dependence; the new engine reproduces the published +410% / 16.4% within ~4%. Detects engine drift. |

## Change protocol

1. Change `CONVENTION` in `harness.py`.
2. Update the table above in the same commit.
3. Run `python3 regression_check.py` — the signal-flip and B&H anchors must
   still pass, and the P20w figures will move; record the new number and say
   plainly in `common/docs/commercial/performance.md` that the convention
   changed.
4. Never change live trading to make a backtest number look better.