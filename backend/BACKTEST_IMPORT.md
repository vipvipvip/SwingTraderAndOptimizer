# Backtest CSV Import Guide

This guide explains how to import backtest trade CSVs from Phase 1 and populate the equity curves on the dashboard.

## Overview

The equity curve visualization requires two datasets:
1. **Backtest**: Historical equity progression from backtested trades
2. **Live**: Current equity from live trading on Alpaca

This document covers importing backtested equity curves from Phase 1's backtest output files.

## Data Format

Phase 1 generates trade CSV files with the following structure:

```
,entry_date,entry_price,exit_date,exit_price,return,pnl_dollar,days_held
0,2025-07-25 04:00:00+00:00,637.02,2025-08-29 04:00:00+00:00,645.03,0.012574173495337652,125.74173495337652,25
1,2025-09-10 04:00:00+00:00,652.28,2026-04-17 04:00:00+00:00,710.06,0.08858159072790822,885.8159072790821,151
```

The import process reconstructs daily equity snapshots from these trades:
- Starting equity: $100,000 (configurable)
- After each trade closes, equity is updated: `new_equity = old_equity * (1 + return%)`

## Commands

### Import Single Ticker

```bash
php artisan backtest:import SPY
```

By default, auto-detects the latest SPY backtest CSV in Phase 1's `backtest_results/` folder.

To specify a custom CSV path:

```bash
php artisan backtest:import SPY --csv-path="/path/to/file.csv"
```

To use a different initial capital (default $100,000):

```bash
php artisan backtest:import SPY --initial-capital=50000
```

### Import All Available Backtests

```bash
php artisan backtest:import-all
```

This scans `c:/data/Program Files/Alpaca-API-Trading/backtest_results/` and imports all `*_trades_*.csv` files.

To scan a different directory:

```bash
php artisan backtest:import-all --csv-dir="/custom/path"
```

## Output

After import, the `equity_snapshots` table is populated with daily equity values:

```
id | ticker_id | snapshot_date | equity_value | snapshot_type | source
1  | 1         | 2025-08-29   | 101257.42    | backtest      | csv_import
2  | 1         | 2026-04-17   | 110226.96    | backtest      | csv_import
```

## Verification

### Via API

```bash
curl http://localhost:8000/api/v1/equity/SPY
```

Expected response:

```json
{
  "backtest": [
    {"date": "2025-08-29T00:00:00.000000Z", "value": 101257.42},
    {"date": "2026-04-17T00:00:00.000000Z", "value": 110226.96}
  ],
  "live": []
}
```

### Via Dashboard

Open `http://localhost:5173` → **Equity Curve - SPY**

You should see:
- **Grey dashed line**: Backtest equity curve
- **Green solid line**: Live equity (empty until trades execute)

## Reset/Re-import

To clear existing backtest data for a ticker:

```bash
php artisan backtest:import SPY
```

This automatically clears old backtest snapshots for that ticker before importing new ones.

To manually clear (database only):

```bash
sqlite3 "c:/data/Program Files/Alpaca-API-Trading/optimized_params/strategy_params.db"
DELETE FROM equity_snapshots WHERE ticker_id=1 AND snapshot_type='backtest';
```

## Troubleshooting

### "CSV file not found"

Ensure the CSV exists in Phase 1's backtest_results folder:

```bash
ls "c:/data/Program Files/Alpaca-API-Trading/backtest_results/"
```

### "No trades found in CSV"

The CSV may be corrupted or empty. Check the file:

```bash
head -5 "path/to/file.csv"
```

Should show header row and at least one trade row.

### Dashboard shows only backtest, no live

This is normal until live trades execute. Live equity snapshots are automatically added by:
- `EquityService->snapshotAccountEquity()` daily at market close
- Dashboard P&L is calculated from `live_trades` table as trades execute

## Generating New Backtests (Phase 1)

To generate fresh backtest CSVs, run Phase 1's optimizer:

```bash
cd "c:/data/Program Files/Alpaca-API-Trading"
python nightly_optimizer.py
```

This runs parameter optimization for SPY, QQQ, IWM and updates the database. To export trades for charting:

```bash
# Within Python
from parameter_optimizer import ParameterOptimizer
from data_fetcher import load_data

symbol = 'SPY'
df = load_data(symbol, '1Day')
optimizer = ParameterOptimizer(df)
trades, metrics, equity = optimizer._backtest_with_params(best_params)

# Export trades
import pandas as pd
trades_df = pd.DataFrame(trades)
trades_df.to_csv(f'{symbol}_trades.csv')
```

## Schedule

Backtests are regenerated nightly at 2 AM when the optimizer runs. To import the latest results:

```bash
php artisan backtest:import-all
```

Add this to your monitoring routine or cron job post-optimization.
