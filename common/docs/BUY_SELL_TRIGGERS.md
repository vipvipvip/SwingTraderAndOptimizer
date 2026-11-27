# Buy/Sell Triggers — Current Live Strategies

**As of:** 2026-11-20 (S1 full replace LIVE on both paper legs; MTF emasma ETF and
MTF-stock/CMO Bounce40 retired; CoreEW **P20w** live since 2026-09-28, replacing CoreEG100).
Source of truth is always `AGENTS.md` (repo root) + the code cited below — this doc is a
readable explanation of the same logic, not a separate spec. If it ever disagrees with AGENTS.md
or the code, the code wins.

Four strategies are live. Three place real orders (CoreEW + S1 stocks + S1 ETFs) across
**three** Alpaca paper accounts; the fourth (Daily Signal) is Slack-only. "Decision cadence" is
how often each **acts**; all three order-placing rows rebalance at **equal weight,
trim-before-top-up** on every run.

| Strategy | Decision cadence | Places orders? | Buy trigger | Sell trigger |
|---|---|---|---|---|
| **CoreEW P20w** ("LegEMA") | Once/week — Mon–Fri 10:05 ET timer, acts on a **new settled week** only (midweek runs are a DB-claimed NO-OP) | ✅ Yes (Alpaca `#PA3GKZYLVO68`) | A leg's own settled **weekly** close is **above** its own EMA(20) → held LONG. The ON legs are equal-weighted to `equity ÷ #ON`; underweight ON legs are topped up | That leg's weekly close crosses **below** its EMA(20) → sold to cash; plus the weekly **equal-weight rebalance** of the ON legs (over-weights trimmed). Trim-before-top-up; all three OFF → whole book cash |
| **S1 — stocks** | Once/day, 10:25 ET — last settled **daily** entry; settled weekly risk exit | ✅ Yes (Alpaca `#PA368CPXNS13`) | Daily EMA(10) crosses up EMA(20) on the last settled daily bar → symbol joins the active target set. All active names are equal-weighted; new/underweight names bought after sells | Settled weekly EMA(10) crosses down EMA(20) → full inactive/exit; names outside the active set are sold first; >20%/$500 overweight trims on every run |
| **S1 — ETFs** | Once/day, 10:25 ET — last settled **daily** entry; settled weekly risk exit | ✅ Yes (Alpaca `#PA3U8GZ96PEN`) | Same S1 rules over all 28 enabled ETFs; one-time handover completed 2026-11-20→11-24, now explicit `--handover` only | Same S1 weekly cross-down exit plus outside-target sells and overweight trims |
| **Daily Signal** | Once/day, 17:00 ET | ❌ No — Slack alert only | **Both** of weekly + daily EMA(10)>SMA(40) crosses are done (see §3) | N/A — never holds a position |

---

## 1. CoreEW P20w ("LegEMA") — per-leg weekly EMA(20) crossover

**Code:** `TradeExecutorService::runLegEma()` / `replayLegEmaSeries()` / `legEmaTrail()` /
`legEmaState()` (`swingtrader/backend/app/Services/TradeExecutorService.php`), driven by
`php artisan trades:execute-leg-ema --span=20` (`ExecuteLegEma.php`) via the systemd timer
`swingtrader-legema.timer` (`swingtrader/services/mtf/systemd/`), Mon–Fri 10:05 ET,
`Persistent=true`. Tickers: QQQ, VTI, VTV. Account `#PA3GKZYLVO68`. Slack `[CoreEW-LegEMA]`.

### What decides "buy" vs "sell"

This is a **per-leg** decision — each ETF is judged on its own trend, so the three legs can be
LONG/LONG/CASH, LONG/CASH/CASH, or all cash. Every run rebuilds the same series from scratch:

1. **Collect settled weekly closes** — for each of QQQ/VTI/VTV, take its weekly closes where
   `date + 7 <= CURRENT_DATE` (a week whose Friday close has not fully formed is never read),
   and keep only week dates present for **all three**.
2. **Compute each leg's EMA(20)** — `ewm(span=20, adjust=False)`: seeded with the leg's first
   weekly close, then `ema[i] = alpha*close[i] + (1-alpha)*ema[i-1]` with `alpha = 2/21`. No
   warm-up gap — it's defined from bar 0.
3. **Compare, per leg** — this is a **pure crossover, no band**: `close > EMA(20)` → that leg
   is **ON** (long), `close < EMA(20)` → **OFF** (cash). ON/OFF only changes on the week where
   the leg actually crosses.

**The signal is PHP-canonical and the backtest cannot drift from it:** the backtest
(`backtest_trio_ew.py --leg-ema 20`) shells out to `php artisan trades:coreew-leg-ema-series`
and consumes the very series this driver computes. Any new CoreEW variant must be added in
PHP for the same reason — never re-implemented in Python.

