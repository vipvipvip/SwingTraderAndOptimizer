# Plan: Making the Database Portable

### Current State
- PostgreSQL database runs in Docker container
- Data persists in `backend/postgres_data/` directory on host
- Database structure defined by Laravel migrations (in `backend/database/migrations/`)
- Current data includes: tickers, bars, strategy_parameters, backtest_trades, equity_snapshots, etc.

---

### Goal
Make the database easily recreatable on any system without manual setup steps. Someone should be able to:
1. Clone the repo
2. Run `docker-compose up`
3. Have a fully initialized database ready to use

---

### What's Needed for Portability

**The Schema** (How tables are structured)
- Already portable via Laravel migrations (version-controlled in git)
- Migrations can be run with: `php artisan migrate`

**The Data** (Actual values in the tables)
- Current state: Only exists inside Docker container or in `postgres_data/` directory
- Problem: Not version-controlled, not portable, will be lost if postgres_data is deleted

---

### Approach Options

**Option A: Schema-Only (Minimal)**
- Keep migrations in git ✅ (already done)
- User runs fresh migrations on startup
- Pros: Small repo size, clean schema
- Cons: Loses all existing data (trades, equity curves, optimization history), requires manual seeding

**Option B: Schema + Data Dump (Full Portability)**
- Keep migrations in git ✅ (already done)
- Export database to SQL dump file
- Docker auto-loads SQL dump on first startup
- Pros: Complete portability, preserves all data, "just works" setup
- Cons: SQL dump adds ~1MB to repo (one-time), larger initial clone

**Option C: Selective Data Export (Hybrid)**
- Keep migrations in git ✅
- Export only essential data (tickers, strategy_parameters)
- Skip volatile data (backtest_trades, equity_snapshots - these regenerate from optimizer)
- Pros: Smaller file, cleaner, data regenerates automatically
- Cons: Need manual configuration to decide what's essential vs volatile

---

### Recommended Approach: **Option C (Selective Data Export)**

**Why?**
1. Tickers and allocation weights should be preserved (these are configuration)
2. Strategy parameters should be preserved (result of past optimization)
3. Backtest trades and equity curves can regenerate when optimizer runs
4. Smaller file size, cleaner separation between "config" and "runtime data"

**Implementation:**
1. Create `backend/postgres_init/` directory
2. Export **only essential data** as SQL (tickers, strategy_parameters)
3. Keep migrations for schema generation
4. Docker will:
   - Run migrations to create empty schema
   - Load the data dump to populate config
5. Document: "Run optimizer to regenerate equity curves and backtest trades"

---

### Files to Add/Modify

**New Files:**
- `backend/postgres_init/README.md` - Instructions for portable setup
- `backend/postgres_init/01_seed_tickers.sql` - Essential data only
- `backend/database/MIGRATIONS.md` - Reference documentation

**Modified Files:**
- `docker-compose.yml` - Add mount for init directory

**Nothing to delete** - postgres_data stays but will auto-initialize next start

---

### User Experience After Setup

**Fresh system (clone repo):**
```bash
docker-compose up -d
# Wait 15 seconds
# Database is ready with:
# - All schema tables
# - Tickers (SPY, QQQ, IWM) configured
# - Strategy parameters from last optimization
# - Empty trade history (runs optimizer to populate)
```

**Update database state (export current config):**
```bash
docker exec swingtrader-db pg_dump -U swingtrader --data-only swingtrader | \
  grep "INSERT INTO tickers\|INSERT INTO strategy_parameters" \
  > backend/postgres_init/01_seed_tickers.sql
git add backend/postgres_init/01_seed_tickers.sql
git commit -m "update: latest configuration state"
```

---

### Questions for Future Review

1. **Do you want to include historical bars data?** (10,000 rows per ticker, ~2MB)
   - If yes: Use Option B (full dump)
   - If no: Use Option C (just config)

2. **Should the optimizer auto-run on first startup to populate equity curves?**
   - Or just document that user needs to trigger it manually?

3. **Any other data that should always be available?**

---

## Lessons Learned (2026-04-30)

### Data Integrity During Migration
When migrating from SQLite to PostgreSQL, historical data inherited all issues from the source database.

**Issue Found:** Bars table contained out-of-hours data (pre-market/after-hours trades)
- SQLite had 438 bars outside 14:00-20:00 UTC (market hours)
- These were transferred to PostgreSQL unchanged
- New bars being fetched were correctly filtered, but old data persisted

**Solution Implemented:**
1. **PostgreSQL cleanup script:** `optimizer/cleanup_after_hours_pg.py`
   - Removes out-of-hours bars on-demand
   - Used once to clean migrated data

2. **Docker initialization safeguard:** `backend/postgres_init/02_ensure_market_hours_data.sql`
   - Runs automatically during `docker-compose up` on fresh databases
   - Prevents out-of-hours data from ever entering new systems
   - Paired with docker-compose.yml volume mount for `/docker-entrypoint-initdb.d`

3. **Code-level filter (ongoing):** `optimizer/data_fetcher.py:292`
   - `filter_market_hours()` applied before INSERT
   - Ensures all NEW bars are clean

### For Future Portability Implementation
- When exporting data with Option C (selective), filter bars: `EXTRACT(HOUR FROM timestamp)::INT BETWEEN 14 AND 20`
- Include the initialization scripts in `backend/postgres_init/` directory
- Docker will auto-run them on fresh setups

---

**Document Date:** 2026-04-29 (Updated 2026-04-30)  
**Status:** Planning phase + data integrity safeguards implemented
