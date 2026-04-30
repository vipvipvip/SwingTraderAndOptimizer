# PostgreSQL Initialization Scripts

Files in this directory are automatically executed by Docker during database initialization (first startup).

## How It Works

When `docker-compose up` starts the PostgreSQL container:
1. Container creates empty database from schema
2. Laravel migrations run (via `php artisan migrate`)
3. All `.sql` files in `/docker-entrypoint-initdb.d/` are executed in alphabetical order
4. Any seed data or cleanup operations happen here

## Scripts in This Directory

### `02_ensure_market_hours_data.sql`
**Purpose:** Guarantees bars table contains ONLY market hours data

**What it does:**
- Removes any bars outside 14:00-20:00 UTC (9:30 AM - 4:00 PM ET)
- Runs after migrations to ensure data integrity
- Handles cases where historical data was migrated with out-of-hours bars

**Why it exists:**
- During SQLite → PostgreSQL migration, old out-of-hours bars were transferred
- This script ensures fresh databases never have this problem
- New bars fetched by optimizer are already filtered via `filter_market_hours()`

## Adding More Scripts

To add additional initialization logic:
1. Create a `.sql` file (or `.sh` script)
2. Name it with a number prefix (e.g., `01_`, `03_`) — they run in alphabetical order
3. Place in this directory
4. On next fresh database (`docker-compose down -v && docker-compose up`), it will execute

## Testing

To verify initialization runs correctly:
```bash
# Fresh start
docker-compose down -v
docker-compose up

# Check that cleanup ran
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c \
  "SELECT EXTRACT(HOUR FROM timestamp)::INT as hour, COUNT(*) FROM bars GROUP BY hour ORDER BY hour;"

# Should show ONLY hours 14-20 (no data in 0-13 or 21-23)
```

## Important Notes

- **Scripts only run on first database creation** (fresh `docker-compose up`)
- To re-run on an existing database, you must: `docker-compose down -v && docker-compose up`
- The `-v` flag removes all volumes (wipes database), so be careful!
- For manual cleanup without recreating database, use: `optimizer/cleanup_after_hours_pg.py`
