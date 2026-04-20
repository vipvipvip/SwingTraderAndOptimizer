#!/usr/bin/env python3
"""Example trading script using Alpaca APIs"""
import os
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

load_dotenv()

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')
base_url = os.getenv('ALPACA_BASE_URL')

# Initialize API
api = tradeapi.REST(api_key, secret_key, base_url)

# Get account info
account = api.get_account()
print(f"Account: {account.id}")
print(f"Buying Power: ${account.buying_power}")
print(f"Cash: ${account.cash}")

# Example: Place a market order
# Uncomment to execute:
# order = api.submit_order(
#     symbol='AAPL',
#     qty=1,
#     side='buy',
#     type='market',
#     time_in_force='day'
# )
# print(f"Order submitted: {order.id}")

# Example: Get current price
# data = api.get_bars('AAPL', '1D')
# latest = data.iloc[-1]
# print(f"AAPL: ${latest.c}")

print("\nTrading API ready. See comments for example trades.")
