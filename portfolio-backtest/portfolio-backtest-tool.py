#!/usr/bin/env python3
"""
Portfolio Backtest Tool
Analyzes N-ticker portfolio allocations and returns decision table

Usage:
  python portfolio-backtest-tool.py --scenarios "VTI+QQQ+BND" "VTI+QQQ+VXUS" "VTI+QQQ+VTV"
  python portfolio-backtest-tool.py --scenarios "VTI+QQQ" "VTI+QQQ+BND" --rebalance monthly --own-window

Or import as module (hyphenated filename -> load with importlib):
  bt = PortfolioBacktester(['VTI', 'QQQ', 'BND'])
  results = bt.compare_with_benchmark([(['VTI', 'QQQ'], 'A'), (['VTI', 'QQQ', 'BND'], 'B')])

Data rules:
  - Adjusted close (dividends + splits), fetched with auto_adjust=False.
  - Prices are NEVER back-filled: a ticker's history starts at its first real bar.
  - By default every scenario (and the benchmark) is measured over the SAME window,
    starting at the latest inception among all tickers used, so results are comparable.
    Pass own_window=True / --own-window to give each scenario its own full history instead.
"""

import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

REBALANCE_FREQ = {'daily': None, 'weekly': 'W', 'monthly': 'M'}
STRESS_WINDOWS = [
    ('COVID crash', '2020-02-19', '2020-03-23'),
    ('2022 bear', '2022-01-03', '2022-10-12'),
]


