# Handoff — OHLC Slope Experiment, Phase 1 (session resume)

**Date:** 2026-09-27
**Branch:** `feature/ohlc-data-prep` (not yet merged; not yet committed as of this doc)
**Owner of record:** `AGENTS.md` (repo root) — read it first for the wider project; this doc is the resume guide for this specific experiment only.

## What this is
Pattern-discovery experiment: treat Open/High/Low/Close as 4 independent price
series, compute a rolling slope for each, store them alongside the price data.
Hypothesis: the 4 slopes (individually or combined) may hint at price
reversals before Close alone shows it. This is **Phase 1 — data prep only**.
No pattern-discovery/backtesting logic has been written yet.

**Eventual scope:** all 28 ETFs (`tbl_stock_tickers.is_etf = true`). **Phase 1
scope (done):** just the "Core" trio — **VTI, QQQ, VTV** (same 3 tickers the
live CoreEW/CoreEG100 strategy trades) — to develop and validate the method
before widening.

## Status: done and verified for VTI/QQQ/VTV, daily + weekly
Slopes are live in the DB right now (see "Where the data lives" below). If
you're picking this up cold, there is nothing to re-run to get the data —
it's already populated. Re-run `run_slope_prep.py` only if source bars have
changed (new trading days) or you change the window config.

## Files in this folder
- `config.py` — universe (`TICKERS`), per-timeframe slope window
  (`SLOPE_WINDOW = {'daily': 10, 'weekly': 5}`), DB creds (`.env`/env vars,
  defaults match the rest of the repo: `127.0.0.1:5432`, db `swingtrader`).
- `acquire_ohlc.py` — **data acquisition, read-only.** Loads settled OHLCV
  bars from the existing scanner tables into DataFrames. No writes, no
  external API calls (Alpaca et al. are NOT involved — the bars already exist
  in Postgres via the existing ingestion pipeline). Daily excludes today's
  in-progress bar (`date < CURRENT_DATE`); weekly needs no such guard because
  weekly rows are only ever written Friday-after-close (backfilling the last
  3-4 weeks) — there's never a partial weekly row to filter out.
- `slope_calc.py` — **pure calc library, zero I/O.** `rolling_ols_slope(values,
  window)` + `add_ohlc_slopes(df, window, columns=...)`. This is the piece
  meant to be imported by future backtests and live trading code directly —
  it has no DB/env dependency, just pandas/numpy in, pandas out.
- `schema.py` — idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for the
  4 slope columns on the two live scanner tables. Safe to re-run.
- `run_slope_prep.py` — **the driver**, separate from acquisition and calc on
  purpose: loads bars, calls `slope_calc`, then bulk-writes results back via
  a temp-table `COPY` + `UPDATE ... FROM` (same pattern
  `scanner/services/scripts/compute_indicators.py` uses for `atr_stop`).
  Run: `venv/bin/python3 run_slope_prep.py --timeframe {daily,weekly,all}`.
- `requirements.txt` — pinned deps, but **no dedicated venv was created** —
  this reuses `swingtrader/services/optimizer/venv` (already has matching
  pandas/numpy/psycopg2-binary/python-dotenv). That venv is the *only* thing
  shared with the rest of the repo; everything else this experiment needs
  lives in this folder.

## Where the data lives (important — not a side table)
Slopes are stored as 4 new nullable columns **directly on the same live
tables that hold the prices**: `tbl_scanner_tickers_daily` (daily) and
`tbl_scanner_tickers` (weekly) — `slope_open`, `slope_high`, `slope_low`,
`slope_close`, `NUMERIC`, joined by the existing `ticker_id`/`date` key.

This was an explicit decision, not a default: slopes are being treated as a
fundamental data point belonging next to the price series, not as an "exotic
indicator" that would get its own table. Worth knowing if you didn't make
that call yourself: `swingtrader/backend/database/migrations/
2026_09_26_000000_drop_legacy_indicator_columns.php` (dated the day before
this work started) dropped a batch of stored MACD/PPO/crossover columns from
these exact two tables because they'd gone stale/unpopulated over time. That
migration is why this was flagged as worth double-checking — it was
considered and the same-table approach was chosen anyway. Only VTI/QQQ/VTV
rows are populated; every other ticker's 4 new columns are `NULL` (verified
zero bleed). Nothing reads these columns yet, so there's no live-strategy
risk today — but if this experiment is abandoned, the 4 columns are the
cleanup surface (mirrors the exact pattern that migration was cleaning up).

## Verification already done (2026-09-27)
Cross-checked with an **independent implementation** (`scipy.stats.linregress`
per rolling window, not the production closed-form calc) for all 6
ticker×timeframe combinations:
- Every stored slope value matches the independent recompute to ~1e-14/1e-15
  (floating-point noise), well under the 1e-6 tolerance used.
- No duplicate/out-of-order dates; daily has zero weekend rows; weekly is
  100% Monday-stamped.
- NaN warmup is exactly `window - 1` rows per ticker (9 daily, 4 weekly) and
  nowhere else — no unexpected gaps mid-series.
- Row counts: 2,698 daily / 560 weekly per ticker, matching source bar counts.
- Manual hand-check: QQQ daily 2026-09-25 `slope_close` = 5.37157575757576,
  confirmed against a manual `np.linalg.lstsq` fit on the same 10 closes.

The one-off audit script used for the independent cross-check was **not**
committed (it lived in the session scratchpad, not this repo) — if you want
to re-verify from scratch, rewrite it: pull raw OHLC + stored slope columns
per ticker/timeframe, recompute slope via a different method than
`slope_calc.rolling_ols_slope` (e.g. `scipy.stats.linregress` or
`np.polyfit`), diff elementwise.

## Open decisions for whoever picks this up next
- **Not yet committed to git as of this handoff doc** — check `git status` /
  `git log` on `feature/ohlc-data-prep` before assuming this is merged or even
  committed.
- Windows (daily=10, weekly=5) were a starting guess, explicitly called out
  as configurable per timeframe — expect these to change as pattern-discovery
  work (Phase 2) starts showing what actually correlates with reversals.
- Widening beyond VTI/QQQ/VTV to the full 28-ETF universe is expected
  eventually but was explicitly deferred — `config.TICKERS` is the only line
  that needs to change to widen it; `run_slope_prep.py` already loops over
  the whole list.
- No Phase 2 (pattern-discovery/backtesting against these slopes) has been
  started. `slope_calc.add_ohlc_slopes` is the intended reuse point.
