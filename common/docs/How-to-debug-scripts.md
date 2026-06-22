# How to Debug Python Scripts

VSCode's launch mode doesn't work with Python 3.14 (bundled debugpy is too old).
Use the **attach** workflow instead.

## Setup

Each venv has `debugpy` installed:
- `stock-analyzer/.venv`
- `scanner/.venv`
- `swingtrader/services/optimizer/venv`

## Steps

1. Set breakpoints in VSCode
2. Run the script from terminal with `--wait-for-client`:

```bash
<venv>/bin/python -m debugpy --listen 5678 --wait-for-client <script> [args]
```

3. In VSCode, select **"Attach: Stock Analyzer"** from the Run & Debug dropdown and press **F5**

## Script Commands

### Stock Analyzer
```bash
# Valuation (Alpaca prices)
stock-analyzer/.venv/bin/python -m debugpy --listen 5678 --wait-for-client stock-analyzer/populate_stock_analyzer.py --valuation

# Fundamentals (stockanalysis.com scrape)
stock-analyzer/.venv/bin/python -m debugpy --listen 5678 --wait-for-client stock-analyzer/populate_stock_analyzer.py --fundamentals

# Single ticker test
stock-analyzer/.venv/bin/python -m debugpy --listen 5678 --wait-for-client stock-analyzer/populate_stock_analyzer.py --valuation --symbol AAPL

# Company names (one-time)
stock-analyzer/.venv/bin/python -m debugpy --listen 5678 --wait-for-client stock-analyzer/populate_company_names.py
```

### Scanner
```bash
# Populate tickers
scanner/.venv/bin/python -m debugpy --listen 5678 --wait-for-client scanner/services/scripts/populate_tickers.py --timeframe week --workers 1

# Compute indicators
scanner/.venv/bin/python -m debugpy --listen 5678 --wait-for-client scanner/services/scripts/compute_indicators.py --timeframe week --workers 1
```

### Optimizer
```bash
swingtrader/services/optimizer/venv/bin/python -m debugpy --listen 5678 --wait-for-client swingtrader/services/optimizer/<script>.py
```

## Notes

- Port `5678` is the default — change it if already in use
- The script blocks until VSCode attaches
- Use `--workers 1` when debugging to avoid threading confusion
- All commands run from the project root
