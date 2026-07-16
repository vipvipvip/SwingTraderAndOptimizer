# MTF Top-N Daily Runner — Multi-TF Rotation Strategy

## Overview

MTF Top-N replaces MTCS (Hilbert sine/lead) as the primary rotation strategy.
Uses Multi-TF scoring (weekly gap + ATR distance + freshness) across all S&P 500
stocks to select the top N most favorable long candidates daily.

**Phase 1: Paper trading** — logs picks, tracks simulated portfolio, sends Slack
alerts. MTCS continues running alongside for cross-validation.

**Phase 2: Replace MTCS** — stop Hilbert runner, wire MTF picks into Alpaca executor.

## Scoring Formula

```
Score = min(gap_w / 20, 3)   (weekly gap from SMA(40), points)
      + min(atr_dist / 1.5, 3)  (distance above ATR stop, points)
      + max(0, 2 - days_since_weekly / 60)  (freshness bonus, 0-2 pts)
```

- **gap_w**: `(close - SMA(40)) / SMA(40) * 100` on weekly bars. Captures momentum
  strength. Capped at 3 pts (gap_w >= 60%).
- **atr_dist**: `(close - ATR_stop) / close * 100` on 1-hour bars. Measures room
  above the trailing stop. Capped at 3 pts (atr_dist >= 4.5%).
- **freshness**: Days since last weekly EMA(10) > SMA(40) crossover. 2 pts at day 0,
  linearly decays to 0 at day 120. Preserves explosive early entries while still
  favoring fresh breakouts.

## Architecture

```
┌──────────┐    ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────┐
│ DB (PSQL)│───▶│  runner.py   │───▶│  CSV logs        │───▶│  Slack alert (1 msg) │
│ scanner  │    │  --mode all  │    │  (picks/portfolio)│   │  stocks + ETFs       │
│ tables   │    │  (one-shot)  │    │                  │    │  combined            │
└──────────┘    └──────────────┘    └──────────────────┘    └──────────────────────┘
                     │
                     ▼
               ┌──────────────┐
               │  state.json  │
               │  (day-over-  │
               │   day delta)  │
               └──────────────┘
```

## Files

All files live under `swingtrader/services/mtf/`:

| File | Purpose |
|------|---------|
| `runner.py` | Daily one-shot — `--mode stock|etf|all`. `--mode all` runs both stock + ETF in one shot with combined Slack message |
| `config.py` | DB creds, scoring params (TOP_N=10, EMA/SMA periods, cost, capital) |
| `db.py` | Scanner DB access (weekly/daily/hourly OHLC, market breadth) |
| `.env` | Environment variables (DB creds, Slack webhook URL) |
| `data/mtf_picks_stock.csv` | Daily stock top-N picks with scores and components |
| `data/mtf_picks_etf.csv` | Daily ETF top-N picks with scores and components |
| `data/mtf_portfolio_stock.csv` | Daily stock portfolio snapshot |
| `data/mtf_portfolio_etf.csv` | Daily ETF portfolio snapshot |
| `data/mtf_trades_stock.csv` | Individual stock trade log |
| `data/mtf_trades_etf.csv` | Individual ETF trade log |
| `.mtf_state_stock.json` | State file: stock picks + portfolio |
| `.mtf_state_etf.json` | State file: ETF picks + portfolio |
| `systemd/mtf-daily-runner.{service,timer}` | systemd oneshot + timer (weekdays 5:30 PM ET, `--mode all`) |

## Backtest Results (Multi-TF Daily Rebalance)

| Metric | Value |
|--------|-------|
| Period | Jul 2023 – Jul 2026 |
| Return | +5,299% ($100k → $5.4M) |
| Max DD | 22.2% |
| Win rate | 68% |
| Avg win | +16.24% |
| Avg loss | -5.31% |
| Buys | 526 (0.44/day) |

## Strategy Comparison

| Aspect | Multi-TF Daily | MTF Min-Score 5 | Multi-TF Weekly | Long Scanner Daily | Long Scanner Weekly |
|--------|---------------|-----------------|-----------------|-------------------|-------------------|
| Return | +5,469% | **+9,061%** | +698% | -6.26% | +70.73% |
| Max DD | 22.2% | 33.2% | 28.1% | — | 37.8% |
| Buys | 526 | **280** | — | 12,399 | — |
| Avg return/buy | +10.4% | **+32.4%** | — | ~0% | — |

### Min-Score 5 Variant (6th Strategy)

Filters candidates to `score ≥ 5` before ranking the top 10. Compared to unfiltered:
- **+66% higher return** (+9,061% vs +5,469%) — fewer, higher-conviction entries
- **47% fewer buys** (280 vs 526) — less churn, no weak marginal picks
- **Higher drawdown** (33.2% vs 22.2%) — less diversification across picks

Backtest confirmed infancy as a hard filter *drags* performance (min-score 5 + infancy: +688% only) — freshness is better as a component of the score (0-2 pts) than a hard cutoff. The min-score 5 variant excludes the lowest-score picks (gap_w < ~10%, atr_dist < ~0.5%, or stale crosses) while preserving explosive entries with high momentum.

**Current status**: Runs automatically as part of `--mode all` alongside the default pipeline, isolated state/CSV (`.mtf_state_min5_stock.json`, `mtf_picks_min5_stock.csv`). Paper-only.

