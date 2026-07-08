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
┌──────────┐    ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐
│ DB (PSQL)│───▶│  runner.py   │───▶│  CSV logs        │───▶│  Slack alert   │
│ scanner  │    │  (one-shot)  │    │  (picks/portfolio)│   │  (daily at 5PM)│
│ tables   │    │              │    │                  │    │                │
└──────────┘    └──────────────┘    └──────────────────┘    └────────────────┘
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
| `runner.py` | Daily one-shot — loads data, scores, picks top N, logs, sends Slack |
| `config.py` | DB creds, scoring params (TOP_N=10, EMA/SMA periods, cost, capital) |
| `db.py` | Scanner DB access (weekly/daily/hourly OHLC, market breadth) |
| `.env` | Environment variables (DB creds, Slack webhook URL) |
| `data/mtf_picks.csv` | Daily top-N picks with scores and components |
| `data/mtf_portfolio.csv` | Daily portfolio snapshot (cash, MTM value, return) |
| `data/mtf_trades.csv` | Individual trade log (BUY/SELL, shares, price, return) |
| `.mtf_state.json` | State file tracking day-over-day picks + portfolio |
| `systemd/mtf-daily-runner.{service,timer}` | systemd oneshot + timer (weekdays 5:30 PM ET) |

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

| Aspect | Multi-TF Daily | Multi-TF Weekly | Long Scanner Daily | Long Scanner Weekly |
|--------|---------------|-----------------|-------------------|-------------------|
| Return | +5,299% | +698% | -6.26% | +70.73% |
| Max DD | 22.2% | 28.1% | — | 37.8% |
| Win rate | 68% | 62% | 50% | 50% |
| Buys/day | 0.44 | 0.13 | 8.3 | 3.5 |

Multi-TF score (weekly+daily bullish filter) eliminates weak stocks completely.
Long scanner's MACD/PPO zero-line crosses are noisy (50% win rate = coin flip).
Multi-TF daily doesn't churn because scores are stable day-to-day.

## Slack Messages

Messages sent to the shared Slack webhook, tagged `[MTF]`:

```
[MTF] Multi-TF Top 10 — 2026-07-08
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 67% uptrend ✅ Risk-on

 1. NVDA  8.2  gap +45.2%  atr 3.10%  12d
 2. AAPL  7.6  gap +32.1%  atr 2.83%  45d
 3. AMZN  7.1  gap +28.4%  atr 2.51%  38d
 4. MSFT  6.8  gap +25.0%  atr 2.22%  52d
 5. GOOGL 6.5  gap +22.8%  atr 2.05%  61d
 6. META  6.2  gap +20.1%  atr 1.92%  74d
 7. TSLA  5.9  gap +18.5%  atr 1.78%  83d
 8. BRK.B 5.6  gap +16.2%  atr 1.65%  91d
 9. JPM   5.3  gap +15.0%  atr 1.52%  98d
10. V     5.1  gap +14.1%  atr 1.48%  102d

  NEW: NVDA (8.2), AAPL (7.6), AMZN (7.1)
  OUT: TSLA, GOOGL, META

Portfolio: $108,342  (+8.3% total, +1.23% today)
Positions: 10  Cash: $1,420
```

## Monitoring

### Slack
Instant visibility via daily `[MTF]` Slack alert at 5:30 PM ET. Shows:
- Market breadth regime
- Top-10 picks with full scoring breakdown
- Changes from previous day (NEW/OUT)
- Paper portfolio value, total return, and daily P&L
- Current cash and positions count

### CSV Logs
- `data/mtf_picks.csv` — Every day's picks with scores for historical analysis
- `data/mtf_portfolio.csv` — Daily portfolio MTM for equity curve tracking
- `data/mtf_trades.csv` — Individual BUY/SELL trades with prices and returns

### Systemd
```bash
# Run once (manual)
sudo systemctl start mtf-daily-runner.service

# Journal
journalctl -u mtf-daily-runner.service -n 50 --no-pager

# Status
systemctl status mtf-daily-runner.timer
```

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf
python3 runner.py
```

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
