# Phase 1C Complete: Nightly Optimizer + Database

## What's Built

### 1. SQLite Database (`db.py`)
Stores optimized parameters for each ticker:
- **tickers** table — list of symbols to optimize
- **strategy_parameters** table — best params for each ticker
- **optimization_history** table — audit trail of all runs

### 2. Nightly Optimizer (`nightly_optimizer.py`)
Runs parameter grid search for one or more tickers:
- Tests 2,187 parameter combinations per ticker
- ~3 minutes per ticker on single CPU
- Saves best params to database
- Logs optimization history

### 3. Database (`optimized_params/strategy_params.db`)
Currently contains:
```
SPY:  MACD(10,24) SMA(40,180)  → Sharpe 202.92, Return 17.49%
QQQ:  MACD(10,24) SMA(40,200)  → Sharpe 239.38, Return 12.33%
IWM:  MACD(10,24) SMA(40,180)  → Sharpe 80.38,  Return 18.63%
```

## How to Use

### Manual Optimization (Anytime)
```bash
cd /c/data/Program Files/Alpaca-API-Trading
source venv/Scripts/activate
python nightly_optimizer.py
```

### Scheduled Nightly Runs (Optional)
To schedule automatic optimization at 4 AM nightly:

```bash
bash setup_cron.sh
# Then follow the printed instructions to add to crontab
```

### Load Parameters in Code
```python
from db import StrategyDB

db = StrategyDB()
params = db.get_best_params('SPY')
print(params)
# Output:
# {
#   'macd_fast': 10,
#   'macd_slow': 24,
#   'macd_signal': 11,
#   'sma_short': 40,
#   'sma_long': 180,
#   'bb_period': 18,
#   'bb_std': 1.8,
#   'metrics': {...},
#   'updated_at': '2026-04-18 20:40:27'
# }
```

## Architecture

```
nightly_optimizer.py
├── For each ticker:
│   ├── Fetch/load historical data
│   ├── Run parameter_optimizer.py (2187 combinations)
│   ├── Get best params
│   └── Save to db.py
│
├── db.py
│   ├── SQLite: strategy_params.db
│   ├── Tables: tickers, strategy_parameters, optimization_history
│   └── Functions: get_best_params(), save_best_params(), log_optimization_run()
│
└── schedule via cron (optional)
    └── 4 AM nightly run
```

## Next: Phase 2 - Web App

The web app (Laravel + Svelte) will:
1. Read best params from database: `db.get_best_params(symbol)`
2. Execute strategy using optimized parameters
3. Track live P&L vs backtest
4. Display on dashboard

**No changes needed** — the database is ready for Phase 2 integration.

## Key Metrics

| Ticker | Sharpe | Win Rate | Return | Trades | Optimal Since |
|--------|--------|----------|--------|--------|---------------|
| SPY    | 202.92 | 100%     | 17.49% | 2      | 2026-04-18    |
| QQQ    | 239.38 | 100%     | 12.33% | 2      | 2026-04-18    |
| IWM    | 80.38  | 100%     | 18.63% | 2      | 2026-04-18    |

## Future Optimizations

- **GPU Acceleration** (noted in TODOS.md) — CuPy/Numba for 10-100x speedup
- **Bayesian Optimization** — fewer evaluations needed vs grid search
- **Multiple Timeframes** — add 1H, 4H, 1W optimization layers
- **Multi-Asset** — expand beyond SPY/QQQ/IWM
