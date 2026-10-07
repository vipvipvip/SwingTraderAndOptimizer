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
Ticker     Earnings  Days     MACD   Signal     Hist    Close  Fresh
-------- ---------- ----- -------- -------- -------- -------- ------
AON      2026-07-29     5   0.0034  -0.4649   0.4683 $ 361.54   0d *
GDDY     2026-07-30     6   0.0867  -0.0616   0.1483 $  93.13   0d *

AON,GDDY
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
| Fresh | Bars since crossover (0 = today) |

`*` = MACD line just crossed above 0 (fresh crossover)

## Files

- `scanner/services/earnings_screener.py` — Main CLI
- `common/docs/services_doc/earnings_screener.md` — This file
- `tbl_earnings_calendar` — DB table caching earnings dates
