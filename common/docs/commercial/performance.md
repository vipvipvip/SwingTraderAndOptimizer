# Performance sheet — P20w (CORE-LEGEMA)

> **HYPOTHETICAL, not a promise.** Live trading started 2026-09-28 on a paper account — there is **no real track record yet**. See `disclosure.md`.

> **REFRESHED 2026-10-22.** The previous sheet's +364.27% came from a script that charged costs on sells only, and the rebuilt engine briefly printed +696.82% because of a lookahead bug (it filled on the Tuesday *inside* the decision week). Both are fixed. The figures below come from the pinned convention in `swingtrader/services/backtest/FILL_CONVENTION.md`, are marked to market daily, and are enforced by `regression_check.py`. See "Refresh outcome".

**Which strategies are compared:** rounded equal-weight buy & hold of QQQ+VTI+VTV (**"B&H"**), a plain weekly equal-weight re-balance with no signals (**"A"**), and **P20w** (per-leg weekly EMA20 crossover, equal-weight among long legs). A is the benchmark that says "what did the signals actually add?"

## Headline table

**Full period: 2016-01-04 → 2026-10-20 (563 settled weeks)**

| Metric | B&H (EW) | A (weekly EW) | **P20w** | P20w vs B&H |
|---|---|---|---|---|
| Total return | +403.44% | +392.35% | **+346.80%** | −56.6pp |
| CAGR | 16.2% | 15.9% | **14.9%** | −1.3pp |
| Max drawdown | 32.6% | 33.2% | **19.5%** | **−13.1pp** |
| Calmar (CAGR ÷ MaxDD) | 0.49 | 0.48 | **0.76** | **+55%** |
| % of weeks up (settled) | 59.1% | 58.8% | 55.8% | — |
| Avg % of capital invested | 100% | 100% | **89%** | −11pp |
| Rebalance orders (total) | — | 1,743 | 1,475 | — |
| Per-leg flips (total, through 2026-10-20) | — | — | QQQ 46 · VTI 41 · VTV 65 | — |

**Recent period: 2023-06-30 → 2026-10-20 (830d)**

| Metric | B&H (EW) | **P20w** |
|---|---|---|
| Total return | +82.15% | **+76.09%** |
| CAGR | 19.9% | **18.7%** |
| Max drawdown | 18.8% | **9.4%** |
| Calmar | 1.06 | **1.98** |
| Avg % capital invested | 100% | 93% |

**The one-sentence summary that survives scrutiny:** P20w historically delivered **~86% of buy-and-hold's total return at ~60% of buy-and-hold's drawdown**, while being in cash ~11% of the time and making ~2–3 small rebalance orders per week.

Definitions: **Max drawdown** = largest daily peak-to-trough decline of the equity curve. **Calmar** = CAGR divided by Max drawdown (higher = more return per unit of pain). Both are historical hypothetical values — a 9–20% drawdown is *what happened before*, not a guarantee of a maximum.

## "Was this cherry-picked?" — the sweeps we publish

In-sample selection is the #1 objection, so we print the sweeps that expose it rather than hide them.

