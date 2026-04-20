"""Technical indicators for swing trading strategies"""
import numpy as np
import pandas as pd


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calculate MACD (Moving Average Convergence Divergence)"""
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    })


def calculate_ppo(prices, fast=12, slow=26, signal=9):
    """Calculate PPO (Percentage Price Oscillator)"""
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    ppo = ((ema_fast - ema_slow) / ema_slow) * 100
    signal_line = ppo.ewm(span=signal).mean()
    histogram = ppo - signal_line

    return pd.DataFrame({
        'ppo': ppo,
        'signal': signal_line,
        'histogram': histogram
    })


def calculate_sma(prices, period):
    """Calculate Simple Moving Average"""
    return prices.rolling(window=period).mean()


def calculate_bollinger_bands(prices, period=20, num_std=2):
    """Calculate Bollinger Bands"""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)

    return pd.DataFrame({
        'upper': upper,
        'middle': sma,
        'lower': lower,
        'std': std
    })


def calculate_crossover(short_ma, long_ma):
    """Detect crossovers between two moving averages
    Returns 1 for bullish crossover, -1 for bearish crossover, 0 for no crossover
    """
    crossovers = np.zeros(len(short_ma))

    for i in range(1, len(short_ma)):
        if short_ma.iloc[i-1] <= long_ma.iloc[i-1] and short_ma.iloc[i] > long_ma.iloc[i]:
            crossovers[i] = 1  # Bullish crossover
        elif short_ma.iloc[i-1] >= long_ma.iloc[i-1] and short_ma.iloc[i] < long_ma.iloc[i]:
            crossovers[i] = -1  # Bearish crossover

    return pd.Series(crossovers, index=short_ma.index)
