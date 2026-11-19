# Buy/Sell Triggers — Current Live Strategies

**As of:** 2026-11-19 (MTF-stock emasma retired 2026-11-18; daily **CMO Bounce40** live on
`#PA368CPXNS13`; CoreEW **P20w** live since 2026-09-28, replacing CoreEG100). Source of truth is
always `AGENTS.md` (repo root) + the code cited below — this doc is a readable explanation of
the same logic, not a separate spec. If it ever disagrees with AGENTS.md or the code, the
code wins.

Four strategies are live. Three place real orders (CoreEW + CMO Bounce40 + MTF ETF) across
**three** Alpaca paper accounts; the fourth (Daily Signal) is Slack-only. "Decision cadence" is
how often each **acts**; all three order-placing rows rebalance at **equal weight,
trim-before-top-up** on every run.

| Strategy | Decision cadence | Places orders? | Buy trigger | Sell trigger |
|---|---|---|---|---|
| **CoreEW P20w** ("LegEMA") | Once/week — Mon–Fri 10:05 ET timer, acts on a **new settled week** only (midweek runs are a DB-claimed NO-OP) | ✅ Yes (Alpaca `#PA3GKZYLVO68`) | A leg's own settled **weekly** close is **above** its own EMA(20) → held LONG. The ON legs are equal-weighted to `equity ÷ #ON`; underweight ON legs are topped up | That leg's weekly close crosses **below** its EMA(20) → sold to cash; plus the weekly **equal-weight rebalance** of the ON legs (over-weights trimmed). Trim-before-top-up; all three OFF → whole book cash |
| **Daily CMO Bounce40 — stocks** | Once/day, 10:25 ET — last settled **daily** bar; weekly P20w `majority` gate | ✅ Yes (Alpaca `#PA368CPXNS13`) | `CMO(20)` crosses up through **−40** on the settled daily bar, P20w has ≥2/3 of QQQ/VTI/VTV above their weekly EMA20, and `EMA10 ≥ 0.99×Bollinger(20) EMA mid`. All qualifiers are equal-weighted; in-play holdings below target are topped up | `CMO` crosses up through **+30**, or `CMO < −60`; 15% HWM stop on the last settled bar of the week (5-session cooldown); P20w OFF → whole-book liquidation; EW trims on every run |
| **MTF Top-N — ETF leg** | Once/day, 10:25 ET — weekly signal, daily execution | ✅ Yes (Alpaca `#PA3U8GZ96PEN`) | Enters the top-**3** by settled-weekly score (weekly EMA10 > SMA40), or EW top-up; freed slots backfilled from rank 4+ | Held ETF still scored today drops out of the top-3, or rebalance trim; 25% profit sweep + 20% weekly-close HWM stop; no ATR ratchet |
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

## 2. Daily CMO Bounce40 stocks and MTF Top-N ETFs

> **Status 2026-11-19:** MTF-stock emasma was retired on 2026-11-18. Stock paper account
> `#PA368CPXNS13` now runs daily CMO Bounce40 via `cmo_live.py` /
> `swingtrader-cmo-bounce.timer`. The old stock book was liquidated manually after close on
> 2026-11-18, and the first clean 10:25 CMO run on 2026-11-19 started flat with
> `0 sells, 0 buys`. The ETF emasma leg is unchanged and ETF-only.

**Code:** `swingtrader/services/mtf/{cmo_live.py,cmo_core.py,cmo_universe.py}` for the daily
stock leg, and `swingtrader/services/mtf/{runner.py,executor.py,config.py}` for the weekly-signal
ETF leg. Two 10:25 ET timers place orders: `swingtrader-cmo-bounce.timer` and
`swingtrader-mtf-executor.timer` (the latter passes `--mode etf`). No live unit passes
`--mode stock` / `--mode all`, so no stock `mtf_pending` row is consumed. Full detail, Slack
formats, and backtest honesty caveats live in [CMO_STRATEGY.md](CMO_STRATEGY.md) §5k and
[services_doc/mtf_daily_runner.md](services_doc/mtf_daily_runner.md).