**Span sensitivity (that's the "20" in P20w; full period 2016→2026)**

| Span (weekly EMA) | Total return | Max drawdown | Calmar |
|---|---|---|---|
| P5w | +219.52% | 19.7% | 0.58 |
| P10w | +286.88% | **14.5%** | **0.92** |
| **P20w (live)** | **+346.80%** | 19.5% | 0.76 |
| P50w | +241.56% | 28.5% | 0.42 |

**Start-date sensitivity** (P20w vs plain weekly-EW benchmark A, from different launch dates — the family of curves, not one lucky window)

| Start | P20w | A (benchmark) |
|---|---|---|
| 2016-01-04 | +346.80% / −19.5% DD (Calmar 0.76) | +392.35% / −33.2% DD (0.48) |
| 2020-01-01 | +184.43% / −19.5% DD (0.85) | +173.94% / −33.2% DD (0.48) |
| 2021-09-20 | +84.01% / −19.5% DD (0.65) | +91.95% / −24.8% DD (0.55) |
| 2023-06-30 | +76.09% / −9.4% DD (1.98) | +82.83% / −18.7% DD (1.07) |

P20w has a **lower drawdown and higher Calmar than A at every start date tested**. A has a slightly higher total return at three of four starts (2016, 2021, 2023); P20w wins the 2020 start outright. Among spans, **P10w has the better Calmar over the full period (0.92 vs 0.76) and at the 2020/2021 starts, but gives up 12–60pp of terminal return depending on the start**; P20w wins the recent window. That trade-off, not a claim that 20 dominates every metric, is why the live span is 20 — see the turn-timing argument below.

## Non-fitted evidence: where the crossovers actually fire

The sweeps above select a parameter and report its result on the same data, so they are in-sample by construction. This section is the opposite: it measures **where the crossovers happen in the price series**, which involves no P&L and no parameter selection.

**Turn timing — weeks between a flip and the local swing extreme.** A crossover is "near a top or bottom" if it fires close to the local extreme of the surrounding ±8 weeks. Lower is closer; exactly 0 is the extreme itself.

| Span | Exit lag after top (median / mean) | Entry lag after bottom (median / mean) | Exits within 3w | Entries within 3w | Flips measured |
|---|---|---|---|---|---|
| 5w | 4w / 4.7 | 3w / 4.6 | 47.9% | 59.0% | 96 / 83 |
| 10w | 4w / 4.8 | 3w / 4.2 | 45.3% | 56.3% | 86 / 71 |
| **20w (live)** | **5w / 5.5** | **3w / 3.4** | **45.3%** | **54.5%** | **53 / 44** |
| 30w | 5w / 5.8 | 3w / 3.6 | 34.1% | 55.3% | 44 / 38 |
| 50w | 6w / 6.4 | 4w / 4.2 | 23.5% | 46.2% | 34 / 26 |

Two things this supports:

- **P20w sits at the last span before timing degrades.** Across 5w–20w the timing is broadly flat; past 20w it falls away, and at 50w only 23.5% of exits land within 3 weeks of the top. That is a structural argument for 20 that does not depend on which span returned the most.
- **The live give-back is visible and expected.** Entries land close to lows (median 3 weeks) but **exits lag tops by a median of 5 weeks**. On a chart you should expect to be out of a position for roughly a month after the high. That is the strategy's actual behaviour, not a defect.

Caveats: the ±8-week extreme window and the "nearest preceding extreme" rule both shape the absolute week counts, so the numbers are comparable *across spans*, not canonical in absolute terms. Sample size per span ranges 149 flips down to 60, so the 50w row is partly small-sample.

**Walk-forward span selection (honest, but not yet quotable).** Each fold picks the span on in-sample data and scores only the unseen period.

| Fold | In-sample | Span picked | Out-of-sample | OOS result |
|---|---|---|---|---|
| 1 | 2016-01 → 2019-12 | 15w | 2020-01 → 2021-12 | +55.79% / −12.8% DD / Calmar 1.98 |
| 2 | 2016-01 → 2021-12 | 15w | 2022-01 → 2023-12 | −0.68% / −19.3% DD / Calmar −0.02 |
| 3 | 2016-01 → 2023-12 | 10w | 2024-01 → 2026-09 | +50.73% / −11.2% DD / Calmar 1.45 |

15w was selected in 2 of 3 folds, 10w in the third; no fold picked 20w. Two of three out-of-sample windows were positive, but the 2022–23 fold lost money and no span avoided it. **These levels must not be quoted as expectations** — they come from a small number of folds, and out-of-sample Calmar above in-sample Calmar is a sign of a short sample, not an achievement. Directionally reassuring only.

**Decision: the live span stays at 20w.** The walk-forward now leans 15w (2/3), not 20w; the turn timing is flat from 5w to 20w and degrades after; and the picked 15w loses money in the 2022–23 fold. There is no evidence strong enough to move live trading, and no live change will be made without sign-off.

> **On the span sweep generally.** Picking the best-performing span from a sweep and reporting it on the same data is in-sample selection, and the reported figure is biased upward by an amount that grows with the number of spans tried. It is not a method for establishing that a shorter span is better, and no span result in this document should be read that way. The turn-timing table above exists precisely because it is not a return sweep.

## Refresh outcome (2026-10-22): what was wrong, and what changed

The rebuild produced two genuine engine bugs and one old-script bug. All three are now understood:

| | Finding |
|---|---|
| **Lookahead in the new driver** | `coreew.py` treated week W as readable on the first trading day after W's Monday, then filled on the next day — i.e. it used that week's Friday close before it was knowable. This is what printed **+696.82%**. Fixed to `action = first date ≥ W+7`, `fill = first date > action`. |
| **Old script charged buys nothing** | `backtest_trio_ew.py::run_sim` deducted cost on sells but left buy equity unchanged, under-charging the buy side by ~5bp. On current data it prints +359.22%; the symmetric engine prints **+346.80%**. The ~12pp gap is the missing buy cost. The old script is kept as a historical artifact. |
| **New harness skipped new legs** | Trims and top-ups ran in one pass, so a new leg's buy could be checked before the trims that funded it and silently skipped. Fixed to sell leavers → trim overweights → top up underweights, capped at available cash. |
| **Signal** | **Unchanged.** Flips through the 2026-09-25 anchor are still QQQ 45 · VTI 41 · VTV 63. Later weeks add QQQ 46 / VTV 65 legitimately; the gate counts through the anchor so new data is not mistaken for drift. |
| **Live config** | **Unchanged.** Still P20w. No strategy change was made. |

**Reconciliation:**

| State | Total return | CAGR | Max DD | Notes |
|---|---|---|---|---|
| Published (old script), to 2026-09-25 | +364.27% | 15.4% | −19.2% | sell-only cost accounting |
| New engine, lookahead bug | +696.82% | 21.4% | −10.3% | invalid; filled inside the decision week |
| New engine, fixed, same 2026-09-25 window | +353.09% | 15.2% | −19.5% | daily marks, symmetric 5bp/side |
| **New engine, fixed, to 2026-10-20** | **+346.80%** | **14.9%** | **−19.5%** | current headline |

On the same window the corrected drawdown (−19.5%) is within 0.3pp of the published −19.2%, and the corrected return is 11pp lower — almost exactly the buy-side cost the old script omitted. The remaining ~6pp to today's headline is three weeks of market drift. **The strategy's shape was not an artifact — the old level was slightly too high.** The +696.82% figure is retired permanently.

**Engine validation that is trustworthy:** buy-and-hold through the new harness returns +403.44% / 16.2% CAGR against the published +410.41% / 16.4% — agreement within ~2% on a benchmark with no signal dependence. The execution engine is sound.

## What we tested and rejected (the research graveyard — disclosed honestly)

| Variant | Idea | Full-period result | Why rejected |
|---|---|---|---|
| **P20 (daily closes)** | Same crossover, decided on daily closes instead of settled weekly | +144.46% / −31.2% DD, ~1,124 buys *(pre-refresh, not recomputed)* | Churned: 30 flips/leg/yr, ~55% of the return, nearly buy-and-hold's drawdown. **The exact reason the strategy is weekly.** |
| P10w (weekly, span 10) | Faster trigger | +286.88% / −14.5% DD | Lower return than P20w, though better Calmar |
| P50w (weekly, span 50) | Slower trigger | +241.56% / −28.5% DD | Worse DD, misses fast exits |
| EG100 (a whole-book EMA100 gate, its predecessor) | One switch for all three | +268.83% / −16.1% DD *(pre-refresh, not recomputed)* | Retired 2026-09-28 in favor of P20w after comparison |
| Variant S (weekly ratchet) | Monotone peak-ratchet, no reset | — | Retired 2026-09-27 (see AGENTS.md) |

The pattern across all of them is one and the same: **trend-following on settled weekly bars is robust; daily-frequency variants pay a churn tax.** P20w is the survivor, chosen for the highest full-period return with a drawdown about 60% of buy-and-hold's, not by a single pretty window.

## Costs and fill assumptions (where backtest ≠ live)

- Backtest fills at the **next-day close** of the decision; the live system fills during **Monday's session** via real market orders. Queues, stale quotes, and thinner early-Monday liquidity can move live fills a few basis points. The 0.05%/side cost model absorbs the typical case but **not** all of it.
- **The fill convention is pinned** in `FILL_CONVENTION.md` and enforced by `regression_check.py` (`weekly` rebalance, `next-close`, `rebalance-orders`, symmetric 5bp/side).
- Survivorship is near-zero here (QQQ/VTI/VTV are large-cap instruments with full history in the test period) — but the trio's *specific* return pattern is not a guarantee the strategy will behave identically in a different regime.
- The 9.4% / 19.5% drawdowns are *daily equity-curve* drawdowns under the backtest's exact fill rules; real-world drawdowns can be larger.
- Signal logic is **shared with live trading**, not reimplemented: the series comes from PHP `TradeExecutorService::replayLegEmaSeries()`, the same code path `trades:execute-leg-ema` runs. A parity gate (`swingtrader/services/backtest/parity_check.py`) fails if live and backtest stop binding to the same implementation.

## Roll forward metric sheet (maintain from the live paper record)

Once the live **paper** record (started 2026-09-28) builds out, this sheet gets a second, clearly separate track:

- Live equity curve, live MaxDD since go-live, live win rate vs the backtest's "weeks up" 55.8%, live fill slippage vs the 0.05% model, per-leg flip accuracy against the backtest signal.

## Provenance

| | |
|---|---|
| Published figures | Refreshed 2026-10-22 under the pinned convention |
| Data refresh | `tbl_prices_daily` (3,634,972 rows, through 2026-10-21) / `tbl_prices_weekly` (753,623 rows, through 2026-10-12), validated |
| Signal verified | PHP `replayLegEmaSeries` — flips through 2026-09-25 are QQQ 45 · VTI 41 · VTV 63; through 2026-10-20, 46/41/65 |
| Engine | `swingtrader/services/backtest/coreew.py`, `harness.py`, `parity_check.py` |
| Turn timing + walk-forward | `swingtrader/services/backtest/walkforward.py` (reads the same PHP series; turn timing is P&L-independent) |
| Regression gate | `swingtrader/services/backtest/regression_check.py` — pins signal flips exactly, B&H within tolerance, P20w loosely |
| Fill convention spec | `swingtrader/services/backtest/FILL_CONVENTION.md` |
| Refresh date | 2026-10-22 |

**Sibling documents were refreshed with these figures on 2026-10-22:** `disclosure.md`, `faq.md`, `regime_matrix.md`, `coreew_family.md`, `TRADING_STRATEGIES.md`, `OPERATING_RULES.md`, and `HANDOFF_commercialization.md`. Historical experiment tables (the 2026-09-28 half-trim study and the old fill-parity paragraph in `coreew_family.md`) are intentionally left as measured and labeled pre-refresh. `one_pager.md` and `commercial/README.md` carry no headline levels. The direction of the story does not change (P20w ≈ 86% of B&H's return at ~60% of its drawdown); the levels move by ~11pp on return and ~0.3pp on drawdown over the old window.
