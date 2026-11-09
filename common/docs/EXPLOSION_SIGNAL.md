# Explosion / jerk signal — research findings & handoff

Status: **research tool, not live.** No orders. A paper-only **shadow** service posts a
Slack snapshot (Tue 10:35) but never touches a broker account. Built 2026-11-07; shadow
service installed 2026-11-07. Pick up from here or extend; nothing in the live trading
path depends on it.

## What it is

A single parameterized script that, for any ticker (stock or ETF), estimates the
probability of an **imminent explosive move** and reports the jerk/OBV/volume signal
**by date**, in the same shape as the MTF "market regime" Slack report
(`swingtrader/services/mtf/runner.py::_regime_block`, ~L1131).

- Code: `common/scripts/imminent_probability.py`
- Model artifact: `common/scripts/models/imminent_probability.joblib`
- Data: existing canonical DB tables — **never re-acquire** from Alpaca/yfinance.

## How to run

```bash
cd common/scripts
python3 imminent_probability.py --train                 # fit + save model (~1 min)
python3 imminent_probability.py MRNA                    # by-date weekly+daily report
python3 imminent_probability.py MRNA --asof 2026-06-08  # report as of a settled date
python3 imminent_probability.py CAT QQQ --score         # compact one-line scores
python3 imminent_probability.py MRNA --trades --tf daily --start 2025-06-01
#   ^ BUY/SELL log + Total, then: B&H <ticker> and B&H SPY over the same window
python3 imminent_probability.py MRNA --trades --tf both --start 2025-06-01
```

`--trades` prints the ATR-filtered trade log, the strategy total, and a benchmark
line: `B&H <TICKER> x%   B&H SPY y%   (first -> last bar)`. The benchmark uses the
same timeframe and date window as the trade log (weekly trades → weekly B&H;
daily trades → daily B&H). This replaces the deleted `/tmp/report_ticker.py`.

`--asof` must be a settled bar (`date < today`). No partial/live bars.

## Data & env

- Postgres `swingtrader-db` (postgres:16-alpine, `127.0.0.1:5432`), db `swingtrader`,
  user `swingtrader`, password **`swingtrader_dev_password`** (default in script; also
  `swingtrader/services/mtf/config.py`).
- Tables: `tbl_prices_weekly` / `tbl_prices_daily` joined to `tbl_stock_tickers`
  (`symbol`, `is_etf`). Columns used: `date, close, high, low, volume`.
- Feed/source: `feed=sip`, `source=alpaca`, **`adjustment=all`** → closes are
  dividend+split adjusted. When cross-checking in Thinkorswim (unadjusted), verify
  **dates and shape**; historical closes differ slightly (esp. just after ex-div).
  Volume is consolidated SIP, so it tracks TOS consolidated volume.

## Model

Weekly cross-sectional logistic regression (comparable across the whole universe),
sigmoid-calibrated with `TimeSeriesSplit(3)`.

- Features (17): `dd_52w, wks_since_hi, base_range_12, dist_base_hi, ema20_dist,
  ret_4w, ret_13w, vel, accel, jerk, rv, rv_dryup, uvr13, obv_slope, vol_exp,
  atr_pct, is_etf`.
- Labels:
  - `up` = max close ≥ +15% within 8 weeks
  - `down` = min close ≤ −15% within 8 weeks
  - `expl` = max close ≥ +30% within 13 weeks
- Dataset: 646,093 rows, 1,416 tickers, 2017-05-15..2026-08-03.
- Base rates: up 0.219, down 0.134, expl 0.113.
- Holdout (date ≥ 2024-01-01): **UP AUC 0.699** (Brier 0.1678),
  **DOWN AUC 0.673** (Brier 0.1089), **EXPL AUC 0.787** (Brier 0.1016).
- `score()` returns `p_up_15pct_8w`, `p_down_15pct_8w`, `p_no_move_8w`,
  `p_expl_30pct_13w`.

Important: only the **weekly** probability model exists. The daily block reports
jerk/OBV/volume but **no trained daily probability** (open item).

