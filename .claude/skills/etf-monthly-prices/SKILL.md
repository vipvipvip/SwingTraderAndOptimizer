---
name: etf-monthly-prices
description: Build monthly price CSV files for ETFs or stocks via yfinance — one file per ticker containing the ADJUSTED (dividend+split-corrected) close of the FIRST trading day of each calendar month, one price per line, no dates, no header, starting from a configurable date (default 2007-01-01). Use whenever the user asks for monthly prices/price history, monthly CSV files, "first trading day" closes, or benchmark/chart input for tickers like QQQ, VTI, VTV, AGG, SCHD, VUG, VGT, XLU — mention this skill even if they just name tickers and a monthly timeframe.
---

# Monthly Price Files from yfinance

Turn any list of tickers into monthly price CSVs suitable for pasting into charts, spreadsheets, or backtests.

## What the output looks like

One file per ticker: `<OUTDIR>/<TICKER>_monthly.csv` — a single column of prices, one per line (the **adjusted close of the first trading day of each calendar month**, rounded to 2 decimal places), **no header, no dates**. Same scheme as the Daily Signal macros' QQQ/VTI/VTV series: Jan 2007 onward by default.

Why adjusted close? A raw close ignores dividends and splits, so long-run series (e.g. QQQ 2007 → today) look misleadingly flat. Back-adjusted close is the standard for return/ratio analysis and is what the user's own references match. Splits before or inside the window are handled automatically by yfinance's `Adj Close` (e.g. VUG/VGT split in 2004–2007, so their 2007 adjusted prices are small).

## Run it

```bash
python3 .claude/skills/etf-monthly-prices/scripts/build_monthly_prices.py \
  QQQ,VTI,VTV --start 2007-01-01 --out monthly_prices
```

- `tickers`: positional, comma-separated and/or space-separated, case-insensitive
- `--start`: earliest date (default `2007-01-01`); the first month's row is the first trading day **on or after** this date
- `--out`: output dir (default `monthly_prices`, created if missing)

The script prints per ticker: month count, actual data range, and first adjusted close — sanity-check this output against the user's expected starting value (e.g. QQQ Jan 2007 ≈ 37.04, AGG ≈ 54.53, SCHD has no data before 2011-10).

## Invariant rules

- Always use `auto_adjust=False` and read the **`Adj Close`** column (raw `Close` stays in the daily frame but is never what the monthly files report).
- "First trading day of the month" = the first row of each month **after sorting by date**, not calendar day 1 and not the last day.
- Round to 2 dp in the output files (the raw floats are ugly; the 2dp values are what every earlier run produced).
- If a ticker has no data before the start date (e.g. SCHD, launched 2011-10), start at its actual first month and tell the user it has fewer rows than the 2007-series tickers — never fabricate or forward-fill earlier prices.
- If the user wants the dated/labeled variant (`Jan 07, Feb, … Dec, Jan-08, …` labels on Januaries only, first year's January as `Jan <YY>`), build the label column that way, but the default deliverable is the bare price column.

## Verification

After generating, verify at least one ticker: the monthly file's first value must equal the `Adj Close` on the first trading day on/after `--start`, and the last value should be the current (or most recent complete) month's first trading day. Compare against yfinance directly if unsure.