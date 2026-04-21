"""Parameter grid search optimizer - find optimal MACD, SMA, BB settings"""
import itertools
import json
import pandas as pd
import numpy as np
from datetime import datetime
from strategies import SPYSwingTradingStrategy


class ParameterOptimizer:
    """Grid search optimizer for strategy parameters"""

    def __init__(self, data_df, initial_capital=100000, symbol=None, allocation_weight=10):
        self.data = data_df.copy()
        self.initial_capital = initial_capital
        self.results = []
        self.symbol = symbol  # For progress tracking (e.g., 'SPY')
        self.allocation_weight = allocation_weight  # Capital allocation percentage per trade (default 10%)

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
            trades, metrics, equity_curve = self._backtest_with_params(params)

            # Store results
            result = {
                'params': params,
                'metrics': metrics,
                'trades': trades,
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

        # Apply custom indicators with parameters
        from indicators import calculate_macd, calculate_sma, calculate_bollinger_bands

        # MACD with custom parameters
        ema_fast = data['close'].ewm(span=params['macd_fast']).mean()
        ema_slow = data['close'].ewm(span=params['macd_slow']).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=params['macd_signal']).mean()
        macd_histogram = macd_line - signal_line

        # SMAs with custom periods
        sma_short = data['close'].rolling(window=params['sma_short']).mean()
        sma_long = data['close'].rolling(window=params['sma_long']).mean()

        # Bollinger Bands with custom parameters
        bb_middle = data['close'].rolling(window=params['bb_period']).mean()
        bb_std = data['close'].rolling(window=params['bb_period']).std()
        bb_lower = bb_middle - (bb_std * params['bb_std'])
        bb_upper = bb_middle + (bb_std * params['bb_std'])

        # Generate signals with custom params
        signals = pd.Series(0, index=data.index)

        for i in range(max(params['sma_long'], params['macd_slow'], params['bb_period']), len(data)):
            # MACD bullish
            macd_bullish = (macd_histogram.iloc[i-1] <= 0 and macd_histogram.iloc[i] > 0)

            # Uptrend: price > sma_short > sma_long
            price = data['close'].iloc[i]
            uptrend = (price > sma_short.iloc[i] and sma_short.iloc[i] > sma_long.iloc[i])

            # Price near lower BB
            bb_condition = price <= bb_lower.iloc[i] * 1.05

            # Entry
            if macd_bullish and uptrend and bb_condition:
                signals.iloc[i] = 1

            # Exit
            if i > 0 and signals.iloc[i-1] == 1:
                macd_bearish = (macd_histogram.iloc[i-1] >= 0 and macd_histogram.iloc[i] < 0)
                bb_break = price < bb_lower.iloc[i]

                if macd_bearish or bb_break:
                    signals.iloc[i] = -1

        # Simulate trades
        trades = []
        equity_curve = [self.initial_capital]
        position_active = False
        entry_price = None
        entry_idx = None

        for i in range(len(signals)):
            signal = signals.iloc[i]
            price = data['close'].iloc[i]

            if signal == 1 and not position_active:
                entry_price = price
                entry_idx = i
                position_active = True

            if (signal == -1 or i == len(signals) - 1) and position_active:
                exit_price = price
                pnl = (exit_price - entry_price) / entry_price
                shares = (self.initial_capital * (self.allocation_weight / 100)) / entry_price
                pnl_dollar = shares * (exit_price - entry_price)

                trades.append({
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'entry_at': str(data.index[entry_idx]),
                    'exit_at': str(data.index[i]),
                    'return': pnl,
                    'pnl_dollar': pnl_dollar,
                    'pnl_pct': pnl
                })

                current_equity = equity_curve[-1] * (1 + pnl)
                equity_curve.append(current_equity)

                position_active = False

        # Calculate metrics
        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            sharpe = self._calculate_sharpe(equity_curve)
            metrics = {
                'total_trades': len(trades_df),
                'winning_trades': wins,
                'win_rate': wins / len(trades_df),
                'avg_return': trades_df['return'].mean(),
                'total_return': (equity_curve[-1] - self.initial_capital) / self.initial_capital,
                'sharpe_ratio': sharpe,
                'max_drawdown': self._calculate_max_drawdown(equity_curve)
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

        return trades, metrics, equity_curve

    @staticmethod
    def _calculate_sharpe(equity_curve):
        """Calculate Sharpe ratio"""
        if len(equity_curve) < 2:
            return 0
        returns = pd.Series(equity_curve).pct_change().dropna()
        if len(returns) == 0 or returns.std() == 0:
            return 0
        return (returns.mean() * 252) / (returns.std() * (252 ** 0.5))

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
        print(f"{'Rank':<6} {'Sharpe':<10} {'Win%':<8} {'Return':<10} {'Trades':<8} {'Parameters':<40}")
        print("-" * 90)

        for idx, result in enumerate(self.results[:n]):
            params = result['params']
            metrics = result['metrics']

            param_str = f"MACD({params['macd_fast']},{params['macd_slow']}) SMA({params['sma_short']},{params['sma_long']}) BB({params['bb_period']},{params['bb_std']})"

            print(
                f"{idx+1:<6} "
                f"{metrics['sharpe_ratio']:<10.2f} "
                f"{metrics['win_rate']*100:<8.1f} "
                f"{metrics['total_return']*100:<10.2f}% "
                f"{metrics['total_trades']:<8} "
                f"{param_str:<40}"
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
            'timestamp': datetime.now().isoformat(),
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