## Signal semantics (by-date report)

Weekly block: `P_expl | P_up | v | a | j | JERK | OBV | Vol`
Daily block: `v | a | j | JERK | OBV | Vol`

- `v, a, j` = normalized fractional velocity / acceleration / jerk per bar.
  - weekly: vspan=4, smooth=3
  - daily: vspan=5, smooth=3
- `JERK`:
  - **IMM** (imminent / pre-breakout hook) = `a > a_min` AND `j > j_min` AND
    `j > prev_j` AND `a > prev_a` AND `v > prev_v` AND `v < v_hi`
  - **FIRE** (already vertical) = `v > v_hi` AND `a > a_min`
  - thresholds: weekly `a_min=j_min=3e-4, v_hi=0.02`;
    daily `a_min=j_min=2e-4, v_hi=0.02`
- `OBV`: `ACCUM` (slope>0 & uvr≥0.55), `DIST` (slope<0 & uvr≤0.45),
  `acc+`, `dist-`, `flat`. Weekly smooth/span 13/4; daily 10/5.
- `Vol`: `rv = ema13(volume)/ema52(volume)` → `EXPAND` (≥1.5),
  `DRY` (≤0.85), else `normal`.

## Trade translation (`--trades`)

`translate_trades()` turns the IMM/FIRE signal into a single-position trade log
(one position at a time) and appends a buy-and-hold benchmark.

```bash
cd common/scripts
python3 imminent_probability.py MRNA --trades --tf daily  --start 2025-06-01
python3 imminent_probability.py MRNA --trades --tf weekly --start 2025-06-01
python3 imminent_probability.py MRNA --trades --tf both   --start 2025-06-01
python3 imminent_probability.py MRNA --trades --tf daily  --start 2025-06-01 --fill next_open
```

### Fill convention (`--fill`)
- `--fill close` (default): signal bar's close is the fill price (optimistic — the
  signal is only known at/after that close).
- `--fill next_open`: fill at the **next bar's open** (more realistic; no look-ahead).
- The row log uses the selected `--fill`; **both totals are always printed**, so
  you can see how much the close-vs-open assumption contributes.
- Stop triggers are always evaluated on closes (`close ≤ entry − 2.5×ATR`); `--fill`
  only changes the assumed execution price.

### Entry
- Enter when state is **IMM** (pre-breakout hook) or **FIRE** (already vertical).
- Skip the signal if either filter trips:
  - **gap filter** — `(close − prev close)/ATR14 > GAP_ATR (2.0)` → don't chase a gap-up.
  - **extension filter** — `(close − EMA20)/ATR14 > EXT_ATR (4.0)` → too extended.
- `ATR_WINDOW = 14`.

### Exit
| Reason | Trigger |
|---|---|
| `stop` | close ≤ entry − `STOP_ATR (2.5) × ATR14` (ATR at entry) |
| `fire-off` | position reached FIRE (entered FIRE, or FIRE printed while held) and state is no longer FIRE |
| `hook-fail` | entered IMM, never FIREd, and wait expired — 4 weekly bars / 10 daily bars (`max_wait`) |
| `open` | still held at the last settled bar (Sell = last close) |

Priority each bar: `stop` → `fire-off` → `hook-fail`.

### Output
- One row per trade: `Buy @ | Sell @ | Move | Reason`, priced under the selected `--fill`.
- Two `Total` lines: `Total (close)` and `Total (next open)` — compounded strategy
  return, `n`, `W/L`. Counts can differ slightly because shifting the fill bar
  changes the stop/wait window.
- Benchmark line: `B&H <TICKER> x%   B&H SPY y%   (first -> last bar)` — a single
  buy-and-hold of the ticker and of SPY over the same timeframe and date window.
  It is the baseline, **not** a trade.
- `--tf both` prints weekly then daily, each with its own benchmark line.

Parameters (top of `imminent_probability.py`): `ATR_WINDOW=14`, `GAP_ATR=2.0`,
`EXT_ATR=4.0`, `STOP_ATR=2.5`; `max_wait` = 4 (weekly) / 10 (daily).

