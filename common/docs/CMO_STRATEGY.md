# CMO Daily Strategy — research spec + live wiring

**Status:** research complete 2026-11-16; was live 2026-11-18/19 on `#PA368CPXNS13`.
**Retired 2026-11-20:** owner-directed S1 full replace. `swingtrader-cmo-bounce.timer` and its
`cmo_live.py` entrypoint are unchanged, but `cmo_live.py` now dispatches to
`s1_live.py --mode stock`; `cmo_core.py` / `backtest_cmo.py` / the CMO Bounce40 rules below are
historical reference only. `cmo_universe.py` remains live as the S1 stock pool source. ETF
`emasma` was also replaced by S1; CoreEW / Daily Signal are unchanged. See §5k for the retired
install/handover history.

Source of truth is the code (`swingtrader/services/mtf/cmo_core.py`,
`backtest_cmo.py`). This doc explains the same logic. Scratch files under
`.tmp_research/` are local-only and not committed; trade books are committed under
`common/docs/trade_books/`.

---

## 1. Signal — daily bars only

All inputs are **settled daily closes** from `tbl_prices_daily` (split/dividend adjusted,
written by the 16:30 backfill). A decision on settled bar **D** is executed at the next
session's open. Nothing reads today's in-progress bar.

### Indicators

| Indicator | Definition |
|---|---|
| **CMO(20)** | Chande Momentum Oscillator on close-to-close changes. `SU`/`SD` = sum of positive/negative changes over the last 20 changes. `CMO = 100 · (SU − SD) / (SU + SD)`. `SU+SD = 0` → `0`. |
| **MACD (10/20/40, Weighted)** | `Val = WMA(close,10) − WMA(close,20)`; `Avg = WMA(Val,40)`; `Diff = Val − Avg`. TOS "Weighted" = linear-weighted MA (newest bar gets the largest weight). `ma_type` is switchable to `ema` for the sensitivity run. |
| **EMA10** | `EMA(close,10)`, `adjust=False`, seeded at the first close. |
| **SMA20** | `SMA(close,20)`. |
| **BB mid** | Bollinger(20) **middle band = EMA(close,20)** (owner's chart). The 2σ bands are not read by the signal. |

Warm-up: `Avg = WMA(Val,40)` is only finite from ~bar 59, so require a ticker to have at
least **80** bars before emitting a signal.

### Conditions and the 10-bar window

Two are **events** (a cross happened), two are **states** (true on the decision bar):

| # | Condition | Test |
|---|---|---|
| 1 | CMO crosses **above 0** | `CMO[i] > 0 and CMO[i−1] <= 0`, for some `i` in the window |
| 2 | **MACD Diff > 0** | `Diff[D] > 0` |
| 3 | **EMA10 > SMA20** | `EMA10[D] > SMA20[D]` |
| 4 | EMA10 crosses **above BB mid** | `EMA10[i] > BBmid[i] and EMA10[i−1] <= BBmid[i−1]`, for some `i` in the window |

**Buy** when 2 and 3 are true today **and** 1 and 4 occurred within the last **10 trading
bars** (inclusive of D). This is the default `armed` mode: states today, fresh events in
the window. Two alternative readings are implemented for the sensitivity run:

- `any_in_window` — each of the four is true/occurred on at least one bar in the window
  (a state need not be true today).
- `same_bar` — all four true on D (the 10-bar window is unused).

**Sell = reverse of buy** (mirror, default): `Diff < 0` and `EMA10 < SMA20` today, and a
CMO down-cross **and** an EMA10 down-cross of BB mid within the window. `sell_mode='any'`
sells on any one bearish condition (sensitivity only).

A name that has been bullish for longer than the window has no fresh CMO/BB cross → **not
buy-eligible**. The strategy is a fresh-trigger strategy, not a "already extended" scanner.

---

## 2. Book — stateful signal book (Mode A)

Capacity **25**, equal weight `equity / 25`, no margin. The book is a **state machine**, not
a daily rank rotation:

- A held name is **sold only when its own mirror sell window fires**. Dropping out of a
  "top-25 rank" does not sell it.
- A name is **bought when its buy window is armed and a slot is free**. An armed name stays
  armed for the rest of its 10-bar window, so a slot that frees up can be filled by a name
  that triggered a few days earlier.
- If more than 25 names arm, new entries are ranked deterministically:
  1. fewest bars since the CMO up-cross,
  2. largest `MACD Diff`,
  3. largest `EMA10 − BBmid`,
  4. symbol ascending.
- Held names with no fresh settled bar are **preserved** (never sold on missing data); the
  live path will instead fail the readiness gate.
- Free slots stay in cash. Sizing is capped at `equity/25`, so a thin book does not
  concentrate.

Overlays are not part of the raw CMO signal. The live book uses P20w majority + 15%
weekly-close HWM + 5-session cooldown; the 2×ATR ratchet was tested and dropped.

---

## 3. State — `tbl_cmo_state` (database only, no flat files)

Created and written in Phase 3 (live wiring). The backtest is stateless. The live runner
will persist one row per `(mode, symbol)` so a restart can rebuild the book without
re-deriving history or reading CSV:

```sql
CREATE TABLE IF NOT EXISTS tbl_cmo_state (
    id                  bigserial PRIMARY KEY,
    mode                text        NOT NULL DEFAULT 'stock',
    symbol              text        NOT NULL,
    status              text        NOT NULL,   -- held | armed | flat | sell
    signal_date         date,                   -- settled bar the row was computed on
    armed_since         date,                   -- first armed bar in the current window
    entry_signal_date   date,
    exit_signal_date    date,
    cmo                 double precision,
    macd_val            double precision,
    macd_avg            double precision,
    macd_diff           double precision,
    ema10               double precision,
    bb_mid              double precision,
    sma20               double precision,
    days_cmo_up         integer,
    days_bb_up          integer,
    days_cmo_down       integer,
    days_bb_down        integer,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (mode, symbol)
);
```

Book membership for the live CMO runner is stored in the separate `cmo_positions` /
`cmo_trades` tables (Alpaca remains the source of truth); the retired emasma stock book
uses `mtf_positions` only until the one-time `--handover` removes those stock rows.

---

## 4. Execution mapping (implemented 2026-11-18)

- `cmo_live.py` runs score + execute in one 10:25 ET unit: it rebuilds the five-source PIT
  universe, scores the last settled daily bar, and trades the same account #PA368CPXNS13.
- Sells = mirror-sell names, HWM stop, P20w-off liquidation and rebalance trims; buys = open
  slots with bounce40 entry + 0.99×BB-mid + P20w ON. Equal-weight trim-before-top-up uses
  `REBALANCE_BAND_PCT=20` / `MIN_TRADE_NOTIONAL=500`.
- Weekly data is required for the five-source universe and P20w gate, not for the CMO itself.
- The ETF leg is untouched emasma, now explicitly `--mode etf`.
- Rollback: disable `swingtrader-cmo-bounce.timer` and revert the ETF service flags. No Alpaca
  account migration; `cmo_positions` / `cmo_trades` can be dropped after flattening the book.

---

## 5. Backtest protocol (the "prove it" gate)

Given that every deployed strategy backtested well and still lost money, a single pretty
equity curve is not evidence. `backtest_cmo.py` reports:

1. **Portfolio A/B** vs the live emasma stock configuration on the same window, same
   next-open fills, same equal-weight sizing and 0.05% per-side cost.
2. **Signal event study** — every buy trigger (not just the 25 that got bought): forward
   5/10/20/60-bar return and the excess over the same-day universe median. This isolates
   signal quality from capacity and sizing.
3. **Regime slices** (2017–2020, 2021–2023, 2024–2026) — require the edge to survive every
   sub-window, not just full-sample.
4. **Sensitivity grid**: `ma_type` WMA/EMA, `window` 5/10/15, `mode` armed/any_in_window/
   same_bar, `sell_mode` mirror/any, fill open/close. A signal that only works at one
   parameter point is rejected.
5. **Turnover / exposure / average hold / trade count** — daily triggers can churn; the
   live account cannot pay 0.05% × 25 names/day.

**Pass bar (owner focus, 2026-11-16):** win% and max drawdown are the decision metrics
(CAGR is context only). The strategy must beat the emasma live baseline on **win% and max
drawdown** in at least the two most recent sub-windows, show positive event-study excess at
10/20 bars, and not depend on a single parameter point. Backtest returns remain indicative
only. Owner approved a live paper-account replacement on 2026-11-18; a 3–4 week
paper-forward remains the follow-up validation, not a precondition.

---

## 6. Decisions (resolved 2026-11-18)

- Keep P20w majority + 15% weekly-close HWM; drop the 2×ATR ratchet.
- Use a 5-session cooldown after an HWM stop.
- Cutover: `cmo_live.py --handover` liquidates the retired emasma stock book and seeds
  fresh state; no gradual transition.

---

## 5a. Backtest results (2026-11-16)

Harness: `swingtrader/services/mtf/backtest_cmo.py`. Window 2017-01-03 → 2026-11-13,
enabled-stock universe (1,411 names, survivor-biased), top-25 equal weight, next-open
fills, 0.05%/side, 20% rebalance band / $500 min delta.

**Full sample, no risk overlay (owner metrics first):**

| Variant | Win% | MaxDD | Return | CAGR | Trades | Hold | Turn |
|---|---:|---:|---:|---:|---:|---:|---:|
| armed WMA10 (spec default) | 36% | -32.7% | +144% | 9.5% | 2,269 | 39d | 17.9x/y |
| armed EMA10 | 38% | -30.2% | +222% | 12.6% | 2,039 | 44d | 16.1x/y |
| any_in_window | 38% | -35.0% | +130% | 8.8% | 2,988 | 30d | 23.1x/y |
| same_bar | 59% | -35.7% | +375% | 17.1% | 251 | 322d | 2.6x/y |
| armed + SPY SMA200 | 38% | -24.0% | +58% | 4.8% | 2,143 | 31d | 17.2x/y |
| armed + P20w `any` | 39% | -32.3% | +171% | 10.6% | 2,282 | 35d | 18.0x/y |
| same_bar + P20w `any` | 51% | -22.6% | +468% | 19.3% | 632 | 118d | 5.0x/y |
| **same_bar + P20w `any` + 15% HWM** | **54%** | **-16.8%** | **+475%** | **19.4%** | **658** | **112d** | **5.1x/y** |

**Recommended candidate sub-windows** (`same_bar + P20w any + 15% HWM`, 5-session cooldown):

| Window | Win% | MaxDD | Return | CAGR |
|---|---:|---:|---:|---:|
| 2017-2020 | 54% | -16.5% | +137% | 24.1% |
| 2021-2023 | 51% | -16.8% | +65% | 18.2% |
| 2024-now | 59% | -16.5% | +52% | 15.8% |

**Live emasma stock baseline** (same P20w `any` gate, weekly, top-25 EW, ratchet-ATR daily):

| Window | Win% | MaxDD | Return |
|---|---:|---:|---:|
| 2017-02 → 2020-12 | 42% | -24.0% | +126% |
| 2021-09 → 2023-12 | 44% | -14.0% | +41% |
| 2024-01 → 2026-11 | 52% | -52.0% | +79% |
| 2021-09 → 2026-09 (cache window) | 47% | -29.2% | +336% |

On the baseline's own cache window (2021-09-21 → 2026-09-25):
**CMO `same_bar` + gate + HWM = 51% win / -19.1% DD / +110.5%** vs
**emasma live = 47% win / -29.2% DD / +335.5%**. It wins both owner metrics, with lower
return.

**Read this honestly:** the gated `same_bar` event study is still ~flat-to-negative excess
at 10/20 bars (full: -0.12% / -0.70%; 2021-2023: -1.05% / -2.65%; 2024-now: +0.63% /
+0.53%). The win%/DD improvement comes mostly from the live P20w gate + long holds, not
from CMO entry alpha. `same_bar` is also stricter than the owner's "within 10 trading days"
spec. HWM 10/12% made DD worse (-29.1%, whipsaw); HWM 20% ≈ off (-22.5%); 15% is the live
stock-leg setting, not tuned. Returns remain survivorship-inflated and indicative only.

**Reproduce:**
```
cd swingtrader/services/mtf
../optimizer/venv/bin/python3 backtest_cmo.py --start 2017-01-01 \
  --mode same_bar --p20w-gate any --hwm-stop 15
```

**Decision needed before phase 3:** (a) accept the stricter `same_bar` definition, and
(b) inherit the live P20w `any` gate + 15% weekly HWM stop on the CMO book. If either is
no, the spec-default `armed`/`any_in_window` variants fail the owner's win%/DD gate.

## 5b. Chain mode (2026-11-17)

Owner rejected `same_bar` ("never seen on TOS") and asked to drop the 10-bar window:
count each of the four conditions the first time it prints, in any order, and buy
when the fourth lands. Implemented as `mode='chain'` in `cmo_core.py` (one-shot
pulse, seen-set resets after each buy/sell; mirror sell is the analogous
four-condition bearish chain). Owner then confirmed a window is needed; `chain`
honors `--window` (trial: 30 daily bars; `window=0` = no expiry). 27 unit tests green.

AAPL-only example, 2026-01-02→2026-11-16, $100k, next-open fills, gate/HWM irrelevant
here (all three configs match):

| Entry | Price | Exit | Price | P&L |
|---|---:|---|---:|---:|
| 2026-02-04 | 271.55 | 2026-03-05 | 260.33 | -$4,227.66 (-4.23%) |
| 2026-04-10 | 259.52 | 2026-06-15 | 293.87 | +$12,568.01 (+13.12%) |
| 2026-07-07 | 315.02 | 2026-08-06 | 314.07 | -$434.68 (-0.40%) |

Re-entry 2026-08-31 still open; final equity $119,048.62 (+19.05%) vs SPY B&H +9.16%.
This buys in April as expected (signal 04-09, fill 04-10) — CMO cross 04-06, EMA/BB
cross 04-09, MACD Diff>0 and EMA10>SMA20 from 04-06.

Full universe (1,411 stocks, 2017-01-03→2026-11-16):

| Config | Win | MaxDD | Return | Trades | Avg hold |
|---|---:|---:|---:|---:|---:|
| `chain` no window, no gate | 36% | -33.1% | 249.9% | 2,343 | 38d |
| `chain` no window + P20w any + HWM15 | 39% | -32.8% | 286.5% | 2,347 | 33d |
| `chain` **30d**, no gate | 36% | -30.0% | 233.0% | 2,312 | 38d |
| `chain` **30d** + P20w any + HWM15 | 39% | -33.3% | 226.9% | 2,389 | 33d |
| `same_bar` + P20w any + HWM15 | 54% | -16.8% | 474.6% | 658 | ~112d |
| emasma baseline (same gate) | 47% | -29.2% | 335.5% | 598 | — |

Chain captures the April AAPL trade but is **far worse at book level** than `same_bar`:
~36-39% win rate, 18-19x/y turnover and ~99% exposure without gate. Adding a 30-day
expiry barely changes it (Win 39%, MaxDD -33.3% gated) — the problem is not just
staleness but the one-shot accumulation firing on many names instead of the rarer
same-bar momentum sync. It fails the owner's win%/DD gate. Reproduce:
```
cd swingtrader/services/mtf
../optimizer/venv/bin/python3 backtest_cmo.py --start 2017-01-01 \
  --mode chain --window 30 --p20w-gate any --hwm-stop 15
```

## 5c. Weekly-bar CMO (2026-11-18, owner-confirmed chart match)

Owner confirmed the AAPL crosses he sees are on the **weekly chart**, using Alpaca
adjusted bars (SIP, `adjustment=all`) and CMO20 / all-four mirrored conditions.
`backtest_cmo.py --timeframe week` reads `tbl_prices_weekly` (native Alpaca weekly
bars, **not** derived from daily); `db.bulk_load_weekly` now carries weekly opens so
next-open fills work. Nothing about the live emasma path changed.

AAPL signal/fill sequence (top-1, next Monday open, 0.05%/side):

| Signal (settled weekly close) | Fill | Exit signal | Exit fill | Result |
|---|---|---|---|---|
| 2025-08-11 | 2025-08-18 @ 230.85 | 2026-03-16 | 2026-03-23 @ 253.52 | +9.71% |
| 2026-04-27 | 2026-05-04 @ 279.16 | open | mark 356.27 | +27.56% |

Why the earlier dates were rejected: 2025-07-14 is an EMA10/SMA20 cross but CMO20
does not cross; 2026-01-19 has no CMO cross; CMO20 crosses down 2026-03-09 and all
four bearish conditions first align 2026-03-16 (EMA10<BBmid only then).

A simplified two-condition variant was also tested (`--mode cmo_bb`): buy = CMO20
up-cross **and** EMA10 > BB mid; sell = CMO20 down-cross **and** EMA10 < BB mid
(MACD and EMA10/SMA20 ignored). Full weekly dataset, top-1, next-open fills:

| Ticker | Mode | Win% | MaxDD | Return | Trades |
|---|---|---:|---:|---:|---:|
| AAPL | armed (4-condition) | 71% | -30.9% | +240.4% | 7 |
| AAPL | cmo_bb (2-condition) | 100% | -31.3% | +585.8% | 3 |
| VTI | armed (4-condition) | 80% | -29.7% | +79.8% | 5 |
| VTI | cmo_bb (2-condition) | 50% | -32.9% | +169.8% | 2 |
| SPY B&H | — | — | -31.7% | +362.9% | — |

The simplified filter boosts return on both names but only AAPL beats SPY B&H; VTI's win%
and drawdown both worsen. It also holds AAPL continuously from 2024-05-20 and VTI from
2023-01-23, so the higher return comes from much longer exposure, not cleaner exits.
Full-history single-ticker sweep (2016-01-04 → 2026-11-09, weekly Alpaca adjusted,
top-1, next-open fills, 0.05%/side). `armed` = 4-condition spec; `cmo_bb` = CMO20 cross
+ EMA10>BB mid:

| Ticker | armed Win/MaxDD/Ret/N | cmo_bb Win/MaxDD/Ret/N |
|---|---|---|
| AAPL | 71% / -30.9% / +240.4% / 7 | 100% / -31.3% / +585.8% / 3 |
| VTI | 80% / -29.7% / +79.8% / 5 | 50% / -32.9% / +169.8% / 2 |
| NVDA | 60% / -33.7% / +2331.0% / 5 | 100% / -34.3% / +458.6% / 1 |
| MSFT | 75% / -25.7% / +316.3% / 4 | 67% / -31.6% / +190.0% / 3 |
| AMZN | 67% / -34.9% / +141.0% / 6 | 50% / -31.6% / +233.5% / 4 |
| GOOG | 43% / -33.1% / +274.4% / 7 | 60% / -31.4% / +204.4% / 5 |
| QQQ | 75% / -27.3% / +189.6% / 4 | 100% / -34.9% / +281.3% / 1 |
| VTV | 50% / -19.3% / +80.7% / 6 | 57% / -34.0% / +92.4% / 7 |

SPY B&H same window: +362.9% / -31.7% DD. NVDA's armed +2331% is a 5-trade outlier
(two multi-year holds, +390% and +508%); cmo_bb has only one NVDA trade. Low `N` makes
these single-name results indicative only.

Equal-weight 8-name basket (AAPL, VTI, NVDA, MSFT, AMZN, GOOG, QQQ, VTV; top-8,
weekly adjusted bars, next-open fills, 0.05%/side, full 2016-01-04 → 2026-11-09):

| Config | Win% | MaxDD | Return | Trades | Exposure |
|---|---:|---:|---:|---:|---:|
| armed raw | 64% | -24.8% | +316.5% | 44 | 55% |
| cmo_bb raw | 65% | -26.6% | +294.3% | 26 | 60% |
| armed + P20w any + HWM15 | **68%** | **-10.4%** | +106.9% | 50 | 36% |
| cmo_bb + P20w any + HWM15 | 63% | -11.5% | +82.8% | 43 | 30% |
| SPY B&H | — | -31.7% | +362.9% | — | 100% |

Sub-window detail: armed raw `2021-2023` 71% / -14.2% / +70.7%, `2024-now` 75% /
-11.2% / +55.8%; cmo_bb raw 73% / -17.4% / +32.0% and 62% / -14.7% / +45.6%.
The gate/HWM overlay wins on drawdown but leaves 64-70% in cash, so return suffers.
No live wiring. Reproduce the basket:
```
cd swingtrader/services/mtf
../optimizer/venv/bin/python3 backtest_cmo.py --timeframe week \
  --tickers AAPL,VTI,NVDA,MSFT,AMZN,GOOG,QQQ,VTV --top-n 8 \
  --mode armed --fill open --p20w-gate any --hwm-stop 15
```

Reproduce the single-ticker AAPL run:
```
cd swingtrader/services/mtf
../optimizer/venv/bin/python3 backtest_cmo.py --timeframe week --tickers AAPL \
  --top-n 1 --mode armed --sell-mode mirror --window 10 \
  --fill open --trade-csv /tmp/opencode/aapl_cmo_weekly_trades.csv
```

## 5d. Daily-bar sweep and basket (2026-11-18)

Same 8 names as the weekly test, now on **daily** Alpaca adjusted bars (`tbl_prices_daily`),
full dataset `2016-01-04 → 2026-11-17`, top-1/tick, next-open fills, 0.05%/side.

| Ticker | armed Win/MaxDD/Ret/N | cmo_bb Win/MaxDD/Ret/N |
|---|---|---|
| AAPL | 50% / -23.4% / +664.5% / 42 | 43% / -31.4% / +310.7% / 30 |
| VTI | 57% / -14.8% / +158.1% / 40 | 62% / -35.0% / +101.5% / 24 |
| NVDA | 43% / -48.1% / +2858.0% / 47 | 46% / -59.0% / +4562.3% / 26 |
| MSFT | 46% / -33.6% / +261.3% / 46 | 50% / -39.7% / +255.3% / 26 |
| AMZN | 34% / -48.6% / +237.9% / 44 | 39% / -33.0% / +330.7% / 28 |
| GOOG | 46% / -42.5% / +146.4% / 50 | 64% / -36.5% / +302.9% / 22 |
| QQQ | 48% / -26.3% / +303.3% / 42 | 57% / -28.6% / +176.4% / 21 |
| VTV | 44% / -28.1% / +38.3% / 45 | 56% / -36.9% / +65.9% / 18 |

Equal-weight 8-name basket (top-8, daily):

| Config | Win% | MaxDD | Return | Trades | Exposure |
|---|---:|---:|---:|---:|---:|
| armed raw | 46% | -24.1% | +396.6% | 356 | 66% |
| cmo_bb raw | 51% | -25.3% | +409.8% | 195 | 66% |
| armed + P20w any + HWM15 | 45% | -20.8% | +261.2% | 340 | 60% |
| cmo_bb + P20w any + HWM15 | 50% | **-13.4%** | +225.2% | 198 | 51% |
| SPY B&H | — | -33.8% | +329.1% | — | 100% |

Daily `cmo_bb` beats SPY return in the raw basket and has the best gated drawdown,
but individual-name DDs are much worse than weekly (NVDA -59%, AMZN -48.6%); the
daily variant is noisier and needs the overlay. No live wiring.

## 5e. Daily overlay grid (2026-11-18)

Same 8-name daily basket, `cooldown 5` throughout. Best on owner metrics (Win%,
MaxDD) is **cmo_bb + P20w majority + HWM15**: 52.1% / -12.6% / +219.5% / expo 48%.
`P20w any + HWM15` is close (50.0% / -13.4% / +225.2%), while `all` cuts return to
+132% without improving Win%. SPY-SMA200 filter hurts both Win% and return.

| Mode | Overlay | Win% | MaxDD | Return | Exposure |
|---|---|---:|---:|---:|---:|
| armed | HWM15 only | 45.8% | -24.1% | +396.6% | 66% |
| armed | any + HWM15 | 45.3% | -20.8% | +261.2% | 60% |
| armed | majority + HWM15 | 46.3% | -20.0% | +164.4% | 52% |
| armed | all + HWM15 | 46.7% | -14.8% | +92.1% | 43% |
| armed | SPY-SMA200 + HWM15 | 44.3% | -17.6% | +162.0% | 52% |
| cmo_bb | HWM15 only | 50.0% | -23.0% | +322.1% | 64% |
| cmo_bb | any + HWM15 | 50.0% | -13.4% | +225.2% | 51% |
| **cmo_bb** | **majority + HWM15** | **52.1%** | **-12.6%** | +219.5% | 48% |
| cmo_bb | all + HWM15 | 50.3% | -12.6% | +132.2% | 38% |
| cmo_bb | any + HWM10 | 50.0% | -12.9% | +219.6% | 50% |
| cmo_bb | SPY-SMA200 + HWM15 | 47.0% | -17.4% | +174.8% | 48% |

Research only; no live changes.

## 5f. RS-Watchlist basket test (2026-11-18)

36-name RS-Watchlist supplied by owner (all 36 loaded), same daily full history and
recommended overlay (`cmo_bb + P20w majority + HWM15 + cooldown5`) unless noted:

| Config | Win% | MaxDD | Return | Trades | Exposure |
|---|---:|---:|---:|---:|---:|
| cmo_bb top36 + overlay | 42.5% | -11.6% | +66.6% | 932 | 40% |
| cmo_bb top36 raw | 39.9% | -22.5% | +90.5% | 925 | 56% |
| armed top36 + overlay | 41.8% | -12.4% | +52.9% | 1503 | 43% |
| cmo_bb top8 of RS + overlay | 44.2% | -21.7% | +171.0% | 414 | 73% |
| Original 8-name basket + overlay | **52.1%** | -12.6% | **+219.5%** | 198 | 48% |

RS list is worse than the original 8-name basket on Win% and Return; only MaxDD is
marginally better in the full-36 version. The top-8 RS subset raises return but DD
jumps to -21.7%. Do not adopt this basket as-is. Research only; no live changes.

## 5g. Point-in-time RS-Watchlist universe (2026-11-18)

Correct test of the RS theory: from the beginning of the dataset, rebuild the
RS-Watchlist on each settled weekly bar (`rs_watchlist.build` logic: rank>=0.8,
FRESH, BASE, daily MACD10/40/400 hist>0 as of that week's Friday), then apply that
list to the **following week's** daily CMO signals. Equal-weight all qualifying
names (no fixed top-N cap); 0.05%/side, next-open fills, 15% HWM + 5-session
cooldown. Current rebuilt list matches the supplied 36 exactly.

| Config | Win% | MaxDD | Return | Trades | Exposure |
|---|---:|---:|---:|---:|---:|
| cmo_bb, no gate | 38.7% | -27.2% | +291.7% | 799 | 80% |
| cmo_bb, P20w any | 38.3% | -30.9% | +222.7% | 702 | 69% |
| cmo_bb, P20w majority | 38.9% | -33.0% | +164.5% | 624 | 62% |
| armed, no gate | 34.4% | -34.9% | +225.1% | 544 | 77% |
| armed, P20w any | 36.3% | -36.5% | +655.6% | 476 | 69% |
| armed, P20w majority | 39.6% | -32.9% | +307.3% | 396 | 60% |
| SPY B&H | — | -33.8% | +329.1% | — | 100% |

Forcing exits when a name drops out of the weekly watchlist was much worse
(cmo_bb 46.2% Win but -78.4% DD / -41.8% return), so held names should exit only
on the CMO mirror sell. The point-in-time RS universe does **not** improve Win%
or MaxDD versus the original 8-name basket (52.1% / -12.6% / +219.5%). Research
script: `/tmp/opencode/backtest_cmo_rs_watchlist.py`; no live changes.

## 5h. Win-rate attempts on the point-in-time RS universe (2026-11-18)

Point-in-time RS universe, daily, equal-weight all qualifying names, HWM15 +
5-session cooldown. Tested RS rank>=0.8/0.9/0.95, freshness<=8/3 weeks, top-N caps
8/12/20/all, 10% per-position stop, and entry-quality filters. Findings:

- High Win corners are small-sample or high-DD: cmo_bb rank>=0.95/fresh<=8 = 54.3% Win but -51.0% DD (46 trades); armed rank>=0.95/fresh<=3 = 53.8% Win / -24.9% DD but only 13 trades.
- Per-position 10% stop lowered Win and did not reduce DD; forcing exits when a name leaves the weekly watchlist was catastrophic (-78% DD).
- Fresh-CMO (`days_cmo_up<=0/1/2`) and MACD-diff filters worsened DD to -70..-75%; discard.
- Best SPY-beating candidate: **armed + EMA10 >= 1% above BB mid + P20w majority + HWM15**: 42.3% Win / -33.1% DD / +446.2% return / 343 trades vs SPY +329.1% / -33.8% DD. Trade Win remains low because breakout CMO is low-hit-rate by design.

To get Win% materially above 50%, this needs a different entry family (oversold
mean-reversion / CMO down-cross bounce) rather than more RS/trend filtering. A/B
research only; no live changes.

## 5i. Combined Slack-sourced universe, PIT vs SPY (2026-11-18)

Full point-in-time reconstruction of all five owner lists, then unioned per date:

- RS-Watchlist: settled-week rebuild, rank>=0.8, FRESH, BASE, daily MACD hist>0.
- MTF EMA/SMA Top 25: weekly EMA10>SMA40, MACD-gate proximity +/-5, score = gap/5 capped 5, top 25.
- Weekly-Takeoff top 25: full `weekly_takeoff` scoring config, top 25.
- EXPL-SHADOW top 10: `imminent_probability.select(top_n=10, min_dvol=50M)`.
- Daily Signal top 25: WCO^DCO score from `daily_signal_service.py`, applied on its settled daily date.

Weekly lists apply to the following week; Daily Signal applies on its own settled
close. Equal-weight all qualifying names, next-open fills, 0.05%/side, CMO WMA10,
P20w majority gate, EMA10 >= 1% above BB mid, 15% HWM + 5-session cooldown.
Latest settled checks: weekly 2026-11-09 = RS 36 / MTF 25 / Takeoff 25 / EXPL 10;
daily 2026-11-17 = Daily Signal 25; union = 96. No RS-only comparison was run.

| Config | Win% | MaxDD | Return | Trades | Exposure | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| combined armed + gap1 + majority + HWM15 | 39.7% | -34.4% | +860.1% | 1757 | 72.5% | 1.03 |
| combined cmo_bb + gap1 + majority + HWM15 | 41.3% | -34.4% | +988.8% | 1103 | 71.6% | 1.04 |
| SPY B&H | — | -33.8% | +329.1% | — | 100% | 0.86 |

Sub-periods: armed 38.8%/-34.4%/+81.4% (2017-20), 34.3%/-32.2%/+75.3% (2021-23),
45.1%/-26.8%/+228.3% (2024-now); cmo_bb 44.6%/-31.2%/+231.2% (2017-20),
35.2%/-29.7%/+65.4% (2021-23), 42.6%/-23.8%/+100.9% (2024-now).

The combined universe clearly beats SPY on total return and Sharpe, but does not
improve trade Win% and is 0.6pp worse on MaxDD. Research script:
`.tmp_research/combined_universe_backtest.py`; results:
`.tmp_research/combined_vs_spy.csv`. No live changes.

## 5j. High-win / low-DD pivot on combined universe (2026-11-18)

Owner's revised research gate: **SPY B&H is the only reference; may not beat SPY
return, but must deliver high Win% and minimum DD.** Original 8-name basket is no
longer a benchmark. Breakout CMO failed that gate (41% Win, -34% DD), so the
search moved to an oversold CMO bounce family:

- `bounce40`: buy when CMO(20) crosses up through **-40**; sell when CMO crosses up
  through **+30** or CMO < **-60**.
- Same combined PIT universe as §5i, P20w majority gate,
  `EMA10 >= 0.99 * Bollinger mid`, next-open fills, 0.05%/side, 15/20% HWM,
  5-session cooldown, equal-weight all qualifiers.

| Config | Win% | MaxDD | Return | Trades | Exposure | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| bounce40 + majority + gap>=-1% + HWM15 | **61.8%** | **-25.4%** | **+414.9%** | 76 | 36.3% | 0.73 |
| bounce40 + majority + gap>=-1% + HWM20 | **63.3%** | -32.1% | +391.5% | 79 | 37.8% | 0.69 |
| SPY B&H | — | -33.8% | +329.1% | — | 100% | 0.86 |

Sub-periods for HWM15: 63.9%/-25.4%/+88.4% (2017-20), 46.2%/-20.0%/+20.4%
(2021-23), 66.7%/-22.4%/+121.1% (2024-now). HWM20: 70.3%/-20.3%/+143.0%,
50.0%/-17.3%/+23.7%, 60.7%/-29.3%/+59.3%.

This is the first candidate that satisfies the revised gate: high Win% (>60%),
meaningfully shallower DD than SPY, and still ahead of SPY return. Caveats: only
76-79 trades and weak 2021-23 Win%/return; 2025 avg trade +18.1% contributes a
large share of return. A/B research only; no live changes.

Trade books: `common/docs/trade_books/bounce40_hwm15_trades.csv` and
`common/docs/trade_books/bounce40_hwm20_trades.csv`. Search:
`.tmp_research/win_dd_search2.csv`; verification:
`.tmp_research/best_config_verify.log`.

## 5k. Daily Bounce40 stock live wiring (2026-11-18)

Owner approved replacing the retired MTF-stock leg on the same paper account
#PA368CPXNS13 at 10:25 ET. Units were installed/enabled on 2026-11-18; the one-time
handover timer was canceled after the owner submitted manual liquidation orders post-close
(2026-11-18); those sells are expected to fill at the 2026-11-19 09:30 ET open, so the first
10:25 CMO run should start from a flat stock book.
The ETF leg and CoreEW are unchanged.

Live parity details:

- `cmo_live.py` scores the last settled daily bar (`date < today`), not the live bar.
- `cmo_universe.py` rebuilds the same five PIT sources as §5i/§5j; latest settled
  dry-run reproduced 96 names (RS 36 / MTF 25 / Takeoff 25 / EXPL 10 / Daily Signal 25).
- Entry: CMO(20) crosses up through -40, P20w `majority` read from the
  PHP-canonical leg-EMA series, and EMA10 >= 0.99 * Bollinger(20) EMA mid.
  P20w is a book-level risk gate: fewer than 2/3 benchmarks above their weekly
  EMA20 liquidates the whole book and blocks entries (same as `backtest_cmo.py`).
- Exit: CMO crosses above +30 or CMO < -60. Held names with no signal data are
  preserved, never blindly sold.
- Book: equal-weight all targets, 20%/ $500 rebalance band, 0.05%/side research cost;
  live fills are 10:25 market orders (next-open drift accepted by owner).
- Risk: 15% HWM checked only on the last settled daily bar of the week, with a
  5-session cooldown, exactly matching the verifier.
- State: Alpaca positions remain the source of truth; `cmo_positions`/`cmo_trades`
  hold strategy state and fills; guard/run state uses `mtf_guard_state` /
  `mtf_runs` mode `cmo40`.
- Unit: `swingtrader/services/mtf/systemd/swingtrader-cmo-bounce.{service,timer}`,
  Mon–Fri 10:25 ET, `Persistent=false`, Slack `[CMO-Bounce40]`.
- One-time `cmo_live.py --handover` cancels open stock orders, liquidates the old
  MTF-stock book, records `handover` sells, and seeds a fresh HWM before the first
  Bounce40 run. Dry-run verified 25 sells and no buys; `--dry-run --assume-flat`
  verified entry sizing on 2026-09-22 (AU + MMSI).

Dry-run commands:

```
swingtrader/services/optimizer/venv/bin/python3 swingtrader/services/mtf/cmo_live.py --dry-run --no-slack --sig-date 2026-11-17
swingtrader/services/optimizer/venv/bin/python3 swingtrader/services/mtf/cmo_live.py --dry-run --handover --no-slack --sig-date 2026-11-17
swingtrader/services/optimizer/venv/bin/python3 swingtrader/services/mtf/cmo_live.py --dry-run --assume-flat --no-slack --sig-date 2026-09-22
```