class PortfolioBacktester:
    """Backtest multiple portfolio allocations"""

    def __init__(self, tickers: List[str], start_date: str = '2007-01-01',
                 end_date: Optional[str] = None, rebalance: str = 'daily',
                 own_window: bool = False):
        """
        Initialize backtester

        Args:
            tickers: List of ticker symbols to fetch up front (more are fetched on demand)
            start_date: Start date (default 2007-01-01)
            end_date: End date (default today)
            rebalance: 'daily' (default), 'weekly' or 'monthly' back to equal/target weights
            own_window: False = all scenarios share one common window (default);
                        True = each scenario uses its own full history
        """
        if rebalance not in REBALANCE_FREQ:
            raise ValueError(f"rebalance must be one of {list(REBALANCE_FREQ)}")
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime('%Y-%m-%d')
        self.rebalance = rebalance
        self.own_window = own_window
        self.prices = None          # Adj Close, NaN before each ticker's inception
        self.inception: Dict[str, pd.Timestamp] = {}
        self.portfolio_returns: Dict[str, pd.Series] = {}   # last backtest(), by scenario name
        self.window_returns: Optional[pd.DataFrame] = None  # last backtest(), per-ticker daily returns

        tickers = list(dict.fromkeys(t.upper() for t in tickers))
        print(f"Fetching data for {tickers} ({self.start_date} to {self.end_date})...")
        self._ensure(tickers)
        self._print_inception()

    def _download(self, tickers: List[str]) -> pd.DataFrame:
        raw = yf.download(tickers, start=self.start_date, end=self.end_date,
                          auto_adjust=False, progress=False)['Adj Close']
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(name=tickers[0])
        return raw.dropna(how='all')

    def _ensure(self, tickers):
        """Fetch any tickers not loaded yet; record inception dates."""
        need = [t for t in tickers if self.prices is None or t not in self.prices.columns]
        if not need:
            return
        new = self._download(need)
        for t in need:
            first = new[t].first_valid_index() if t in new.columns else None
            if first is None:
                print(f"⚠ No data for {t} — scenarios using it will be skipped")
                new = new.drop(columns=[t], errors='ignore')
            else:
                self.inception[t] = first
        self.prices = new if self.prices is None else self.prices.join(new, how='outer')

    def _print_inception(self):
        print("✓ Data loaded. First available bar per ticker:")
        for t, d in sorted(self.inception.items(), key=lambda kv: kv[1]):
            print(f"    {t:<6} {d.date()}")
        print()

    def _calculate_stats(self, portfolio_returns: pd.Series, name: str) -> Dict:
        """
        Calculate portfolio statistics

        Args:
            portfolio_returns: Series of daily returns
            name: Portfolio name

        Returns:
            Dict with performance metrics
        """
        # Cumulative returns
        cumulative = (1 + portfolio_returns).cumprod()

        # Total return
        total_ret = (cumulative.iloc[-1] - 1) * 100

        # Annualized metrics
        years = len(cumulative) / 252
        ann_ret = ((cumulative.iloc[-1] ** (1/years)) - 1) * 100
        ann_vol = portfolio_returns.std() * np.sqrt(252) * 100

        # Max drawdown
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min() * 100

        # Sharpe Ratio (2% risk-free rate)
        rf = 0.02 / 252
        excess_returns = portfolio_returns - rf
        if excess_returns.std() > 0:
            sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0

        # Calmar Ratio
        if max_dd != 0:
            calmar = ann_ret / abs(max_dd)
        else:
            calmar = 0

        # Win rate (% of days with positive returns)
        win_rate = (portfolio_returns > 0).sum() / len(portfolio_returns) * 100

        return {
            'Portfolio': name,
            'Total Return %': total_ret,
            'Ann. Return %': ann_ret,
            'Ann. Vol %': ann_vol,
            'Max DD %': max_dd,
            'Sharpe': sharpe,
            'Calmar': calmar,
            'Win Rate %': win_rate,
            'Start': portfolio_returns.index[0].date(),
            'End': portfolio_returns.index[-1].date(),
        }

    def _portfolio_returns(self, returns: pd.DataFrame, tickers: List[str],
                           weights: pd.Series) -> pd.Series:
        """Daily portfolio returns for target `weights`, reset at each rebalance date."""
        freq = REBALANCE_FREQ[self.rebalance]
        if freq is None:
            return (returns[tickers] * weights).sum(axis=1)
        out = []
        for _, g in returns[tickers].groupby(returns.index.to_period(freq)):
            level = ((1 + g).cumprod() * weights).sum(axis=1)  # $1 at period start, drifting
            r = level.pct_change()
            r.iloc[0] = level.iloc[0] - 1
            out.append(r)
        return pd.concat(out)

    def backtest(self, scenarios: List[Tuple[List[str], str]],
                 weights: Optional[Dict[str, float]] = None) -> pd.DataFrame:
        """
        Run backtest on multiple scenarios

        Args:
            scenarios: List of (tickers, name) tuples
                       Example: [(['VTI', 'QQQ'], 'A: VTI+QQQ'),
                                 (['VTI', 'QQQ', 'BND'], 'B: VTI+QQQ+BND')]
            weights: Optional dict of ticker weights (default: equal weight).
                     Applied to every scenario; tickers not listed get weight 0.

        Returns:
            DataFrame with performance comparison
        """
        scenarios = [([t.upper() for t in tk], name) for tk, name in scenarios]
        self._ensure({t for tk, _ in scenarios for t in tk})

        usable = []
        for ticker_list, name in scenarios:
            valid = [t for t in ticker_list if t in self.inception]
            if len(valid) != len(ticker_list):
                print(f"⚠ Skipping {name}: no data for {sorted(set(ticker_list) - set(valid))}")
                continue
            usable.append((ticker_list, name))
        if not usable:
            return pd.DataFrame()

        used = sorted({t for tk, _ in usable for t in tk})
        common_start = max(self.inception[t] for t in used)
        if not self.own_window:
            binding = max(used, key=lambda t: self.inception[t])
            older = [t for t in used if self.inception[t] < common_start]
            print(f"Common window starts {common_start.date()} (limited by {binding}); "
                  f"{', '.join(older)} have earlier history — use own_window/--own-window "
                  f"to see it per scenario.\n" if older else
                  f"Common window starts {common_start.date()} (limited by {binding}).\n")

        self.portfolio_returns = {}
        results = []
        for ticker_list, name in usable:
            start = (max(self.inception[t] for t in ticker_list) if self.own_window
                     else common_start)
            px = self.prices.loc[start:, ticker_list].dropna()
            returns = px.pct_change().dropna()

            if weights:
                w = pd.Series({t: weights.get(t, 0) for t in ticker_list}, dtype=float)
                if w.sum() <= 0:
                    print(f"⚠ Skipping {name}: weights sum to 0")
                    continue
                w = w / w.sum()
            else:
                w = pd.Series(1.0 / len(ticker_list), index=ticker_list)

            port = self._portfolio_returns(returns, ticker_list, w).dropna()
            self.portfolio_returns[name] = port
            results.append(self._calculate_stats(port, name))

        self.window_returns = self.prices.loc[common_start:, used].dropna().pct_change().dropna()
        return pd.DataFrame(results)

    def compare_with_benchmark(self, scenarios: List[Tuple[List[str], str]],
                               benchmark: str = 'SPY') -> pd.DataFrame:
        """
        Run backtest and include benchmark comparison (benchmark joins the common window)

        Args:
            scenarios: List of (tickers, name) tuples
            benchmark: Benchmark ticker (default 'SPY')

        Returns:
            DataFrame with all scenarios + benchmark
        """
        return self.backtest(list(scenarios) + [([benchmark], f'BENCHMARK: {benchmark.upper()}')])

    def print_comparison(self, results_df: pd.DataFrame):
        """Pretty-print comparison table"""
        first = results_df.iloc[0]
        print("\n" + "="*130)
        print(f"PORTFOLIO PERFORMANCE COMPARISON  (rebalance: {self.rebalance}; "
              f"{first['Start']} → {first['End']}"
              f"{'' if not self.own_window else '; per-scenario windows'})")
        print("="*130 + "\n")

        for idx, row in results_df.iterrows():
            span = f"  [{row['Start']} → {row['End']}]" if self.own_window else ""
            print(f"{row['Portfolio']}{span}")
            print(f"  Total Return:    {row['Total Return %']:>8.1f}%")
            print(f"  Ann. Return:     {row['Ann. Return %']:>8.1f}%  |  Ann. Vol: {row['Ann. Vol %']:>6.1f}%")
            print(f"  Max Drawdown:    {row['Max DD %']:>8.1f}%")
            print(f"  Sharpe Ratio:    {row['Sharpe']:>8.2f}  |  Calmar: {row['Calmar']:>6.2f}  |  Win Rate: {row['Win Rate %']:>6.1f}%")
            print()

        print("="*130)
        print("RANKINGS")
        print("="*130 + "\n")

        # Best return
        best_return = results_df.loc[results_df['Total Return %'].idxmax()]
        print(f"1. Highest Total Return: {best_return['Portfolio']}")
        print(f"   {best_return['Total Return %']:.1f}%\n")

        # Best Sharpe
        best_sharpe = results_df.loc[results_df['Sharpe'].idxmax()]
        print(f"2. Best Risk-Adjusted (Sharpe): {best_sharpe['Portfolio']}")
        print(f"   Sharpe {best_sharpe['Sharpe']:.2f}\n")

        # Best Calmar
        best_calmar = results_df.loc[results_df['Calmar'].idxmax()]
        print(f"3. Best Crash Recovery (Calmar): {best_calmar['Portfolio']}")
        print(f"   Calmar {best_calmar['Calmar']:.2f}\n")

        # Least drawdown
        best_dd = results_df.loc[results_df['Max DD %'].idxmax()]  # Least negative
        print(f"4. Smoothest Ride (Least Drawdown): {best_dd['Portfolio']}")
        print(f"   Max DD {best_dd['Max DD %']:.1f}%\n")

    def print_details(self):
        """Calendar-year returns, stress-window returns and ticker correlations for the last backtest."""
        if not self.portfolio_returns:
            return
        rets = pd.DataFrame(self.portfolio_returns)  # NaN outside a scenario's own window
        yearly = ((1 + rets.fillna(0)).groupby(rets.index.year).prod() - 1) * 100
        yearly = yearly.where(rets.groupby(rets.index.year).count() > 0)
        print("="*130)
        print("CALENDAR-YEAR RETURNS % (first/last year may be partial)")
        print("="*130)
        print(yearly.round(1).to_string(), "\n")

        rows = {}
        for label, a, b in STRESS_WINDOWS:
            for name, r in self.portfolio_returns.items():
                if r.index[0] <= pd.Timestamp(a) and r.index[-1] >= pd.Timestamp(b):
                    rows.setdefault(f"{label} ({a} → {b})", {})[name] = ((1 + r.loc[a:b]).prod() - 1) * 100
        if rows:
            print("="*130)
            print("STRESS WINDOWS % (portfolio return over the window)")
            print("="*130)
            print(pd.DataFrame(rows).T.round(1).to_string(), "\n")

        if self.window_returns is not None and self.window_returns.shape[1] > 1:
            print("="*130)
            print("DAILY-RETURN CORRELATION (common window)")
            print("="*130)
            print(self.window_returns.corr().round(2).to_string(), "\n")


