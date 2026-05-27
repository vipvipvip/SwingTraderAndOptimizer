# Market Hours Data Filtering

## Critical Issue: Bars Table Must Only Contain Market Hours Data

### Correct Market Hours (UTC)
- **Valid Range:** 13:00 - 20:00 UTC (hourly bars at :30 minutes)
- **Represents:** 9:30 AM - 4:30 PM EDT (US stock market hours + final bar)
- **Hourly Timestamps:** 13:30, 14:30, 15:30, 16:30, 17:30, 18:30, 19:30, 20:30 UTC

### Why This Matters
- Out-of-hours bars cause incorrect backtests and equity curve calculations
- Data outside 13:00-20:00 UTC (hours 13-20) represents pre-market (0-12 UTC) or after-hours (21-23 UTC) trading
- These periods have low liquidity and should not be included in optimization
- Signal parameters deteriorate significantly with noisy after-hours data
- Critical: Each ticker must have exactly 8 bars per trading day for consistent signal quality

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

### Root Cause — FILTER BUG FOUND
- **Filter boundary too restrictive:** Used `<= '16:00'` ET (4:00 PM) instead of `<= '16:30'` ET
- **Result:** Missing the 4:30 PM bar (hour 20 starting at :30 minutes)
- **Missing first bar too:** Hour 13 (9:30 AM ET) was excluded
- **Actual bars fetched:** Only 7 per day instead of 8
- **OLD bars:** Also contaminated from SQLite migration

### The Fixes Applied (2026-04-30)

**1. Filter Range Fixed in Code:**
```python
# OLD (missing 8th bar):
market_hours = (df_copy['_time_str'] >= '09:30') & (df_copy['_time_str'] <= '16:00')

# NEW (includes all 8 bars):
market_hours = (df_copy['_time_str'] >= '09:30') & (df_copy['_time_str'] <= '16:30')
```

**2. Database UTC Range Fixed:**
```sql
-- OLD (7 hours):
WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 14 AND 20

-- NEW (8 hours):
WHERE EXTRACT(HOUR FROM timestamp)::INT NOT BETWEEN 13 AND 20
```

- All 8 bars now included: 13:30, 14:30, 15:30, 16:30, 17:30, 18:30, 19:30, 20:30 UTC
- Corresponds to: 9:30, 10:30, 11:30, 12:30, 1:30 PM, 2:30 PM, 3:30 PM, 4:30 PM ET

### How to Prevent This Forever
1. **Docker Init Script:** Now runs during `docker-compose up` (automatic)
2. **New Databases:** Never start with out-of-hours data
3. **Existing Databases:** Can be cleaned manually with `cleanup_after_hours_pg.py`
4. **Ongoing:** Filter at insert time ensures only clean data enters

---

## Verification Commands

### Check if database is clean (should see ONLY hours 13-20)
```bash
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c \
  "SELECT EXTRACT(HOUR FROM timestamp)::INT as hour, COUNT(*) FROM bars GROUP BY hour ORDER BY hour;"
```

Expected output (8 consecutive hours, no gaps):
```
 hour | count
------+-------
   13 |  ~500
   14 | ~1000+
   15 | ~1500+
   16 | ~1500+
   17 | ~1500+
   18 | ~1500+
   19 | ~1500+
   20 | ~1300+
```

**Verify 8 bars per ticker per day:**
```bash
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c \
  "SELECT t.symbol, DATE(b.timestamp), COUNT(*) as bar_count FROM bars b JOIN tickers t ON b.ticker_id = t.id GROUP BY t.symbol, DATE(b.timestamp) ORDER BY t.symbol, DATE(b.timestamp) DESC LIMIT 15;"
```

Expected: Each row should show exactly 8 bars per ticker per trading day.

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
