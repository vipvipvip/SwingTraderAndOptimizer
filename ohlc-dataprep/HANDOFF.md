# Handoff — OHLC Slope Experiment (session resume)

**Date:** 2026-09-27 (Phase 1 written earlier today; Phase 2 added the same
day; Phase 3 tested cross-slope-gap against the actual live EG100 gate,
also the same day; this update adds Phase 4 — turning the step-4 candidate
reframings into actual backtests, same day)
**Branch:** `feature/ohlc-data-prep` (still not committed to git — check
`git status`/`git log` before assuming otherwise)
**Owner of record:** `AGENTS.md` (repo root) — read it first for the wider
project; this doc is the resume guide for this specific experiment only.

## TL;DR for whoever picks this up
Phase 1 (data prep) is done and widened to the full 28-ETF universe. Phase 2
tested three different constructions of "does an OHLC slope pattern predict
a reversal": binary swing-pivot divergence, a continuous momentum-fade
score, and a cross-slope gap (one slope vs a different slope at the same
bar, rather than a slope vs its own past). **None of the three shows a
leading signal** — nothing gets ahead of price. But the third one
(`cross_slope_calc.py`) found something genuinely useful in a different
way on the 28-ETF/weekly/15%-swing test: a **fast, statistically strong
CONFIRMATION signal** that a major top/bottom is underway, firing 1-4 weeks
after the turn (p<0.0001, 70-80th percentile of its normal range) — 5-15x
faster than the live EMA10/SMA40 crossover's 9-17 week confirmation lag.

**Phase 3 (same day) took that signal to the thing it would actually need
to improve — the live EG100 gate — and the story changes.** Built the exact
synthetic EG100 index (QQQ/VTI/VTV equal-weight, verified to 1e-6 and all
103 flip dates against the live PHP gate) and re-ran the event study
anchored to EG100's own flips instead of a fresh 15%-zigzag. The gap IS
still statistically significant near EG100's flips (p<0.0001) — so the
pattern is not just a large-rare-swing artifact — but it's **CONCURRENT
with the flip, not a lead over it**: elevated from offset 0 through +3
trading days, back to baseline by +5, nothing meaningfully elevated before
offset 0. Since EG100 itself decides on that same settled bar, this doesn't
offer a speed edge over EG100 the way it does over the much-slower
EMA10/SMA40 crossover — the "5-15x faster" framing does not carry over to
EG100. See "Phase 3 findings" below; this changes what step 4 of "Plan for
next session" should mean.

**Phase 4 (same day) built and ran the actual portfolio backtests for step
4's candidate reframings.** EG100 + conviction-sized entries (keep the gate,
throttle entry size by the flip-day gap) captures 82% of EG100's return for
only a 20% drawdown cut — short of a "90% return, meaningfully reduced risk"
bar, Sharpe basically unchanged. Worse: a gate-free version that throttles
the EW trio continuously by the gap's daily percentile (no on/off gate at
all) clearly destroys value — Sharpe 0.51 vs EW B&H's 0.92, only 19% of the
return captured. That failure is structural, not a tuning problem: the gap
is a brief, event-anchored confirmation signal, not one with continuous
day-to-day information, and using it as a standing exposure dial mostly
reacts to its own noise. See "Phase 4 findings" below.

## What this is
Pattern-discovery experiment: treat Open/High/Low/Close as 4 independent price
series, compute a rolling slope for each, store them alongside the price data.
Original hypothesis (HANDOFF v1): the 4 slopes, individually or combined, may
hint at price reversals before Close alone shows it. The concrete, testable
form that took shape this session: **divergence**, the same idea as MACD/RSI
divergence — price makes a new swing extreme but the slope of that same
series doesn't confirm it (weaker momentum despite the new high/low).

## Status
- **Phase 1 (data prep): done for the full 28-ETF universe**, daily + weekly.
  Originally scoped to just VTI/QQQ/VTV to develop the method; widened this
  session once the method was validated. Nothing to re-run to get the data —
  it's already populated. Re-run `run_slope_prep.py` only if source bars
  change or window config changes.
- **Phase 2 (pattern discovery): done. Leading-signal hypothesis rejected;
  a fast confirmation signal found instead.** Full methodology and results
  below. The original goal (spot a reversal before price shows it) did not
  pan out across three different feature constructions — but the last one
  tried (cross-slope gap) is a real, strongly-significant, much-faster
  confirmation signal than what's currently live, ON THE 28-ETF/WEEKLY TEST.
- **Phase 3 (is it ready for live EG100? steps 1-3 of the plan): done.**
  Built the actual EG100 synthetic index (not proxy ETFs), verified to 1e-6
  + exact 103-flip parity against the live PHP gate, re-ran the event study
  anchored to EG100's own flips at daily resolution/trading-day offsets.
  Verdict: the confirmation signal survives (p<0.0001) but is CONCURRENT
  with EG100's own flip, not a lead over it — a materially weaker result
  than Phase 2's finding, since there's no speed edge to exploit if it fires
  the same day EG100 already decided. Stopped at the plan's step 4 decision
  point per the handoff's own instruction. See "Phase 3 findings" below.
