# MTF Infrastructure Refactor Plan

## Status: Ready to implement (next session)

## Goal
Expand MTF Top-N universe from 503 S&P 500 stocks to ~2,000 VTI constituents, fix compute_indicators.py lock contention, and prepare for 3K+ ticker scaling.

## Decisions Made
| # | Decision | Chosen |
|---|----------|--------|
| 1 | Hourly data retention | Keep all (from 2023) |
| 2 | Partition tables | Hourly only |
| 3 | ETF universe | Keep 22 |
| 4 | Downtime tolerance | As much as needed |
| 5 | Time constraint | Weekend, no rush |
| 6 | Worker scheduler | Full redesign (partition-aware + COPY) |
| 7 | Backtest runtime | 40 min acceptable |
| 8 | Keep backup table | Yes |
| 9 | Sector classification | Deferred (later) |
| 10 | Ticker universe source | VTI (CRSP US Total Market) |
| 11 | Ticker filters | Price > $10, Avg dollar volume > $10M |

## Why VTI over S&P 500
- S&P 500 is a lagging indicator — adds stocks AFTER explosive growth
- TSLA: +757% BEFORE S&P inclusion, only +35% AFTER
- NVDA: +103% BEFORE S&P inclusion
- VTI catches stocks at ~$100M market cap (years before S&P 500)
- MTF's early-momentum signals work better on small/mid-cap growth stocks

## Implementation Tasks

### Task 1: Get VTI Universe (~2,000 tickers)
- Source: Vanguard VTI holdings (or Wikipedia CRSP US Total Market)
- Apply filters: Price > $10, Avg dollar volume > $10M
- NO yfinance needed (no sector data)
- Add to `tbl_stock_tickers` with `enabled = false`

### Task 2: Partition `tbl_scanner_tickers_1hour` (16 hash buckets)
- DDL: `ALTER TABLE ... PARTITION BY HASH (ticker_id)`
- Create 16 partition tables
- Migrate existing 2.8M rows
- Keep old table as backup (`tbl_scanner_tickers_1hour_old`)
- Current table size: 1.5 GB (table + 6 indexes)

### Task 3: Rewrite `compute_indicators.py`
**Current problem**: 10 workers × 5,260 individual UPDATEs per ticker = lock contention (1h 47min runtime)

**Fix**:
- Partition-aware worker scheduler (each worker owns specific partitions)
- COPY bulk writes instead of individual UPDATEs
- 16 workers (1 per partition) = zero lock contention
- Expected runtime: ~5-8 min on 2.8M rows

**Key changes**:
- Pre-compute partition map: `ticker_id % 16 → partition_id`
- Group tickers by partition
- Assign partition groups to workers (round-robin)
- Each worker keeps one DB connection
- Use `COPY` to temp table + `INSERT ... ON CONFLICT DO UPDATE`

### Task 4: Update `populate_tickers.py`
- Currently pulls hourly data for all enabled tickers
- With 2K tickers: ~180K bars (vs 45K now)
- Runtime: ~20-25 min (vs 5 min now)
- Memory: ~2 GB (vs 500 MB now)
- Need to handle partition-aware inserts

### Task 5: Update `runner.py` (MTF Top-N)
- Read from partitioned table
- Partition-aware data loading
- No other logic changes needed

## Files to Modify
1. `scanner/services/scripts/compute_indicators.py` — major rewrite
2. `scanner/services/scripts/populate_tickers.py` — update for partitions
3. `swingtrader/services/mtf/runner.py` — minor updates
4. `swingtrader/services/mtf/db.py` — update queries for partitions
5. New: `scanner/services/scripts/get_vti_universe.py` — fetch VTI constituents
6. DDL: partition migration SQL

## Testing Checklist
- [ ] VTI universe fetches correctly (~2K tickers)
- [ ] Filters applied (Price > $10, Avg $ vol > $10M)
- [ ] Partitions created (16 hash buckets)
- [ ] Existing data migrated to partitions
- [ ] `compute_indicators.py` runs without lock contention
- [ ] `populate_tickers.py` handles 2K tickers
- [ ] `runner.py` reads from partitioned table
- [ ] Backtest runs on expanded universe
- [ ] Slack messages still work
- [ ] No interference with MTCS (separate tables)

## Rollback Plan
1. Keep `tbl_scanner_tickers_1hour_old` as backup
2. If partitioning fails: rename old table back
3. If compute_indicators fails: revert to individual UPDATEs
4. If universe expansion fails: filter back to S&P 500

## Deferred Work
- Sector classification (add via yfinance later)
- MTCS → MTF replacement (separate session, 2-3 hrs)
- Alpaca executor for MTF (separate session)

## Critical Context
- PostgreSQL `swingtrader-db` on `127.0.0.1:5432`
- Scanner tables: `tbl_scanner_tickers_1hour` (2.8M rows), `tbl_scanner_tickers_daily` (790K), `tbl_scanner_tickers` (165K)
- EMA=10, SMA=40, COST=0.0005, CAPITAL=100000
- MTF runner fires at 16:45 ET via `mtf-daily-runner.timer`
- `compute_indicators.py` currently broken (1h 47min runtime due to lock contention)
- Three Alpaca paper accounts: CHAND, EMAC, MTCS
- MTCS still running (separate from this refactor)
