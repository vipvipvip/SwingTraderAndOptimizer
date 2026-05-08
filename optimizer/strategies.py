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
        self.position_size = position_size  # % of capital per trade
        self.name = "SPY Swing Trading (MACD + EMA/SMA Crossover + BB)"
        # Default parameters (can be overridden)
        self.params = params or {
            'ema_fast': 10,
            'sma_medium': 40,
            'min_signals': 2,  # Require 2-of-4 signals by default
        }

    def generate_signals(self, df):
        """
        Generate entry/exit signals based on:
        - MACD + signal line crossover
        - EMA10/SMA40 crossover confirmation (fast/slow momentum)
        - 50/200 day uptrend confirmation
        - Bollinger Bands positioning

        Returns DataFrame with 'signal' column: 1=long, -1=exit, 0=hold
        """

        df = df.copy()

        # Calculate indicators
        macd_data = calculate_macd(df['close'])
        ppo_data = calculate_ppo(df['close'])
        sma_50 = calculate_sma(df['close'], 50)
        sma_200 = calculate_sma(df['close'], 200)
        ema_momentum = calculate_ema(df['close'], self.params['ema_fast'])
        sma_trend = calculate_sma(df['close'], self.params['sma_medium'])
        bb_data = calculate_bollinger_bands(df['close'], period=20)

        # Detect crossovers
        crossover_50_200 = calculate_crossover(sma_50, sma_200)
        crossover_momentum = calculate_crossover(ema_momentum, sma_trend)

        # Initialize signals
        signals = pd.Series(0, index=df.index)
        last_signal = 0  # Track last non-zero signal to enforce alternation

        # Entry conditions
        for i in range(200, len(df)):  # Start after 200 period for all indicators

            # Bollinger Bands conditions
            price = df['close'].iloc[i]
            bb_lower = bb_data['lower'].iloc[i]
            bb_upper = bb_data['upper'].iloc[i]
            sma_50_val = sma_50.iloc[i]
            sma_200_val = sma_200.iloc[i]

            # Count entry signals (need 2 or more)
            signal_count = 0

            # Signal 1: MACD bullish (histogram crosses above 0)
            macd_bullish = (macd_data['histogram'].iloc[i-1] <= 0 and
                           macd_data['histogram'].iloc[i] > 0)
            if macd_bullish:
                signal_count += 1

            # Signal 2: EMA/SMA bullish (EMA crosses above SMA)
            ema_bullish = (ema_momentum.iloc[i-1] <= sma_trend.iloc[i-1] and
                          ema_momentum.iloc[i] > sma_trend.iloc[i])
            if ema_bullish:
                signal_count += 1

            # Signal 3: Uptrend (Price > SMA50 > SMA200)
            uptrend = (price > sma_50_val and sma_50_val > sma_200_val)
            if uptrend:
                signal_count += 1

            # Signal 4: Price near lower Bollinger Band (pullback in uptrend)
            bb_condition = price <= bb_lower * 1.05
            if bb_condition:
                signal_count += 1

            # Entry: min_signals or more required (and last signal was not a buy)
            min_sigs = self.params.get('min_signals', 2)
            if signal_count >= min_sigs and last_signal != 1:
                signals.iloc[i] = 1  # Long signal
                last_signal = 1

            # Exit conditions: only if we're in a position (last signal was buy)
            elif last_signal == 1:
                # Exit 1: MACD bearish crossover (histogram crosses below 0)
                macd_bearish = (macd_data['histogram'].iloc[i-1] >= 0 and
                               macd_data['histogram'].iloc[i] < 0)

                # Exit 2: EMA/SMA bearish crossover (momentum loss)
                ema_bearish = (ema_momentum.iloc[i-1] >= sma_trend.iloc[i-1] and
                              ema_momentum.iloc[i] < sma_trend.iloc[i])

                # Exit 3: Price breaks below lower Bollinger Band
                bb_break = price < bb_lower

                # Exit 4: Stop loss at 2% below entry (simple)
                # (Would need to track entry price, simplified for now)

                if macd_bearish or ema_bearish or bb_break:
                    signals.iloc[i] = -1  # Exit signal
                    last_signal = -1

        df['signal'] = signals
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal']
        df['ppo'] = ppo_data['ppo']
        df['sma_50'] = sma_50
        df['sma_200'] = sma_200
        df['ema_momentum'] = ema_momentum
        df['sma_trend'] = sma_trend
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
        df['close'] = df['close'].astype(float)
        trades = []
        trade_equity_curve = [self.initial_capital]  # Equity curve updated only at trade closes
        bar_equity_curve = [self.initial_capital]    # Equity curve at each bar (mark-to-market)
        entry_price = None
        entry_idx = None
        position_active = False
        last_closed_equity = self.initial_capital  # Track equity after last closed trade

        for i in range(len(df)):
            signal = df['signal'].iloc[i]
            price = df['close'].iloc[i]
            date = df.index[i]

            # Entry signal
            if signal == 1 and not position_active:
                entry_price = price
                entry_idx = i
                position_active = True

            # Mark-to-market equity at each bar (for continuous curve)
            if position_active:
                # Unrealized P&L on open position
                unrealized_pnl = (price - entry_price) / entry_price * self.position_size
                current_bar_equity = last_closed_equity * (1 + unrealized_pnl)
            else:
                current_bar_equity = last_closed_equity

            bar_equity_curve.append(current_bar_equity)

            # Exit signal or end of data
            if (signal == -1 or i == len(df) - 1) and position_active:
                exit_price = price
                exit_idx = i

                # Calculate trade P&L
                pnl = (exit_price - entry_price) / entry_price
                shares = (self.initial_capital * self.position_size) / entry_price
                pnl_dollar = shares * (exit_price - entry_price)

                trades.append({
                    'entry_date': df.index[entry_idx],
                    'entry_price': entry_price,
                    'exit_date': date,
                    'exit_price': exit_price,
                    'return': pnl,
                    'pnl_dollar': pnl_dollar,
                    'days_held': exit_idx - entry_idx
                })

                # Update equity after trade closes (for metrics calculation)
                last_closed_equity = last_closed_equity * (1 + pnl * self.position_size)
                trade_equity_curve.append(last_closed_equity)

                position_active = False

        # Calculate metrics using trade_equity_curve (for consistency with trade-based returns)
        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            win_rate = wins / len(trades_df) if len(trades_df) > 0 else 0
            avg_return = trades_df['return'].mean()
            total_return = (trade_equity_curve[-1] - self.initial_capital) / self.initial_capital
            max_drawdown = self._calculate_max_drawdown(trade_equity_curve)
            sharpe_ratio = self._calculate_sharpe_ratio(trade_equity_curve)

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
            if df['signal'].iloc[i] == 1:  # Buy signal
                signals.append({
                    'timestamp': df.index[i],
                    'price': df['close'].iloc[i],
                    'type': 'buy'
                })
            elif df['signal'].iloc[i] == -1:  # Sell signal
                signals.append({
                    'timestamp': df.index[i],
                    'price': df['close'].iloc[i],
                    'type': 'sell'
                })

        # Return bar_equity_curve (mark-to-market) for charting, but metrics from trade_equity_curve
        return trades_df, metrics, bar_equity_curve, signals

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
