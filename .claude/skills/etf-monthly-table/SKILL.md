# Skill: etf-monthly-table

# Monthly Return Tables from yfinance

Turn any list of tickers into month-end return tables whose returns the user's own prices match exactly — built for SPY/IWM (+ any ticker) from Jan 2007 to present.

## What the output looks like

One CSV per ticker, `<OUTDIR>/<TICKER>_monthly_table.csv`, with header:

```
id, mth_start, mth_end, prev_mth_end, prev_mth_close_price, mth_end_price, mthly_return%
```

- `id`: 1..N over the requested window
- `mth_start`: FIRST trading day of the calendar month
- `mth_end`: LAST trading day of the calendar month
- `prev_mth_end`: last trading day of the PRIOR calendar month
- `prev_mth_close_price`: prior month's mth_end_price
- `mth_end_price`: adjusted close on mth_end
- `mthly_return%`: decimal fraction `(mth_end_price / prev_mth_close_price - 1)` at 3 decimals (e.g. a `1.50%` month reads `0.015`, `-1.95%` reads `-0.019`) so the column pastes straight into an xls cell formatted as `%`. It is the 2dp-rounded percentage divided by 100 then rounded to 3 dp, so it matches the previously-validated percentage to 1 decimal place of a percent.

Every row is complete — row 1's `prev_*` columns come from the month BEFORE the start window (e.g. Dec 2006 for a Jan 2007 start), so returns are computable from the first row. All prices are **adjacent-month adjusted closes**.

## Run it

```bash
python3 .claude/skills/etf-monthly-table/scripts/build_monthly_table.py \
  SPY,IWM --start 2007-01-01 --out monthly_prices
```

- `tickers`: positional, comma-separated and/or space-separated, case-insensitive
- `--start`: earliest month (default `2007-01-01`); row 1 is that month, its `prev_*` values come from the last trading day of the month before
- `--out`: output dir (default `monthly_prices`, created if missing)

The script prints per ticker: row count, actual data range, first mth_end_price and first mthly_return%.

## Invariant rules

- Use `auto_adjust=False` and read the **`Adj Close`** column (never raw `Close`), so returns are dividend+split corrected.
- `mth_start`/`mth_end` are the first/last trading days of each month **after sorting by date**, not calendar day 1/last.
- `mthly_return%` is always relative to the PRIOR month's `mth_end_price`, rounded to 2 dp.
- If a ticker has no data before the start date (e.g. a fund launched later, like SCHD 2011-10), it starts at its first available month and has fewer rows than the 2007-series tickers — never fabricate or forward-fill earlier prices.
- The last row's `mth_end` is the current (possibly incomplete) month's latest trading day.

## Verification

After generating, verify: row 1's `prev_mth_end` precedes the row-1 `mth_start` by one trading-month boundary, and spot-check one month: `mthly_return% × prev_mth_close_price / 100 + prev_mth_close_price == mth_end_price`. Compare `mth_end_price` against yfinance `Adj Close` on `mth_end` directly if unsure.