- **Phase 4 (turn step 4's reframings into backtests): done.** Two portfolio
  variants built and run full-history against SPY B&H + EW trio B&H:
  EG100-gated conviction-sized entries (short of a 90% capture bar, Sharpe
  flat) and a gate-free continuous EW throttle (clearly destroys value,
  structurally — not a tuning problem). Neither is ready to replace
  anything live. See "Phase 4 findings" below.

## Files in this folder
- `config.py` — universe (`TICKERS`, now all 28 ETFs per
  `tbl_stock_tickers.is_etf = true` — see "Universe widening" below), slope
  window (`SLOPE_WINDOW = {'daily': 10, 'weekly': 5}`), DB creds.
- `acquire_ohlc.py` — **data acquisition, read-only.** `load_daily`/`load_weekly`
  (OHLCV only, as Phase 1 shipped them) plus `load_daily_with_slopes`/
  `load_weekly_with_slopes` (added this session — same settled-bar rules,
  also selects the 4 slope columns via a shared `_load_with_slopes` helper).
  No writes, no external API calls.
- `slope_calc.py` — **pure calc library, zero I/O.** `rolling_ols_slope`/
  `add_ohlc_slopes`. Unchanged this session.
- `schema.py` — idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Unchanged.
- `run_slope_prep.py` — the Phase 1 driver (acquire → slope_calc → bulk write).
  Unchanged code; now iterates all 28 tickers in `config.TICKERS` instead of 3.
  Run: `venv/bin/python3 run_slope_prep.py --timeframe {daily,weekly,all}`.
- `requirements.txt` — reuses `swingtrader/services/optimizer/venv` (has
  pandas/numpy/psycopg2-binary/python-dotenv/scipy — scipy is used by
  `utility_scripts/run_divergence_scan_universe.py` for Fisher's exact test).
- `run_eg_index_build.py` — **Phase 3 driver, new this session.** Builds the
  synthetic EG100 index (see `utility_scripts/eg_index_calc.py`), verifies it
  against the live gate via a read-only shell-out
  (`php artisan trades:execute-EW-gate100 --json` — traced the source, the
  `--json` branch returns before the clock check/Alpaca calls/dedupe file, so
  this is safe to re-run any time), computes slopes + cross-slope gap on top,
  and caches `eg100_index_daily.csv` + `eg100_flips.json` so downstream
  analysis doesn't need DB/PHP access. Run:
  `venv/bin/python3 run_eg_index_build.py [--span 100] [--window 10]`.
  `eg100_index_daily.csv`/`eg100_flips.json` — generated cache, not source;
  re-run the build script if scanner data or the live gate's history changes.
- `run_eg_throttle_backtest.py` — **Phase 4, new this session.** EG100's
  binary flip series stays the timing trigger; throttles entry SIZE by
  `gap_bot`'s causal percentile at the flip (linear ramp, floor..100%),
  held until the next flip; exits always go fully to cash. Also exposes
  `COST`/`CAPITAL`/`weekly_boundary_mask`/`run_throttled_sim`/`stats`,
  imported directly by `run_ew_throttle_backtest.py` (same directory, no
  `config` module collision — see Phase 3's note on why cross-folder
  imports into `swingtrader/services/mtf/` are avoided instead).
- `run_ew_throttle_backtest.py` — **Phase 4, new this session.** No EG100
  gate at all — always at least partially invested in the trio, with the
  fraction set EVERY DAY by `net_gap = gap_bot - gap_top`'s causal
  percentile (same ramp shape). Result: destroys value (see "Phase 4
  findings" #3) — kept as a documented negative result, not because it's
  worth reusing.

## `utility_scripts/` — Phase 2 reusable modules (new this session)
Same split as the Phase 1 files: pure-calc modules (zero I/O, importable by
backtests/live code) + thin drivers (I/O, CLI, printing).

**Calc modules:**
- `swing_calc.py` — `find_swings(dates, prices, threshold)`: percentage
  zigzag over ANY price series (generic — used on close for major swings, and
  on high/low for minor swings). Returns `Pivot(index, date, price, kind,
  pct_from_prior)`, `kind` = TOP/BOTTOM (+ ' (ongoing)' if the series ends
  mid-trend). Also `pinpoint_extreme(dates, highs, lows, kind)` — finds the
  single bar of the actual extreme within a window (used to find which
  DAY within a pivot's week the real high/low printed on).
- `ema_sma_calc.py` — `compute_ema_sma(closes, ema_period, sma_period)` +
  `detect_crossovers(dates, ema, sma)`. Mirrors the live convention exactly
  (`ewm(span=N, adjust=False)` / rolling mean — see
  `swingtrader/services/mtf/backtest_single_ticker.py:_cross_events`), so
  results are directly comparable to the live emasma scoring.
- `divergence_calc.py` — `check_divergence(prior, latest, kind)`: the first
  Phase 2 test, binary. Given two consecutive same-kind swing pivots of one
  series (date, price, slope) tuples, returns whether price made a new
  extreme AND the slope failed to confirm it. **Gotcha fixed this session:**
  slope values read via pandas `.iloc[]` are `numpy.float64`, so a naive
  `l_slope < p_slope` produces `numpy.bool_` — and `numpy.bool_(True) is True`
  is `False` in Python (identity check on a non-singleton type). This
  silently broke every divergence classification (`report_row`'s `is True`/
  `is False` checks) until fixed by wrapping with `bool(...)` in
  `check_divergence`. Worth remembering for any future code that stores
  comparison results from pandas/numpy values and later branches on them
  with `is`.
- `momentum_fade_calc.py` — `fade_score(prices, slopes, direction,
  rolling_window, fade_lookback)`: second Phase 2 test, continuous (not
  binary) — scores every bar on how close price is to its rolling extreme
  combined with how much the matching slope has decelerated over the last
  `fade_lookback` bars. Built to test a graded "start lightening exposure"
  signal instead of a yes/no trigger. Result: flat-to-*below* baseline
  approaching major pivots (see finding #4) — this construction is
  structurally reactive (a slope compared to its own past can only show
  deceleration after it's already happened), not leading.
- `cross_slope_calc.py` — `cross_slope_gap(slope_a, slope_b)`: third Phase 2
  test, the one that found something. Compares two DIFFERENT slopes at the
  SAME bar (e.g. `slope_high - slope_close`) instead of a slope against its
  own past, so it isn't structurally lagging the way `momentum_fade_calc` is.
  Result: a strong, fast CONFIRMATION signal 1-4 weeks after major pivots
  (see finding #5) — still not leading, but far faster than the live
  crossover. **Reused unchanged in Phase 3** against the actual EG100 index.
- `eg_index_calc.py` — **Phase 3, new this session.** Pure calc, zero I/O.
  `build_eg_index(legs)`: the synthetic EG100 close series (equal-weight
  QQQ/VTI/VTV, averaged daily returns, compounded from 1.0 — identical
  formula to `TradeExecutorService::replayIndexEgGate()`/
  `backtest_trio_ew.py`'s `ema_gate_series()`), PLUS synthetic Open/High/Low
  (no live-code equivalent exists — see "Phase 3 findings" #1 for the
  construction and its order-preservation proof). Also `ema()`/
  `crossover_state()` — the pure EMA(span)/no-band-crossover convention
  EG100 uses, for the parity check in `run_eg_index_build.py`.
- `eg_index_acquire.py` — **Phase 3, new this session.** Thin I/O:
  `load_eg_legs()` (reuses `acquire_ohlc.load_daily` for QQQ/VTI/VTV) +
  `fetch_live_flip_ground_truth()` (the read-only `--json` shell-out).
- `run_eg_flip_event_study.py` — **Phase 3, new this session.** Same
  event-study machinery as `run_cross_slope_study.py` (imports `collect`/
  `report` from `run_fade_score_study.py` unchanged), but anchored to
  EG100's own 103 flips (from `eg100_flips.json`) instead of a fresh
  15%-zigzag, with offsets in TRADING DAYS instead of weeks (the `(wk)`/
  "weeks" labels printed by the reused `report()` function are cosmetic
  leftovers — the offsets passed and displayed are trading-day counts).

**Driver scripts (read-only, no writes):**
- `run_swing_scan.py` — prints major swing tops/bottoms for given ticker(s)/threshold.
- `run_crossover_alignment.py` — pairs each swing pivot with the weekly
  EMA10/SMA40 crossover that would confirm it; reports lag in weeks and how
  much of the move was missed by the time the crossover fires. Also flags
  "stale" pivots where the crossover state was already in the expected
  direction at the pivot bar (no fresh signal to measure).
- `run_daily_pinpoint.py` — within a swing pivot's Monday-stamped weekly
  bar, finds which actual DAY the high/low printed on using daily OHLC, and
  prints the daily slope trajectory around it.
- `run_divergence_scan.py` — the single-ticker divergence test: for each
  major pivot, compares the two most recent minor swing pivots (of the
  matching high/low series) and checks for divergence, against a baseline
  rate computed from ALL minor-pivot pairs (not just ones near a major
  pivot) — the baseline comparison is what actually tests the hypothesis,
  not just whether divergence "shows up."
- `run_divergence_scan_universe.py` — same test, pooled across all of
  `config.TICKERS`, plus a Fisher's exact test (prior/latest divergence rate
  near major pivots vs. baseline rate) per side (tops/bottoms).
- `run_fade_score_study.py` — event-study driver for `momentum_fade_calc`:
  for each major pivot, samples the fade score at offsets (default
  -12..0 weeks) and compares the pooled distribution at each offset against
  the feature's own all-time baseline distribution (Mann-Whitney U +
  average percentile). Exposes reusable `collect()`/`report()` helpers that
  `run_cross_slope_study.py` imports directly rather than duplicating.
- `run_cross_slope_study.py` — same event-study machinery (imports
  `collect`/`report` from `run_fade_score_study.py`), applied to
  `cross_slope_calc.cross_slope_gap` instead, with offsets spanning both
  before AND after each pivot (default -12..+8 weeks) to see the full
  lead/lag shape rather than assuming the signal is only ever pre-pivot.

## Universe widening (this session)
`config.TICKERS` widened from `['VTI', 'QQQ', 'VTV']` to the full 28-ETF list
from `tbl_stock_tickers.is_etf = true` (DIA, EEM, EFA, IJH, IJR, IWM, QQQ,
RSP, SCHB, SCHD, SMH, SPY, TLT, VGT, VTI, VTV, VUG, XLB, XLC, XLE, XLF, XLI,
XLK, XLP, XLRE, XLU, XLV, XLY). Note: `tbl_etf_tickers` has a 29th row,
`BLENDED`, which has zero rows in the scanner price tables — not a real
tradeable ticker, excluded. `run_slope_prep.py --timeframe all` was re-run
for the full list; all 28 wrote successfully (560 weekly / 2,698 daily rows
each, except XLC which has fewer — it's a newer sector, Communication
Services was only created in 2018). **Not independently re-verified per
ticker** the way VTI/QQQ/VTV were in Phase 1 (scipy cross-check to 1e-14) —
it's the same code path already verified to that precision, just applied to
25 more symbols, so risk is low, but this hasn't been separately spot-checked.

## Phase 2 findings (in the order they were discovered this session)

**1. Major swing tops/bottoms** — 15% zigzag on weekly close
(`swing_calc.find_swings`). VTI/QQQ/VTV: 5 tops + 5 bottoms each over
2016-2026 (VTV only 2+2 — value didn't correct as sharply as growth in
2018/2022). All three move together on the big turns (2018-09/12, COVID
2020-02/03, 2021-11 top, 2022 bear, 2025-02/03 correction).

**2. EMA10/SMA40 crossover lag** (`run_crossover_alignment.py`, VTI) — the
live emasma crossover reliably confirms every major swing eventually, but
late and asymmetrically: tops confirm in ~9 weeks avg (~17% of the move
already gone), bottoms confirm in ~17 weeks avg (~20% already gone) — nearly
2x slower on bottoms, consistent with a trend-following pair being slower to
catch V-shaped recoveries than rollovers. One 2022 bear-market-rally top
(2022-08-08) never got a fresh confirming cross at all — the system was
already bearish from an earlier cross and stayed that way through the whole
chop.

**3. Daily-level pinpointing** (`run_daily_pinpoint.py`, VTI, 10 confirmed
pivots) — the actual daily high/low consistently lands late in the
Monday-stamped weekly bar's trading week (offsets +2 to +4 days, i.e.
Wed-Fri, never early). Real, consistent, useful for narrowing "which week"
to "which day." **But the daily `slope_close` itself does NOT lead the
actual extreme day** — its own peak/trough wobbles from 1 day early to 3
days late with no repeatable pattern across the 10 events (expected: a
10-day slope is itself a lagging/smoothed measure).

**Side-finding, not part of the divergence test but worth keeping:** the
2018-12-17 BOTTOM case exposes a real limitation of weekly-close zigzag
dating. Raw daily bars show the true lowest close of that selloff (106.89)
and lowest intraday low (106.57, the famous Dec-26-2018 snapback rally day)
both fell in the calendar week *after* the one the zigzag anchored the
bottom to — because that following week's own Friday close (112.90) bounced
back above the anchored week's Friday close (109.63). A weekly-close zigzag
can misdate a bottom by a full week when a sharp V-reversal follows the
trough. Not fixed/handled in any script — just documented as a known
limitation of the pivot-dating method.

**4. Divergence hypothesis — the actual test** (`divergence_calc.py`,
`run_divergence_scan.py`, `run_divergence_scan_universe.py`). Definition:
for TOPs, compare the two most recent swing-high pivots of the `high` series
— does the later one have a higher price but LOWER `slope_high` (bearish
divergence)? Symmetric for BOTTOMs using the `low` series and `slope_low`
(bullish divergence = lower price, higher/less-negative slope). Tested
against a baseline: the same check applied to ALL consecutive minor-pivot
pairs in the series, not just the ones near a major pivot — if divergence is
equally common at random swings, it isn't predictive of anything.

Single-ticker pass (VTI/QQQ/VTV) was suggestive on tops (4/6 testable major
tops diverged, ~67%, vs ~45% baseline) and flat on bottoms (~25% vs ~22%) —
but n=6 for tops is far too small to trust, and 4 of 12 major tops across
the 3 tickers couldn't even be tested (the rally into them was too smooth —
no 5%+ pullback in the `high` series existed anywhere in the prior 52 weeks
to compare against; e.g. VTI's Dec-2018→Feb-2020 and Aug-2020→Nov-2021 runs).

**Full 28-ETF universe pass, with Fisher's exact test** (this is the real
result — see `run_divergence_scan_universe.py`):

| | Near major pivots | Baseline | Odds ratio | p-value |
|---|---|---|---|---|
| TOPs (slope_high) | 39/68 = 57% | 140/306 = 46% | 1.59 | **0.107 — not significant** |
| BOTTOMs (slope_low) | 35/109 = 32% | 74/243 = 30% | 1.08 | **0.803 — not significant** |

**Verdict on divergence:**
- **Bottom-side divergence: ruled out.** 32% vs 30%, odds ratio ~1 — no
  signal at any reasonable threshold of evidence.
- **Top-side divergence: unconfirmed trend, not a finding.** 57% vs 46% is
  directionally consistent with the hypothesis but p=0.107 doesn't clear
  p<0.05. Worse: the 68 "testable major tops" are NOT independent events —
  most ETFs cross their major-top threshold in the same handful of calendar
  weeks (2018-09, 2020-02, 2021-11, 2022-08, 2025-02) because sector/style
  ETFs move together at broad-market tops. The true independent-event count
  behind that 68 is closer to 5-6, meaning the real p-value is almost
  certainly worse than 0.107, not better. Same kind of correlated-universe
  inflation already flagged elsewhere in this repo for other backtests
  (survivor bias, ~50-name dependence in the MTF stock-leg backtest — see
  `project_coreew_backtest_findings.md` memory / AGENTS.md Backtests section).

**5. Continuous fade score, then cross-slope gap — reframed the question
from "binary divergence at discrete pivots" to "is there a graded signal
usable for gradual de-risking" (user pushback: a binary yes/no test on 68
sparse comparisons was the wrong tool for a "just give me a reasonable
hint" use case).**

- `momentum_fade_calc.fade_score` (a slope compared to its own recent past,
  weighted by proximity to the rolling extreme) came back **flat-to-BELOW**
  its own baseline in the 12 weeks approaching major pivots across all 28
  ETFs (e.g. right at a top, the score sits at the 36.7th percentile of its
  normal range — the opposite of "elevated"). This makes sense given finding
  #3: a slope typically peaks ON OR AFTER the actual price extreme, so
  "recent deceleration" can only show up once the turn has already happened
  — the construction is structurally lagging, not leading, by its own
  arithmetic.
- `cross_slope_calc.cross_slope_gap` (one slope vs a DIFFERENT slope at the
  SAME bar — `slope_high - slope_close` for tops, `slope_close - slope_low`
  for bottoms — no dependence on the slope's own past, so no structural lag
  built in) tells a clearer story when checked at both negative AND
  positive offsets around each major pivot:

  | Offset | TOPs (high−close gap) | BOTTOMs (close−low gap) |
  |---|---|---|
  | −12..−1 wk | flat, 42-56th pctile, no consistent signal | flat, 42-57th pctile, no consistent signal |
  | 0 (at pivot) | 38.6th pctile (below normal) | 39.0th pctile (below normal) |
  | **+1 wk** | 69.2th pctile, **p<0.0001** | 66.8th pctile, **p<0.0001** |
  | **+2 wk** | **80.5th pctile, p<0.0001** | **81.1th pctile, p<0.0001** |
  | +4 wk | 71.9th pctile, p<0.0001 | 79.1th pctile, p<0.0001 |
  | +6..+8 wk | back to flat | back to flat |

  (Two isolated "significant" pre-pivot readings at −8wk/tops and −2wk/bottoms
  are almost certainly noise from testing 24 offsets total, not a real early
  warning — no surrounding offsets support a trend there.)

**Verdict on the fade/cross-slope work: no leading signal exists in any of
the three constructions tried, but the cross-slope gap is a real, strongly
significant (p<0.0001) FAST CONFIRMATION signal** — it recognizes a major
top/bottom is underway within 1-4 weeks, versus the live EMA10/SMA40
crossover's 9-17 week confirmation lag (finding #2). Not predictive, but a
5-15x faster read that "this move is real" is directly useful for a graded
"start lightening exposure once this looks real" rule, which is the actual
use case the user described (not a pinpoint, not a binary trade trigger).

**Bottom line: after being pursued as deep as this dataset allows across
three different feature designs, no leading (pre-turn) signal was found in
the OHLC slopes.** But the cross-slope-gap confirmation signal is a genuine,
well-supported finding worth building on — it's a materially faster
alternative/companion to the current crossover-based confirmation, not a
dead end.

## Phase 3 findings: testing cross-slope-gap against the actual EG100 gate

**1. Built the real EG100 index (steps 1-2 of the prior plan, which turned
out to be one step — EG100 is inherently daily, no separate "move to daily
resolution" step needed).** `eg_index_calc.build_eg_index()` replicates the
close series exactly (equal-weight QQQ/VTI/VTV, averaged daily returns,
compounded from 1.0) and extends it with synthetic O/H/L, which has no
live-code equivalent to copy: each leg's O/H/L is expressed as a return
relative to THAT LEG'S OWN PRIOR CLOSE (same anchor the close index already
uses), averaged across legs, applied to the synthetic index's own prior
close. This guarantees `idx_high >= idx_close >= idx_low` on every row by
construction (proof: every leg satisfies `high_i >= close_i >= low_i` daily,
so the same ordering holds on each leg's return-to-prior-close, and survives
averaging since it's linear) — checked and holds on all 2698 rows.

**Verified against the live gate, not just self-consistent:**
`run_eg_index_build.py` shells out to `php artisan trades:execute-EW-gate100
--json` (confirmed from source to be read-only — no Alpaca calls, no orders,
no dedupe-file writes, returns before the clock/warm-up gate) and asserts
match. Result: **index and EMA100 matched to 1e-6, and all 103 flip
dates+directions matched exactly** — same parity AGENTS.md already documents
between the PHP gate and `backtest_trio_ew.py`, now independently confirmed
a third way. The close-index side of this has zero drift risk. The synthetic
O/H/L side has no such external ground truth to check against (the live gate
has no OHLC concept) — the order-preservation proof above is the only
correctness argument for it, same caveat style as other "not independently
re-verified" notes elsewhere in this doc.

**2. Re-ran the event study anchored to EG100's own 103 flips (step 3),
daily resolution, trading-day offsets, `run_eg_flip_event_study.py`:**

| Offset (trading days) | Exits→cash (high−close gap, n=50-51) | Re-entries→long (close−low gap, n=51-52) |
|---|---|---|
| −15 | 50.7 pctile, n.s. | 49.5 pctile, n.s. |
| −10 | 49.8 pctile, n.s. | 47.6 pctile, n.s. |
| −5 | 51.9 pctile, n.s. | 57.9 pctile, **p=0.026** |
| −2 | 56.4 pctile, p=0.060 (borderline) | 56.9 pctile, **p=0.046** |
| **0 (flip day)** | **67.2 pctile, p<0.0001** | **63.9 pctile, p=0.0003** |
| **+1** | **68.4 pctile, p<0.0001** | **59.9 pctile, p=0.0078** |
| **+2** | **65.9 pctile, p<0.0001** | 52.3 pctile, n.s. |
| **+3** | **65.2 pctile, p<0.0001** | 51.5 pctile, n.s. |
| +5 | 43.2 pctile, n.s. (below baseline) | 39.3 pctile, n.s. (below baseline) |
| +8..+12 | back to/below baseline | back to/below baseline |

(The isolated −5/−2 "significant" bottom-side readings, like the isolated
pre-pivot blips in the Phase 2 weekly study, have no supporting trend around
them across 13 offsets tested — treat as noise, not an early-warning finding.)

**Verdict: the signal is real (not a large-rare-swing artifact — it survives
at EG100's much higher event frequency, ~1 flip every 26 trading days,
n≈103 vs Phase 2's 5-8 major swings/ticker) but it is CONCURRENT with the
flip, not a lead over it.** Elevated from offset 0 through +2/+3 trading
days, back to baseline by +5 — a ~3-5 TRADING DAY window, not the 1-4 WEEK
(5-20 trading day) window Phase 2 found relative to the EMA10/SMA40
crossover. Critically, **offset 0 is the same settled bar EG100 itself
already decided on** — both signals are reading the same day's data, so
there is no speed edge to exploit the way there was against the much slower
weekly crossover. The "5-15x faster" framing from Phase 2 does not carry
over to EG100; it only ever applied to the crossover EG100 replaced.

**Why this makes sense in hindsight:** EG100's EMA(100) crossover is already
a comparatively fast, reactive trigger relative to a 15%-major-swing
threshold (that's the whole reason it replaced the slower ratchet gate) —
there isn't much confirmation lag left for a same-underlying-data signal to
beat. The gap and EG100's own flip are close to redundant at EG100's scale,
not staggered the way they are relative to the slow crossover.

**Caveat on the outer offsets:** average flip spacing is 26.2 trading days
and the offset range tested goes to ±15, so in below-average-spacing cases
adjacent flip windows could technically overlap (minor non-independence) —
this only affects the already-non-significant ±8/±10/±12/±15 columns, not
the core 0..+3 finding, but is worth knowing before trusting those numbers.

## Phase 4 findings: turning step 4's reframings into actual backtests

Same day, same session as Phase 3. Three portfolio variants were built and
run against the trio (QQQ/VTI/VTV) full settled history, 2016-01-04 →
2026-09-25 (2698 days), cost 0.05%, alongside SPY B&H as the outside
reference. **All are full-history/in-sample, no holdout — exploratory
"does this shape look promising" checks, not step-5 rigor.**

| Strategy | Return | CAGR | Max DD | Sharpe |
|---|---|---|---|---|
| SPY B&H | +351.9% | +15.13% | 33.8% | 0.89 |
| EW trio B&H (QQQ/VTI/VTV, always invested) | +410.4% | +16.45% | 32.6% | 0.92 |
| EG100 (live, binary — replicated here) | +265.9% | +12.88% | 16.2% | 1.09 |
| EG100 throttled (gate + conviction-sized entries) | +218.6% | +11.43% | 12.9% | 1.08 |
| EW trio, gate-free continuous throttle | +76.5% | +5.45% | 23.3% | 0.51 |

(EG100 binary's 16.2% DD here lines up closely with AGENTS.md's own
documented 5.5y figure of -16.1% — an independent sanity check that this
leg-level replication is sound, beyond the index/EMA/flip parity already
verified in Phase 3.)

**1. EW trio B&H vs EG100 (binary) — the "why not just buy and hold"
question.** EW B&H wins on raw return (+410% vs +266%) and is far simpler
(no gate, no rebalancing logic, no monitoring) — but its 32.6% drawdown is
almost double EG100's 16.2%, and barely better than SPY's own 33.8%, because
QQQ/VTI/VTV are all broad-equity exposure with little real diversification
between them. On Sharpe, EG100 (1.09) beats EW B&H (0.92) despite the lower
raw return — the drawdown cut is worth more than the return given up. This
is the same tradeoff that got EG100 picked over plain buy-and-hold
originally (AGENTS.md's "64% of the drawdown removed, 70% of the return
kept" framing when EG100 replaced the old ratchet gate). Verdict: EW B&H is
the better choice only if raw return is the sole objective and a ~33%
drawdown is acceptable; EG100 is the better choice for risk-adjusted return
and staying power through a bear market — same conclusion the repo already
reached once before, now re-confirmed against this specific signal's context.

**2. EG100 + conviction-sized entries** (`run_eg_throttle_backtest.py`,
step 4(a)'s "corroboration/quality filter" reframing, one concrete
instance): keeps EG100's binary flip series as the timing trigger
unchanged; on every flip TO LONG, sizes the entry by `gap_bot`'s causal
percentile at the flip (linear ramp, 25% floor below the 30th percentile,
100% above the 70th, held constant until the next flip); exits always go
fully to cash (deliberately not second-guessed, since that's where EG100's
downside protection comes from). **Result: captures 82% of EG100's total
return (89% of CAGR) for a 20% drawdown cut — Sharpe is essentially flat
(1.08 vs 1.09).** Does NOT clear a "90% return, meaningfully reduced
drawdown" bar at these parameters: it gives up about as much return as it
saves in risk, rather than improving the risk/return trade. 52 long entries,
average throttled weight at entry 75%.

**3. EW trio, gate-free continuous throttle** (`run_ew_throttle_backtest.py`
— testing whether the gap can work as a continuous exposure dial with NO
EG100 gate underneath it at all, i.e. always at least partially invested,
never a hard cash-out): signal is `net_gap = gap_bot - gap_top` (a NEW
combined construction this session — Phase 2/3 only ever validated
`gap_top`/`gap_bot` separately, each anchored to a specific event type, never
combined and applied continuously), causal-percentile-ranked and ramped to
an exposure weight EVERY DAY (not just at discrete flip moments), rebalanced
weekly. **Result: clearly destroys value** — +76.5% return / CAGR +5.45% /
Sharpe 0.51, captures only 19% of EW B&H's return (22% of SPY's) while
cutting drawdown just 29-31%. Spends 45% of days at the floor, only 37% at
full exposure.

**Why #3 fails where #2 doesn't:** this is the clearest evidence yet for
what Phase 2/3 already implied — cross-slope-gap is a brief, event-anchored
CONFIRMATION signal (elevated for a few days around a real flip/pivot, flat
at the 42-56th percentile the rest of the time, per Phase 2 findings #5 and
Phase 3 finding #2), not a signal with continuous day-to-day informational
content. Recomputing it every day and using its percentile as a standing
exposure dial mostly just reacts to noise in the "normal" 42-56th-percentile
range, producing noise-driven whipsaw (chopping between the floor and full
exposure) that gives up most of buy-and-hold's compounding for a
disappointing drawdown benefit. Anchoring the throttle to actual discrete
flip events (#2) avoids this failure mode — which is exactly why #2, while
still short of the 90% bar, is the structurally sound version and #3 is not.

**Overall verdict: neither throttle variant is ready to replace anything
live.** #2 (EG100 + conviction-sized entries) is the closer of the two and
the one worth any further iteration — #3 (gate-free continuous) should be
considered ruled out by this result, not just under-tuned; the failure mode
is structural (misusing an event-anchored signal as a continuous one), not a
parameter-tuning problem.

## Plan for next session: is cross-slope-gap ready for live CoreEW/EG100?

**Verdict as of this writing: steps 1-3 done (see "Phase 3 findings" above),
still not ready for live integration — but for a different reason than
originally expected.** The original concern was "maybe the pattern is a
large-rare-swing artifact absent at EG100's scale" — that's ruled out, the
signal is real at EG100's scale too. The concern now is different: it's
concurrent with EG100's own signal, not faster than it, which undercuts the
original "faster confirmation companion" rationale from step 4(a) below.
Steps 4-6, updated in light of this:

1. ~~Build the feature on the actual EG100 index, not proxy ETFs.~~ **DONE**
   — `eg_index_calc.build_eg_index()`, verified to 1e-6 + exact 103-flip
   parity against the live PHP gate. Synthetic O/H/L construction and its
   order-preservation proof are in "Phase 3 findings" #1 above.
2. ~~Recompute at daily resolution.~~ **DONE** (turned out to be the same
   step as #1 — EG100 is inherently daily, there's no separate weekly form
   of it). Slope window used: `config.SLOPE_WINDOW['daily']=10`, unchanged
   from Phase 2 — NOT sensitivity-checked yet (see "Open decisions").
3. ~~Re-run the event study anchored to EG100's own 103 historical flips~~
   **DONE** — `run_eg_flip_event_study.py`, trading-day offsets. Result: the
   gap is real at EG100's scale (rules out "large-rare-swing artifact") but
   CONCURRENT with the flip (0 to +2/+3 trading days), not a multi-week lead
   the way it is over the EMA10/SMA40 crossover. See "Phase 3 findings" #2.
4. **Reframed by the result above — needs a fresh decision, not the original
   one.** The original framing was (a) faster confirmation companion to the
   crossover vs (b) graduated position-sizing overlay, with (a) recommended
   as the smaller lift. (a) no longer makes sense as originally scoped: if
   the gap and EG100's own flip fire on the SAME settled bar, there's no lead
   time for a "faster companion" to exploit — this is the piece that needs a
   human call before any more building happens. Candidate reframings, none
   started:
   - **Corroboration/quality filter**: does an elevated gap AT the flip
     predict which flips turn into a durable move vs a quick whipsaw
     reversal (EG100's own known failure mode)? If so, the gap's value isn't
     speed, it's conviction-weighting the SAME-DAY decision — e.g. size the
     entry/exit by how elevated the gap is rather than skip/delay on it. This
     is (b)'s territory (graduated overlay) but motivated differently than
     originally proposed — not "trim gradually ahead of a slow crossover" but
     "size the all-in/all-out flip itself by same-day conviction."
   - **Conclude the signal isn't useful for EG100 and stop here** — it's a
     genuine, well-supported confirmation signal relative to the SLOW
     EMA10/SMA40 crossover (Phase 2's finding stands on its own, unaffected
     by Phase 3), just not one EG100 specifically needs, since EG100 already
     moved past the point where a same-day companion adds information.
5. **Backtest the concrete rule from step 4** (once decided) against the live
   EG100 baseline, matching this repo's existing rigor: `--ema-gate 100`
   conventions, cost=0.0005, full history + the same holdout split already
   used for EG100 itself (2016-11→2021-04). Report return/max-DD/Calmar vs
   "EG100 alone," not just statistical significance. Not started — blocked on 4.
6. **Only after 1-5 hold up** does this become a live-integration conversation
   — and per AGENTS.md, that requires explicit user sign-off before touching
   `TradeExecutorService.php`/`ExecuteEWGate100.php` or the cron, same as any
   other live emasma/CoreEW path change.

## Open decisions for whoever picks this up next
- **Not yet committed to git** — check `git status`/`git log` on
  `feature/ohlc-data-prep`.
- User was mid-decision on next steps as of this update, now with the
  cross-slope-gap finding in hand. Candidate next angles, none started:
  - **Build a graduated de-risking rule on the cross-slope gap** — this is
    the natural next step given finding #5. Define percentile thresholds
    (e.g. "start trimming once the gap crosses its 70th percentile, trim
    more at 80th") and backtest what that would have done vs. the current
    EMA10/SMA40 crossover exit, on the same VTI/QQQ/VTV history already used
    for `backtest_trio_ew.py`. This is the first idea that's actually
    gradable/actionable rather than another significance test.
  - **Check whether the +1..+4wk confirmation window is fast enough to be
    useful net of the move already lost, for the ORIGINAL weekly/28-ETF
    finding** (this is about Phase 2's crossover-companion case, which still
    stands on its own — not about EG100, which Phase 3 answered differently:
    concurrent, not a lead, so "move already lost" isn't the open question
    there). Still not done for Phase 2's own use case.
  - ~~Daily-level version of cross_slope_gap~~ **DONE in Phase 3**, but as
    part of the EG100 index specifically, not as a general daily version of
    the 28-ETF weekly study — that's still a distinct, untried angle if the
    weekly/crossover-companion use case (above) is pursued further.
  - **Go back further in time** for the still-open top-side divergence
    question (finding #4) — genuinely independent additional events
    (pre-2016 data, if available) would test it without the cross-ETF
    correlation problem that undermines the current p=0.107. Lower priority
    now that #5 found something more concrete.
  - **Conclude here and stop** — write up the leading-signal negative result
    plus the confirmation-signal positive result and move on; the infra
    (slope columns, all the utility_scripts calc modules) remains
    available/reusable regardless.
- Windows (daily=10, weekly=5 for slopes; rolling_window=20/fade_lookback=4
  for the fade score) were starting guesses, never retuned during Phase 2 —
  if any of the above is pursued, worth checking sensitivity to these before
  concluding anything from the specific numbers found this session.
- If this experiment is abandoned entirely, the cleanup surface is: the 4
  slope columns on `tbl_scanner_tickers`/`tbl_scanner_tickers_daily` (now
  populated for all 28 ETFs, still NULL for every stock — verified zero
  bleed in Phase 1), plus the `ohlc-dataprep/` and `ohlc-dataprep/utility_scripts/`
  directories (Phase 3 added `eg100_index_daily.csv`/`eg100_flips.json` —
  generated caches, nothing in the DB; safe to delete along with the rest).
  Nothing here is called by any live strategy path.
- Phase 3's daily slope window (10, same as Phase 2's daily default) was not
  sensitivity-checked for the EG100 case specifically — if step 4 above ends
  up pursued, worth checking whether a different window changes the
  concurrent-vs-leading finding before building anything on it.

## Session close (2026-09-27)

**Closed for now — "conclude and stop," not "abandon."** No leading (pre-turn)
signal was found anywhere across four different tests on the OHLC slopes
(Phase 2's divergence/fade-score/cross-slope-gap trio, then Phase 3's
EG100-anchored re-test). The one real, statistically strong finding —
cross-slope-gap as a fast CONFIRMATION signal — holds up on its own terms
(1-4 weeks faster than the live EMA10/SMA40 crossover, p<0.0001) but turned
out concurrent rather than leading when re-tested against EG100 specifically
(Phase 3), and neither portfolio strategy built on top of it in Phase 4
cleared a bar worth acting on: the EG100-gated conviction-sizing variant
captured 82% of return for only a 20% drawdown cut (Sharpe flat), and the
gate-free continuous-throttle variant destroyed value outright (Sharpe 0.51
vs 0.92 B&H) — a structural failure, not a tuning problem, since the signal
is event-anchored, not continuously informative. **EG100 binary (the current
live strategy) remains the best risk-adjusted option found in this entire
experiment; nothing here is being integrated into it.**

Nothing live was touched at any point — no changes to `TradeExecutorService.php`,
`ExecuteEWGate100.php`, the cron, or any scanner table read by a live
strategy. Everything produced lives in `ohlc-dataprep/` (code) plus 4 new
NULL-by-default slope columns on the scanner tables (data, ETFs only,
verified zero bleed to stocks). All of it stays available and re-runnable if
this is picked back up — nothing needs to be rebuilt from scratch, just
re-read this doc top to bottom. If picked back up, the open thread most
worth pulling first is Phase 3/4's "corroboration/quality filter" idea
(does gap magnitude at a flip predict durable-vs-whipsaw), since that's the
one angle from step 4 that was never actually tested (Phase 4 tested
*sizing* by conviction, not *predicting durability* by it — a different,
still-open question).
