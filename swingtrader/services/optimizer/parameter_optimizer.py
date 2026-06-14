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
                    'chandelier_period': [14, 18, 22],
                    'chandelier_mult':      [2.5, 3.0, 3.5],
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

        entry_mode = 'chandelier_entry' if 'chandelier_entry_mult' in param_names else 'always'

        for idx, combo in enumerate(combinations):
            params = dict(zip(param_names, combo))

            # Run backtest with these parameters
            trades, metrics, equity_curve, equity_dates = self._backtest_with_params(params, entry_mode=entry_mode)

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

    @staticmethod
    def _compute_ppo(close_prices):
        """Compute PPO (Percentage Price Oscillator) from close prices.

        PPO = ((12-period EMA - 26-period EMA) / 26-period EMA) * 100
        Returns numpy array of PPO values (same length as input, NaN until warmup).
        """
        close = pd.Series(close_prices)
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        ppo = ((ema_12 - ema_26) / ema_26) * 100
        return ppo.values

    @staticmethod
    def _linear_reg_slope(close_prices, window):
        """Compute linear regression slope over last `window` bars.
        Returns numpy array (same length, NaN until warmup)."""
        slope = np.full(len(close_prices), np.nan)
        for i in range(window - 1, len(close_prices)):
            y = close_prices[i - window + 1 : i + 1]
            x = np.arange(window)
            A = np.vstack([x, np.ones(window)]).T
            m, _ = np.linalg.lstsq(A, y, rcond=None)[0]
            slope[i] = m
        return slope

    @staticmethod
    def _compute_ema_sma_cross(close_prices, fast_period, slow_period):
        """Compute EMA(fast) / SMA(slow) crossover signals.

        Returns (ema_fast, sma_slow) arrays for bar-by-bar checking.
        """
        close = pd.Series(close_prices)
        ema_fast = close.ewm(span=fast_period, adjust=False).mean()
        sma_slow = close.rolling(window=slow_period).mean()
        return ema_fast.values, sma_slow.values

    def _backtest_with_params(self, params, entry_mode='always'):
        """Run backtest with specific parameters

        Args:
            params: dict with 'chandelier_period' and 'chandelier_mult'
            entry_mode: 'always', 'ppo_zero_cross', 'ema_sma_cross', or 'chandelier_entry'
        """
        data = self.data.copy()

        # Use daily bars if available (UTC hour=4/5, min=0 = NY midnight EDT/EST)
        daily_mask = (data.index.minute == 0) & (data.index.hour.isin([4, 5]))
        if daily_mask.any():
            data = data[daily_mask].copy()
            data.index = data.index.normalize()
        else:
            data = data.resample('1D').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()

        n = len(data)
        if n < 2:
            return [], self._empty_metrics(), [], []

        cost_per_trade = 0.0005

        chandelier_period = int(params.get('chandelier_period', 18))
        chandelier_mult = float(params.get('chandelier_mult', 3.0))

        # Regression exit params
        reg_window = params.get('reg_slope_window')
        reg_threshold = params.get('reg_slope_threshold')
        reg_type = params.get('reg_slope_type')

        # Pre-extract numpy arrays for speed
        open_p = data['open'].values.astype(float)
        high_p = data['high'].values.astype(float)
        low_p = data['close'].values.astype(float)
        close_p = data['close'].values.astype(float)

        # Compute entry indicators
        ppo_values = None
        ppo_warmup = 0
        ema_fast_values = None
        sma_slow_values = None
        ema_sma_warmup = 0
        fast_ema_period = 24
        slow_sma_period = 52

        if entry_mode == 'ppo_zero_cross':
            ppo_values = self._compute_ppo(close_p)
            ppo_warmup = 27  # 26 bars EMA warmup + 1 to detect cross
        elif entry_mode == 'ema_sma_cross':
            fast_ema_period = int(params.get('ema_sma_fast', 10))
            slow_sma_period = int(params.get('ema_sma_slow', 40))
            ema_fast_values, sma_slow_values = self._compute_ema_sma_cross(
                close_p, fast_ema_period, slow_sma_period
            )
            ema_sma_warmup = slow_sma_period + 1  # SMA needs full window

        # Pre-compute rolling high for Chandelier entry
        rolling_high = None
        chandelier_entry_mult = None
        if entry_mode == 'chandelier_entry':
            chandelier_entry_mult = float(params.get('chandelier_entry_mult', 1.0))
            rolling_high = pd.Series(high_p).rolling(window=chandelier_period, min_periods=1).max().values

        prev_close = np.roll(close_p, 1)
        prev_close[0] = close_p[0]
        tr = np.maximum.reduce([
            high_p - low_p,
            np.abs(high_p - prev_close),
            np.abs(low_p - prev_close)
        ])
        atr_series = pd.Series(tr).rolling(window=chandelier_period).mean()
        atr = atr_series.values

        # Pre-compute regression slope if enabled
        reg_slope = None
        reg_warmup = 0
        if reg_window is not None and reg_threshold is not None and reg_type is not None:
            reg_slope_raw = self._linear_reg_slope(close_p, reg_window)
            reg_slope = np.full(len(close_p), np.nan)
            for i in range(len(close_p)):
                if np.isnan(reg_slope_raw[i]):
                    continue
                if reg_type == 'slope_atr':
                    if atr[i] and not np.isnan(atr[i]) and atr[i] > 0:
                        reg_slope[i] = reg_slope_raw[i] / atr[i]
                elif reg_type == 'slope_pct':
                    if close_p[i] > 0:
                        reg_slope[i] = reg_slope_raw[i] / close_p[i] * 100
                elif reg_type == 'slope':
                    reg_slope[i] = reg_slope_raw[i]
            reg_warmup = reg_window

        warmup = max(chandelier_period, ppo_warmup, ema_sma_warmup, reg_warmup)
        alloc = 1.0  # Single-ticker backtest: always fully invested (allocation only splits capital in portfolio backtest)

        trades = []
        bar_equity = [self.initial_capital]
        trade_equity = [self.initial_capital]
        trade_dates = [str(data.index[0])]
        position_active = False
        pending_entry = False
        pending_exit = False
        exit_type = None
        entry_price = 0.0
        entry_idx = 0
        equity_before = self.initial_capital
        high_since = 0.0

        for i in range(warmup, n):
            po = open_p[i]
            pc = close_p[i]
            ph = high_p[i]

            if pending_exit and position_active:
                allocated = equity_before * alloc
                deployed = allocated * (1 - cost_per_trade)
                shares = deployed / entry_price
                net_proceeds = shares * po * (1 - cost_per_trade)
                net_dollar = net_proceeds - deployed
                net_pnl = net_dollar / deployed

                trades.append({
                    'entry_price': entry_price,
                    'exit_price': po,
                    'entry_at': str(data.index[entry_idx]),
                    'exit_at': str(data.index[i]),
                    'return': net_pnl,
                    'pnl_dollar': net_dollar,
                    'pnl_pct': net_pnl,
                    'days_held': round(i - entry_idx, 1),
                    'allocation_pct': 100,
                    'exit_type': exit_type or 'chandelier',
                })

                trade_equity.append(trade_equity[-1] + net_dollar)
                trade_dates.append(str(data.index[i]))
                position_active = False
                pending_exit = False
                exit_type = None

            if pending_entry and not position_active:
                entry_price = po
                entry_idx = i
                equity_before = trade_equity[-1]
                position_active = True
                high_since = ph
                pending_entry = False

            if not position_active and not pending_entry:
                if entry_mode == 'ppo_zero_cross':
                    if ppo_values[i] > 0 and ppo_values[i - 1] <= 0:
                        pending_entry = True
                elif entry_mode == 'ema_sma_cross':
                    if (ema_fast_values[i] > sma_slow_values[i]
                            and ema_fast_values[i - 1] <= sma_slow_values[i - 1]):
                        pending_entry = True
                elif entry_mode == 'chandelier_entry':
                    entry_level = rolling_high[i] - atr[i] * chandelier_entry_mult
                    if pc > entry_level:
                        pending_entry = True
                else:
                    pending_entry = True

            if position_active and not pending_exit:
                if ph > high_since:
                    high_since = ph
                stop_level = high_since - atr[i] * chandelier_mult
                if pc < stop_level:
                    pending_exit = True
                    exit_type = 'chandelier'
                # Regression exit: exit when normalized slope drops below threshold
                if not pending_exit and reg_slope is not None and not np.isnan(reg_slope[i]):
                    if reg_slope[i] < reg_threshold:
                        pending_exit = True
                        exit_type = 'regression'

            if i == n - 1 and position_active:
                simulated_close = not pending_exit
                allocated = equity_before * alloc
                deployed = allocated * (1 - cost_per_trade)
                shares = deployed / entry_price
                net_proceeds = shares * pc * (1 - cost_per_trade)
                net_dollar = net_proceeds - deployed
                net_pnl = net_dollar / deployed

                trades.append({
                    'entry_price': entry_price,
                    'exit_price': pc,
                    'entry_at': str(data.index[entry_idx]),
                    'exit_at': str(data.index[i]),
                    'return': net_pnl,
                    'pnl_dollar': net_dollar,
                    'pnl_pct': net_pnl,
                    'days_held': round(i - entry_idx, 1),
                    'simulated_close': simulated_close,
                    'allocation_pct': 100,
                    'exit_type': 'force_close' if simulated_close else (exit_type or 'chandelier'),
                })

                trade_equity.append(trade_equity[-1] + net_dollar)
                trade_dates.append(str(data.index[i]))
                position_active = False
                pending_exit = False

            if position_active:
                shares = (equity_before * alloc) / entry_price
                bar_equity.append(equity_before + shares * (pc - entry_price))
            else:
                bar_equity.append(trade_equity[-1])

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
                'total_return': (trade_equity[-1] - self.initial_capital) / self.initial_capital,
                'sharpe_ratio': sharpe,
                'max_drawdown': self._calculate_max_drawdown(trade_equity)
            }
        else:
            metrics = self._empty_metrics()
            trades = []

        return trades, metrics, trade_equity, trade_dates

    @staticmethod
    def _empty_metrics():
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'win_rate': 0,
            'avg_return': 0,
            'total_return': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0
        }

    @staticmethod
    def backtest_portfolio(ticker_data, ticker_params, initial_capital=100000,
                           cost_per_trade=0.0005):
        """
        Single-pool portfolio backtest:
        - All capital in one pool, split equally among tickers that trigger on the same bar
        - If only one ticker triggers, it gets all available cash
        - When a position exits, freed cash is redistributed equally to remaining
          in-position tickers immediately (buy more shares at same bar's open)

        Args:
            ticker_data:     dict of {symbol: DataFrame} with OHLCV data
            ticker_params:   dict of {symbol: dict} with CHAND params
            initial_capital: starting cash
            cost_per_trade:  round-trip transaction cost fraction
        """
        tickers = list(ticker_data.keys())
        empty = {'total_trades': 0, 'winning_trades': 0, 'win_rate': 0,
                 'avg_return': 0, 'total_return': 0, 'sharpe_ratio': 0, 'max_drawdown': 0}
        if not tickers:
            return [], empty, [], []

        # Align all tickers to common date index and filter to daily bars
        common_index = None
        aligned = {}
        for sym, df in ticker_data.items():
            d = df.copy()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in d.columns:
                    d[col] = d[col].astype(float)
            daily_mask = (d.index.minute == 0) & (d.index.hour.isin([4, 5]))
            if daily_mask.any():
                d = d[daily_mask].copy()
                d.index = d.index.normalize()
            aligned[sym] = d
            common_index = d.index if common_index is None else common_index.intersection(d.index)

        # Precompute ATR, rolling high, and regression slope for each ticker
        atr_data = {}
        rolling_high_data = {}
        reg_slope_data = {}
        for sym in tickers:
            d = aligned[sym].loc[common_index]
            p = ticker_params.get(sym, {})
            period = int(p.get('chandelier_period', 18))
            prev_close = d['close'].shift(1)
            tr = pd.concat([
                d['high'] - d['low'],
                (d['high'] - prev_close).abs(),
                (d['low'] - prev_close).abs()
            ], axis=1).max(axis=1)
            atr_data[sym] = tr.rolling(window=period).mean()
            if p.get('chandelier_entry_mult') is not None:
                rolling_high_data[sym] = d['high'].rolling(window=period, min_periods=1).max()
            aligned[sym] = d

            # Pre-compute regression slope for this ticker
            rw = p.get('reg_slope_window')
            rt = p.get('reg_slope_threshold')
            rtyp = p.get('reg_slope_type')
            if rw is not None and rt is not None and rtyp is not None:
                close_vals = d['close'].values.astype(float)
                raw = ParameterOptimizer._linear_reg_slope(close_vals, rw)
                slp = np.full(len(close_vals), np.nan)
                atr_arr = atr_data[sym].values
                for i in range(len(close_vals)):
                    if np.isnan(raw[i]) or np.isnan(atr_arr[i]):
                        continue
                    if rtyp == 'slope_atr':
                        if atr_arr[i] > 0:
                            slp[i] = raw[i] / atr_arr[i]
                    elif rtyp == 'slope_pct':
                        if close_vals[i] > 0:
                            slp[i] = raw[i] / close_vals[i] * 100
                    elif rtyp == 'slope':
                        slp[i] = raw[i]
                reg_slope_data[sym] = slp

        warmup = max(int(p.get('chandelier_period', 18)) for p in ticker_params.values())
        for p in ticker_params.values():
            if p.get('reg_slope_window') is not None:
                warmup = max(warmup, int(p['reg_slope_window']))

        cash = initial_capital
        positions = {}           # sym -> {shares, entry_price, entry_idx, entry_at, allocation_pct}
        pend_entry = {sym: False for sym in tickers}
        pend_exit  = {sym: False for sym in tickers}
        exit_type  = {sym: None  for sym in tickers}
        high_since = {sym: 0.0  for sym in tickers}

        trades = []
        equity_curve = [initial_capital]
        equity_dates  = [str(common_index[0])]

        def _make_trade(sym, pos, exit_price, exit_date, simulated=False, etype=None):
            cost = pos['shares'] * pos['entry_price']
            net  = pos['shares'] * exit_price * (1 - cost_per_trade)
            pnl  = net - cost
            return {
                'symbol': sym,
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'entry_at': pos['entry_at'],
                'exit_at': str(exit_date),
                'return': pnl / cost if cost else 0,
                'pnl_dollar': pnl,
                'pnl_pct': pnl / cost if cost else 0,
                'days_held': round(pos.get('days', 0), 1),
                'allocation_pct': pos.get('allocation_pct', 0),
                'simulated_close': simulated,
                'exit_type': etype or ('force_close' if simulated else 'chandelier'),
            }

        def _buy_shares(amount, price):
            return amount * (1 - cost_per_trade) / price if price > 0 else 0

        for i in range(len(common_index)):
            if i < warmup:
                continue
            date = common_index[i]

            # ── 1. Process exits ────────────────────────────────────────────
            exited = []
            for sym in list(positions.keys()):
                if not pend_exit[sym]:
                    continue
                ep = aligned[sym]['open'].iloc[i]
                positions[sym]['days'] = i - positions[sym]['entry_idx']
                trades.append(_make_trade(sym, positions[sym], ep, date, etype=exit_type[sym]))
                cash += positions[sym]['shares'] * ep * (1 - cost_per_trade)
                del positions[sym]
                pend_exit[sym] = False
                exit_type[sym] = None
                exited.append(sym)

            # ── 3. New entries — split cash equally among triggering tickers ─
            entering = [sym for sym in tickers
                        if pend_entry[sym] and sym not in positions]
            if entering and cash > 0:
                amount_each = cash / len(entering)
                total_eq = cash + sum(
                    pos['shares'] * aligned[s]['close'].iloc[i]
                    for s, pos in positions.items()
                )
                for sym in entering:
                    ep = aligned[sym]['open'].iloc[i]
                    positions[sym] = {
                        'shares': _buy_shares(amount_each, ep),
                        'entry_price': ep,
                        'entry_idx': i,
                        'entry_at': str(date),
                        'allocation_pct': round(amount_each / total_eq * 100, 2),
                    }
                    high_since[sym] = aligned[sym]['high'].iloc[i]
                    pend_entry[sym] = False
                    cash -= amount_each

            # ── 4. Generate signals ─────────────────────────────────────────
            for sym in tickers:
                close = aligned[sym]['close'].iloc[i]
                high  = aligned[sym]['high'].iloc[i]

                if sym in positions and not pend_exit[sym]:
                    high_since[sym] = max(high_since[sym], high)
                    stop = high_since[sym] - atr_data[sym].iloc[i] * float(ticker_params[sym].get('chandelier_mult', 3.0))
                    if close < stop:
                        pend_exit[sym] = True
                        exit_type[sym] = 'chandelier'
                    # Regression exit
                    if not pend_exit[sym] and sym in reg_slope_data and len(reg_slope_data[sym]) > i:
                        reg_val = reg_slope_data[sym][i]
                        rt = ticker_params[sym].get('reg_slope_threshold')
                        if not np.isnan(reg_val) and rt is not None and reg_val < rt:
                            pend_exit[sym] = True
                            exit_type[sym] = 'regression'

                if sym not in positions and not pend_entry[sym]:
                    em = ticker_params[sym].get('chandelier_entry_mult')
                    if em is not None and sym in rolling_high_data and not pd.isna(rolling_high_data[sym].iloc[i]):
                        if close > rolling_high_data[sym].iloc[i] - atr_data[sym].iloc[i] * float(em):
                            pend_entry[sym] = True
                    else:
                        pend_entry[sym] = True

            # ── 5. Force-close all positions at end of data ─────────────────
            if i == len(common_index) - 1:
                for sym, pos in list(positions.items()):
                    ep = aligned[sym]['close'].iloc[i]
                    pos['days'] = i - pos['entry_idx']
                    trades.append(_make_trade(sym, pos, ep, date,
                                               simulated=not pend_exit.get(sym, False),
                                               etype=exit_type.get(sym) if pend_exit.get(sym) else 'force_close'))
                    cash += pos['shares'] * ep * (1 - cost_per_trade)
                    del positions[sym]

            # ── 6. Track equity ─────────────────────────────────────────────
            equity = cash + sum(
                pos['shares'] * aligned[sym]['close'].iloc[i]
                for sym, pos in positions.items()
            )
            equity_curve.append(equity)
            equity_dates.append(str(date))

        # Calculate metrics
        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            metrics = {
                'total_trades': len(trades_df),
                'winning_trades': int(wins),
                'win_rate': wins / len(trades_df),
                'avg_return': float(trades_df['return'].mean()),
                'total_return': (equity_curve[-1] - initial_capital) / initial_capital,
                'sharpe_ratio': ParameterOptimizer._calculate_sharpe(equity_curve),
                'max_drawdown': ParameterOptimizer._calculate_max_drawdown(equity_curve),
            }
        else:
            metrics = empty

        return trades, metrics, equity_curve, equity_dates

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
        print(f"{'Rank':<6} {'Sharpe':<10} {'Win%':<8} {'Return':<10} {'Trades':<8} {'Parameters':<70}")
        print("-" * 120)

        for idx, result in enumerate(self.results[:n]):
            params = result['params']
            metrics = result['metrics']

            reg = ''
            if params.get('reg_slope_window') is not None:
                reg = f" + REG({params['reg_slope_type']} {params['reg_slope_window']}d th={params['reg_slope_threshold']})"
            param_str = f"CHAND(period={params['chandelier_period']}, mult={params['chandelier_mult']}, entry={params.get('chandelier_entry_mult', 'N/A')}){reg}"

            print(
                f"{idx+1:<6} "
                f"{metrics['sharpe_ratio']:<10.2f} "
                f"{metrics['win_rate']*100:<8.1f} "
                f"{metrics['total_return']*100:<10.2f}% "
                f"{metrics['total_trades']:<8} "
                f"{param_str:<70}"
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

        reg_note = ''
        if best['params'].get('reg_slope_window') is not None:
            reg_note = f" + REG({best['params']['reg_slope_type']} {best['params']['reg_slope_window']}d th={best['params']['reg_slope_threshold']})"
            print(f"  Exit: Chandelier{reg_note}")
        else:
            print(f"  Exit: Chandelier only")

        output = {
            'timestamp': datetime.now(ZoneInfo('America/New_York')).isoformat(),
            'best_params': convert_to_native(best['params']),
            'best_metrics': convert_to_native(best['metrics']),
            'regression_exit': reg_note != '',
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