def main():
    """CLI interface"""
    parser = argparse.ArgumentParser(
        description='Portfolio Backtest Tool - Analyze N-ticker allocations'
    )
    parser.add_argument('--tickers', nargs='+', default=[],
                       help='Extra ticker symbols to pre-fetch (scenario tickers are added automatically)')
    parser.add_argument('--scenarios', nargs='+', required=True,
                       help='Portfolio scenarios (e.g., "VTI+QQQ" "VTI+QQQ+BND")')
    parser.add_argument('--start', default='2007-01-01',
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--benchmark', default='SPY',
                       help='Benchmark ticker (default SPY)')
    parser.add_argument('--rebalance', choices=list(REBALANCE_FREQ), default='daily',
                       help='Rebalance to equal weight daily (default), weekly or monthly')
    parser.add_argument('--own-window', action='store_true',
                       help='Give each scenario its own full history instead of one common window')

    args = parser.parse_args()

    # Parse scenarios
    scenarios = []
    for scenario_str in args.scenarios:
        name = scenario_str
        tickers_in_scenario = scenario_str.replace('+', ' ').split()
        scenarios.append((tickers_in_scenario, name))

    all_tickers = args.tickers + [t for tk, _ in scenarios for t in tk] + [args.benchmark]

    # Run backtest
    bt = PortfolioBacktester(all_tickers, start_date=args.start, end_date=args.end,
                             rebalance=args.rebalance, own_window=args.own_window)
    results = bt.compare_with_benchmark(scenarios, benchmark=args.benchmark)
    if results.empty:
        raise SystemExit("No scenario could be run.")

    # Print results
    bt.print_comparison(results)
    bt.print_details()

    # Export to CSV
    csv_filename = f"portfolio_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    results.to_csv(csv_filename, index=False)
    print(f"\nResults saved to {csv_filename}")


if __name__ == '__main__':
    main()
