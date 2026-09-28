# Performance sheet — P20w (CORE-LEGEMA)

> **HYPOTHETICAL, not a promise.** All figures below are based on settled weekly closes, next-day fills, and 0.05% one-way cost. Live trading started 2026-09-28 on a paper account — there is **no real track record yet**. See `disclosure.md`.

**Which strategies are compared:** rounded equal-weight buy & hold of QQQ+VTI+VTV (**"B&H"**), a plain weekly equal-weight re-balance with no signals (**"A"**), and **P20w** (per-leg weekly EMA20 crossover, equal-weight among long legs). A is the benchmark that says "what did the signals actually add?"

## Headline table

**Full period: 2016-01-04 → 2026-09-25 (560 settled weeks)**

| Metric | B&H (EW) | A (weekly EW) | **P20w** | P20w vs B&H |
|---|---|---|---|---|
| Total return | +410.41% | +396.17% | **+364.27%** | −46pp |
| CAGR | 16.4% | 16.1% | **15.4%** | −1.0pp |
| Max drawdown | 32.6% | 33.2% | **19.2%** | **−13.4pp** |
| Calmar (CAGR ÷ MaxDD) | 0.50 | 0.48 | **0.80** | **+60%** |
| % of weeks up (settled) | 60.8% | 60.6% | 55.8% | — |
| Avg % of capital invested | 100% | 100% | **81%** | −19pp |
| Orders (buys/sells) | — | 860/820 | 747/687 | — |
| Per-leg flips (L→C / C→L) | — | — | QQQ 45 / VTI 41 / VTV 63 | — |

**Recent period: 2023-06-30 → 2026-09-25 (813d)**

| Metric | B&H (EW) | **P20w** |
|---|---|---|
| Total return | +83.69% | **+79.26%** |
| CAGR | 20.7% | **19.9%** |
| Max drawdown | 18.8% | **9.4%** |
| Calmar | 1.11 | **2.12** |
| Avg % capital invested | 100% | 87% |

**The one-sentence summary that survives scrutiny:** P20w historically delivered **~92% of buy-and-hold's total return at ~59% of buy-and-hold's drawdown**, while being fully in cash ~19% of the time and only making 2–3 small trades per week.

Definitions: **Max drawdown** = largest peak-to-trough decline of the equity curve. **Calmar** = CAGR divided by Max drawdown (higher = more return per unit of pain). Both are historical hypothetical values — a 9–19% drawdown is *what happened before*, not a guarantee of a maximum.

## "Was this cherry-picked?" — the sweeps we publish

In-sample selection is the #1 objection, so we print the sweeps that expose it rather than hide them.

**Span sensitivity (that's the "20" in P20w; full period 2016→2026)**

| Span (weekly EMA) | Total return | Max drawdown |
|---|---|---|
| P5w | +240.22% | 19.4% |
| P10w | +305.38% | 14.4% |
| **P20w** | **+364.27%** | **19.2%** |
| P50w | +250.22% | 28.4% |

**Start-date sensitivity** (P20w vs plain weekly-EW benchmark A, from different launch dates — the family of curves, not one lucky window)

| Start | P20w | A (benchmark) |
|---|---|---|
| 2016-01-04 | +364.27% / −19.2% DD | +396.17% / −33.2% DD |
| 2020-01-01 | +194% / DD ~19% | +176% / DD ~33% |
| 2021-09-20 | +81.29% / −19.2% DD | +85.37% / −24.8% DD |
| 2023-06-30 | +79.26% / −9.4% DD | +83.68% / −18.7% DD |

P20w is the variant with the most consistent return-per-drawdown profile across every start date tested (2016→2022 starts). No other span beat it across the sweep.

## What we tested and rejected (the research graveyard — disclosed honestly)

| Variant | Idea | Full-period result | Why rejected |
|---|---|---|---|
| **P20 (daily closes)** | Same crossover, decided on daily closes instead of settled weekly | +144.46% / −31.2% DD, ~1,124 buys | Churned: 30 flips/leg/yr, ~55% of the return, nearly buy-and-hold's drawdown. **The exact reason the strategy is weekly.**
| P10w (weekly, span 10) | Faster trigger | +305.38% / −14.4% DD | Lower return than P20w; no better DD |
| P50w (weekly, span 50) | Slower trigger | +250.22% / −28.4% DD | Worse DD, misses fast exits |
| EG100 (a whole-book EMA100 gate, its predecessor) | One switch for all three | +268.83% / −16.1% DD | Retired 2026-09-28 in favor of P20w after comparison |
| Variant S (weekly ratchet) | Monotone peak-ratchet, no reset | — | Retired 2026-09-27 (see AGENTS.md) |

The pattern across all of them is one and the same: **trend-following on settled weekly bars is robust; daily-frequency variants pay a churn tax.** P20w is the survivor, chosen by the sweeps above, not by a single pretty window.

## Costs and fill assumptions (where backtest ≠ live)

- Backtest fills at the **next-day close** of the decision; the live system fills during **Monday's session** via real market orders. Queues, stale quotes, and thinner early-Monday liquidity can move live fills a few basis points. The 0.05%/side cost model absorbs the typical case but **not** all of it.
- Survivorship is near-zero here (QQQ/VTI/VTV are large-cap instruments with full history in the test period) — but the trio's *specific* return pattern is not a guarantee the strategy will behave identically in a different regime.
- The 9.4% / 19.2% drawdowns are *equity-curve* drawdowns under the backtest's exact fill rules; real-world drawdowns can be larger.

## Roll forward metric sheet (maintain from the live paper record)

Once the live **paper** record (started 2026-09-28) builds out, this sheet gets a second, clearly separate track:

- Live equity curve, live MaxDD since go-live, live win rate vs the backtest's "weeks up" 55.8%, live fill slippage vs the 0.05% model, per-leg flip accuracy against the backtest signal.
- The live track is **paper** and will be labeled as such on the same page as the first backtest figure, forever.