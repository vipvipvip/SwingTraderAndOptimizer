"""Strategy definitions and signal generation"""
import pandas as pd
import numpy as np
from indicators import (
    calculate_macd, calculate_ppo, calculate_sma, calculate_ema,
    calculate_bollinger_bands, calculate_crossover
)


class SPYSwingTradingStrategy:
    """
    SPY Swing Trading Strategy
    - Entry: MACD + EMA10/SMA40 crossover confirmation + Bollinger Bands
    - Exit: Opposite signals or stop loss
    """

    def __init__(self, initial_capital=100000, position_size=0.1, params=None):
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.name = "SPY Swing Trading (MACD + EMA/SMA + BB + ATR)"
        self.params = params or {
            'ema_fast': 10,
            'sma_medium': 40,
            'min_signals': 2,
            'cost_per_trade': 0.0005,
        }

    def generate_signals(self, df):
        df = df.copy()

        # Use daily bars if available, otherwise resample hourly
        daily_mask = (df.index.minute == 0) & (df.index.hour.isin([4, 5]))
        if daily_mask.any():
            df = df[daily_mask].copy()
            df.index = df.index.normalize()
        else:
            df = df.resample('1D').agg({
                'open': 'first', 'high': 'max', 'low': 'min',
                'close': 'last', 'volume': 'sum'
            }).dropna()

        macd_data = calculate_macd(df['close'])
        ppo_data = calculate_ppo(df['close'])
        sma_50 = calculate_sma(df['close'], 350)
        sma_200 = calculate_sma(df['close'], 1400)
        bb_data = calculate_bollinger_bands(df['close'], period=20)

        # Chandelier Exit(22, 3.0) for growth trend following
        chandelier_period = 22
        chandelier_mult = 3.0

        prev_close = df['close'].shift(1)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(window=chandelier_period).mean()

        # Always-long with chandelier exit: signals generated in backtest
        signals = pd.Series(0, index=df.index)
        df['chandelier_atr'] = atr

        df['signal'] = signals
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal']
        df['ppo'] = ppo_data['ppo']
        df['sma_50'] = sma_50
        df['sma_200'] = sma_200
        df['bb_upper'] = bb_data['upper']
        df['bb_middle'] = bb_data['middle']
        df['bb_lower'] = bb_data['lower']

        return df

    def backtest(self, df):
        """
        Run backtest on OHLCV data

        Returns:
        - DataFrame with trades and performance
        - Dictionary with metrics (win rate, Sharpe, max drawdown, etc.)
        - bar_equity_curve: List with equity at each bar (for continuous chart display)
        - signals: List with buy/sell signal timestamps and prices
        """

        df = self.generate_signals(df)
        df['open'] = df['open'].astype(float)
        df['close'] = df['close'].astype(float)
        trades = []
        trade_equity_curve = [self.initial_capital]
        bar_equity = [self.initial_capital]
        entry_price = None
        entry_idx = None
        position_active = False
        pending_entry = False
        pending_exit = False
        last_closed_equity = self.initial_capital
        cost = self.params.get('cost_per_trade', 0.0005)

        for i in range(len(df)):
            signal = df['signal'].iloc[i]
            price_open = df['open'].iloc[i]
            price_close = df['close'].iloc[i]

            if pending_exit and position_active:
                exit_price = price_open
                exit_idx = i
                gross_pnl = (exit_price - entry_price) / entry_price
                gross_dollar = (last_closed_equity * self.position_size) * gross_pnl
                trade_value = (last_closed_equity * self.position_size) + gross_dollar
                net_dollar = gross_dollar - trade_value * cost
                net_pnl = net_dollar / (last_closed_equity * self.position_size)

                trades.append({
                    'entry_date': df.index[entry_idx],
                    'entry_price': entry_price,
                    'exit_date': df.index[i],
                    'exit_price': exit_price,
                    'return': net_pnl,
                    'pnl_dollar': net_dollar,
                    'days_held': round((exit_idx - entry_idx) / 7, 1)
                })

                last_closed_equity = last_closed_equity * (1 + net_pnl * self.position_size)
                trade_equity_curve.append(last_closed_equity)
                position_active = False
                pending_exit = False

            if pending_entry and not position_active:
                entry_price = price_open
                entry_idx = i
                position_active = True
                pending_entry = False

            if signal == 1 and not position_active and not pending_entry:
                pending_entry = True

            if (signal == -1 or i == len(df) - 1) and position_active and not pending_exit:
                pending_exit = True

            if position_active:
                unrealized_pnl = (price_close - entry_price) / entry_price * self.position_size
                bar_equity.append(last_closed_equity * (1 + unrealized_pnl))
            else:
                bar_equity.append(last_closed_equity)

        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            win_rate = wins / len(trades_df) if len(trades_df) > 0 else 0
            avg_return = trades_df['return'].mean()
            total_return = (trade_equity_curve[-1] - self.initial_capital) / self.initial_capital
            max_drawdown = self._calculate_max_drawdown(trade_equity_curve)
            sharpe_ratio = self._calculate_sharpe_ratio(bar_equity)

            metrics = {
                'total_trades': len(trades_df),
                'winning_trades': wins,
                'losing_trades': len(trades_df) - wins,
                'win_rate': win_rate,
                'avg_return_per_trade': avg_return,
                'total_return': total_return,
                'final_equity': trade_equity_curve[-1],
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'profit_factor': self._calculate_profit_factor(trades_df)
            }
        else:
            metrics = {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'avg_return_per_trade': 0,
                'total_return': 0,
                'final_equity': self.initial_capital,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'profit_factor': 0
            }

            trades_df = pd.DataFrame()

        # Extract signals for charting
        signals = []
        for i in range(len(df)):
            if df['signal'].iloc[i] == 1:
                signals.append({
                    'timestamp': df.index[i],
                    'price': float(df['close'].iloc[i]),
                    'type': 'buy'
                })
            elif df['signal'].iloc[i] == -1:
                signals.append({
                    'timestamp': df.index[i],
                    'price': float(df['close'].iloc[i]),
                    'type': 'sell'
                })

        return trades_df, metrics, bar_equity, signals

    @staticmethod
    def _calculate_max_drawdown(equity_curve):
        """Calculate maximum drawdown from equity curve"""
        peak = equity_curve[0]
        max_dd = 0
        for value in equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _calculate_sharpe_ratio(equity_curve, risk_free_rate=0.02):
        """Calculate Sharpe ratio (annualized for hourly data: 252 days × 6.5 hours/day = 1638)"""
        returns = np.diff(equity_curve) / equity_curve[:-1]
        if len(returns) == 0:
            return 0
        hourly_periods = 1638  # 252 trading days × 6.5 hours/day
        avg_return = np.mean(returns) * hourly_periods  # Annualized
        std_return = np.std(returns) * np.sqrt(hourly_periods)  # Annualized
        if std_return == 0:
            return 0
        return (avg_return - risk_free_rate) / std_return

    @staticmethod
    def _calculate_profit_factor(trades_df):
        """Calculate profit factor (gross profit / gross loss)"""
        if len(trades_df) == 0:
            return 0
        gross_profit = trades_df[trades_df['pnl_dollar'] > 0]['pnl_dollar'].sum()
        gross_loss = abs(trades_df[trades_df['pnl_dollar'] < 0]['pnl_dollar'].sum())
        if gross_loss == 0:
            return 0
        return gross_profit / gross_loss
