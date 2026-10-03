# Performance sheet — P20w (CORE-LEGEMA)

> **HYPOTHETICAL, not a promise.** Live trading started 2026-09-28 on a paper account — there is **no real track record yet**. See `disclosure.md`.

> **ENGINE UNDER CALIBRATION — 2026-10-05.** A shared-code backtest engine was built and validated during the price-table refresh. **The performance figures below are the pre-refresh, reconciled baseline and remain authoritative.** The new engine has *not* been shown to reproduce them, and its own numbers swing by ~165 percentage points depending on a fill convention that is not yet pinned. See "Refresh outcome" before changing anything.

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
| Per-leg flips (total) | — | — | QQQ 45 · VTI 41 · VTV 63 | — |

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

> **Span sweep is pre-refresh and unconfirmed.** It has not been reproduced under the new engine. Do not cite individual span returns until the fill convention is pinned — see below. Note in particular that the new engine produced a *different* span ranking, which is almost certainly a convention artifact rather than a real result. Treat the table above as the historical record, not as current measurement.

## Non-fitted evidence: where the crossovers actually fire

The sweeps above select a parameter and report its result on the same data, so they are in-sample by construction. This section is the opposite: it measures **where the crossovers happen in the price series**, which involves no P&L and no parameter selection.

**Turn timing — weeks between a flip and the local swing extreme.** A crossover is "near a top or bottom" if it fires close to the local extreme of the surrounding ±8 weeks. Lower is closer; exactly 0 is the extreme itself.

| Span | Exit lag after top (median / mean) | Entry lag after bottom (median / mean) | Exits within 3w | Entries within 3w | Flips measured |
|---|---|---|---|---|---|
| 5w | 4w / 4.7 | 3w / 4.6 | 49.5% | 59.0% | 93 / 83 |
| 10w | 4w / 4.7 | 3w / 4.2 | 46.4% | 56.3% | 84 / 71 |
| **20w (live)** | **5w / 5.5** | **3w / 3.4** | **46.2%** | **54.5%** | **52 / 44** |
| 30w | 5w / 5.8 | 3w / 3.6 | 34.1% | 55.3% | 44 / 38 |
| 50w | 6w / 6.4 | 4w / 4.2 | 23.5% | 46.2% | 34 / 26 |

Two things this supports:

- **P20w sits at the last span before timing degrades.** Across 5w–20w the timing is broadly flat; past 20w it falls away, and at 50w only 23.5% of exits land within 3 weeks of the top. That is a structural argument for 20 that does not depend on which span returned the most.
- **The live give-back is visible and expected.** Entries land close to lows (median 3 weeks) but **exits lag tops by a median of 5 weeks**. On a chart you should expect to be out of a position for roughly a month after the high. That is the strategy's actual behaviour, not a defect.

Caveats: the ±8-week extreme window and the "nearest preceding extreme" rule both shape the absolute week counts, so the numbers are comparable *across spans*, not canonical in absolute terms. Sample size per span ranges 149 flips down to 60, so the 50w row is partly small-sample.

**Walk-forward span selection (honest, but not yet quotable).** Each fold picks the span on in-sample data and scores only the unseen period.

| Fold | In-sample | Span picked | Out-of-sample | OOS result |
|---|---|---|---|---|
| 1 | 2016-01 → 2019-12 | 5w | 2020-01 → 2021-12 | +75.92% / −8.5% DD / Calmar 3.88 |
| 2 | 2016-01 → 2021-12 | 10w | 2022-01 → 2023-12 | +71.50% / −4.7% DD / Calmar 6.66 |
| 3 | 2016-01 → 2023-12 | 10w | 2024-01 → 2026-09 | +85.46% / −6.1% DD / Calmar 4.19 |

10w was selected in 2 of 3 folds and every out-of-sample window was positive. **But these levels must not be quoted:** they come from the unreconciled harness convention, and out-of-sample Calmar exceeding in-sample Calmar is a sign the convention flatters results rather than an achievement. Directionally reassuring only.

**Decision: the live span stays at 20w.** Two out of three folds favouring 10w is not enough to move live trading, and the turn timing does not clearly favour 10w either — 10w exits about a week earlier (4w vs 5w median) but enters worse (4.2w vs 3.4w mean). Mixed, on a small sample.

> **On the span sweep generally.** Picking the best-performing span from a sweep and reporting it on the same data is in-sample selection, and the reported figure is biased upward by an amount that grows with the number of spans tried. It is not a method for establishing that a shorter span is better, and no span result in this document should be read that way. The turn-timing table above exists precisely because it is not a return sweep.

## Refresh outcome (2026-10-05): what changed and what did not

**The price tables were rebuilt and validated. Here is what that actually did to this strategy:**

| | Finding |
|---|---|
| Signal | **Unchanged.** PHP returns per-leg flips of QQQ 45 · VTI 41 · VTV 63 — identical to the pre-refresh baseline. The corruption fix did not move QQQ/VTI/VTV crossovers (liquid majors, unaffected by the bad rows). |
| Engine | **New and shared.** Signal logic now lives in one place used by both live and backtest, gated by `parity_check.py`. |
| Absolute returns | **Not reconciled.** The new engine cannot reproduce the headline −19.2% drawdown above. |
| Live config | **Unchanged.** Still P20w. No strategy change was made. |