Note: `--backtest` is a different, cross-sectional top-N portfolio test — it exits
on `target` (+30%), `stop` (if `--stop` > 0), or `time` (13 weeks), not the reasons
above.

## Shadow service & signal-state table

`common/scripts/explosion_shadow.py` is the paper-only shadow leg. It still builds the
top-N cross-sectional picks (`ip.select()`, default `--top 10`), maintains the paper
ledger, and applies the QQQ daily+weekly regime gate — but its Slack post is now a
**signal-state snapshot**, not a ranked pick list.

- Units: `common/systemd/swingtrader-explosion-shadow.{service,timer}`, installed to
  `/etc/systemd/system`; **Tue 10:35 ET** (`Persistent=false`), so Monday's daily bar
  is loaded by the 16:30 backfill. **Paper only — no orders, no live account.**
- Live command: `explosion_shadow.py --top 10 --min-dvol 50000000`.
- Ledger: `common/scripts/jerk/shadow_ledger.json` (paper positions, +30%/13w exits).

### ON definition
- **`weekly_on`** = latest settled weekly `JERK` state is **IMM or FIRE**
  **and close > EMA20** (20-week mean).
- **`daily_on`** = latest settled daily `JERK` state is **IMM or FIRE**
  **and close > EMA20** (20-day mean).
- Both IMM and FIRE are entries in `--trades` (`translate_trades`, IMM = early hook,
  FIRE = already vertical), so ON is the union. `*_state` keeps the raw `IMM`/`FIRE`/`-`.
- The **close > EMA20** trend gate (`ON_ABOVE_EMA20 = True`) exists to reject
  counter-trend dead-cat bounces: e.g. on 2026-11-06 it removed daily IMMs ALNT, ACLS,
  ACMR, ANET, ATI (all below EMA20 after -5% to -11% down days) while keeping AGO, AGL,
  AIR, ALGN (all above EMA20). It cuts the daily ON list 176 → 108 and weekly 487 → 358.
  Set `ON_ABOVE_EMA20 = False` to restore the raw IMM/FIRE union.
- Universe: `tbl_stock_tickers WHERE enabled` with trailing 13-week dollar volume
  ≥ `--min-dvol` (default **$50M/wk**).

### Per-run snapshot table
`ensure_state_table()` creates it on first non-dry run:

```sql
CREATE TABLE IF NOT EXISTS tbl_explosion_signal_state (
    run_date DATE NOT NULL,
    ticker_id BIGINT NOT NULL REFERENCES tbl_stock_tickers(id),
    symbol VARCHAR(20) NOT NULL,
    weekly_on BOOLEAN NOT NULL,
    daily_on BOOLEAN NOT NULL,
    weekly_date DATE,
    daily_date DATE,
    weekly_state VARCHAR(8),
    daily_state VARCHAR(8),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_date, ticker_id)
);
```

- One row per enabled/liquid ticker per run (`INSERT ... ON CONFLICT (run_date,
  ticker_id) DO UPDATE`), so re-running the same `run_date` is idempotent.
- `weekly_date` is the settled weekly bar (Monday stamp; e.g. 2026-11-02 covers the
  week ending Fri 2026-11-06). `daily_date` is the latest settled daily bar.
- `weekly_state` / `daily_state` keep `IMM` / `FIRE` / `-` so the list can be split
  later without recomputing.

### Slack message
The Slack post is two blocks concatenated, chunked at 3,500 chars/webhook call, and all
ticker lists are **comma-delimited**.

Block 1 — `state_message()`:

```
asof <weekly settled date> | weekly ON <n> | daily ON <n> | both ON <n>
regime: daily=ON|OFF weekly=ON|OFF
WEEKLY ON(n): <symbols>
DAILY ON(n): <symbols>
BOTH ON(n): <symbols>          # weekly_on AND daily_on
WEEKLY OFF(n): <symbols>
DAILY OFF(n): <symbols>
```

