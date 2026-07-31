# Earnings Crossover Screener

Finds stocks with upcoming earnings where hourly MACD line just crossed above zero — the pattern that preceded IP, SW, and SLB's ~11% earnings pops.

## Strategy

1. **Earnings calendar** — cache upcoming earnings dates from yfinance (refreshed weekly)
2. **MACD line crossover** — check if hourly MACD line crossed above zero (bullish signal)
3. **Last crossover must be bullish** — skip if last crossover was bearish
4. **Freshness sort** — show most recent crossovers first

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

# Custom lookahead
python3 services/earnings_screener.py --days 7

# Show stats
python3 services/earnings_screener.py --stats
```

## Systemd Services

| Service | Timer | Schedule |
|---------|-------|----------|
| earnings-refresh | earnings-refresh.timer | Sun 6:00 AM ET |
| earnings-screener | earnings-screener.timer | Mon-Fri every 30 min, 9:30 AM - 3:30 PM ET |

## Installation

```bash
sudo cp common/docs/services_doc/earnings-*.service /etc/systemd/system/
sudo cp common/docs/services_doc/earnings-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now earnings-refresh.timer earnings-screener.timer
```

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
- `scanner/services/earnings_screener.md` — In-project docs
- `common/docs/services_doc/earnings_screener.md` — This file
- `tbl_earnings_calendar` — DB table caching earnings dates