### What happens on each weekly action

- **ON legs are equal-weighted against each other**, target value = `account_equity / (number
  of ON legs)`. If all three are OFF, the whole book is cash and nothing is bought.
- **Sells run before buys (trim-before-top-up)** on every action: a leg holding more than its
  equal share is sold down first (this is what keeps winners trimmed and losers parked), then
  the underweight ON legs are bought up to their equal share. Exits go through `rebalanceTrim`
  when a DB trade record exists for the position, otherwise a direct market sell gated on
  `waitForOrderFill`. **A sell is never logged/claimed until Alpaca actually confirms
  `status=filled`** — a `new`/`accepted` order is not a fill.

### Why it doesn't trade every day despite running every weekday

The last settled **week** date is the run's identity, claimed atomically in the `coreew_runs`
table (unique `strategy='legema'`, `span`, `week` → `insertOrIgnore` → Postgres
`ON CONFLICT DO NOTHING`). Exactly one process can claim a given week, cluster-safely; losers
get 0 rows and return a NO-OP. So the 10:05 weekday timer costs nothing mid-week — the book
acts once per **new settled week** (Monday, on last Friday's close). `--override` releases the
current week's claim to force a re-action; `--dry-run` never claims, releases, or writes, and
respects an existing claim as a NO-OP.

### Other guardrails

- **Settled weeks only** (`date + 7 <= CURRENT_DATE`) — week *W*'s Friday close decides, and
  the action is taken from the following Monday. The **backtest** prices the trade at the
  following **Tuesday's close**; **live** fills Monday intraday at 10:05 ET (+0–60 s
  randomized delay) — a real, expected one-session divergence, documented in
  `coreew_family.md`, not a bug.
- **30-minute opening warm-up**: no trades in the first 30 minutes of the session
  (09:30–10:00 ET), even with `--override`. This check happens *before* the week claim, so a
  catch-up run landing in the warm-up window can never burn a week.
- Read-only state check anytime (works market-closed too, no orders):
  `php artisan trades:execute-leg-ema --span=20 --state` (or `--json` for machine-readable
  output, also used to verify backtest parity).
- Performance history, rejected overlays, and the full predecessor timeline:
  [coreew_family.md](coreew_family.md). Backtest figures are **signal quality, not expected
  returns** (A/B comparison only, and the published numbers fill a session later than live).

### What this replaced

**CoreEG100 / EG100** (`trades:execute-EW-gate100`) was live 2026-09-27 → replaced 2026-09-28
by P20w. It was a **portfolio-level** all-in/all-out gate: a synthetic equal-weight QQQ/VTI/VTV
index vs its own **EMA(100)** on *daily* closes, pure crossover, one switch for all three legs.
P20w is a different algorithm (per-leg, **weekly**, EMA 20) that reuses variant A's weekly
equal-weight machinery. EG100's code is retained **off-cron** for rollback (uncomment the
crontab line — the books hand over cleanly, since both target EW among the 3 legs). Before it
came the **monotone weekly-ratchet gate** ("variant S", `trades:execute-EW-gate`, retired
2026-09-27) and before that the original pure drift-gated equal-weight driver
(`trades:execute-EW-ETF`, intraday, no signal at all). **Any doc describing CoreEW's trigger as
an index EMA(100) gate, a weekly ATR ratchet, or a 0.5%-drift rebalance is describing a
retired driver, not the live one.**

---

## 2. S1 stocks and S1 ETFs

> **Status 2026-11-20:** owner-directed full replace. The existing 10:25 ET systemd units and
> their entrypoint paths are unchanged; the scripts those units call now dispatch to
> `s1_live.py`. MTF emasma ETF and MTF-stock/CMO Bounce40 are retired. No installed systemd
> units were changed and no live orders were placed during the code cutover.

**Code:** `swingtrader/services/mtf/s1_live.py` is the live runner for both legs;
`cmo_universe.py` supplies the dynamic stock pool; `executor.py` supplies Alpaca fill/key
helpers; `backtest_s1_single.py` / `backtest_s1_portfolio.py` are the A/B research scripts.
Two 10:25 ET timers place orders: `swingtrader-cmo-bounce.timer` (stock entrypoint
`cmo_live.py` → `s1_live.py --mode stock`) and `swingtrader-mtf-executor.timer` (ETF entrypoint
`executor_retry.py --mode etf` → `s1_live.py --mode etf`). The 16:45
`swingtrader-mtf-scorer.timer` still calls `runner.py`, which now calls
`s1_live._recap('etf')` and exits without orders.

**S1 signal (settled bars only):**

