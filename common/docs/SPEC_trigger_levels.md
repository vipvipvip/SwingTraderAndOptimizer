# SPEC — Trigger Levels (next buy / sell price per ticker)

**Status:** design agreed 2026-10-07, **no code yet.** Scope: ETF strategies only — **CoreEW P20w**
(QQQ/VTI/VTV) and **MTF-ETF** (28 ETFs, top-3). Delivery: Slack only, no orders.

## 1. Core idea — one flip price per ticker

Both strategies decide on the **settled weekly close** (Friday close decides, Monday acts). Each ticker
therefore has a single price level: below it the ticker is out/off, above it in/on. Out of the position
that level is the **buy trigger**; in the position it is the **sell trigger**. Only the Friday close
counts — touching the level mid-week does nothing.

**CoreEW P20w.** Leg is ON when weekly close C > EMA20. With `E' = αC + (1−α)E`, `C > E'` simplifies to
`C > E`. **Trigger = the last settled weekly EMA(20).**

**MTF-ETF.** In top-3 iff (a) eligible: weekly EMA10 > SMA40, and (b) its score beats the **3rd-best score
among the other ETFs** (the cut-line competitor). Score = `min(gap_w/5, 5)`, `gap_w = (C − SMA40)/SMA40·100`,
tie-break `(-score, -gap_w)`.
- With the in-progress close C: `EMA10' = aC + (1−a)E` (a = 2/11), `SMA40' = S + (C − D)/40`
  (D = the close leaving the 40-bar window). Both linear in C → closed-form price for (a) and (b).
- **Trigger = max(eligibility price, rank price).** `binding` reports which one set it.
- Competitor: ticker outside top-3 → the current **#3**; ticker inside top-3 → the current **#4**.
- Prices are **conditional**: other ETFs assumed to keep their last settled scores (true all week, since
  scores come from the weekly bar).

## 2. Rows shown

| Section | Rows |
|---|---|
| CoreEW P20w | all 3 legs (QQQ, VTI, VTV) |
| MTF-ETF TOP 3 | ranks 1–3 → **sell** triggers |
| MTF-ETF NEXT 3 | eligible ETFs ranked 4–6 → **buy** triggers (fewer rows if <6 eligible) |

QQQ/VTI/VTV can appear in both strategies; that is intended (separate accounts).

## 3. Columns

| Column | Notes |
|---|---|
| `strategy`, `ticker`, `state` | CoreEW: LONG/CASH. MTF: HELD / TOP3 / NEXT |
| `rank`, `score` | MTF only |
| `live_px` | Alpaca **last trade** via the MTF-ETF keys (existing helper); `n/a` if unavailable (row still prints) |
| `settled_px` | last settled daily close — what the signal is built on |
| `buy_trigger_px` / `sell_trigger_px` | weekly-close level; only the applicable one is filled |
| `dist_pct` | `(trigger − live_px) / live_px` |
| `binding`, `competitor` | EMA20 · ELIGIBILITY · RANK vs `<ticker> <score>` |
| `decides_on` / `acts_on` | Friday close / Monday fill |

## 4. Slack message

Every message starts with a **HOW TO READ** block (the Section 1 explainer, condensed). It is controlled by
`--no-explainer` (default **on**; planned to be suppressed later). Tables are monospace code blocks with
**header rows and aligned columns**. Placeholder values:

```
[Triggers] 10:00 ET · 2026-10-07 · settled week 2026-09-28
--- HOW TO READ (--no-explainer to hide) ---
Each ticker has ONE flip price: out of the position it is the BUY
trigger, in the position it is the SELL trigger. Only the Friday weekly
CLOSE counts (acts the following Monday); touching it mid-week does
nothing. CoreEW: price vs weekly EMA20. MTF-ETF: top-3 membership
(EMA10>SMA40 and beating the cut-line score); assumes rivals hold scores.

CoreEW P20w
Ticker  State  Live     Settled  Trigger        Dist    Basis
------  -----  -------  -------  -------------  ------  -----
QQQ     LONG   601.20   600.00   SELL < 575.00  -4.4%   EMA20
VTI     LONG   285.10   283.00   SELL < 270.40  -5.2%   EMA20
VTV     CASH   190.00   189.50   BUY  > 192.50  +1.3%   EMA20

MTF-ETF  TOP 3 (sell below)
Rank  Ticker  Score  Live     Settled  Trigger        Dist    Binding
----  ------  -----  -------  -------  -------------  ------  ---------------
#1    SMH     4.90   298.40   300.00   SELL < 268.00  -10.2%  RANK vs XLU 2.6
#2    XLK     3.20   212.30   211.80   SELL < 196.50  -7.4%   RANK vs XLU 2.6
#3    XLV     2.80   148.00   147.60   SELL < 143.10  -3.3%   RANK vs XLU 2.6

MTF-ETF  NEXT 3 (buy above)
Rank  Ticker  Score  Live     Settled  Trigger        Dist    Binding
----  ------  -----  -------  -------  -------------  ------  ---------------
#4    XLU     2.60   80.00    79.80    BUY  > 81.20   +1.5%   RANK vs XLV 2.8
#5    XLF     2.20   52.10    52.00    BUY  > 54.00   +3.6%   RANK vs XLV 2.8
#6    IWM     1.90   238.00   237.50   BUY  > 248.60  +4.5%   RANK vs XLV 2.8

Decides Fri 2026-10-09 close · acts Mon 2026-10-12
```

