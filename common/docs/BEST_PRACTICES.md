# Development Best Practices - SwingTrader Project

Based on session work from 2026-04-20/21, implementing allocation weights system and API endpoints.

## 1. Configuration & Cache Management + Server Restart

**Rule:** After ANY code changes, YOU (the agent) must clear config/cache AND restart the servers. Never ask the user to test without doing this first.

**How to apply:**
```bash
# 1. Clear cache
php artisan config:clear && php artisan cache:clear

# 2. Kill old backend process (Ctrl+C in terminal)
# 3. Restart backend fresh
cd swingtrader/backend
php artisan serve --host=127.0.0.1 --port=9000

# 4. THEN tell user "Ready to test" — don't ask them to restart
```

**Why:** 
- Laravel caches routes and config in memory. Old code persists until process restarts
- Frontend caches API responses. Stale data causes apparent failures
- The user shouldn't have to restart — that's your job after making changes
- Asking "restart and try again" adds friction and means you forgot step 2-3

**Evidence:** Implemented trigger endpoints, cleared cache, but forgot to restart server. User had to remind: "always restart after each change before u ask me to test"

---

## 2. Path Portability - Use Relative Paths

**Rule:** Convert absolute file paths to relative paths throughout the project. Use `../` notation relative to the executing file.

**How to apply:**
- `.env` files: Use `../optimizer/...` instead of `C:/absolute/path/...`
- Database config: Implement custom path normalization to handle `..` properly
- Environment variables: Always test path resolution on different machines before committing

**Why:** Absolute paths break when the project moves to a different machine or drive. Relative paths work universally.

**Example from session:**
```php
// Before (breaks on different machines)
DB_DATABASE=C:/data/Program Files/SwingTraderAndOptimizer/optimizer/optimized_params/strategy_params.db

// After (works anywhere)
DB_DATABASE=../optimizer/optimized_params/strategy_params.db
```

---

## 3. API Endpoint Testing Before Commit

**Rule:** Test every endpoint immediately after creation with curl. Don't assume it works.

**How to apply:**
```bash
# Create endpoint → implement method → test via curl
curl -X PUT http://localhost:9000/api/v1/tickers/SPY/allocation \
  -H "Content-Type: application/json" \
  -d '{"allocation_weight": 50}'
```

**Why:** Silent failures are worse than obvious ones. An endpoint might be routed but the method doesn't exist, or validation fails silently. Testing immediately catches these.

**Session instance:** Allocation endpoint was created and routed before being tested. Initial test confirmed 200 OK and correct response format.

---

## 4. Database Migrations for Schema Changes

**Rule:** Use Laravel migrations for any database schema changes. Never modify database directly.

**How to apply:**
```bash
# Create migration
php artisan make:migration add_allocation_weight_to_tickers

# Edit migration file with up() and down() methods
# Run it
php artisan migrate

# Confirm in database
```

**Why:** Migrations are version-controlled, reversible, and document what changed and when. Direct DB modifications are lost and can't be rolled back.

---

## 5. Parallelization for Long-Running Tasks

**Rule:** Use joblib for embarrassingly parallel workloads (backtest sweeps, batch processing).

**How to apply:**
```python
from joblib import Parallel, delayed

# Before: Sequential
for ticker in tickers:
    process_ticker(ticker)

# After: Parallel (~3x speedup on a multi-core box)
results = Parallel(n_jobs=-1, verbose=10)(
    delayed(process_ticker)(ticker) for ticker in tickers
)
```

**Why:** CPU-bound, per-ticker work is embarrassingly parallel. Sequential processing wastes compute.

---

## 6. Cross-Service Database Communication

**Rule:** When one service (Python) needs to read config from another service's DB (Laravel/Postgres), create an explicit read function with error handling and a sensible default.

**How to apply:**
```python
# In db.py
def get_laravel_value(self, query, params, default=None):
    """Fetch a value from the Laravel-owned Postgres DB, with graceful fallback."""
    try:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            if row and row[0] is not None:
                return row[0]
    except Exception:
        pass

    return default
```

**Why:** Graceful fallback prevents one service's DB failure from crashing another. Explicit read functions are clearer than ad-hoc queries scattered through the codebase.

---

## 7. API Documentation Integration

**Rule:** Keep generated OpenAPI docs in a location where the UI expects them. Verify the path chain: Generator → Storage → UI.

**How to apply:**
1. Identify where Swagger UI loads docs from (check JavaScript in template)
2. Configure L5-Swagger to generate to that exact location
3. Test generation and verify file updates with `stat` command
4. When generation fails, restore from git and manually edit JSON

**Why:** L5-Swagger configuration can be opaque. If docs don't appear in UI, it's usually a path mismatch, not a code issue.

**Session discovery:**
- Swagger UI template: `resources/views/swagger.blade.php`
- Loads from: `/openapi.json` (JavaScript `url` parameter)
- Disk location: `public/openapi.json`
- L5-Swagger config issue: Was generating to `storage/api-docs/` instead
- Solution: Restore file from git, manually add endpoint JSON to `/api/v1/tickers/{symbol}/allocation`

---

## 8. Graceful Degradation & Error Handling at Service Boundaries

