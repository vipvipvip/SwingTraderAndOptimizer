#!/usr/bin/env python3
"""Test Trading API connection"""
import os
from dotenv import load_dotenv
import alpaca_trade_api as tradeapi

load_dotenv()

api_key = os.getenv('ALPACA_API_KEY')
secret_key = os.getenv('ALPACA_SECRET_KEY')
base_url = os.getenv('ALPACA_BASE_URL')

# Initialize API
api = tradeapi.REST(api_key, secret_key, base_url)

print("=" * 50)
print("TRADING API TEST")
print("=" * 50)

# Test 1: Get Account Info
account = api.get_account()
print(f"\n[OK] Account Connected")
print(f"  Account ID: {account.id}")
print(f"  Buying Power: ${account.buying_power}")
print(f"  Portfolio Value: ${account.portfolio_value}")
print(f"  Cash: ${account.cash}")

# Test 2: Get Account Status
print(f"\n[OK] Account Status")
print(f"  Status: {account.status}")
print(f"  Day Trade Count: {account.daytrade_count}")

print("\n[SUCCESS] Trading API connection working!")
