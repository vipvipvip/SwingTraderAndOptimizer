# MTF Top-N Daily Runner — Multi-TF Rotation Strategy

## Overview

MTF Top-N replaces MTCS (Hilbert sine/lead) as the primary rotation strategy.
Uses Multi-TF scoring (weekly gap + ATR distance + freshness) across VTI stocks
and thematic ETFs to select the top N most favorable long candidates daily.

**Two-phase execution**: Evening scorer (4:45 PM) runs analytics, scores, saves
pending trades. Morning executor (10:00 AM) reads pending trades, places market
orders when market is open, and records fills immediately.

**State is DB-backed**: pending picks live in `mtf_pending` (JSONB), run history
in `mtf_runs`, and real holdings in `mtf_positions`. No state files, no R&D
paper-portfolio accounting — the live Alpaca positions are the source of truth.

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

**Evening (4:45 PM)** — `--action score`:
```
┌──────────┐    ┌──────────────────┐    ┌──────────────────────┐
│ DB (PSQL)│───▶│  runner.py       │───▶│  Slack alert (picks) │
│ scanner  │    │  data guard      │    │  (stocks + ETFs +    │
│ tables   │    │  + score + MTM   │    │   sectors)           │
└──────────┘    │  + CSV (idemp.)  │    └──────────────────────┘
                └────────┬─────────┘
                         │ saves pending → mtf_pending (JSONB)
                         │ logs run      → mtf_runs
                         ▼
                 ┌───────────────┐
                 │ PostgreSQL    │
                 │ mtf_pending   │
                 │ mtf_runs      │
                 └───────────────┘
```

**Morning (10:00 AM)** — `--action execute`:
```
                 ┌───────────────┐
                 │ mtf_pending   │ ─── reads unconsumed pending
                 └───────────────┘
                         │
                         ▼
                ┌────────────────┐    ┌──────────────────────┐
                │  runner.py     │───▶│  Slack alert (fills) │
                │  executor.py   │    │  (bought/sold/fills) │
                └───────┬────────┘    └──────────────────────┘
                        │
                        ▼
                ┌────────────────┐
                │  Alpaca API    │
                │  (market open) │
                └────────────────┘
                        │
                        ▼
                ┌────────────────┐
                │  mtf_positions │ (real fills → holdings)
                │  mtf_trades    │ (trade log)
                └────────────────┘
```

Key principle: **All analytics happen in the evening. Morning only acts.**
No guessing after-hours fills — market orders at 10 AM record fills immediately.

## Files

All files live under `swingtrader/services/mtf/`:

