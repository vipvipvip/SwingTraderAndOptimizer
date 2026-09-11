# MTF Top-N Daily Runner — emasma Rotation Strategy

## Overview

MTF Top-N replaces MTCS (Hilbert sine/lead) as the primary rotation strategy.
Both legs now run the weekly EMA10>SMA40 gap rotation (**emasma**): `--strategy
emasma` on the stock leg (top-10) and the same emasma rotation on the ETF leg
(top-3). Stock emasma replaces the v2 freshest-crossover strategy (validated
2026-09-10: emasma top-10 + daily-ATR ratchet over 2021-09-20→2026-09-10 =
+17,052% / −23.6% DD / 74% win vs v2's 40.5% win; regime-gate variants all
rejected for amputating returns).

**emasma daily flow**: the executor (`swingtrader-mtf-executor`) runs **once/day**
at 10:25 ET (`--action score` then `--action execute`, `--strategy emasma`, no
`--fresh`) scoring on the last COMPLETE daily bar (settled bars only — never
intraday/partial bars) and fills the rotation same-run. Exit protection is the
**daily-ATR ratchet** (`executor._compute_ratchet_stops`): sells when the last
settled daily close < (highest daily close since entry − 2×daily ATR from the
daily table's atr_stop column). Live == backtest: both the ATR and the
comparison close come from settled daily bars only, so the ratchet fires only
after a daily bar genuinely closes below the stop (signal on day D's close →
fill at day D+1's open). The standalone evening scorer is disabled (score is now
inline in the executor).

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

**Intraday sampler (`swingtrader-scanner-hourly`)** — 09:10–15:10 ET: captures latest-trade prices into the hourly table, then recomputes MACD/EMA/SMA (retained; emasma scoring doesn't consume hourly data).
**Executor (`swingtrader-mtf-executor`)** — once/day at 10:25: `--action score` then `--action execute` on the last COMPLETE daily bar (no `--fresh`): emasma stock leg (top-10) + EMA/SMA ETF leg (top-3), with the daily-ATR ratchet exit on the stock leg.
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

**Executor (7×/day)** — `--action execute`:
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
| `config.py` | DB creds, scoring params (TOP_N=10, ETF_TOP_N=3, EMA/SMA periods, cost, capital) |
| `db.py` | Scanner DB access + `mtf_pending`/`mtf_runs`/`mtf_positions`/`mtf_trades` state |
| `executor.py` | Alpaca order executor (mode-dependent keys: stock #PA368CPXNS13, etf #PA3U8GZ96PEN — from `mtf/.env`); `reconcile_trades()` rebuilds `mtf_trades` from Alpaca fills |
| `reconcile_trades.py` | CLI wrapper: `--mode all\|stock\|etf` — idempotent fill-log rebuild from Alpaca's authoritative order history |
| `format_etf.py` | Shared ETF P&L table formatting (Slack + show_picks) |
| `health_check.py` | DB-backed health checks (mtf_runs staleness, pending status, data freshness) |
| `.env` | Environment variables (DB creds, Slack webhook URL) |
| `data/mtf_picks_stock.csv` | Daily stock top-N picks with scores and components (pick history) |
| `data/mtf_picks_etf.csv` | Daily ETF top-N picks with scores and components (pick history) |
| `systemd/swingtrader-scanner-hourly.{service,timer}` | Intraday hourly sampler (weekdays 09:10–15:10 ET) — captures prices + recomputes MACD/EMA/SMA each hour |
| `systemd/swingtrader-mtf-scorer.{service,timer}` | DISABLED 2026-08-27 (score is inline in the executor); kept for manual/analytics use |
| `systemd/swingtrader-mtf-executor.{service,timer}` | emasma executor (once/day at 10:25, `--action score` then `--action execute`, both `--strategy emasma` on settled daily bars; no `--fresh`) |

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

### ETF-leg top-3 concentration pilot (2026-09-08)

The ETF leg was holding top-10 of 28 (too diversified — little selection power).
Audited backtest (same window 2020-03-02 → 2026-09-08, `--score emasma`, daily
rebalance, ledger reconciliation = PASS within $0.03):

| Config | Final | Return | MaxDD | Sharpe | Sortino |
|--------|-------|--------|-------|--------|---------|
| ETF-28 **top-3** (pilot) | $1,222,649 | **+1,122.7%** | **15.7%** | **1.94** | **1.87** |
| ETF-28 top-10 (prior live) | $522,568 | +422.6% | 20.3% | 1.56 | 1.44 |
| Sector-11 top-3 (info-only) | $657,254 | +557.3% | 21.8% | 1.68 | 1.56 |

Concentration, not the sector universe, is the edge: applying top-3 to the full
28-ETF universe strictly dominates the sector-11 top-3 (return AND drawdown).
`config.ETF_TOP_N = 3` (stocks stay `TOP_N = 10`); revert by setting
`ETF_TOP_N = TOP_N`. Full artifacts: `audit/etf_audit/` (top-3/top-10) and
`audit/sector_etf_audit/`. The audit also exposed & fixed an engine off-by-one:
the no-candidates MTM path valued equity at the *prior* date's close while
stamping the next day's label (understated the final equity point). Canonical
risk metrics moved slightly (sector MaxDD −20.2% → −21.8%, Sharpe 1.75 → 1.68);
final equity unchanged (+557.25%).

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

Sector ETFs — top-3 (ema-sma) — 2026-09-08
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Ticker  Score     Gap   Fresh     Close   ATR%    WkEMA    WkSMA
--- ------- ----- ------- ------- --------- ------ -------- --------
1   XLE       3.4  +17.2%    379d $   64.94  +0.8% $   61.1 $   55.3
2   XLK       3.3  +16.4%    148d $  188.16  +0.6% $  183.4 $  161.8
3   XLV       1.6   +8.3%     99d $  167.72  +0.8% $  165.7 $  154.9

Next: XLF 1.6 | XLB 0.7 | XLRE 0.5 | XLI 0.4 | XLP 0.2
Flat (weekly EMA10<=SMA40): XLC, XLU, XLY
```

- **NEW/OUT** lines show picks added/removed vs real `mtf_positions` holdings
- **MTM** is sum of held quantity × today's close (real positions, not a simulated portfolio)
- ETF entry prices come from real Alpaca fills recorded in `mtf_positions`
- Positions held but not scored today (failed the bullish filter or missing data) are preserved, listed after ⚠️

### Sector ETFs (Informational)

Sector ETF scores appear in the daily Slack for situational awareness — which sectors have
strong momentum. No portfolio, no state, no CSVs. Ranked by the audited sector strategy
(weekly EMA10>SMA40 gap, `--score emasma`, top-3 rotation): the top 3 rows are the picks,
`Score` = min(gap/5, 5), `Gap` = weekly close vs SMA40 gap, `Fresh` = days since the
weekly cross, `ATR%` = distance above the hourly ATR stop, `WkEMA`/`WkSMA` = the weekly
trend reference levels. The trailing comma list (all 11, alpha-sorted) is preserved for
tooling/quick copy.

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
Multiple Slack messages per day:
- **Sampler (09:10–15:10 ET)** — intraday hourly capture + recompute (silent unless an alert).
- **Executor 1×/day (10:25 ET)** — scores emasma on the last complete daily bar then fills (what was bought/sold).

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
| `swingtrader-scanner-hourly.timer` | Mon–Fri 09:10–15:10 ET | Intraday hourly capture + recompute | `swingtrader-scanner-hourly.service` |
| `swingtrader-mtf-executor.timer` | Mon–Fri 10:25 ET (once/day) | emasma score+execute on settled daily bars | `swingtrader-mtf-executor.service` |

### Manual
```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/swingtrader/services/mtf

# emasma daily run (what the 10:25 executor does): score on the last complete daily bar, then execute
python3 runner.py --action score --mode all --strategy emasma   # score on settled daily bars
python3 runner.py --action execute --mode all --strategy emasma # fill pending same day

# Scoring without --fresh (last complete date, e.g. evening re-scoring)
python3 runner.py --action score --mode all --strategy emasma
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