Block 2 — `variations_message()`:

```
asof <weekly settled date> | universe <n>
weekly bar <date> | daily bar <date>
regime: daily=ON|OFF weekly=ON|OFF

FIRE ONLY - weekly (<n>)
<symbols>

FIRE ONLY - daily (<n>)
<symbols>

WEEKLY AND DAILY ON (<n>)
<symbols>
```

- `WEEKLY ON` / `DAILY ON` / `BOTH ON` and the `WEEKLY AND DAILY ON` variation apply
  the `close > EMA20` gate; `BOTH ON` is the weekly∧daily intersection.
- `FIRE ONLY` lists are the **raw** FIRE state (no EMA20 gate), so they still show
  210 weekly / 36 daily.
- **OFF** = was ON in the previous snapshot (`max(run_date)` strictly before the current
  one) and is not ON now. First run prints `OFF: first run (no prior snapshot)`.
- Email is **not** used — the variations block goes to Slack (`send_email` removed).
- The old top-10 pick summary is still printed to stdout/journal (`msg_ledger`) but is
  **not** posted to Slack.
- `--dry-run` writes neither the table nor the ledger and sends no Slack;
  `--no-slack` writes both but posts nothing; `--print-variations` prints block 2.

### `--asof` and the settled-weekly rule
`last_settled()` requires `bar_date + 7 <= today` (imminent_probability.py), so a
Sunday run still lands on the prior Monday: on **Sun 2026-11-08** it picks **2026-10-26**
(`11-02 + 7 = 11-09`). The scheduled **Tue** run picks **2026-11-02**. To seed the latest
complete week early, pass a cutoff that admits it:

```bash
cd common/scripts
python3 explosion_shadow.py --asof 2026-11-09 --no-slack   # weekly 2026-11-02, daily <= 2026-11-06
python3 explosion_shadow.py --dry-run                      # print only
```

Query the latest snapshot:

```sql
SELECT symbol, weekly_on, daily_on, weekly_state, daily_state
FROM tbl_explosion_signal_state
WHERE run_date = (SELECT max(run_date) FROM tbl_explosion_signal_state)
ORDER BY symbol;
```

## Findings

### 1) MRNA — the reference case (works)
- Weekly **IMM 2026-06-08**, daily **IMM 2026-08-12**, daily FIRE 2026-08-13 —
  right before the Aug-19 gap-up (~63 → 174). FIRE again Aug 19–25; IMM Sep 16–17
  before the second leg (145 → 199).
- Weekly `P(expl≥30%/13w)` rose 0.29 (Aug 10) → 0.58 (Aug 17) → 0.62 (Aug 24)
  vs 0.11 base rate.
- Volume context: distribution 2024-10→2025-03, accumulation 2025-06 / Dec-2025,
  dry-up Mar–Jun 2026, blow-off week 2026-08-17 (394M, rv≈1.56).

### 2) QQQ — historical check (catches up-legs, not breakdowns)
Dividend-adjusted closes; TOS unadjusted may differ slightly.

| Window | What the process did |
|---|---|
| **2020 Jan–Jun** (crash Feb–Mar, V-recovery) | Caught the recovery: daily IMM 03-19 @170 / 03-23 @164 (fwd65 +39%/+43%), weekly IMM 04-06 @193 (fwd13 +31.7%), weekly FIRE 04-20/27, 05-04 (+20–25%). **Faked pre-trough:** weekly IMM 01-06 (fwd13 −7.8%); daily IMM 03-02/03-04 (fwd20 −11%/−16%). |
| **2022 Jan–Mar** (down) | **No clean breakdown signal.** All IMMs were counter-trend bounces that failed: weekly 02-14 @331 (fwd13 −15.4%), 03-14 @341 (−21.8%); daily 01-12 @376 (fwd65 −12.5%), 02-10 @348 (−16.6%). |
| **2023** (up) | Strong: weekly IMM 01-09 @275 (fwd13 +13.6%, 26w +35.3%), 01-30 FIRE @300, 04-03 @312 (+15.3%), 10-30 @362 (+17.0%), 11-13 @380 + 11-20 FIRE @383. Jul–Aug chop faded by 65d. |
| **2025** (up) | Caught the April bottom: weekly IMM 04-07 @451 (fwd13 +22.1%, 26w +30.0%), 04-21 @469 (+20.0), 04-28 @485 (+13.4%); weekly FIRE 05-12/19; daily IMM 04-09 @463 (+11.8% 20d / +23.8% 65d). **Faked in the Feb correction:** weekly 02-03 @519 (fwd13 −6.5%), daily Jan IMMs (fwd65 −11 to −16%). |
| **2026** (up) | Weekly FIRE cluster Apr-20/27, May-04 (662→710) at the April leg start; QQQ has no daily FIRE in 2026 (only weekly). |