**ETF scoring (settled weekly bar only):** `min(gap_w / 5, 5)`, where `gap_w` is how far the
weekly close sits above its weekly SMA(40). Long-eligible only while weekly EMA(10) > SMA(40);
flat otherwise. Ties broken deterministically by `(-score, -gap_w)`. This score is used only
by the ETF leg; the stock leg no longer consumes it.

### Daily CMO Bounce40 stock paper (account `#PA368CPXNS13`, live 2026-11-18)

**Code:** `cmo_live.py` / `cmo_core.py` / `cmo_universe.py`, driven by
`swingtrader-cmo-bounce.timer` Mon–Fri 10:25 ET (`Persistent=false`), Slack `[CMO-Bounce40]`.
The runner scores the last settled daily bar (`date < today`), never the live bar.

- **Universe:** five PIT sources (RS / MTF / weekly takeoff / EXPL / Daily Signal), newest
  valid weekly + daily entries. Latest settled rebuild: 96 names (RS 36 / MTF 25 / TO 25 /
  EXPL 10 / DS 25).
- **Buy:** `CMO(20)` crosses up through **−40** on the settled daily bar, P20w `majority` is ON
  (≥2/3 of QQQ/VTI/VTV above their weekly EMA20), and `EMA10 ≥ 0.99×Bollinger(20) EMA mid`.
  All qualifiers are bought equal-weight.
- **Sell:** `CMO` crosses up through **+30**, `CMO < −60`, 15% HWM on the last settled bar of
  the week (5-session cooldown), or P20w OFF (whole-book liquidation). Held names with no
  signal data are preserved, never blindly sold.
- **Sizing:** equal weight across all targets; 20% / $500 trim-before-top-up band; 0.05%/side
  research cost. Live orders are 10:25 ET market orders (next-open drift accepted by owner).
- **State:** `cmo_positions` / `cmo_trades` hold strategy state and fills; guard/run state uses
  `mtf_guard_state` / `mtf_runs` mode `cmo40`. Alpaca remains the source of truth.
- **Cutover:** the one-time `cmo_live.py --handover` path is retained for verification/rollback
  only and is **not scheduled**; the scheduled handover was canceled after the owner submitted
  manual liquidation sells post-close on 2026-11-18 (filled at the 2026-11-19 open).

### ETF leg (top-3, account `#PA3U8GZ96PEN`, live 2026-11-18 as ETF-only)

**Code:** `runner.py` / `executor.py`, driven by `swingtrader-mtf-executor.timer` Mon–Fri 10:25 ET
via `executor_retry.py --mode etf`. The name signal is the settled weekly bar; execution and
rebalance run daily.

- **Buy (NEW BUY / REBALANCE):** enters the top-**3** by the weekly score above, or EW top-up;
  freed slots backfilled from rank 4+. Target value is `equity ÷ N` on every run.
- **Sell:** a held ETF **that is still scored today** drops out of the top-3, or a rebalance
  trim. There is **no ATR ratchet** on this leg.
- **Guards:** 25% profit sweep and a 20% weekly-close HWM stop (live since 2026-11-05). The old
  stock-leg ratchet/cool-off/chase-guard logic is not part of the ETF strategy.
- **Pending data:** only `mtf_pending` mode `etf` is written/consumed. Stale `stock` rows from
  before 2026-11-18 are ignored.

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
- `swingtrader/services/mtf/trigger_levels.py` + [SPEC_trigger_levels.md](SPEC_trigger_levels.md) — Slack report (10:00 / 17:05 ET) of the next buy/sell **price** per ticker for CoreEW P20w and MTF-ETF: the weekly-close level at which each flips (CoreEW = last settled weekly EMA20; MTF-ETF = lowest weekly close that puts the ETF in the top 3).
