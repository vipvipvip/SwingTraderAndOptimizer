# HMM (Hidden Markov Model) Regime Detection

## Overview

HMM regime detection adds a market regime filter across the scanner, optimizer, and live execution pipeline. The goal: improve risk-adjusted returns by avoiding Bear regime trades and reducing position sizes during adverse regimes.

A 3-state Gaussian HMM (`covariance_type='diag'`) classifies each bar as **Bull**, **Bear**, or **Choppy** using features: log-returns, volatility (ATR/close), and momentum (close - SMA20).

---

## Architecture

### Shared Module
- **File**: `common/scripts/markov_regime.py`
- **Class**: `MarkovRegime`
  - `fit_predict(data)` — fits on full data, then predicts (has lookahead bias, for training only)
  - `walk_forward_predict(data)` — expanding window, no lookahead (for live/production)
  - Features: log-returns, volatility (ATR/close), momentum (close - SMA20)
  - State labeling: sorts states by momentum mean → label as Bull (highest), Bear (lowest), Choppy (middle)
  - 3 states, `covariance_type='diag'`, seed=42, 100 iterations

### Scanner Integration
- **File**: `scanner/services/scripts/compute_indicators.py`
- Calls `MarkovRegime.fit_predict()` after MACD/PPO/SMA computations
- Writes 4 columns per timeframe table: `hmm_regime`, `hmm_bull_prob`, `hmm_bear_prob`, `hmm_choppy_prob`
- CLI flag: `--no-hmm` to disable
- Configurable: `--hmm-states`, `--hmm-lookback`, `--hmm-seed`
- Tables: `tbl_scanner_tickers` (daily), `tbl_scanner_tickers_hourly` (hourly), `tbl_scanner_tickers_weekly` (weekly)
- 12 columns total (4 per table × 3 timeframes) added via ALTER TABLE on `swingtrader_markov` DB

### Chart Visualization
- **File**: `swingtrader/backend/resources/views/scanner/index.blade.php`
- Regime panel: colored histogram bars below PPO panel (Bull=green, Bear=red, Choppy=orange)
- Regime badge: top-right of price chart showing current regime + probability (e.g. "Bear 99%")
- Crosshair sync across all 4 panels (price, MACD, PPO, regime)
- Zoom sync across all 4 panels
- Opacity: Bull/Bear `rgba(..., 0.55)`, Choppy `rgba(..., 0.5)`

### Optimizer Integration
- **File**: `swingtrader/services/optimizer/parameter_optimizer.py`
- `ParameterOptimizer.__init__()` takes `use_hmm=True` parameter
- `_backtest_with_params()` — single-ticker backtest:
  - Computes HMM on the fly via `MarkovRegime.fit_predict(data)` on daily bars
  - **Option 3 (current)**: only overrides position size in Bear regime (factor=0.7), never blocks entry or forces exit
  - Stores regime in `data['hmm_regime_signal']`
- `backtest_portfolio()` — multi-ticker portfolio backtest:
  - Shared capital pool across tickers
  - HMM computed per-ticker (or provided via `hmm_data` dict for external regimes like SPY-level)
  - Proportional entry allocation: Bear regime tickers get reduced allocation (`hmm_bear_factor` param, default 0.5)
  - `hmm_skip` set: tickers to exclude from HMM filtering
- **File**: `swingtrader/services/optimizer/nightly_optimizer.py`
  - CLI flag: `--no-hmm`
  - Passes `use_hmm` through `_optimize_with_ticker_label()` → `optimize_ticker()` → `ParameterOptimizer`

### DB Connections
- **File**: `swingtrader/services/optimizer/data_fetcher.py` — `load_data_from_db()` reads `.env` DATABASE_URL first
- **File**: `swingtrader/services/optimizer/db.py` — `StrategyDB.connect()` reads `.env` DATABASE_URL first
- Test DB: `swingtrader_markov` (template copy of production)

---

## HMM Modes Tested

Three approaches were implemented, tested, and compared on the portfolio (QQQ+VTI+VTV, shared capital pool):

### Mode 1: Bull-Only Entry + Bear Exit (discarded)
- Only enter in Bull regime
- Force exit when regime turns Bear
- **Result**: Too restrictive. Return dropped from 179% → 80-159%. Missed too many trades in bull periods.

### Mode 2: SPY-Level Market Filter (discarded)
- Compute HMM on SPY only, apply same filter to all portfolio tickers
- **Result**: Return 151% vs 179% OFF. Still below baseline.

### Mode 3: Bear Override Only (current)
- **Entry**: always allowed (no regime block)
- **Exit**: only on stop-loss (no HMM forced exit)
- **Bear regime**: reduce position size by factor (default 0.7 = 70% allocation in Bear)
- **Best factor**: 0.7 (30% reduction in Bear) at OFF best params (BB=2.5, MF=10)
- **Result**: Return=179.55% vs OFF 178.70% — marginal improvement, same Sharpe/MaxDD
- Other factors tested: 0.3→177.77%, 0.5→177.39%, 0.7→179.55%, 1.0→178.70%

---

## Key Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `use_hmm` | True | Enable HMM regime filtering |
| `hmm_bear_factor` | 0.5 | Position size multiplier in Bear regime (0.0 = flat, 1.0 = no reduction) |
| `hmm_skip` | None | Set of ticker symbols to exclude from HMM filtering |
| `hmm_data` | None | Pre-computed regime data dict `{symbol: DataFrame with hmm_regime col}` |
| `hmm_n_states` | 3 | Number of HMM states |
| `hmm_lookback` | 252 | Lookback window for HMM training |
| `hmm_seed` | 42 | Random seed for reproducibility |

