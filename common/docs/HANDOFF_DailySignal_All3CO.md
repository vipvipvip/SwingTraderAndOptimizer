# Handoff — Daily Signal all-3-CO gate (session resume)

**Date:** 2026-09-16 (updated 2026-09-16)
**Owner of record:** AGENTS.md (repo root) — read it first; this doc is the *live-state* resume guide.
**Commit:** `c24b084` (pushed to `main`) — `feat(daily-signal): emit all-3-CO tickers only ...`

## What the Daily Signal service IS now
`swingtrader/services/ema_sma_crossover/daily_signal_service.py` emits a Slack
message **only for tickers where ALL THREE EM(10)>SM(40) crossovers are done**:

1. **WCO done** — weekly EMA10 > SMA40 on the last **settled** weekly bar.
2. **DCO done** — daily EMA10 > SMA40 on the last **settled** daily bar.
3. **HCO done + fresh** — hourly EMA10 > SMA40 on the last **settled, quality-gated**
   hourly bar AND the most recent hourly up-cross (bear→bull) is within the last
   **1-2 trading days** of that settled hourly series.

It is **event/alert only** (Slack `[DAILY]` @ 17:00 ET Mon–Fri + CSV
`data/daily_signals.csv`) — it **never places orders**. Universe: all enabled
`tbl_stock_tickers` (1,461) + ETFs (readiness checks both modes).

## SETTLED-BAR + QUALITY-GATE CONVENTIONS (why this matters)
The scanner hourly DB is **degraded/tainted** (synthetic bars vol 40-700, flat OHLC;
partial daily captures since 09-01; pre/post-market bars). Live hourly is a known
challenge and the user has **accepted day-old signals**: WCO/DCO/HCO may be 1-2 days old.

Every timeframe is evaluated on **settled bars only — never today's in-progress bar**:
- Hourly: `vol >= MIN_HOURLY_VOL` (**1000.0**, `daily_signal_service.py:27`) filters out
  synthetic/degraded rows; **today's bars are excluded entirely** (`_bar_date(r) < now_date`).
  Hourly load limit bumped 80 → **300** so SMA40 has warmup in the degraded era.
- Daily & weekly: the **last settled bar with `date < today`** is used (`wi`/`di` via
  `_bar_date(...) < now_date`). Today's partial bar must never flip a signal.

### The BAND/DOCN lesson (2026-09-16 — do not regress)
BAND's daily EMA10 was **below** SMA40 on the settled 09-15 bar (bearish since the
07-28 down-cross, matching TOS) but flipped **above** on 09-16's in-progress bar —
the old code evaluated DCO on the last row regardless of date and wrongly emitted it.
DOCN had the identical pattern. Fix: settle on yesterday. **Verification helpers:**
- BAND: last daily down-cross 2026-07-28; settled-09-15 EMA10=49.96 < SMA40=50.08;
  today's partial flipped it (49.99 > 49.57).
- DOCN: settled-09-15 EMA10=121.38 < SMA40=121.71; today partial 121.36 > 121.33.

## Slack message format
```
*Daily Signal* — <date> (all-3 COs only)
In uptrend (W+D): <n>/1461 (<pct>%) — <regime>         # breadth is W+D bull only; hourly NOT required
🚀 *Infancy entries (k):*  /  📈 *Mature entries (m):*
```<per-line ticker + HCO date + score + gap_w% + atr% + wk age>```
Tickers: AAA, BBB, CCC, ...                              # comma-delimited list at END of each section
```
No separate "New daily uptrend" (DCO-only) section anymore — removed per user
directive (only all-3-done tickers may be emitted). Regime thresholds: <35 Risk-off,
35-54 Neutral, >54 Risk-on. Infancy = weekly cross age < 60d (unchanged).

## Verification / manual run
Real run posts to Slack (`config.SLACK_WEBHOOK_URL` from repo `.env`, vi `_send_slack`,
`[DAILY] ` prefix):
```bash
cd swingtrader/services/ema_sma_crossover
"$PWD/../../optimizer/venv/bin/python3" daily_signal_service.py
```
Dry (no Slack): monkeypatch `_send_slack` to `print`. The run ALSO mutates state
(`.daily_signal_state.json`) + CSV (dedup: entries logged once per ticker per date).
First 2026-09-16 run logged **36 entries**; subsequent same-day runs log 0 new.
`_ensure_data_ready()` gate runs `scanner/services/scripts/data_readiness.py --ensure
--tf day,hour,week --mode all` first (may repair); it must pass or the run is skipped.

## Known-OK example (sanity anchor)
**PANW**: WCO bull (weekly 09-14), DCO bull (daily down/up history per TOS), HCO
crossed **2026-09-15** on settled gated bars (TOS said 09-14 9:30; ~1 day lag = partial
capture, direction/state consistent). Score 4.4, correctly emitted both before and after fix.

## Interplay with other strategies (unchanged cadence)
- **MTF stocks + MTF ETFs** (emasma v3): trade **once/day @ 10:25 ET** via
  `swingtrader-mtf-executor` (`--mode all`). emasma is **weekly-only** — `runner.py:550`
  `uses_hourly` only for `mtf`/`v2`, so MTF never reads degraded hourly. Do not regress.
- **CoreEW** (trio QQQ/VTI/VTV): intraday **every 5-min** cron, **drift-gated**
  (trim/top-up only when leg deviates > `COREEW_DRIFT_PCT` 0.5%). No signals/stop.
- **Daily Signal**: alerts only, once/day 17:00 ET (systemd `swingtrader-daily-signal.timer`).

## Session trail (2026-09-16)
- 15:26/15:46/15:49/15:57 ET manual real Slack posts during verification (superseded by
  the 17:01 timer run — timer untouched, still fires daily Mon–Fri 17:01 ET).
- Single-ticker tool commits earlier this week (79ed16d, 4aa4c6e, 68e020e, 07b6e22,
  82d7b12): settled prev-day HCO, quality gate, `--min-bars`, win-rate research flags —
  see AGENTS.md Findings "HOURLY DATA DROPPED FROM MTF" bullet.