# Earnings Crossover Screener

Finds stocks with upcoming earnings where the DAILY MACD line just crossed above zero.

> **Changed 2026-09-26:** converted from hourly to daily MACD. The stored MACD/PPO
> columns were dropped from all bar tables as lookahead-biased legacy artifacts, so
> MACD is now computed inline from settled daily closes. Hourly bars remain in the
> DB for the MTF stock leg only.

## Strategy

1. **Earnings calendar** — cache upcoming earnings dates from yfinance (refreshed weekly)
2. **MACD line crossover** — check if the DAILY MACD line crossed above zero (bullish signal)
3. **Last crossover must be bullish** — skip if last crossover was bearish
4. **Freshness sort** — show most recent crossovers first
5. **Window (2026-10-06)** — earnings within the next **7 days** (`--days`) and a MACD cross at most **10 days** old (`--max-fresh`); anything else is dropped
6. **Fundamentals research (2026-10-14)** — each pick is scored **0-8** on revenue/earnings growth + margin trend, minus red-flag deductions, gated by the R&D-adoption **$5-50B scope** and shown in a **Fund** column. A separate **Rate** column shows Yahoo consensus (not CFRA — see below). See [Fundamentals research](#fundamentals-research).

## Usage

```bash
# Refresh earnings calendar (run weekly)
python3 services/earnings_screener.py --refresh

# Run screener (default: shows only fresh crossovers)
python3 services/earnings_screener.py

# Send to Slack
python3 services/earnings_screener.py --slack

# Show all tickers with bullish MACD (not just fresh)
python3 services/earnings_screener.py --all

# Custom windows (defaults: --days 7 --max-fresh 10)
python3 services/earnings_screener.py --days 14 --max-fresh 5

# Skip the fundamentals research column (faster)
python3 services/earnings_screener.py --no-research

# Force a fresh fundamentals fetch for every ticker (ignore the cache)
python3 services/earnings_screener.py --refresh-fundamentals

# Keep only tickers inside the $5-50B R&D-adoption scope
python3 services/earnings_screener.py --scope-only

# Show stats
python3 services/earnings_screener.py --stats
```

## Systemd Services

| Service | Timer | Schedule |
|---------|-------|----------|
| swingtrader-earnings-screener | swingtrader-earnings-screener.timer | Mon-Fri every 30 min, 9:30 AM - 3:30 PM ET |

⛔ `swingtrader-earnings-refresh.{service,timer}` was **REMOVED 2026-10-05**. The cache is
refreshed **on demand** — see [Cache refresh](#cache-refresh) below.

The scheduled run is `--days 7 --max-fresh 10 --all --slack`: earnings within the next 7 days and a MACD cross at most 10 days old. It passes `--all` deliberately:
on hourly data the default fresh-only filter ("cross on the latest bar") fired
several times a day, but on **daily** data that happens only a handful of times
a year, so fresh-only would post an empty Slack list nearly every day. `--all`
posts the full ranked list instead, sorted by how many days since the cross.

## Installation

```bash
# Unit files moved out of services_doc/ on 2026-10-05 — they now live with the
# scanner component that owns earnings_screener.py. Only ONE unit remains.
sudo cp scanner/systemd/swingtrader-earnings-screener.service /etc/systemd/system/
sudo cp scanner/systemd/swingtrader-earnings-screener.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swingtrader-earnings-screener.timer
```

The screener timer is installed and enabled on this box.

## Cache refresh

⛔ There is **no scheduled refresh timer** — it was removed 2026-10-05 after a long run of
silent failures (the persistent Sun 06:00 timer fired before `swingtrader-db.service` was
ready, so it exited 1 every week and the cache silently aged; last real update drifted to
`2026-09-13`). Refresh explicitly instead:

```bash
cd scanner
./.venv/bin/python3 services/earnings_screener.py --refresh
```

The screener itself reads the existing cache — it does **not** refresh — so a stale cache
means the 30-min Slack posts go out against old dates. Accepted for now; nothing consumes
this table for trading. Only `earnings_screener.py` (Slack) and `sec_research.py` (ticker
selection) read `tbl_earnings_calendar`; no strategy reads it.

Last refresh: 1,380 rows, horizon `2026-11-02`, done manually 2026-10-05.

## Output

```
Ticker     Earnings  Days     MACD   Signal     Hist    Close  Fresh   Fund   Rate
-------- ---------- ----- -------- -------- -------- -------- ------ ------ ------
RLI      2026-10-19     5   0.2143   0.1761   0.0381 $  20.18     9d    8/8*  H 3.4
CME      2026-10-21     7   0.1373  -0.1154   0.2528 $  88.84    0d*   2/8!  H 2.5

RLI,CME

Fundamentals (Fund = 0-8 growth score; * = max, ! = outside $5-50B scope;
Rate = Yahoo consensus; MC = margin compression -1, GW = goodwill impairment -2):
Ticker         MC  RevYoY  RevQoQ EarnYoY EarnQoQ Margin  Rating Scope Flags
-------- -------- ------- ------- ------- ------- ------ ------- ----- ------
RLI       $5.3B  +15.2%  +35.8%  +35.1% +206.1%     ok   H 3.4    in
CME     $102.9B   +0.8%   -9.2%   +1.6%   -9.7%   comp   B 2.5   OUT MC
```

| Column | Meaning |
|--------|---------|
| Ticker | Stock symbol |
| Earnings | Earnings date |
| Days | Days until earnings |
| MACD | Current MACD line value |
| Signal | MACD signal line |
| Hist | MACD histogram |
| Close | Current close price |
| Fresh | Bars since crossover (0 = today); `*` marks a crossover on the latest settled bar |
| Fund | Fundamentals score 0-8; `*` = max, `!` = outside $5-50B scope, `-` = no data |
| Rate | Yahoo analyst consensus (grade + mean, e.g. `SB 1.4`); blank = no coverage |

`*` = MACD line just crossed above 0 (fresh crossover), or a perfect 8/8 fundamentals score

### Table formatting

Both tables are rendered by `services/table_fmt.py`. Column widths are computed
from the rendered cells (floored at a per-column minimum), so a value wider than
the usual width — e.g. `+4659.4%` or a `$123456.78` close — widens that column
for every row instead of pushing the rest of the row out of alignment with the
header. Numeric columns are rendered at one shared width so their decimals line
up, and the `$`/`%`/`n/a` markers stay in a vertical line. A NaN metric renders
as `n/a` rather than `nan`.

## Fundamentals research

The **Fund** column ranks each pick 0-8 on the fundamentals that matter for an
earnings setup, then gates by the R&D-adoption mid-cap scope and applies two
red-flag deductions. All data is structured yfinance output — no filing text.

**Subtotal (max 8):**

| Pts | Signal |
|-----|--------|
| +2 | Revenue YoY > 15% (framework growth threshold) |
| +1 | Revenue YoY up (0-15%) |
| +1 | Revenue up QoQ |
| +2 | Earnings (net income) up YoY |
| +1 | Earnings up QoQ |
| +1 | Operating margin stable/expanding (op income, net-income fallback) |

**Red-flag deductions:** margin compression `-1` (revenue up but margin
contracting) · goodwill impairment `-2` (balance-sheet goodwill down > 2% of
market cap). Total is clamped to 0-8.

**Scope gate:** in-scope = market cap **$5B-$50B**. Out-of-scope tickers stay on
the momentum list but are marked `!` and are not adoption candidates;
`--scope-only` drops them entirely.

YoY prefers quarter-vs-same-quarter (4 quarters back), falling back to the latest
two annual figures. Direction is a value comparison (latest > prior), so a
company improving from a smaller loss still counts. Growth percentages are shown
in the fundamentals table (`n/a` when a prior-period base is ≤ 0). The table has
aligned headings: `Ticker · MC · RevYoY · RevQoQ · EarnYoY · EarnQoQ · Margin ·
Rating · Scope · Flags`.

Implementation: `scanner/services/fundamentals_research.py`. Results are cached in
`scanner/services/.earnings_fundamentals_cache.json`, keyed by ticker, so the
30-minute screener **only does the (slow) network fetch for new tickers** — cached
symbols are reused. Cache entries expire after 30 days (so a ticker is re-scored
after its next quarterly report); `--refresh-fundamentals` forces a full re-fetch
and `--no-research` skips the column entirely.

### Rating column (not CFRA)

The **Rate** column is **Yahoo Finance's analyst consensus** (`recommendationMean`
mapped to SB/B/H/S/SS), with analyst count and mean price target in the detail
line. It is added at no extra cost — `t.info` is already fetched for market cap.

> **CFRA (STARS) ratings are not available here.** CFRA is a licensed product with
> no free/public API; it is delivered via subscription/RaaS and enterprise feeds
> (Bloomberg/FactSet/Refinitiv) and to account-holders on broker platforms such as
> Schwab. Nothing in this repo or `yfinance` exposes it. Yahoo consensus is the
> nearest free substitute.

> Uses yfinance income-statement data, not the raw 10-Q, because the question is
> simply "is revenue/earnings rising". For the SEC-filing R&D adoption framework
> (0-15), use the `stock-analysis` skill / `rnd_adoption_analyzer.py`.

## Files

- `scanner/services/earnings_screener.py` — Main CLI
- `scanner/services/fundamentals_research.py` — 0-8 growth scorer + scope gate + rating (Fund/Rate columns)
- `scanner/services/table_fmt.py` — Shared fixed-width table renderer (both report tables)
- `scanner/services/.earnings_fundamentals_cache.json` — Per-ticker fundamentals cache (gitignored)
- `common/docs/services_doc/earnings_screener.md` — This file
- `tbl_earnings_calendar` — DB table caching earnings dates
