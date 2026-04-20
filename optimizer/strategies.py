"""Strategy definitions and signal generation"""
import pandas as pd
import numpy as np
from indicators import (
    calculate_macd, calculate_ppo, calculate_sma,
    calculate_bollinger_bands, calculate_crossover
)


class SPYSwingTradingStrategy:
    """
    SPY Swing Trading Strategy
    - Entry: MACD + crossover confirmation + Bollinger Bands
    - Exit: Opposite signals or stop loss
    """

    def __init__(self, initial_capital=100000, position_size=0.1):
        self.initial_capital = initial_capital
        self.position_size = position_size  # % of capital per trade
        self.name = "SPY Swing Trading (MACD + Crossover + BB)"

    def generate_signals(self, df):
        """
        Generate entry/exit signals based on:
        - MACD + signal line crossover
        - 50/200 day crossover (10/40 also available)
        - Bollinger Bands positioning

        Returns DataFrame with 'signal' column: 1=long, -1=exit, 0=hold
        """

        df = df.copy()

        # Calculate indicators
        macd_data = calculate_macd(df['close'])
        ppo_data = calculate_ppo(df['close'])
        sma_50 = calculate_sma(df['close'], 50)
        sma_200 = calculate_sma(df['close'], 200)
        sma_10 = calculate_sma(df['close'], 10)
        sma_40 = calculate_sma(df['close'], 40)
        bb_data = calculate_bollinger_bands(df['close'], period=20)

        # Detect crossovers
        crossover_50_200 = calculate_crossover(sma_50, sma_200)
        crossover_10_40 = calculate_crossover(sma_10, sma_40)

        # Initialize signals
        signals = pd.Series(0, index=df.index)

        # Entry conditions
        for i in range(200, len(df)):  # Start after 200 period for all indicators

            # MACD entry signal: histogram crosses above 0 (bullish)
            macd_bullish = (macd_data['histogram'].iloc[i-1] <= 0 and
                           macd_data['histogram'].iloc[i] > 0)

            # Bollinger Bands conditions
            price = df['close'].iloc[i]
            bb_lower = bb_data['lower'].iloc[i]
            bb_upper = bb_data['upper'].iloc[i]
            sma_50_val = sma_50.iloc[i]
            sma_200_val = sma_200.iloc[i]

            # UPTREND REQUIREMENT: Price > SMA50 > SMA200 (all in alignment)
            uptrend = (price > sma_50_val and sma_50_val > sma_200_val)

            # Bollinger Bands: Price near lower band (pullback in uptrend)
            bb_condition = price <= bb_lower * 1.05

            # Entry: MACD bullish + Uptrend + Bollinger Bands pullback
            # Only enter when: trend is UP, MACD turns bullish, price pulls back to lower BB
            if macd_bullish and uptrend and bb_condition:
                signals.iloc[i] = 1  # Long signal

            # Exit conditions
            if i > 0 and signals.iloc[i-1] == 1:
                # Exit 1: MACD bearish crossover (histogram crosses below 0)
                macd_bearish = (macd_data['histogram'].iloc[i-1] >= 0 and
                               macd_data['histogram'].iloc[i] < 0)

                # Exit 2: Price breaks below lower Bollinger Band
                bb_break = price < bb_lower

                # Exit 3: Stop loss at 2% below entry (simple)
                # (Would need to track entry price, simplified for now)

                if macd_bearish or bb_break:
                    signals.iloc[i] = -1  # Exit signal

        df['signal'] = signals
        df['macd'] = macd_data['macd']
        df['macd_signal'] = macd_data['signal']
        df['ppo'] = ppo_data['ppo']
        df['sma_50'] = sma_50
        df['sma_200'] = sma_200
        df['sma_10'] = sma_10
        df['sma_40'] = sma_40
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
        """

        df = self.generate_signals(df)
        trades = []
        equity_curve = [self.initial_capital]
        entry_price = None
        entry_idx = None
        position_active = False

        for i in range(len(df)):
            signal = df['signal'].iloc[i]
            price = df['close'].iloc[i]
            date = df.index[i]

            # Entry signal
            if signal == 1 and not position_active:
                entry_price = price
                entry_idx = i
                position_active = True

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

                # Update equity
                current_equity = equity_curve[-1] * (1 + pnl)
                equity_curve.append(current_equity)

                position_active = False

        # Calculate metrics
        if trades:
            trades_df = pd.DataFrame(trades)
            wins = (trades_df['return'] > 0).sum()
            win_rate = wins / len(trades_df) if len(trades_df) > 0 else 0
            avg_return = trades_df['return'].mean()
            total_return = (equity_curve[-1] - self.initial_capital) / self.initial_capital
            max_drawdown = self._calculate_max_drawdown(equity_curve)
            sharpe_ratio = self._calculate_sharpe_ratio(equity_curve)

            metrics = {
                'total_trades': len(trades_df),
                'winning_trades': wins,
                'losing_trades': len(trades_df) - wins,
                'win_rate': win_rate,
                'avg_return_per_trade': avg_return,
                'total_return': total_return,
                'final_equity': equity_curve[-1],
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

        return trades_df, metrics, equity_curve

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
        """Calculate Sharpe ratio (annualized)"""
        returns = np.diff(equity_curve) / equity_curve[:-1]
        if len(returns) == 0:
            return 0
        avg_return = np.mean(returns) * 252  # Annualized
        std_return = np.std(returns) * np.sqrt(252)  # Annualized
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