**Rule:** Handle failures at service boundaries (file paths, external API calls) gracefully. Trust internal code.

**How to apply:**
- Try/except around file operations, with sensible defaults
- Log warnings but don't crash on non-critical failures
- Validate external input, not internal function results

**Why:** External systems fail. Internal code is trusted (covered by tests). Distinguishing them prevents cascading failures.

---

## 9. Commit Strategy - Logical Separation

**Rule:** Each commit should be a single logical change. Separate refactors, schema changes, and feature implementation.

**How to apply:**
```bash
# One commit: Schema + migration
# One commit: Model + controller changes
# One commit: Feature implementation + tests
# One commit: Documentation + configuration
```

**Why:** Bisectability. If a bug appears, you can `git bisect` to find the exact commit that introduced it. Mixed changes make debugging harder.

**Session commitment:**
```
feat: allocation weights for trade sizing
- Add allocation_weight column (migration)
- Backend API endpoint for updates
- TradeExecutorService calculation updates
- All tested and verified
```

---

## 10. Testing the Golden Path Before Shipping

**Rule:** Test the golden path (happy path) end-to-end before declaring done.

**How to apply:**
1. Make the change
2. Exercise it through the real interface (API call, UI action, CLI command)
3. Verify the downstream effect (DB row, Slack message, order placed) — not just the immediate response
4. Check dashboard/UI displays correct data

**Why:** Unit tests pass but integration fails silently. End-to-end testing catches misaligned assumptions across layers.

---

## 11. Environment Variables & Defaults

**Rule:** All dynamic paths and credentials come from `.env`. Provide `.env.example` with sensible defaults.

**How to apply:**
```env
# .env.example
DB_CONNECTION=pgsql
DB_DATABASE=swingtrader
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

**Why:** `.env` is gitignored. New developers copy `.env.example` and customize for their machine. Prevents hardcoded paths/credentials.

---

## 12. Progress Visibility in Parallel Operations

**Rule:** When parallelizing work, add progress indicators showing which item is being processed.

**How to apply:**
```python
def _process_with_label(symbol, *args):
    print(f"\n[{symbol}] Starting...")
    return process(symbol, *args)
```

**Why:** Parallel work feels like it hangs if there's no output. Per-item labels let you see progress in real-time.

---

## 13. API Route Organization

**Rule:** Group related routes by resource. Keep route definitions and controller methods aligned.

**How to apply:**
```php
// Tickers resource group
Route::get('/tickers', [TickerController::class, 'index']);
Route::post('/tickers', [AdminController::class, 'addTicker']);
Route::delete('/tickers/{symbol}', [AdminController::class, 'removeTicker']);

// Strategies resource group
Route::get('/strategies', [StrategyController::class, 'index']);
Route::get('/strategies/{symbol}', [StrategyController::class, 'show']);
```

**Why:** RESTful organization makes the API predictable and easy to navigate.

---

## 14. Database Schema Design for Multi-Service Access

**Rule:** When multiple services access the same data, use a shared database with clear ownership semantics.

**How to apply:**
- One "source of truth" table per concern (e.g., `mtf_positions` for MTF holdings)
- Each service reads/writes to its area
- No service-specific hacks or sync loops
- Use migrations to evolve schema

**Why:** Dual databases lead to sync issues and stale data. Single source avoids that.

---

## 15. Self-Hosted Assets for External Dependencies

**Rule:** For critical UI libraries (Swagger UI, Chart.js, etc.), download and serve them locally instead of relying on CDNs.

**How to apply:**
```bash
cd swingtrader/backend/public
curl -O https://unpkg.com/swagger-ui-dist@3/swagger-ui.css
curl -O https://unpkg.com/swagger-ui-dist@3/swagger-ui.js
curl -O https://unpkg.com/swagger-ui-dist@3/swagger-ui-bundle.js
curl -O https://unpkg.com/swagger-ui-dist@3/swagger-ui-standalone-preset.js
```

Then update the template:
```html
<!-- Before: CDN (network dependent) -->
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@3/swagger-ui.css">
<script src="https://unpkg.com/swagger-ui-dist@3/swagger-ui.js"></script>

<!-- After: Local (always available) -->
<link rel="stylesheet" href="/swagger-ui.css">
<script src="/swagger-ui.js"></script>
```

**Why:**
- CDN outages or network issues block the UI entirely
- Offline environments (corporate networks) can't load external resources
- Local assets load instantly, no network latency
- No dependency on unpkg.com availability

---

## Summary of Key Learnings

1. **Restart everything after config changes** - Non-negotiable
2. **Use relative paths** - Portable, tested on day 1
3. **Test endpoints immediately** - Catch misconfigurations fast
4. **Migrations for schema** - Version-controlled, reversible
5. **Parallelize long tasks** - Massive speedup with joblib
6. **Cross-service DB reads need error handling** - Graceful fallback
7. **Verify doc generation → storage → UI path chain** - Common failure point
8. **Separate concerns in commits** - Easier debugging, clearer history
9. **End-to-end golden path test** - Before shipping
10. **Self-host external assets** - Don't depend on CDNs for critical UI

---

**Document created:** 2026-04-21  
**Last updated:** 2026-09-27