- **Daily entry:** EMA(10) crosses up EMA(20) on the last settled daily bar (`date < today`);
  the symbol becomes active and stays in the target set until a settled weekly exit.
- **Weekly exit:** weekly EMA(10) crosses down EMA(20) on a bar with `bar_date + 7 <= sig_date`.
  That is the only exit signal; there is no separate recent-down/cross-down carry state.
- **EMA:** `ewm(span=N, adjust=False, min_periods=N)`; long/flat only; cost 0.05%/side.
- **Targets:** all active names on `sig_date`, equal-weighted to `equity ÷ #targets`.

**Sizing and execution:** sell-first — exit outside-target names and trim >20%/$500 overweight
positions, refresh cash/positions, then buy new/underweight targets with a 0.995 cash cap. Dry-run
simulates the same cash/position path but places no orders. Live uses 10:25 ET market orders,
after the data gate and outside the 09:30–10:00 ET warm-up; DB trades are recorded only after
`waitForOrderFill` confirms `status=filled`.

### Stock leg (account `#PA368CPXNS13`)

- **Pool:** current five-source `cmo_universe.active_universe()`; 2026-11-19 dry-run: 96 names,
  90 S1 targets. Dynamic universe means live counts may differ from the static backtest.
- **State:** `s1_runs` / `s1_trades`; Slack `[S1-STOCK]`.
- **Cutover:** account expected flat from the manual 2026-11-18 liquidation; no handover needed.
  `cmo_live.py --handover` maps to S1 handover for verification/rollback only; normal execute never auto-handovers on either leg.

### ETF leg (account `#PA3U8GZ96PEN`)

- **Pool:** all enabled ETFs (28 at cutover); 2026-11-19 dry-run: 23 S1 targets.
- **State:** `s1_runs` / `s1_trades`; Slack `[S1-ETF]`.
- **Cutover:** the one-time ETF handover completed 2026-11-20→11-24; normal execute no longer
  claims `handover`, and `--handover` is explicit/manual only.

**Corrected A/B (2016-01-04→2026-11-19, cost 0.0005):** ETF S1 +252.1% / -20.82% MDD / 0.81
Sharpe vs daily-only +36.9% / -34.00% / 0.27 and EW B&H +283.8% / -34.04% / 0.82. Stock S1
+417.8% / -37.93% / 0.76 vs daily-only +574.6% / -53.76% / 0.73 and EW B&H +1996.2% /
-36.32% / 0.79. These are relative A/B only, not expected returns (survivorship and idealized
fills still apply).

Everything on all live legs is evaluated on the last **complete** daily/weekly bar — never an
in-progress/partial bar.

---

## 3. Daily Signal — alert only, never places an order

**Code:** `swingtrader/services/ema_sma_crossover/daily_signal_service.py`, once/day at
17:00 ET.

- **Trigger (both required, on settled bars only):**
  1. **WCO** — weekly EMA(10) > SMA(40) on the last settled weekly bar.
  2. **DCO** — daily EMA(10) > SMA(40) on the last settled daily bar.

- When both are true, the ticker is posted to Slack (`[DAILY]`) with its score. There is
  no "sell" side — it's a one-shot alert, not a position.

---

## Reference

- `AGENTS.md` (repo root) + `common/docs/OPERATING_RULES.md` "CoreEW family" bullets —
  authoritative summary, updated whenever any of the above changes.
- `swingtrader/backend/app/Services/TradeExecutorService.php` — CoreEW P20w implementation
  (`runLegEma`/`replayLegEmaSeries`); `swingtrader/backend/app/Console/Commands/ExecuteLegEma.php`
  — the live driver (`trades:execute-leg-ema --span=20`).
- `common/docs/coreew_family.md` — CoreEW narrative, backtest numbers, rejected overlays, and
  the EG100 → P20w decision history.
- `swingtrader/services/mtf/{cmo_live.py,cmo_core.py,cmo_universe.py}` — daily CMO Bounce40 stock implementation.
- `common/docs/CMO_STRATEGY.md` §5k — CMO live wiring, cutover, and verification detail.
- `swingtrader/services/mtf/{runner.py,executor.py,config.py}` — MTF ETF Top-N implementation (ETF-only live).
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py` — Daily Signal implementation.
- `swingtrader/services/mtf/trigger_levels.py` + [SPEC_trigger_levels.md](SPEC_trigger_levels.md) — Slack report (10:00 / 17:05 ET) of the next buy/sell **price** per ticker for CoreEW P20w only (QQQ/VTI/VTV): the last settled weekly EMA20, at which the leg flips. MTF-ETF rank levels were removed 2026-11-25 (strategy replaced by S1 on 2026-11-20).
