# Buy/Sell Triggers — Current Live Strategies

**As of:** 2026-09-27. Source of truth is always `AGENTS.md` (repo root) + the code cited
below — this doc is a readable explanation of the same logic, not a separate spec. If it
ever disagrees with AGENTS.md or the code, the code wins.

Three strategies are live. Only two place real orders:

| Strategy | Decision cadence | Places orders? | Buy trigger | Sell trigger |
|---|---|---|---|---|
| **CoreEG100** | Checked every 5 min, market open only | ✅ Yes (Alpaca) | Equal-weight QQQ/VTI/VTV index crosses **above** its own EMA(100) | Index crosses **below** its own EMA(100) |
| **MTF Top-N — stock leg** | Once/day, 10:25 ET | ✅ Yes (Alpaca, acct `#PA368CPXNS13`) | Ticker enters the top-**10** by weekly score | Drops out of top-10, **or** daily-ATR ratchet stop hit |
| **MTF Top-N — ETF leg** | Once/day, 10:25 ET (same run) | ✅ Yes (Alpaca, acct `#PA3U8GZ96PEN`) | Ticker enters the top-**3** by weekly score | Drops out of top-3 (no ratchet on this leg) |
| **Daily Signal** | Once/day, 17:00 ET | ❌ No — Slack alert only | All three of weekly+daily+hourly EMA(10)>SMA(40) crosses are done | N/A — never holds a position |

---

## 1. CoreEG100 — index EMA(100) crossover (the only whole-book, always-on/all-out strategy)

**Code:** `TradeExecutorService::runEg100Gate()` / `replayIndexEgGate()` / `indexEgGateState()`
(`swingtrader/backend/app/Services/TradeExecutorService.php`), driven by
`php artisan trades:execute-EW-gate100` (`ExecuteEWGate100.php`), on a 5-min cron while the
market is open. Tickers: QQQ, VTI, VTV. Account `#PA3GKZYLVO68`.

### What decides "buy" vs "sell"

This is a **portfolio-level** decision — all three ETFs move together, there is no per-leg
signal. Every run rebuilds the same index from scratch:

1. **Build the index** — pull each ticker's settled daily closes (`date < CURRENT_DATE`,
   from `tbl_scanner_tickers_daily`), keep only dates present for all three, and compute an
   equal-weight, daily-rebalanced index: seed at `1.0`, then each day multiply by
   `1 + mean(pct_change of the 3 closes)`. Day 0's return is defined as 0.
2. **Compute its EMA(100)** — `ewm(span=100, adjust=False)`: seeded with the index's first
   value, then recursively `ema[i] = alpha*index[i] + (1-alpha)*ema[i-1]` with
   `alpha = 2/(span+1)`. No warm-up gap — it's defined from bar 0.
3. **Compare** — this is a **pure crossover, no band**: `index > EMA(100)` → LONG,
   `index < EMA(100)` → CASH. The state only changes on the bar where the index actually
   crosses the EMA (a "flip").

### What happens on each state

- **LONG (index > EMA):** every one of QQQ/VTI/VTV should be at `account_equity / 3`.
  **Trim runs before top-up** on every cycle (a leg holding more than its equal share is sold
  down first) — this matters most right after a cutover, when the book can be left unequal
  by whatever ran before; topping up alone could never converge it. Only then are underweight
  legs bought up to their equal share.
- **CASH (index < EMA):** every held leg is sold to zero. If a DB trade record exists for
  the position, the exit goes through `rebalanceTrim`; otherwise it's a direct market sell
  gated on `waitForOrderFill`. **A sell is never logged/claimed until Alpaca actually
  confirms `status=filled`** — a `new`/`accepted` order is not a fill.

### Why it doesn't trade every 5 minutes despite checking every 5 minutes

The command dedupes on the **date of the most recent flip** (stored in
`storage/coreew_eg100_last_flip.txt`). If today's settled bar didn't produce a new flip,
the run is a no-op — the gate does not rebalance daily drift, only real state changes.
`--override` bypasses the dedupe to force a re-evaluation.

### Other guardrails

- **Settled bars only** (`date < CURRENT_DATE`) — a decision made on day *t*'s close is acted
  on in session *t+1*. The **backtest** fills at *t+1*'s close; **live** fills intraday
  whenever the 5-min cron happens to run that day — this is a real, expected divergence, not a bug.
- **30-minute opening warm-up**: no trades in the first 30 minutes of the session
  (09:30–10:00 ET), even with `--override`.
- Read-only state check anytime (works market-closed too, no orders):
  `php artisan trades:execute-EW-gate100 --state` (or `--json` for machine-readable output,
  also used to verify backtest parity).

### What this replaced

CoreEG100 (live 2026-09-27) replaced the **monotone weekly-ratchet gate** ("variant S",
`trades:execute-EW-gate`, retired the same day) — a completely different algorithm (weekly,
per-leg, peak-anchored ATR ratchet) rather than a re-tune of it. Variant S's code is retained
off the cron for rollback. The original pure drift-gated equal-weight driver
(`trades:execute-EW-ETF`, intraday, no signal at all — always long all three) is retained
further back as the deepest rollback. **Any doc describing CoreEW's trigger as a weekly ATR
ratchet or a 0.5%-drift rebalance is describing a retired driver, not the live one.**

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

- `AGENTS.md` "Live Strategies" table and "CoreEG100 logic" bullet — authoritative summary,
  updated whenever any of the above changes.
- `swingtrader/backend/app/Services/TradeExecutorService.php` — CoreEG100 implementation.
- `swingtrader/services/mtf/{runner.py,executor.py,config.py}` — MTF Top-N implementation.
- `swingtrader/services/ema_sma_crossover/daily_signal_service.py` — Daily Signal implementation.