**Verdict:** the process reliably fires at the **start of explosive up-legs after a base
or capitulation** (Mar-2020, Jan-2023, Apr-2025, Apr-2026). It is **not a crash or
downtrend detector** — in Jan-2022 and Feb-2025 it produced false long IMMs into
declines. For QQQ it is an "explosive leg confirmation" tool, not a top/warning tool.

### 3) Low-beta names — daily-only does NOT work
Tested AGO daily-only (full history) and a 28-name low-beta basket
(AGO, CB, TRV, PGR, ALL, AFL, KO, PG, GIS, K, MCD, WMT, JNJ, CL, SO, DUK, ED, XEL,
MMC, AON, AJG, BRO, KMB, CLX, HSY, SYY, ADM, MO, PM, UPS).

- AGO daily: IMM n=403 → median fwd65 **+3.1%**, hit +30%/65d **6.0%** vs baseline
  +2.6% / 5.9% → **no edge**. Adding OBV-ACC made it worse.
- Low-vol tercile (daily): baseline hit +10%/20d 2.8%, IMM 2.9% → no edge.
  Volatility-normalized a/j (z-scored per ticker) still only lifted to ~3.3–4.3%.
  Weekly on the same basket: IMM low-vol hit +20%/13w 1.6% vs baseline 1.7% → no edge.
- Only `FIRE` (already moving) shows edge, but it is rare and even that had a
  negative median 13w in low-vol names. AGO FIRE+ACC is n=17 — not robust.

**Verdict:** jerk/acceleration is a **high-beta phenomenon**. Keep the process for
MRNA-type names; for low-beta (AGO, broad ETFs) it is the wrong tool regardless of
weekly vs daily. Natural next test: **range breakout + volume expansion** (Donchian
20/55 + RVOL), not derivative timing.

### 4) Current state (2026-11-07, weekly bar 2026-11-02)
- QQQ P_expl 0.046, OBV rolling to `dist-`; VTI P_expl 0.041, OBV `DIST`;
  VTV P_expl 0.040, OBV `acc+` but last IMM (10-26 @228) faded. No live signal.
- For QQQ/VTI/VTV the daily threshold is too loose (~35–42 signals/yr → 3–4/month,
  mostly flickers); treat only weekly FIRE clusters as high-conviction.

## Caveats / known weaknesses
- Thresholds (`a_min`, `j_min`, `v_hi`) were hand-tuned to MRNA → overfit risk.
- No drawdown→base precondition, so uptrend jerk can false-positive (e.g. CAT 2025-08-22).
- Probabilities are **weekly-only**; daily rows have no calibrated probability.
- Backtest forward returns are not tradeable returns (no costs/slippage); treat as
  relative signal quality only.

## Open next steps
1. Add a **daily probability model** (or explicitly document daily as signal-only).
2. Add a **base/capitulation precondition** to cut false IMMs (require prior drawdown
   or range contraction).
3. Validate thresholds out-of-sample across high-beta names; consider
   volatility-normalized a/j.
4. Test **Donchian breakout + RVOL** for low-beta / ETFs (the code above says jerk is
   not the right tool there).
5. If ever surfaced, format as a Slack block mirroring `_regime_block` — but do not
   wire into live path without user sign-off.