| File | Purpose |
|------|---------|
| `runner.py` | Two-phase: `--action score` (evening analytics) or `--action execute` (morning trades) |
| `config.py` | DB creds, scoring params (TOP_N=10, EMA/SMA periods, cost, capital) |
| `db.py` | Scanner DB access + `mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades` state |
| `executor.py` | Alpaca order executor (mode-dependent keys: stock #PA3PPZAZR76Z, etf #PA3U8GZ96PEN); `reconcile_trades()` rebuilds `mtf_trades` from Alpaca fills |
| `reconcile_trades.py` | CLI wrapper: `--mode all\|stock\|etf` — idempotent fill-log rebuild from Alpaca's authoritative order history |
| `format_etf.py` | Shared ETF P&L table formatting (Slack + show_picks) |
| `health_check.py` | DB-backed health checks (mtf_runs staleness, pending status, data freshness) |
| `.env` | Environment variables (DB creds, Slack webhook URL) |
| `data/mtf_picks_stock.csv` | Daily stock top-N picks with scores and components (pick history) |
| `data/mtf_picks_etf.csv` | Daily ETF top-N picks with scores and components (pick history) |
| `systemd/mtf-daily-runner.{service,timer}` | Evening scorer (weekdays 4:45 PM ET, `--action score --mode all`) |
| `systemd/mtf-executor.{service,timer}` | Morning executor (weekdays 10:00 AM ET, `--action execute --mode all`) |

## Backtest Results (Multi-TF Daily Rebalance)

| Metric | Value |
|--------|-------|
| Period | Jul 2023 – Jul 2026 |
| Return | +5,469% ($100k → $5.57M) |
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

### Min-Score 5 Variant (research only — dropped)

The `score ≥ 5` filter was backtested as an alternative strategy:
- **+66% higher return** (+9,061% vs +5,469%) — fewer, higher-conviction entries
- **47% fewer buys** (280 vs 526) — less churn, no weak marginal picks
- **Higher drawdown** (33.2% vs 22.2%) — less diversification across picks

Backtest confirmed infancy as a hard filter *drags* performance (min-score 5 + infancy: +688% only) — freshness is better as a component of the score (0-2 pts) than a hard cutoff.

**Status: research paper portfolio only — not run in production.** The min-score 5 pipeline, its state files, and CSV variants were removed from `runner.py` (2026-07-31) to keep production lean. The backtest result is retained for reference; revisit only if the default top-10 underperforms live.

Multi-TF score (weekly+daily bullish filter) eliminates weak stocks completely.
Long scanner's MACD/PPO zero-line crosses are noisy (50% win rate = coin flip).
Multi-TF daily doesn't churn because scores are stable day-to-day.

## Slack Messages

**Evening (4:45 PM)** — picks and analytics, tagged `[MTF-TopN]`:
```
Multi-TF Top 10 — 2026-07-13 (stocks + ETFs + sectors)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multi-TF Top 10 — 2026-07-13 (stocks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 52% uptrend ➖ Neutral

#   Ticker   Score     Gap   Fresh
--- -------- ----- ------- -------
1   CRNX       4.6  +82.1%     24d
2   FBRX       4.6 +179.3%     24d
3   MNPR       4.3  +56.3%     31d
...
10  OKTA       3.3  +48.1%     66d

No changes since last run

MTM: $96,656  |  Positions: 10  |  Picks: 10
CRNX,FBRX,MNPR,MAN,CBRL,CORT,SEZL,KFRC,DAVE,OKTA

Multi-TF Top 10 — 2026-07-13 (ETFs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Breadth: 64% uptrend ✅ Risk-on

#   Ticker   Score  Entry $    Now $   P&L %   Fresh
--- -------- ----- -------- -------- ------- -------
1   XLF        2.2   $56.36   $56.87  +0.90%     39d
2   XLV        2.0  $162.60  $162.14  -0.28%     60d
...

⚠️ preserved (not scored today — filter or data gap): IJH

MTM: $105,282  |  Positions: 11  |  Picks: 10
XLF,XLV,SCHD,XLE,IJR,VTV,XLI,XLRE,DIA,RSP

Sector ETFs — 2026-07-13
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 1. XLK     3.5  gap +18.2%  atr 1.80%  45d
 ...
```

- **NEW/OUT** lines show picks added/removed vs real `mtf_positions` holdings
- **MTM** is sum of held quantity × today's close (real positions, not a simulated portfolio)
- ETF entry prices come from real Alpaca fills recorded in `mtf_positions`
- Positions held but not scored today (failed the bullish filter or missing data) are preserved, listed after ⚠️

### Sector ETFs (Informational)

Sector ETF scores appear in the daily Slack for situational awareness — which sectors have
strong momentum. No portfolio, no state, no CSVs. Just score rankings so you can see
where the rotational strength is.

**Morning (10:00 AM)** — fill confirmation, tagged `[MTF-TopN]`:
```
Multi-TF Execution — 2026-07-14 (stocks + ETFs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*Executing stocks trades (scored 2026-07-13 16:45:00)*
  SELL 10 AAPL @ $215.30  (PnL: +12.5%)
  BUY 25 MSFT @ $185.20 ($4,630.00)
  Rotation: 2 sells, 3 buys — $1,000,000 equity

*Executing ETFs trades (scored 2026-07-13 16:45:00)*
  BUY 15 SMH @ $220.10 ($3,301.50)
  Rotation: 0 sells, 1 buy — $1,000,000 equity
```

## Monitoring

### Slack
Two Slack messages per day:
- **4:45 PM** — Evening picks with full scoring, portfolio status, sector info
- **10:00 AM** — Morning fill confirmation (what was bought/sold)

Evening message includes:
- Market breadth regime per universe
- Top-10 stock picks with full scoring breakdown
- Top-10 ETF picks with P&L vs real fill prices
- Sector ETF rankings (informational only, no portfolio)
- Changes from previous day (NEW/OUT) vs real holdings
- MTM (held positions × latest close) and positions/picks counts per universe
- Comma-separated ticker line for copying into a broker

### CSV Logs (pick history only)
- `data/mtf_picks_stock.csv` — Daily stock top-N picks (idempotent per date)
- `data/mtf_picks_etf.csv` — Daily ETF top-N picks (idempotent per date)

Trade fills and holdings are logged in PostgreSQL (`mtf_trades`, `mtf_positions`),
not CSV.

### Systemd

```bash
# Evening scorer (manual)
sudo systemctl start mtf-daily-runner.service

# Morning executor (manual)
sudo systemctl start mtf-executor.service

# Journal — scorer
sudo journalctl -u mtf-daily-runner.service -n 50 --no-pager

# Journal — executor
sudo journalctl -u mtf-executor.service -n 50 --no-pager

# Status — both timers
sudo systemctl status mtf-daily-runner.timer
sudo systemctl status mtf-executor.timer

# Tail live — scorer
sudo journalctl -u mtf-daily-runner.service -f

# Tail live — executor
sudo journalctl -u mtf-executor.service -f
```

**Dependency**: `mtf-daily-runner.service` declares `After=scanner-hourly.service` + `Wants=scanner-hourly.service`. When the runner starts, it pulls in `scanner-hourly.service` (populate + capture close quote + compute ATR_stop) and waits for it to complete before scoring. This ensures hourly `atr_stop` indicators are always freshly computed, even if `scanner-hourly.timer` is disabled or delayed.

**Data completeness guard**: Runner checks all enabled tickers have today's daily bar before scoring. If incomplete, it retries `populate_tickers.py` + `compute_indicators.py` up to 3 times. On failure, sends a red `🚨🔴 DATA INCOMPLETE` Slack alert and aborts. No trades are placed.

### Timers

| Timer | Time | Action | Service |
|-------|------|--------|---------|
| `mtf-daily-runner.timer` | Mon–Fri 4:45 PM ET | Evening scoring | `mtf-daily-runner.service` |
| `mtf-executor.timer` | Mon–Fri 10:00 AM ET | Morning execution | `mtf-executor.service` |

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf

# Evening: score only (default)
python3 runner.py --action score --mode all       # Both modes + sectors
python3 runner.py --action score --mode stock     # Stocks only
python3 runner.py --action score --mode etf       # ETFs only

# Morning: execute pending trades
python3 runner.py --action execute --mode all     # Execute pending for both modes
python3 runner.py --action execute --mode stock   # Execute pending for stocks only
python3 runner.py --action execute --mode etf     # Execute pending for ETFs only

# Legacy (deprecated — same as --action execute)
python3 runner.py --mode all --live
```

Note: `--mode all` runs both stock and ETF modes plus sector ETF info in a single
execution. State lives in PostgreSQL (`mtf_pending` unconsumed row per mode);
re-running the scorer replaces that mode's pending, and executing marks it consumed.

## Phases

| Phase | Action | Status |
|-------|--------|--------|
| 1 | Paper trading — log picks, track portfolio, Slack alerts alongside MTCS | ✅ Done |
| 2 | Stop MTCS/EMAC, wire MTF picks into Alpaca executor (--live flag, top-n 10) | ✅ Live |
| 3 | Scale top-N, add stop-loss/trailing exit if needed | ⏳ Pending |

## DB Schema

### Read-only (scanner tables)
- `tbl_stock_tickers` — Master ticker list (1,435 stocks + 28 ETFs, `is_etf` flag)
- `tbl_etf_tickers` — ETF display names (company_name)
- `tbl_scanner_tickers` — Weekly OHLCV + indicators
- `tbl_scanner_tickers_daily` — Daily OHLCV + indicators
- `tbl_scanner_tickers_1hour` — 1-hour OHLCV + atr_stop

### Read-write (mtf_ tables, created by init_db())
- `mtf_positions` — Real open positions (ticker_id, symbol, quantity, entry_price, entry_at) — source of truth for holdings/MTM
- `mtf_trades` — Historical trade log (ticker_id, symbol, side, quantity, price, pnl, executed_at). **Source of truth for fills is Alpaca** — if the log ever disagrees with real fills, rebuild it with `python3 reconcile_trades.py --mode all`
- `mtf_pending` — Evening scorer's picks for the morning executor (mode, top_symbols JSONB, score_detail JSONB, sig_date, consumed_at)
- `mtf_runs` — Run history for ops/staleness (mode, sig_date, action, status, detail, created_at)
