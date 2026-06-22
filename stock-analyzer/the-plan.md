# Stock Analyzer — Plan

## Goal

Scrape fundamental financial data from [stockanalysis.com](https://stockanalysis.com) for
all 503 stock tickers in `tbl_stock_tickers` and populate `tbl_stock_analyzer`.

---

## Data Source

Each ticker's overview page at `https://stockanalysis.com/stocks/<symbol>/` displays
key financial metrics in a structured key-value layout. Example (AAPL):

| Metric             | Page label              | Example value          |
|--------------------|-------------------------|------------------------|
| Revenue            | Revenue (TTM)           | $451.44B (+12.8%)      |
| Net Income         | Net Income              | $122.58B (+26.0%)      |
| EPS                | EPS (Diluted)           | $8.25 (+28.9%)         |
| Shares Outstanding | Shares Outstanding      | 14.69B                 |
| PE Ratio           | PE Ratio                | 36.13                  |
| Forward PE         | Forward PE              | 32.71                  |
| Dividend           | Dividend Yield          | $1.04 (0.35%)          |

---

## Target Table — `tbl_stock_analyzer`

| Column                 | Type              | Nullable | Source mapping                          |
|------------------------|-------------------|----------|-----------------------------------------|
| id                     | bigint (PK, auto) | NO       | Auto-increment                          |
| ticker_id              | bigint (FK)       | NO       | `tbl_stock_tickers.id`                  |
| date                   | timestamp         | NO       | Scrape date (point-in-time snapshot)    |
| db_revenue             | numeric           | NO       | Revenue (TTM) — raw number              |
| db_net_income          | numeric           | NO       | Net Income — raw number                 |
| db_eps                 | numeric           | NO       | EPS (Diluted) — raw number              |
| db_shares_outstanding  | numeric           | NO       | Shares Outstanding — raw number         |
| db_pe_ratio            | numeric           | YES      | PE Ratio — nullable (some stocks lack)  |
| db_forward_pe          | numeric           | YES      | Forward PE — nullable                   |
| db_dividend            | numeric           | YES      | Dividend — nullable (not all pay)       |

---

## Script Location

```
common/stock-analyzer/
├── the-plan.md              # this file
└── populate_stock_analyzer.py
```

---

## Implementation Details

### Technology
- **Python 3** — consistent with existing scanner scripts
- **requests** — HTTP fetching
- **BeautifulSoup (bs4)** — HTML parsing
- **psycopg2** — PostgreSQL insertion (same as scanner scripts)
- **concurrent.futures.ThreadPoolExecutor** — parallel scraping

### DB Connection
Reuse the existing `scanner/services/config.py` which provides `get_db_conn()` and
`DB_CONFIG` pointing at the local PostgreSQL instance.

### Value Parsing
The page displays human-readable values that need conversion to raw numerics:
- `$451.44B` → `451440000000`
- `$122.58M` → `122580000`
- `$8.25`    → `8.25`
- `36.13`    → `36.13`
- Percentage suffixes like `(+12.8%)` are stripped
- `N/A` or missing → `None` (for nullable columns)

Multiplier map: `T=1e12`, `B=1e9`, `M=1e6`, `K=1e3`

### Symbol Normalization
stockanalysis.com uses lowercase slugs with dots replaced by hyphens:
- `AAPL` → `aapl`
- `BRK.B` → `brk-b`
- `BF.B` → `bf-b`

### Workflow
1. Query all 503 tickers + IDs from `tbl_stock_tickers`
2. For each ticker (parallelized across workers):
   a. Build URL: `https://stockanalysis.com/stocks/{normalized_symbol}/`
   b. Fetch page HTML with realistic User-Agent header
   c. Parse the 7 financial metrics from the overview section
   d. Convert display values to raw numerics
   e. Insert row into `tbl_stock_analyzer`
3. Print summary: successes, failures, skipped

### Rate Limiting & Resilience
- **Workers:** 3 (conservative to avoid IP blocking)
- **Delay:** 1-2 second pause between requests per worker
- **Retries:** 2 retries with exponential backoff (2s, 4s)
- **Timeout:** 15 seconds per request
- **User-Agent:** realistic browser string
- **Error handling:** log and skip failed tickers, continue with the rest

### Idempotency
- Use `(ticker_id, date::date)` as the logical key
- Before inserting, delete any existing row for the same ticker + date
  (or use an upsert pattern) so the script can be re-run safely on the same day

### Runtime Estimate
503 tickers × ~1.5s average per ticker ÷ 3 workers ≈ **4-5 minutes**

---

## Usage

```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer
python3 common/stock-analyzer/populate_stock_analyzer.py
```

Optional flags (planned):
- `--workers N` — override default concurrency (default: 3)
- `--symbol AAPL` — scrape a single ticker (for testing)
- `--dry-run` — parse and print but don't insert into DB

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Rate limiting / IP block | Low concurrency, delays between requests |
| HTML structure changes | Fail gracefully, log unparseable tickers |
| Ticker not found on site | Log 404s, skip, continue |
| Non-NOT-NULL field missing | Skip ticker, log warning (revenue/net income/eps/shares are required) |
| Symbol format mismatch | Normalize dots to hyphens, lowercase |
