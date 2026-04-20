"""Debug script to visualize signals and indicators"""
import pandas as pd
from data_fetcher import load_data
from strategies import SPYSwingTradingStrategy

# Load data
df = load_data('SPY', '1Day')
if df is None:
    print("No cached data found")
    exit(1)

# Generate signals
strategy = SPYSwingTradingStrategy()
df_signals = strategy.generate_signals(df)

# Find recent bars with interesting signals
print("\n" + "="*80)
print("RECENT SIGNALS (Last 50 bars)")
print("="*80 + "\n")

# Show last 50 bars with key indicators
recent = df_signals.tail(50).copy()

print(f"{'Date':<12} {'Close':<10} {'MACD':<8} {'MACD.H':<8} {'SMA50':<10} {'SMA200':<10} {'Signal':<8}")
print("-" * 80)

for idx, row in recent.iterrows():
    date = idx.strftime('%Y-%m-%d')
    close = f"{row['close']:.2f}"
    macd = f"{row['macd']:.3f}" if pd.notna(row['macd']) else "N/A"
    macd_h = f"{row['macd_signal']:.3f}" if pd.notna(row['macd_signal']) else "N/A"
    sma50 = f"{row['sma_50']:.2f}" if pd.notna(row['sma_50']) else "N/A"
    sma200 = f"{row['sma_200']:.2f}" if pd.notna(row['sma_200']) else "N/A"
    signal = "LONG" if row['signal'] == 1 else ("EXIT" if row['signal'] == -1 else "HOLD")

    print(f"{date:<12} {close:<10} {macd:<8} {macd_h:<8} {sma50:<10} {sma200:<10} {signal:<8}")

# Count signal occurrences
print("\n" + "="*80)
print("SIGNAL SUMMARY")
print("="*80)
print(f"Total Long Signals: {(df_signals['signal'] == 1).sum()}")
print(f"Total Exit Signals: {(df_signals['signal'] == -1).sum()}")
print(f"Total Hold Signals: {(df_signals['signal'] == 0).sum()}")

# Find specific indicators firing
print("\n" + "="*80)
print("INDICATOR ANALYSIS (Last 100 bars)")
print("="*80 + "\n")

df_recent = df_signals.tail(100).copy()

# MACD histogram crossovers
macd_cross = []
for i in range(1, len(df_recent)):
    if (df_recent['macd'].iloc[i-1] <= df_recent['macd_signal'].iloc[i-1] and
        df_recent['macd'].iloc[i] > df_recent['macd_signal'].iloc[i]):
        macd_cross.append(df_recent.index[i].strftime('%Y-%m-%d'))

print(f"MACD Bullish Crossovers (last 100 bars): {len(macd_cross)}")
if macd_cross:
    for date in macd_cross[-5:]:
        print(f"  {date}")

# SMA 50/200 crossovers
sma_cross = []
for i in range(1, len(df_recent)):
    if (df_recent['sma_50'].iloc[i-1] <= df_recent['sma_200'].iloc[i-1] and
        df_recent['sma_50'].iloc[i] > df_recent['sma_200'].iloc[i]):
        sma_cross.append(df_recent.index[i].strftime('%Y-%m-%d'))

print(f"\n50/200 Bullish Crossovers (last 100 bars): {len(sma_cross)}")
if sma_cross:
    for date in sma_cross[-5:]:
        print(f"  {date}")

print("\n" + "="*80)
