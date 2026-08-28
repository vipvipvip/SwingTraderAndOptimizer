# MTF Top-N Daily Runner — Multi-TF Rotation Strategy

## Overview

MTF Top-N replaces MTCS (Hilbert sine/lead) as the primary rotation strategy.
Uses Multi-TF scoring (weekly gap + ATR distance + freshness) across VTI stocks
and weekly EMA10>SMA40 rotation (EMASMA) across thematic ETFs to select the top N
most favorable long candidates daily.

**v2 same-day flow**: An intraday sampler (`swingtrader-scanner-hourly`) runs
during market hours (09:10–13:10 ET) and snapshots latest-trade prices into the
hourly table + recomputes MACD/EMA/SMA. The executor
(`swingtrader-mtf-executor`, 1:30 PM ET) then scores **v2** (freshest-CO top-10
stock leg + EMA/SMA ETF leg) on TODAY's intraday bars (`--fresh`) and places
orders in the same run. The standalone evening scorer is disabled (score is now
inline in the executor); the ETF leg keeps the EMA/SMA rotation.
**v2 strategy** (freshest-CO top-10) drives the stock leg; ETF leg keeps the EMA/SMA rotation.

**State is DB-backed**: pending picks live in `mtf_pending` (JSONB), run history
in `mtf_runs`, and real holdings in `mtf_positions`. No state files, no R&D
paper-portfolio accounting — the live Alpaca positions are the source of truth.

## Scoring Formula

Stocks use **Multi-TF** scoring:

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

ETFs use **EMA/SMA** scoring (pure weekly rotation, no daily/hourly/ATR filters):

```
Score = min(gap_w / 5, 5)   (weekly close vs SMA(40) gap, points)
```

- Long only while weekly EMA(10) > SMA(40); flat otherwise. Same top-N rotation
  mechanics, no additional filters. Backtested at **+143% (10.5% DD)** vs MTF
  +66% (15.4% DD) over Jul 2023 – Jul 2026 on the same 28-ETF universe.

## Architecture

**Intraday sampler (`swingtrader-scanner-hourly`)** — 09:10–13:10 ET: captures latest-trade prices into the hourly table, then recomputes MACD/EMA/SMA.
**Executor (`swingtrader-mtf-executor`, 1:30 PM)** — `--action score` then `--action execute` on TODAY's intraday bars (`--fresh`): v2 stock leg + EMA/SMA ETF leg.
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

**Executor (1:30 PM)** — `--action execute`:
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
| `runner.py` | Two-phase: `--action score` (evening analytics) or `--action execute` (morning trades). Stocks scored with Multi-TF, ETFs with EMA/SMA |
| `config.py` | DB creds, scoring params (TOP_N=10, EMA/SMA periods, cost, capital) |
| `db.py` | Scanner DB access + `mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades` state |
| `executor.py` | Alpaca order executor (mode-dependent keys: stock #PA3PPZAZR76Z, etf #PA3U8GZ96PEN); `reconcile_trades()` rebuilds `mtf_trades` from Alpaca fills |
| `reconcile_trades.py` | CLI wrapper: `--mode all\|stock\|etf` — idempotent fill-log rebuild from Alpaca's authoritative order history |
| `format_etf.py` | Shared ETF P&L table formatting (Slack + show_picks) |
| `health_check.py` | DB-backed health checks (mtf_runs staleness, pending status, data freshness) |
| `.env` | Environment variables (DB creds, Slack webhook URL) |
| `data/mtf_picks_stock.csv` | Daily stock top-N picks with scores and components (pick history) |
| `data/mtf_picks_etf.csv` | Daily ETF top-N picks with scores and components (pick history) |
| `systemd/swingtrader-scanner-hourly.{service,timer}` | Intraday hourly sampler (weekdays 09:10–13:10 ET) — feeds the 1 PM v2 signal |
| `systemd/swingtrader-mtf-scorer.{service,timer}` | DISABLED 2026-08-27 (score is inline in the executor); kept for manual/analytics use |
| `systemd/swingtrader-mtf-executor.{service,timer}` | v2 same-day executor (weekdays 1:30 PM ET, `--action score` then `--action execute`, both `--strategy v2 --fresh`) |

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

**Evening (4:45 PM)** — picks and analytics, tagged `[MTF+EMA-SMA stocks+ETFs]`:
```
MTF Top 10 + EMA/SMA Top 10 — 2026-07-13 (stocks + ETFs + sectors)
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

EMA/SMA Top 10 — 2026-07-13 (ETFs)
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

**Morning (10:00 AM)** — fill confirmation, tagged `[MTF+EMA-SMA stocks+ETFs]`:
```
MTF + EMA/SMA Execution — 2026-07-14 (stocks + ETFs)
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
- **09:10–13:10 ET** — Intraday hourly sampler (snapshot prices + recompute MACD/EMA/SMA)
- **1:00 PM / 1:30 PM** — Executor scores v2 on fresh intraday bars then fills (what was bought/sold)

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
sudo systemctl start swingtrader-mtf-scorer.service

# Morning executor (manual)
sudo systemctl start swingtrader-mtf-executor.service

# Journal — scorer
sudo journalctl -u swingtrader-mtf-scorer.service -n 50 --no-pager

# Journal — executor
sudo journalctl -u swingtrader-mtf-executor.service -n 50 --no-pager

# Status — both timers
sudo systemctl status swingtrader-mtf-scorer.timer
sudo systemctl status swingtrader-mtf-executor.timer

# Tail live — scorer
sudo journalctl -u swingtrader-mtf-scorer.service -f

# Tail live — executor
sudo journalctl -u swingtrader-mtf-executor.service -f
```

**Dependency**: `swingtrader-mtf-scorer.service` declares `After=swingtrader-scanner-backfill.service` + `Wants=swingtrader-scanner-backfill.service`. When the runner starts, it pulls in `swingtrader-scanner-backfill.service` (populate + capture close quote + compute ATR_stop) and waits for it to complete before scoring. This ensures hourly `atr_stop` indicators are always freshly computed, even if `swingtrader-scanner-backfill.timer` is disabled or delayed.

**Data completeness guard**: Runner checks all enabled tickers have today's daily bar before scoring. If incomplete, it retries `populate_tickers.py` + `compute_indicators.py` up to 3 times. On failure, sends a red `🚨🔴 DATA INCOMPLETE` Slack alert and aborts. No trades are placed.

### Timers

| Timer | Time | Action | Service |
|-------|------|--------|---------|
| `swingtrader-scanner-hourly.timer` | Mon–Fri 09:10–13:10 ET | Intraday hourly capture | `swingtrader-scanner-hourly.service` |
| `swingtrader-mtf-executor.timer` | Mon–Fri 1:30 PM ET | v2 score+execute | `swingtrader-mtf-executor.service` |

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf

# v2 same-day run (what the 1:30 PM executor does): score TODAY's intraday bars, then execute
python3 runner.py --action score --mode all --strategy v2 --fresh   # score on today's bars
python3 runner.py --action execute --mode all --strategy v2 --fresh # fill pending same day

# Scoring without --fresh (last complete date, e.g. evening re-scoring)
python3 runner.py --action score --mode all --strategy v2
python3 runner.py --action score --mode stock
python3 runner.py --action score --mode etf

# Executor: place pending trades (--dry-run reports per-account buys/sells, no orders)
python3 runner.py --action execute --mode all --dry-run   # Preview buys/sells, no orders
python3 runner.py --action execute --mode all             # Execute pending for both modes
python3 runner.py --action execute --mode stock
python3 runner.py --action execute --mode etf
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
