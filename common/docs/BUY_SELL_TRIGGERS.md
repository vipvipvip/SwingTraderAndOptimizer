# Buy/Sell Triggers — Current Live Strategies

**As of:** 2026-09-28 (CoreEW **P20w** go-live, replacing CoreEG100). Source of truth is
always `AGENTS.md` (repo root) + the code cited below — this doc is a readable explanation of
the same logic, not a separate spec. If it ever disagrees with AGENTS.md or the code, the
code wins.

Three strategies are live. Only two place real orders:

| Strategy | Decision cadence | Places orders? | Buy trigger | Sell trigger |
|---|---|---|---|---|
| **CoreEW P20w** ("LegEMA") | Once/week — Mon–Fri 10:05 ET systemd timer, acts on a **new settled week** only | ✅ Yes (Alpaca) | A leg's own settled **weekly** close is **above** its own EMA(20) → held long and equal-weighted with the other ON legs | That leg's weekly close crosses **below** its own EMA(20) → sold to cash; plus the weekly equal-weight rebalance of the ON legs (over-weights are trimmed, under-weights topped up) |
| **MTF Top-N — stock leg** | Once/day, 10:25 ET | ✅ Yes (Alpaca, acct `#PA368CPXNS13`) | Ticker enters the top-**10** by weekly score | Drops out of top-10, **or** daily-ATR ratchet stop hit |
| **MTF Top-N — ETF leg** | Once/day, 10:25 ET (same run) | ✅ Yes (Alpaca, acct `#PA3U8GZ96PEN`) | Ticker enters the top-**3** by weekly score | Drops out of top-3 (no ratchet on this leg) |
| **Daily Signal** | Once/day, 17:00 ET | ❌ No — Slack alert only | All three of weekly+daily+hourly EMA(10)>SMA(40) crosses are done | N/A — never holds a position |

---

## 1. CoreEW P20w ("LegEMA") — per-leg weekly EMA(20) crossover (the only whole-book strategy)

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

## 2. MTF Top-N — weekly EMA/SMA rotation, run as **two independent legs**

**Code:** `swingtrader/services/mtf/runner.py` + `executor.py`, driven once/day at 10:25 ET
by `swingtrader-mtf-executor --mode all`, which scores and executes **both legs in the same
run** — a stock universe (VTI stocks, top-10) and a separate ETF universe (top-3) — each with
its own Alpaca paper account, its own holdings, and its own buy/sell trigger. They share the
same scoring formula but are otherwise fully independent books; being top-N on one leg has no
effect on the other. Full detail, Slack message formats, and the backtest honesty caveats
live in [services_doc/mtf_daily_runner.md](services_doc/mtf_daily_runner.md) — this is a
summary, not a replacement for it.

**Shared scoring** (settled weekly bar only): `min(gap_w / 5, 5)`, where `gap_w` is how far
the weekly close sits above its weekly SMA(40). Long-eligible only while weekly EMA(10) >
SMA(40); flat otherwise. Ties broken deterministically by `(-score, -gap_w)`.

### Stock leg (top-10, account `#PA368CPXNS13`)
- **Buy:** a stock ranks inside the top-10 by score that it didn't hold yesterday.
- **Sell (rotation):** a held stock drops out of the top-10.
- **Sell (ratchet):** the last settled **daily** close falls below
  `(highest daily close since entry) − 2×daily ATR`. This fires independently of ranking —
  a name can still be top-10 and get stopped out.

### ETF leg (top-3, account `#PA3U8GZ96PEN`)
- **Buy:** an ETF ranks inside the top-3 by score that it wasn't held yesterday.
- **Sell:** a held ETF drops out of the top-3. **No ratchet stop on this leg** — rotation out
  of the top-3 is the only exit.

Everything on both legs is evaluated on the last **complete** daily/weekly bar — never an
in-progress/partial bar.

---

## 3. Daily Signal — alert only, never places an order

**Code:** `swingtrader/services/ema_sma_crossover/daily_signal_service.py`, once/day at
17:00 ET. Full detail in
[HANDOFF_DailySignal_All3CO.md](HANDOFF_DailySignal_All3CO.md).

- **Trigger (all three required, on settled bars only):**
  1. **WCO** — weekly EMA(10) > SMA(40) on the last settled weekly bar.
  2. **DCO** — daily EMA(10) > SMA(40) on the last settled daily bar.
  3. **HCO** — hourly EMA(10) > SMA(40) on the last settled, quality-gated (`vol >= 1000`)
     hourly bar, **and** that up-cross happened within the last 1-2 trading days.
- When all three are true, the ticker is posted to Slack (`[DAILY]`) with its score. There is
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
- `swingtrader/services/mtf/{runner.py,executor.py,config.py}` — MTF Top-N implementation.
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py` — Daily Signal implementation.
