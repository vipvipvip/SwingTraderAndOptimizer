"""Build per-ticker monthly price files from yfinance.

Each output file holds one adjusted close per line (the close of the FIRST
trading day of each calendar month, dividend+split adjusted), rounded to 2 dp,
with no dates and no header row.

Defaults: start 2007-01-01, output ./monthly_prices/<TICKER>_monthly.csv.
"""
import argparse
import sys

import pandas as pd
import yfinance as yf

DEFAULT_START = "2007-01-01"


def build_ticker(ticker: str, start: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"{ticker}: no data returned from yfinance")
    df = df.reset_index()[["Date", "Close", "Adj Close"]]
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    sub = df[df["Date"] >= start].reset_index(drop=True)
    if sub.empty:
        raise RuntimeError(f"{ticker}: no data on or after {start} (earliest {df['Date'].iloc[0]})")
    period = pd.to_datetime(sub["Date"]).dt.to_period("M")
    monthly = sub.groupby(period).first()["Adj Close"].dropna().round(2)
    return sub, monthly


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="Comma-separated tickers, e.g. QQQ,VTI,VTV")
    parser.add_argument("--start", default=DEFAULT_START, help=f"Earliest date (default {DEFAULT_START})")
    parser.add_argument("--out", default="monthly_prices", help="Output directory (default monthly_prices)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for group in args.tickers for t in group.split(",") if t.strip()]
    out_dir = args.out
    import os
    os.makedirs(out_dir, exist_ok=True)

    failed = []
    for t in tickers:
        try:
            sub, monthly = build_ticker(t, args.start)
            path = f"{out_dir}/{t}_monthly.csv"
            monthly.to_csv(path, index=False, header=False)
            print(f"{t}: {len(monthly)} months ({sub['Date'].iloc[0]} -> {sub['Date'].iloc[-1]}), "
                  f"first adj close {monthly.iloc[0]:.2f}, wrote {path}")
        except Exception as e:
            failed.append(f"{t}: {e}")
            print(f"ERROR {t}: {e}", file=sys.stderr)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()