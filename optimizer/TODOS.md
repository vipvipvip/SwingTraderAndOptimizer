# Alpaca Trading Platform - TODOs

## Phase 1: Strategy Framework ✅
- [x] Indicators (MACD, PPO, SMA, Bollinger Bands)
- [x] Strategy logic (entry/exit rules)
- [x] Data fetcher (Alpaca API)
- [x] Backtest engine
- [x] Parameter optimizer (grid search, 2187 combinations tested)

## Phase 1B: Parameter Optimization ✅
- [x] Grid search optimizer
- [x] Rank by Sharpe ratio
- [x] Save best params to JSON
- [ ] **TODO: GPU Acceleration** — Implement CuPy/Numba or multiprocessing for parallel backtests
  - Current: Serial (2187 combos in ~3 min on single CPU)
  - Target: 10x speedup via GPU-accelerated backtest loops or multiprocessing pool
  - Use when: Phase 1C (nightly optimizer) + multi-ticker support

## Phase 1C: Nightly Optimizer + DB
- [ ] PostgreSQL schema for storing optimized parameters
- [ ] Nightly cron job (runs optimizer for each ticker)
- [ ] Multi-ticker support (SPY, QQQ, IWM, etc.)
- [ ] **Implement multiprocessing** for parallel parameter testing (Phase 1B note)

## Phase 2: Web Showcase + Live Tracking
- [ ] Laravel backend (REST API)
- [ ] Svelte frontend (dashboard)
- [ ] Real-time strategy execution
- [ ] Live P&L tracking vs backtest

## Phase 3: Subscription Model
- [ ] Identify proven strategies (live track record)
- [ ] Stripe integration
- [ ] Signal distribution (API/webhook)

## Technical Debt / Future Optimization
- **GPU Acceleration (HIGH PRIORITY):** Replace serial backtest loops with GPU-accelerated code
  - Libraries: CuPy, Numba CUDA, PyTorch
  - Impact: 10-100x speedup for large parameter grids
  - Timeline: After Phase 1C (multi-ticker working)
- Consider Bayesian optimization instead of grid search (fewer evals needed)
- Add risk management (drawdown limits, position sizing)
