# Alpaca API Trading Project

Connected to Alpaca paper trading account with both Trading and Market Data APIs.

## Setup

```bash
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt
```

## Configuration

Create a `.env` file with your Alpaca credentials:
```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## Test Scripts

- `test_trading_api.py` - Test Trading API connection and account details
- `test_market_data_api.py` - Test Market Data API for stocks and prices

Run tests:
```bash
python test_trading_api.py
python test_market_data_api.py
```

## Account Details

- **Account ID:** b893cbdb-5b18-44b3-8a55-122328314489
- **Buying Power:** $167,661.96
- **Portfolio Value:** $83,830.98
- **Status:** ACTIVE (Paper Trading)

## Next Steps

1. Build trading strategies
2. Create buy/sell order logic
3. Implement real-time data streaming
4. Add portfolio analysis tools