**Size tracking:** each post logs its character count (journal + a line in the run log) so message growth
can be reviewed after a week of runs.

## 5. Delivery — new unit, no trading

- New `swingtrader-trigger-levels.{service,timer}`; Mon–Fri **10:00 ET** (once in the morning; after the
  09:30–10:00 warm-up so quotes are live, before 10:05 legema / 10:25 MTF) and **17:05 ET** (after the
  17:01 daily-signal).
- **`Persistent=false`** (posts a signal → skipped, never replayed at the wrong hour). Installing into
  `/etc/systemd/system` needs `sudo` (repo-only until installed).
- CLI: `--no-explainer`, `--dry-run` (print, don't post).
- Levels are constant within a week except on Monday (new settled week) — the second daily post mostly
  refreshes `live_px` and `dist_pct`.

## 6. Reuse map — import, don't rewrite (decided 2026-10-07)

Rule: the report is a thin orchestrator in a **new** module (`swingtrader/services/mtf/trigger_levels.py`)
that **imports** everything below and modifies **none** of these files (live emasma path stays untouched).

| Need | Import / call (existing) |
|---|---|
| **Alpaca keys — MTF-ETF pair** (longest-running, stable) | `executor._set_alpaca_keys('etf')` → `config.ALPACA_ETF_API_KEY/_SECRET_KEY` |
| **Live price** | `executor._latest_trade_price(symbol)` (IEX last trade, retrying session; returns `None` → `n/a`) |
| **Slack post** | `runner._send_slack(msg, mode='etf')` (uses `config.SLACK_WEBHOOK_URL`, `[EMA-SMA ETFs]` prefix) |
| DB connection | `runner._get_db_conn()` / `db.get_conn()` |
| ETF universe | `db.get_all_tickers(conn, is_etf=True)`, `db.get_etf_name` |
| Weekly bars + EMA10/SMA40 arrays | `db.bulk_load_weekly(conn, tids)` (`dates`, `close`, `ema`, `sma`) |
| Daily bars (staleness / settled px) | `db.bulk_load_daily`; `executor.latest_settled_daily_closes(conn, symbols)` |
| Settled-week index | `emasma_core.settled_weekly_idx` |
| Score / eligibility | `emasma_core.compute_emasma_score` |
| Rank + tie-break + top-N cut | `emasma_core.rank_candidates` |
| Held positions (HELD vs TOP3) | `db.get_all_positions(conn)` |
| Constants | `config.EMA_PERIOD`, `config.SMA_PERIOD`, `config.WARMUP_BARS`, `config.ETF_TOP_N` |
| **CoreEW levels** (PHP-canonical) | `backtest_trio_ew.fetch_live_leg_ema_series(20, ['QQQ','VTI','VTV'])` → shells to `php artisan trades:coreew-leg-ema-series`; payload already has per-week `close`, `ema`, `long`, plus `state` and `last_week`. Trigger = last point's `ema`. (Module is import-safe: `__main__`-guarded.) |

**Genuinely new code (nothing existing covers it) — kept as small as possible:**
1. **Trigger solver** — the closed-form price for eligibility (EMA10>SMA40) and rank-vs-competitor. Pure
   arithmetic on the `bulk_load_weekly` arrays. This is the feature itself.
2. **Candidate loop glue** — the "score every ETF at the settled week" loop is **inline** in
   `runner._run_single_mode` (lines ~620–650), not a function, so it is repeated here in a few lines using the
   imported `settled_weekly_idx` / `compute_emasma_score`. *Option:* extract it into `emasma_core` so there is
   one copy — but that edits the live scoring path and needs your sign-off, so it is **not** in scope unless approved.
3. **Aligned-table formatter** — `format_etf.etf_table_lines` is a P&L table (Entry/Now/P&L), different columns,
   so it cannot be reused as-is; a ~15-line header+aligned-column helper is needed.
4. CLI (`--no-explainer`, `--dry-run`) and the HOW TO READ text.

**Safety self-check (reuses scoring, no new scoring logic):** after solving a trigger price P, re-run
`compute_emasma_score` + `rank_candidates` with the ticker's in-progress close set to P±0.01 and assert
top-3 membership flips between the two. A failing assert drops that row to `n/a` rather than posting a wrong level.

## 7. Constraints (from AGENTS.md safety rails)

- **CoreEW is PHP-canonical — never re-implement in Python**; consume the PHP series only (see table).
- Settled bars only (`bar_date + 7 <= today` weekly), via `settled_weekly_idx`.
- Read-only: no orders, no writes to MTF state tables; no changes to `runner.py` / `executor.py` / `emasma_core.py`.
- Keys: MTF-ETF pair only (also used for CoreEW tickers' live price, since the quote is just market data).

## 8. Open items

- **Live price is last trade, not a bid/ask quote, and has no timestamp** (that is what the existing, stable
  helper returns). Accepting that keeps us on existing code; a true quote/timestamp would be new code.
- Tie handling near the score cap (5.0) — the rank price must honor the `gap_w` tie-break (covered by the self-check).
- Tickers below `WARMUP_BARS` → `n/a`.
- Importing `runner` pulls in its module-level imports (`executor`, `db`, `requests`); acceptable, but the unit
  must run with the same working dir / `.env` as the existing MTF units.
- Whether to also expose the table in Explorer later (out of scope here).