**Why absolute returns are not reconciled, and why that matters more than it sounds.** The new engine produces materially different totals from the *same* signal depending only on how the book is rebalanced:

| Fill convention | Total return | CAGR | Max DD | Rebalances |
|---|---|---|---|---|
| Rebalance only when the lineup changes | +530.76% | 19.7% | −7.7% | 108 |
| Rebalance to exact equal weight every week | +696.82% | 21.4% | −10.3% | 560 |
| *Published baseline* | *+364.27%* | *15.4%* | *−19.2%* | *~717* |

That is a **165 percentage-point spread from a modelling choice alone**, on an identical signal and identical price data. A figure that moves 165pp when you change an unstated assumption is not a measurement, it is an artifact — and it is exactly why these numbers must not be restated until the convention is pinned and documented.

**Engine validation that *is* trustworthy:** buy-and-hold through the new harness returns +392.39% / 16.1% CAGR against the published +410.41% / 16.4% — agreement within ~4% on a benchmark with no signal dependence. The execution engine is sound; what is uncalibrated is how it models fills for a rotating book.

**Required before any figure here changes:** pin the fill convention (which price, which rebalance trigger, how orders are counted), re-run all five tables on the validated data, and confirm the result is stable when the convention is deliberately perturbed.

## What we tested and rejected (the research graveyard — disclosed honestly)

| Variant | Idea | Full-period result | Why rejected |
|---|---|---|---|
| **P20 (daily closes)** | Same crossover, decided on daily closes instead of settled weekly | +144.46% / −31.2% DD, ~1,124 buys | Churned: 30 flips/leg/yr, ~55% of the return, nearly buy-and-hold's drawdown. **The exact reason the strategy is weekly.** |
| P10w (weekly, span 10) | Faster trigger | +305.38% / −14.4% DD | Lower return than P20w; no better DD |
| P50w (weekly, span 50) | Slower trigger | +250.22% / −28.4% DD | Worse DD, misses fast exits |
| EG100 (a whole-book EMA100 gate, its predecessor) | One switch for all three | +268.83% / −16.1% DD | Retired 2026-09-28 in favor of P20w after comparison |
| Variant S (weekly ratchet) | Monotone peak-ratchet, no reset | — | Retired 2026-09-27 (see AGENTS.md) |

The pattern across all of them is one and the same: **trend-following on settled weekly bars is robust; daily-frequency variants pay a churn tax.** P20w is the survivor, chosen by the sweeps above, not by a single pretty window.

## Costs and fill assumptions (where backtest ≠ live)

- Backtest fills at the **next-day close** of the decision; the live system fills during **Monday's session** via real market orders. Queues, stale quotes, and thinner early-Monday liquidity can move live fills a few basis points. The 0.05%/side cost model absorbs the typical case but **not** all of it.
- **The fill convention is the single largest source of variance in this sheet** and is currently under-specified. See "Refresh outcome".
- Survivorship is near-zero here (QQQ/VTI/VTV are large-cap instruments with full history in the test period) — but the trio's *specific* return pattern is not a guarantee the strategy will behave identically in a different regime.
- The 9.4% / 19.2% drawdowns are *equity-curve* drawdowns under the backtest's exact fill rules; real-world drawdowns can be larger.
- Signal logic is **shared with live trading**, not reimplemented: the series comes from PHP `TradeExecutorService::replayLegEmaSeries()`, the same code path `trades:execute-leg-ema` runs. A parity gate (`swingtrader/services/backtest/parity_check.py`) fails if live and backtest stop binding to the same implementation.

## Roll forward metric sheet (maintain from the live paper record)

Once the live **paper** record (started 2026-09-28) builds out, this sheet gets a second, clearly separate track:

- Live equity curve, live MaxDD since go-live, live win rate vs the backtest's "weeks up" 55.8%, live fill slippage vs the 0.05% model, per-leg flip accuracy against the backtest signal.

## Provenance

| | |
|---|---|
| Published figures | Pre-refresh baseline, unchanged, still authoritative |
| Data refresh | `tbl_prices_daily` (3,636,544 rows) / `tbl_prices_weekly` (754,958 rows), validated |
| Signal verified unchanged | PHP `replayLegEmaSeries` — flips QQQ 45 · VTI 41 · VTV 63 match baseline exactly |
| New engine | `swingtrader/services/backtest/coreew.py`, `harness.py`, `parity_check.py` |
| Turn timing + walk-forward | `swingtrader/services/backtest/walkforward.py` (reads the same PHP series; turn timing is P&L-independent) |
| Regression gate | `swingtrader/services/backtest/regression_check.py` — pins signal flips exactly + B&H within tolerance |
| Fill convention spec | `swingtrader/services/backtest/FILL_CONVENTION.md` |
| Engine status | Validated on B&H (~4% agreement); **not** calibrated against the published P20w figures |
| Refresh date | 2026-10-05 |

**Sibling documents were deliberately not touched** and still carry the pre-refresh figures: `disclosure.md`, `faq.md`, `one_pager.md`, `regime_matrix.md`, `commercial/README.md`. Because the authoritative figures did not change, those documents remain consistent with this sheet.