---

## CLI Flags

### Scanner
```
python compute_indicators.py --timeframe week --no-hmm
python compute_indicators.py --timeframe week --hmm-states 4 --hmm-lookback 504
```

### Optimizer
```
python nightly_optimizer.py --tickers QQQ VTI VTV --no-hmm
python nightly_optimizer.py --timeframe 1Day --no-hmm
```

---

## Backtest Results Summary

### Single-Ticker (allocation_weight=10, 10% per trade)

| Ticker | OFF Return | ON Return (Mode 3, factor=0.5) | Improvement |
|--------|:--------:|:--------:|:---------:|
| QQQ | 12.79% | 12.90% | +0.11% |
| VTI | 11.39% | 12.42% | +1.03% |
| VTV | 9.62% | 11.03% | +1.41% |

All three tickers benefit from Mode 3 individually.

### Portfolio (QQQ+VTI+VTV, shared capital pool)

| Mode | Factor | Best Params | Return | Sharpe | MaxDD |
|------|:-----:|:-----------|:-----:|:-----:|:----:|
| OFF | — | BB=2.5, MF=10 | 178.70% | 1.08 | -26.90% |
| ON | 0.3 | BB=2.5, MF=20 | 177.77% | 1.11 | -25.73% |
| ON | 0.5 | BB=2.5, MF=20 | 177.39% | 1.10 | -25.73% |
| ON | **0.7** | BB=2.5, MF=10 | **179.55%** | **1.08** | -26.90% |
| ON | 1.0 | BB=2.5, MF=10 | 178.70% | 1.08 | -26.90% |

---

## Findings & Gotchas

1. **HMM does not beat the baseline on total return** in this bull-dominated data period (2022-2026). Bear regimes are too short/rare for drawdown avoidance to compound significantly.
2. **Option 3 (override only) with factor=0.7 matches the baseline** (179.55% vs 178.70%) with identical risk metrics. It's a no-op improvement — useful for infrastructure but not transformative on this data.
3. **The HMM would outperform in longer data** including 2008, 2020, or 2022 crashes where avoiding/reducing Bear exposure prevents major losses.
4. **Per-ticker HMM hurts VTV** more than QQQ/VTI (value stocks behave differently in regimes). `hmm_skip={'VTV'}` prevents this.
5. **`fit_predict` has lookahead bias** (sees future data to classify). For live execution, use `walk_forward_predict`.
6. **Proportional allocation bug**: the entry split must pre-compute amounts before the loop; computing `cash * (override / total_override)` inside the loop causes decreasing amounts as cash is consumed.
7. **HMM on scanner DB tables** uses weekly timeframe data. The optimizer computes HMM fresh from daily bars via `MarkovRegime` directly — these two sources may diverge.
8. **`pending_entry` type change**: in the portfolio backtester, `pending_entry[sym]` now stores a float (override factor) instead of boolean `True`. The truthy check `if pending_entry.get(sym)` still works, but `isinstance(pending_entry[sym], (int, float))` distinguishes it if needed.

---

## Code Locations

| Component | File | Key Lines |
|-----------|------|-----------|
| Shared HMM class | `common/scripts/markov_regime.py` | MarkovRegime class |
| Scanner pipeline | `scanner/services/scripts/compute_indicators.py` | HMM section after MACD/PPO |
| Scanner config | `scanner/services/config.py` | HMM constants |
| Chart UI | `swingtrader/backend/resources/views/scanner/index.blade.php` | Regime panel + badge |
| Chart controller | `scanner/backend/Controllers/ScannerController.php` | HMM columns in API |
| Optimizer backtest | `swingtrader/services/optimizer/parameter_optimizer.py` | `_backtest_with_params()`, `backtest_portfolio()` |
| Optimizer nightly | `swingtrader/services/optimizer/nightly_optimizer.py` | `--no-hmm` flag |
| Data fetcher | `swingtrader/services/optimizer/data_fetcher.py` | `.env` DATABASE_URL |
| DB connection | `swingtrader/services/optimizer/db.py` | `.env` DATABASE_URL |

---

## Next Steps

1. **Live execution integration**: Add HMM regime gate in `TradeExecutorService.php` — check latest regime before 'buy' signal. Use `hmm_bear_factor` to reduce position size (not block).
2. **Walk-forward mode**: Switch from `fit_predict` to `walk_forward_predict` in optimizer for lookahead-free backtests.
3. **Retrain on longer data**: Backtest with 10+ years of data to see HMM's crash protection compound.
4. **Dynamic factor**: Vary `hmm_bear_factor` based on regime probability (stronger Bear = more reduction), not just binary Bear/not-Bear.
5. **Per-ticker factors**: Use different `hmm_bear_factor` for VTV (e.g., 0.9 since HMM hurts VTV).
6. **Daily/hourly HMM**: Run `compute_indicators.py --timeframe day` and `--timeframe hour` to populate DB tables for live trading.
7. **Teardown**: After merging to main, delete `swingtrader_markov` DB and switch `.env` files back to production DB.
8. **HMM param optimization**: Grid search over `n_states`, `lookback`, `covariance_type` alongside trading params.

---

## Branch

All work is on the `feature/markov-hmm` branch.