Multi-TF score (weekly+daily bullish filter) eliminates weak stocks completely.
Long scanner's MACD/PPO zero-line crosses are noisy (50% win rate = coin flip).
Multi-TF daily doesn't churn because scores are stable day-to-day.

## Slack Messages

One combined message sent after market close (5:30 PM ET), tagged `[MTF-TopN]`:

```
Multi-TF Top 10 — 2026-07-13 (stocks + ETFs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multi-TF Top 10 — 2026-07-13 (stocks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 52% uptrend ➖ Neutral

 1. HPE     6.2  gap +64.0%  atr 4.40%  105d
 2. SNDK    6.0  gap +97.5%  atr 7.25%  old
 3. WDC     6.0  gap +66.1%  atr 5.09%  420d
 4. MU      5.9  gap +81.5%  atr 4.34%  399d
 5. DDOG    5.8  gap +58.0%  atr 3.12%  70d
 6. DELL    5.7  gap +101.4%  atr 4.01%  133d
 7. MRNA    5.5  gap +50.7%  atr 4.78%  210d
 8. PANW    5.5  gap +56.6%  atr 2.54%  63d
 9. AMAT    5.4  gap +55.4%  atr 3.93%  378d
10. AMD     5.4  gap +74.6%  atr 3.63%  378d

Portfolio: $99,557  (-0.4%)
Positions: 10  Cash: $11

Multi-TF Top 10 — 2026-07-13 (ETFs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 64% uptrend ✅ Risk-on

 1. SMH     3.1  gap +31.4%  atr 2.33%  392d
 2. XLF     2.5  gap +7.0%  atr 0.78%  21d
 3. IWM     1.2  gap +11.3%  atr 0.88%  357d
 4. IJR     1.0  gap +12.2%  atr 0.64%  336d
 5. IJH     0.9  gap +7.9%  atr 0.69%  364d
 6. SCHD    0.9  gap +9.8%  atr 0.61%  329d
 7. RSP     0.8  gap +8.3%  atr 0.55%  385d
 8. SPY     0.8  gap +7.9%  atr 0.54%  399d
 9. VTV     0.8  gap +9.9%  atr 0.44%  385d
10. DIA     0.7  gap +7.7%  atr 0.50%  378d

Portfolio: $99,900  (-0.1%)
Positions: 10  Cash: $50
```

## Monitoring

### Slack
One combined `[MTF-TopN]` message at 5:30 PM ET with both stock and ETF results:
- Market breadth regime per universe
- Top-10 stock picks with full scoring breakdown
- Top-10 ETF picks with full scoring breakdown
- Changes from previous day (NEW/OUT) per universe
- Paper portfolio value, total return, and daily P&L per universe
- Current cash and positions count per universe

### CSV Logs (separate per mode and variant)
- `data/mtf_picks_stock.csv` / `data/mtf_picks_etf.csv` — Daily top-N picks (default)
- `data/mtf_picks_min5_stock.csv` / `data/mtf_picks_min5_etf.csv` — Score ≥ 5 variant
- `data/mtf_portfolio_stock.csv` / `data/mtf_portfolio_etf.csv` — Portfolio MTM (default)
- `data/mtf_portfolio_min5_stock.csv` / `data/mtf_portfolio_min5_etf.csv` — Score ≥ 5 variant
- `data/mtf_trades_stock.csv` / `data/mtf_trades_etf.csv` — Individual trades (default)
- `data/mtf_trades_min5_stock.csv` / `data/mtf_trades_min5_etf.csv` — Score ≥ 5 variant

### Systemd
```bash
# Run once (manual)
systemctl --user start mtf-daily-runner.service

# Journal
journalctl --user -u mtf-daily-runner.service -n 50 --no-pager

# Status
systemctl --user status mtf-daily-runner.timer

# Tail live
journalctl --user -u mtf-daily-runner.service -f
```

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf
python3 runner.py --mode all              # Both stock + ETF + min-score 5, one Slack message
python3 runner.py --mode stock            # Stocks only (default scoring)
python3 runner.py --mode stock --min-score 5  # Stocks only, score ≥ 5 filter
python3 runner.py --mode etf              # ETFs only (default scoring)
python3 runner.py --mode etf --min-score 5   # ETFs only, score ≥ 5 filter
```

Note: `--mode all` automatically runs both the default and min-score 5 variants
in a single execution. The min-score variant has isolated state files (`.mtf_state_min5_*.json`)
and separate CSVs.

## Phases

| Phase | Action | Status |
|-------|--------|--------|
| 1 | Paper trading — log picks, track portfolio, Slack alerts alongside MTCS | 🚧 In Progress |
| 2 | Stop MTCS runner, wire MTF picks into Alpaca executor (start --top-n 5) | ⏳ Pending |
| 3 | Scale to --top-n 10, add stop-loss/trailing exit if needed | ⏳ Pending |

## DB Schema (Read-Only)

The runner reads from existing scanner tables:
- `tbl_stock_tickers` — Stock master list (503 S&P 500)
- `tbl_scanner_tickers` — Weekly OHLCV + indicators
- `tbl_scanner_tickers_daily` — Daily OHLCV + indicators
- `tbl_scanner_tickers_1hour` — 1-hour OHLCV + atr_stop
