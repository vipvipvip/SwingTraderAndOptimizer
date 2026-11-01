# Fill convention — the pinned specification

**Why this document exists.** On an identical signal and identical price data,
the rebuilt engine initially produced total returns of **+530.76%** and
**+696.82%** for CoreEW P20w — a **165 percentage-point spread**. Most of it was
a **lookahead bug** (both runs filled on the Tuesday *inside* the decision week,
using that week's Friday close before it was knowable) on top of a legitimate
rebalance-trigger difference. With the lookahead fixed and the trigger pinned,
the reconciled figure is +346.8%.

The lesson stands: a number that moves 165pp when unstated assumptions change is
not a measurement. This file pins the assumptions so they stop being implicit,
and `regression_check.py` enforces them.

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

## Resolution — 2026-10-22

The published P20w figures are now reproduced, and three culprits were found:

1. **Lookahead in `coreew.py` (fixed).** Week W is stamped with its Monday but
   only becomes readable on the first trading day >= W+7. The driver was
   filling on the first trading day after W, i.e. inside the decision week.
   That used the week's own Friday close as if it were known on Tuesday — a
   ~3-day lookahead that inflated P20w from ~+347% to **+696.82%**. Fixed by
   the two-step `action = first date >= W+7`, `fill = first date > action`.
2. **Sell-only cost accounting in the old published script (diagnosed).**
   `mtf/backtest_trio_ew.py::run_sim` deducts cost on sells but leaves buy
   equity unchanged, so it under-charges the buy side by ~5bp. On current data
   it prints +359.22% for P20w; the symmetric-cost engine prints **+346.8%**.
   The ~12pp gap is the missing buy cost. The old script is left as the
   historical artifact; new figures come from the harness.
3. **Trim-before-top-up (fixed).** The harness originally interleaved trims and
   top-ups in one pass, so a new leg's buy could be skipped when checked before
   the trims that funded it. It now sells leavers, trims overweights, then tops
   up underweights (capped at available cash), matching the pinned spec and
   live's stated sizing rule.

**Reconciled P20w (2016-01-04 → 2026-10-20, daily marks):**
**+346.8% / 14.91% CAGR / −19.5% max DD / Calmar 0.76**, 1,475 rebalance
orders, 89% average invested. On the published 2026-09-25 window the same
engine gives +353.09% / −19.5% DD (the 11pp gap to the old +364.27% is the
missing buy-side cost; the rest is three extra weeks of market drift).

## What IS regression-gated

Three anchors, all stable and all verified against the refresh:

| Anchor | Why it is trustworthy |
|---|---|
| **Signal flips** — QQQ 45 · VTI 41 · VTV 63, counted through 2026-09-25 | Pure function of the PHP EMA series. Detects any price-data drift. Must match **exactly**. Later weeks can add flips legitimately and are excluded from the anchor. |
| **Buy-and-hold benchmark** — ~+398% / 16.1% CAGR | No signal dependence; the new engine reproduces the published +410% / 16.4% within ~4%. Detects engine drift. |
| **P20w absolute return** — ~+346.8% / −19.5% DD | Reconciled under the pinned convention; loose tolerance so a convention or execution change fails loudly instead of silently rewriting the sheet. |

## Change protocol

1. Change `CONVENTION` in `harness.py`.
2. Update the table above in the same commit.
3. Run `python3 regression_check.py` — the signal-flip and B&H anchors must
   still pass, and the P20w figures will move; record the new number and say
   plainly in `common/docs/commercial/performance.md` that the convention
   changed.
4. Never change live trading to make a backtest number look better.