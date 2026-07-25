# Earnings Crossover Screener

Finds stocks with upcoming earnings where hourly MACD just turned positive — the pattern that preceded IP, SW, and SLB's ~11% earnings pops.

## Usage

```bash
# Refresh earnings calendar (run weekly)
python3 services/earnings_screener.py --refresh

# Run screener (default: 14 days ahead)
python3 services/earnings_screener.py

# Send to Slack
python3 services/earnings_screener.py --slack

# Custom lookahead
python3 services/earnings_screener.py --days 7

# Filter by freshness (only last 3 days)
python3 services/earnings_screener.py --min-freshness 3

# Show stats
python3 services/earnings_screener.py --stats
```

## Systemd Installation

```bash
# Copy files to systemd
sudo cp /tmp/earnings-refresh.service /etc/systemd/system/
sudo cp /tmp/earnings-refresh.timer /etc/systemd/system/
sudo cp /tmp/earnings-screener.service /etc/systemd/system/
sudo cp /tmp/earnings-screener.timer /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable --now earnings-refresh.timer
sudo systemctl enable --now earnings-screener.timer

# Verify
sudo systemctl list-timers | grep earnings
```

## Schedule

| Timer | Schedule | What it does |
|-------|----------|--------------|
| earnings-refresh | Sun 6:00 AM ET | Fetch next 4 weeks of earnings dates |
| earnings-screener | Mon-Fri 5:15 PM ET | Run screener + send Slack |

## How it works

1. **Refresh** (`--refresh`): Fetches earnings dates for all 532 tickers via yfinance, caches in `tbl_earnings_calendar`
2. **Screener** (default): Reads cached earnings dates, checks hourly MACD for each ticker with upcoming earnings, outputs sorted by freshness

## Output columns

| Column | Meaning |
|--------|---------|
| Ticker | Stock symbol |
| Earnings | Earnings date |
| Days | Days until earnings |
| MACD | Current MACD line |
| Signal | MACD signal line |
| Hist | MACD histogram (positive = bullish) |
| Close | Current close price |
| Fresh | Days since MACD turned positive (0 = today) |

`*` = MACD just turned positive today (freshest signal)
