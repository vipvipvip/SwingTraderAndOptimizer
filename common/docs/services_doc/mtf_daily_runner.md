# MTF Top-N Daily Runner — Multi-TF Rotation Strategy

## Overview

MTF Top-N replaces MTCS (Hilbert sine/lead) as the primary rotation strategy.
Uses Multi-TF scoring (weekly gap + ATR distance + freshness) across all S&P 500
stocks and ETFs to select the top N most favorable long candidates daily.

**Phase 2 (Current): Live trading** — EMAC and MTCS stopped; MTF executes real
Alpaca orders (market orders at ~4:45 PM ET queue for next-day open fill).
Paper simulation still runs alongside for record-keeping.

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
│ tables   │    │  --live      │    │                  │    │  + live trade details│
└──────────┘    └──┬───────────┘    └──────────────────┘    └──────────────────────┘
                    │
                    ▼
           ┌────────────────┐
           │  executor.py   │───▶ Alpaca Paper API
           │  execute_rot.  │───▶ mtf_positions / mtf_trades
           └────────────────┘
```

## Files

All files live under `swingtrader/services/mtf/`:

| File | Purpose |
|------|---------|
| `runner.py` | Daily one-shot — `--mode stock\|etf\|all`. `--mode all` runs both modes with combined Slack message |
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
| `systemd/mtf-daily-runner.{service,timer}` | systemd oneshot + timer (weekdays 5:30 PM ET, `--mode all --live`) |
| `executor.py` | Alpaca order executor (mode-dependent keys: stock #PA3PPZAZR76Z, etf #PA3U8GZ96PEN) |

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
Multi-TF Top 10 — 2026-07-13 (stocks + ETFs + sectors)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multi-TF Top 10 — 2026-07-13 (stocks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 52% uptrend ➖ Neutral

 1. HPE     6.2  gap +64.0%  atr 4.40%  105d
 2. SNDK    6.0  gap +97.5%  atr 7.25%  old
 ...

Multi-TF Top 10 — 2026-07-13 (ETFs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 64% uptrend ✅ Risk-on

 1. SMH     3.1  gap +31.4%  atr 2.33%  392d
 2. XLF     2.5  gap +7.0%  atr 0.78%  21d
 ...

Sector ETFs — 2026-07-13
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1. XLK     3.5  gap +18.2%  atr 1.80%  45d
 2. XLF     2.8  gap +12.5%  atr 1.20%  21d
 3. XLE     2.3  gap +8.3%   atr 0.95%  30d
 ...

Portfolio: $102,340  (+2.3%)
Positions: 5  Cash: $28,000
```

### Sector ETFs (Informational)

Sector ETF scores appear in the daily Slack for situational awareness — which sectors have
strong momentum. No portfolio, no state, no CSVs. Just score rankings so you can see
where the rotational strength is.

## Monitoring

### Slack
One combined `[MTF-TopN]` message at 5:30 PM ET with stock, ETF, and sector results:
- Market breadth regime per universe
- Top-10 stock picks with full scoring breakdown
- Top-10 ETF picks with full scoring breakdown
- Sector ETF rankings (informational only, no portfolio)
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
sudo systemctl start mtf-daily-runner.service

# Journal
sudo journalctl -u mtf-daily-runner.service -n 50 --no-pager

# Status
sudo systemctl status mtf-daily-runner.timer

# Tail live
sudo journalctl -u mtf-daily-runner.service -f
```

**Dependency**: `mtf-daily-runner.service` declares `After=scanner-hourly.service` + `Wants=scanner-hourly.service`. When the runner starts, it pulls in `scanner-hourly.service` (populate + capture close quote + compute ATR_stop) and waits for it to complete before scoring. This ensures hourly `atr_stop` indicators are always freshly computed, even if `scanner-hourly.timer` is disabled or delayed.

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf
python3 runner.py --mode all --live       # Both modes + live Alpaca trades + sector info + min-score 5
python3 runner.py --mode all              # Both modes, paper-only (no live trades)
python3 runner.py --mode stock            # Stocks only (default scoring, TOP_N=10)
python3 runner.py --mode stock --min-score 5  # Stocks only, score ≥ 5 filter
python3 runner.py --mode etf              # ETFs only (default scoring, TOP_N=10)
python3 runner.py --mode etf --min-score 5   # ETFs only, score ≥ 5 filter
```

Note: `--mode all` automatically runs both stock and ETF modes, sector ETF info, and both the default and min-score 5 variants
in a single execution. Each variant has isolated state files (`.mtf_state_min5_*.json`)
and separate CSVs.

## Phases

| Phase | Action | Status |
|-------|--------|--------|
| 1 | Paper trading — log picks, track portfolio, Slack alerts alongside MTCS | ✅ Done |
| 2 | Stop MTCS/EMAC, wire MTF picks into Alpaca executor (--live flag, top-n 10) | ✅ Live |
| 3 | Scale top-N, add stop-loss/trailing exit if needed | ⏳ Pending |

## DB Schema

### Read-only (scanner tables)
- `tbl_stock_tickers` — Master ticker list (1,534 stocks + 22 ETFs, `is_etf` flag)
- `tbl_etf_tickers` — ETF display names (company_name)
- `tbl_scanner_tickers` — Weekly OHLCV + indicators
- `tbl_scanner_tickers_daily` — Daily OHLCV + indicators
- `tbl_scanner_tickers_1hour` — 1-hour OHLCV + atr_stop

### Read-write (mtf_ tables, created by init_db())
- `mtf_positions` — Current open positions (ticker_id, symbol, quantity, entry_price, entry_at)
- `mtf_trades` — Historical trade log (ticker_id, symbol, side, quantity, price, pnl, executed_at)
