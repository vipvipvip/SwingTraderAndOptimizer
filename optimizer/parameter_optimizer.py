"""Parameter grid search optimizer - find optimal MACD, SMA, BB settings"""
import itertools
import json
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo


class ParameterOptimizer:
    """Grid search optimizer for strategy parameters"""

    def __init__(self, data_df, initial_capital=100000, symbol=None, allocation_weight=10):
        self.data = data_df.copy()
        # Convert Decimal types from PostgreSQL to float
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in self.data.columns:
                self.data[col] = self.data[col].astype(float)
        self.initial_capital = float(initial_capital)
        self.results = []
        self.symbol = symbol  # For progress tracking (e.g., 'SPY')
        self.allocation_weight = float(allocation_weight)  # Capital allocation percentage per trade (default 10%)

    def optimize(self, param_grid):
        """
        Run grid search over parameter combinations

        Args:
            param_grid: dict with lists of values for each parameter
                {
                    'macd_fast': [10, 12, 14],
                    'macd_slow': [24, 26, 28],
                    'macd_signal': [7, 9, 11],
                    'sma_short': [40, 50, 60],
                    'sma_long': [180, 200, 220],
                    'bb_period': [18, 20, 22],
                    'bb_std': [1.8, 2.0, 2.2]
                }

        Returns:
            List of results sorted by Sharpe ratio (best first)
        """

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = [param_grid[name] for name in param_names]
        combinations = list(itertools.product(*param_values))

        print(f"\nTesting {len(combinations)} parameter combinations...")
        print(f"This may take a few minutes...\n")

        for idx, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))

            # Run backtest with these parameters
            trades, metrics, equity_curve, equity_dates = self._backtest_with_params(params)

            # Store results
            result = {
                'params': params,
                'metrics': metrics,
                'trades': trades,
                'equity_curve': equity_curve,
                'equity_dates': equity_dates,
                'trades_count': len(trades) if trades is not None else 0
            }
            self.results.append(result)

            # Progress indicator
            if (idx + 1) % 10 == 0:
                ticker_label = f"[{self.symbol}] " if self.symbol else ""
                print(f"  {ticker_label}Tested {idx + 1}/{len(combinations)} combinations...")

        # Sort by Sharpe ratio (descending)
        self.results.sort(
            key=lambda x: x['metrics']['sharpe_ratio'],
            reverse=True
        )

        print(f"\n[OK] Optimization complete! Top 5 results:\n")
        self._print_top_results(5)

        return self.results

    def _backtest_with_params(self, params):
        """Run backtest with specific parameters"""
        data = self.data.copy()

        # Use daily bars if available (UTC hour=4, min=0 = NY midnight)
        daily_mask = (data.index.hour == 4) & (data.index.minute == 0)
        if daily_mask.any():
            data = data[daily_mask].copy()
            data.index = data.index.normalize()
        else:
            # Resample hourly to daily
            data = data.resample('1D').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()

        from indicators import calculate_macd, calculate_sma, calculate_ema, calculate_bollinger_bands

        # Cost model: 0.05% round-trip (slippage + commission)
        cost_per_trade = 0.0005

        # Chandelier Exit(18, 3.0) for growth trend following
        chandelier_period = 18
        chandelier_mult = 3.0

        prev_close = data['close'].shift(1)
        tr = pd.concat([
            data['high'] - data['low'],
            (data['high'] - prev_close).abs(),
            (data['low'] - prev_close).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=chandelier_period).mean()

        warmup = chandelier_period

        # Simulate trades with chandelier exit
        trades = []
        bar_equity = [self.initial_capital]
        trade_equity_curve = [self.initial_capital]
        trade_equity_dates = [str(data.index[0])]
        position_active = False
        pending_entry = False
        pending_exit = False
        entry_price = None
        entry_idx = None
        equity_before_trade = self.initial_capital
        high_since_entry = 0

        for i in range(len(data)):
            if i < warmup:
                continue

            price_open = data['open'].iloc[i]
            price_close = data['close'].iloc[i]
            price_high = data['high'].iloc[i]

            if pending_exit and position_active:
                exit_price = price_open
                shares_amount = (equity_before_trade * (self.allocation_weight / 100)) / entry_price
                gross_dollar = shares_amount * (exit_price - entry_price)

                trade_value = shares_amount * exit_price
                cost = trade_value * cost_per_trade
                net_dollar = gross_dollar - cost
                net_pnl = net_dollar / (equity_before_trade * (self.allocation_weight / 100))

                days_held = round((i - entry_idx) / 7, 1)

                trades.append({
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'entry_at': str(data.index[entry_idx]),
                    'exit_at': str(data.index[i]),
                    'return': net_pnl,
                    'pnl_dollar': net_dollar,
                    'pnl_pct': net_pnl,
                    'days_held': days_held
                })

                current_equity = trade_equity_curve[-1] + net_dollar
                trade_equity_curve.append(current_equity)
                trade_equity_dates.append(str(data.index[i]))

                position_active = False
                pending_exit = False

            if pending_entry and not position_active:
                entry_price = price_open
                entry_idx = i
                equity_before_trade = trade_equity_curve[-1]
                position_active = True
                high_since_entry = price_high
                pending_entry = False

            # Always ready to enter after warmup
            if not position_active and not pending_entry:
                pending_entry = True

            # Chandelier exit: close drops below (highest high - ATR * mult)
            if position_active and not pending_exit:
                high_since_entry = max(high_since_entry, price_high)
                stop_level = high_since_entry - atr.iloc[i] * chandelier_mult
                if price_close < stop_level:
                    pending_exit = True

            # Force exit at end of data
            if i == len(data) - 1 and position_active and not pending_exit:
                pending_exit = True

            if position_active:
                shares_amount = (equity_before_trade * (self.allocation_weight / 100)) / entry_price
                unrealized_pnl = shares_amount * (price_close - entry_price)
                bar_equity.append(equity_before_trade + unrealized_pnl)
            else:
                bar_equity.append(trade_equity_curve[-1])

        # Calculate metrics
        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            sharpe = self._calculate_sharpe(bar_equity)
            metrics = {
                'total_trades': len(trades_df),
                'winning_trades': wins,
                'win_rate': wins / len(trades_df),
                'avg_return': trades_df['return'].mean(),
                'total_return': (trade_equity_curve[-1] - self.initial_capital) / self.initial_capital,
                'sharpe_ratio': sharpe,
                'max_drawdown': self._calculate_max_drawdown(trade_equity_curve)
            }
        else:
            metrics = {
                'total_trades': 0,
                'winning_trades': 0,
                'win_rate': 0,
                'avg_return': 0,
                'total_return': 0,
                'sharpe_ratio': 0,
                'max_drawdown': 0
            }
            trades = []

        return trades, metrics, trade_equity_curve, trade_equity_dates

    @staticmethod
    def _calculate_sharpe(equity_curve):
        """Calculate Sharpe ratio (annualized for hourly data: 252 days × 6.5 hours/day = 1638)"""
        if len(equity_curve) < 2:
            return 0
        returns = pd.Series(equity_curve).pct_change().dropna()
        if len(returns) == 0 or returns.std() == 0:
            return 0
        daily_periods = 252  # Trading days per year
        return (returns.mean() * daily_periods) / (returns.std() * (daily_periods ** 0.5))

    @staticmethod
    def _calculate_max_drawdown(equity_curve):
        """Calculate max drawdown"""
        peak = equity_curve[0]
        max_dd = 0
        for value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _print_top_results(self, n=5):
        """Print top N results"""
        print(f"{'Rank':<6} {'Sharpe':<10} {'Win%':<8} {'Return':<10} {'Trades':<8} {'Parameters':<50}")
        print("-" * 100)

        for idx, result in enumerate(self.results[:n]):
            params = result['params']
            metrics = result['metrics']

            param_str = f"BB(period={params['bb_period']}, std={params['bb_std']})"

            print(
                f"{idx+1:<6} "
                f"{metrics['sharpe_ratio']:<10.2f} "
                f"{metrics['win_rate']*100:<8.1f} "
                f"{metrics['total_return']*100:<10.2f}% "
                f"{metrics['total_trades']:<8} "
                f"{param_str:<50}"
            )

    def save_best_params(self, filepath):
        """Save best parameters to JSON"""
        if not self.results:
            print("No results to save")
            return

        best = self.results[0]

        # Convert numpy types to native Python types for JSON serialization
        def convert_to_native(obj):
            if isinstance(obj, dict):
                return {k: convert_to_native(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_native(v) for v in obj]
            elif isinstance(obj, (np.integer, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, float)):
                return float(obj)
            elif isinstance(obj, bool):
                return bool(obj)
            else:
                return obj

        output = {
            'timestamp': datetime.now(ZoneInfo('America/New_York')).isoformat(),
            'best_params': convert_to_native(best['params']),
            'best_metrics': convert_to_native(best['metrics']),
            'top_10_results': [
                {
                    'params': convert_to_native(r['params']),
                    'metrics': convert_to_native(r['metrics'])
                }
                for r in self.results[:10]
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n[OK] Best parameters saved to: {filepath}")

    def load_best_params(self, filepath):
        """Load best parameters from JSON"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return data['best_params']
