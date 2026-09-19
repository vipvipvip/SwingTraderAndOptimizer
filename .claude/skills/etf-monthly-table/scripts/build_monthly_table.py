"""Build per-ticker month-end return tables from yfinance.

One CSV per ticker with columns:
    id, mth_start, mth_end, prev_mth_end, prev_mth_close_price,
    mth_end_price, mthly_return%

mth_start/mth_end are the FIRST/LAST trading day of each calendar month;
all prices are dividend+split-adjusted closes. mthly_return% is
(mth_end_price / prev_mth_close_price - 1) * 100. Every row including the
first is complete (row 1's prev columns come from the prior calendar month).
"""
import argparse
import os
import sys

import pandas as pd
import yfinance as yf

DEFAULT_START = "2007-01-01"


def build_ticker(ticker: str, start: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{ticker}: no data returned from yfinance")
    df = df.reset_index()[["Date", "Adj Close"]]
    df["Date"] = pd.to_datetime(df["Date"])
    df["ym"] = df["Date"].dt.to_period("M")

    monthly = []
    for ym, g in df.groupby("ym"):
        g = g.sort_values("Date")
        monthly.append((
            ym,
            g["Date"].iloc[0].strftime("%Y-%m-%d"),
            g["Date"].iloc[-1].strftime("%Y-%m-%d"),
            round(float(g["Adj Close"].iloc[-1]), 2),
        ))
    monthly.sort(key=lambda r: r[0])

    start_p = pd.Period(start, "M")
    prev_rows = [r for r in monthly if r[0] < start_p]
    rows = [r for r in monthly if r[0] >= start_p]
    if not rows:
        raise RuntimeError(f"{ticker}: no months on/after {start} (earliest {monthly[0][0]})")

    out = []
    for i, (ym, start_dt, end_dt, end_price) in enumerate(rows, start=1):
        if i == 1:
            prev_end_dt, prev_price = prev_rows[-1][2], prev_rows[-1][3]
        else:
            prev_end_dt, prev_price = rows[i - 2][2], rows[i - 2][3]
        # keep the value exact relative to the 2dp percentage the user validated,
        # then express as a decimal fraction with 3 decimals so it pastes
        # cleanly into xls "%" cells
        ret = round(round((end_price / prev_price - 1) * 100, 2) / 100, 3)
        out.append([i, start_dt, end_dt, prev_end_dt, prev_price, end_price, ret])

    return pd.DataFrame(out, columns=[
        "id", "mth_start", "mth_end", "prev_mth_end",
        "prev_mth_close_price", "mth_end_price", "mthly_return%",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="Comma-separated tickers, e.g. SPY,IWM")
    parser.add_argument("--start", default=DEFAULT_START, help=f"Earliest month (default {DEFAULT_START})")
    parser.add_argument("--out", default="monthly_prices", help="Output directory (default monthly_prices)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for group in args.tickers for t in group.split(",") if t.strip()]
    os.makedirs(args.out, exist_ok=True)

    failed = []
    for t in tickers:
        try:
            table = build_ticker(t, args.start)
            path = f"{args.out}/{t}_monthly_table.csv"
            table.to_csv(path, index=False)
            r1, rl = table.iloc[0], table.iloc[-1]
            print(f"{t}: {len(table)} rows ({r1['mth_start']} -> {rl['mth_end']}), "
                  f"first mth_end_price {r1['mth_end_price']:.2f}, "
                  f"first mthly_return% {r1['mthly_return%']:.2f}, wrote {path}")
        except Exception as e:
            failed.append(f"{t}: {e}")
            print(f"ERROR {t}: {e}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()