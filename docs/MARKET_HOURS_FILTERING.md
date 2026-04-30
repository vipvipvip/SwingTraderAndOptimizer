# Market Hours Data Filtering

## Critical Issue: Bars Table Must Only Contain Market Hours Data

### Correct Market Hours (UTC)
- **Valid Range:** 14:00 - 20:00 UTC
- **Represents:** 9:30 AM - 4:00 PM EDT (US stock market hours)

### Why This Matters
- Out-of-hours bars cause incorrect backtests and equity curve calculations
- Data outside 14:00-20:00 UTC represents pre-market (0-2 UTC) or after-hours (18-23 UTC) trading
- These periods have low liquidity and should not be included in optimization
- Signal parameters deteriorate significantly with noisy after-hours data

## How Filtering Works

### New Data (Real-Time Fetches)
**File:** `optimizer/data_fetcher.py`  
**Function:** `filter_market_hours()` (lines 13-37)  
**Applied:** In `append_bars_to_db()` at line 292 — BEFORE any INSERT

```python
# New bars are filtered automatically when fetched
new_bars = filter_market_hours(new_bars)  # Line 292
```

**Status:** ✅ **Working correctly** — all new bars from Alpaca are filtered

### Historical Data (Database Initialization)
**File:** `backend/postgres_init/02_ensure_market_hours_data.sql`  
**Runs:** During Docker initialization (`docker-compose up`)  
**Action:** Removes any out-of-hours bars from bars table

**Status:** ✅ **Implemented** — prevents migrations from introducing dirty data

### Manual Cleanup (If Needed)
**File:** `optimizer/cleanup_after_hours_pg.py`  
**Usage:** `python3 optimizer/cleanup_after_hours_pg.py`  
**Action:** Reports and removes out-of-hours bars from existing database

---

## The Recurring Issue (2026-04-27 to 2026-04-30)

### What Happened
1. **2026-04-27:** Filtering implemented, 6,242 out-of-hours bars removed → 6,397 clean bars
2. **2026-04-28:** SQLite → PostgreSQL migration (data transferred as-is)
3. **2026-04-30:** Database had 10,247 bars again (438 out-of-hours)

### Root Cause
- **NEW bars:** Filtered correctly before insert (working since 2026-04-27)
- **OLD bars:** Migrated from SQLite → PostgreSQL without being re-filtered
- **Result:** Historical data from pre-filtering era contaminated the new database

### The Fix Applied
```sql
DELETE FROM bars WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 14 AND 20;
```
- Removed 438 out-of-hours bars
- Kept 9,809 clean bars
- Verified all remaining data in hours 14-20 UTC

### How to Prevent This Forever
1. **Docker Init Script:** Now runs during `docker-compose up` (automatic)
2. **New Databases:** Never start with out-of-hours data
3. **Existing Databases:** Can be cleaned manually with `cleanup_after_hours_pg.py`
4. **Ongoing:** Filter at insert time ensures only clean data enters

---

## Verification Commands

### Check if database is clean (should see ONLY hours 14-20)
```bash
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c \
  "SELECT EXTRACT(HOUR FROM timestamp)::INT as hour, COUNT(*) FROM bars GROUP BY hour ORDER BY hour;"
```

Expected output:
```
 hour | count
------+-------
   14 |  993
   15 | 1503
   16 | 1500
   17 | 1500
   18 | 1493
   19 | 1482
   20 | 1338
```

### Manual cleanup (if out-of-hours data reappears)
```bash
python3 optimizer/cleanup_after_hours_pg.py
```

---

## Key Files

| File | Purpose | Status |
|------|---------|--------|
| `optimizer/data_fetcher.py:13-37` | Filter function | ✅ Active |
| `optimizer/data_fetcher.py:292` | Apply filter before insert | ✅ Active |
| `optimizer/cleanup_after_hours_pg.py` | Manual cleanup tool | ✅ Available |
| `backend/postgres_init/02_ensure_market_hours_data.sql` | Auto cleanup on init | ✅ Active |

---

## Lessons Learned

1. **Filter at INSERT, not after:** Always apply filters before data enters database
2. **Migrations need validation:** Check for data integrity after schema migrations
3. **Keep cleanup tools:** Don't archive scripts just because they're "used once"
4. **Automate safeguards:** Docker init scripts prevent recurring issues
5. **Signal quality matters:** Removing out-of-hours data significantly improved optimization results

## Timeline

- **2026-04-27 21:12:** Filtering implemented, database cleaned to 6,397 bars
- **2026-04-28 13:59:** Historical files archived (cleanup_after_hours.py moved to NotUsed)
- **2026-04-28 ~14:00:** SQLite → PostgreSQL migration (dirty data transferred)
- **2026-04-30 morning:** User reports out-of-hours bars reappeared
- **2026-04-30 ~11:00:** Manual cleanup (438 bars removed) + automated solution implemented
