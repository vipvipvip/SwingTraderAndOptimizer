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
cd backend
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

## 3. Trade Sizing Consistency Across Backtest & Live

**Rule:** Backtest and live trading must use identical position sizing logic.

**How to apply:**
- Store allocation weights in database (single source of truth)
- Backtest reads allocation_weight when simulating trades
- Live trading reads same allocation_weight when executing
- Calculate shares the same way: `(capital * allocation_weight%) / entry_price`

**Why:** Backtest results become meaningless if live trading uses different sizing. A profitable backtest with 10% allocation might fail live with 100% allocation per trade.

**Session implementation:**
- Added `allocation_weight` column to tickers table (default 33.33%)
- Optimizer reads from Laravel DB before running backtests
- TradeExecutorService uses same formula for position sizing
- All three tickers (SPY/QQQ/IWM) tested with different allocations

---

## 4. API Endpoint Testing Before Commit

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

## 5. Database Migrations for Schema Changes

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

## 6. Parallelization for Long-Running Tasks

**Rule:** Use joblib for embarrassingly parallel workloads (grid search, batch processing).

**How to apply:**
```python
from joblib import Parallel, delayed

# Before: Sequential (87 minutes for 3 tickers)
for ticker in tickers:
    optimize_ticker(ticker)

# After: Parallel (30 minutes for 3 tickers, ~3x speedup)
results = Parallel(n_jobs=-1, verbose=10)(
    delayed(optimize_ticker)(ticker) for ticker in tickers
)
```

**Why:** Parameter optimization is CPU-bound and parallelizable. Sequential processing wastes compute.

**Session context:** Reduced optimizer runtime from 87 min to ~30 min for 3 tickers. Added `_optimize_with_ticker_label()` wrapper to show progress labels in parallel output.

---

## 7. Cross-Service Database Communication

**Rule:** When one service (Python) needs to read config from another service's DB (Laravel), create an explicit read function with error handling.

**How to apply:**
```python
# In db.py
def get_laravel_allocation_weight(self, symbol, default=10):
    """Fetch allocation_weight from Laravel database"""
    try:
        laravel_db_path = Path(__file__).parent.parent / 'backend' / 'database' / 'database.sqlite'
        if not laravel_db_path.exists():
            return default
        
        with sqlite3.connect(str(laravel_db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT allocation_weight FROM tickers WHERE symbol = ?', (symbol,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return float(row[0])
    except Exception:
        pass
    
    return default
```

**Why:** Graceful fallback prevents one service's DB failure from crashing another. Explicit path resolution is clearer than hardcoding.

---

## 8. API Documentation Integration

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

## 9. Graceful Degradation & Error Handling at Service Boundaries

**Rule:** Handle failures at service boundaries (file paths, external API calls) gracefully. Trust internal code.

**How to apply:**
- Try/except around file operations, with sensible defaults
- Log warnings but don't crash on non-critical failures
- Validate external input, not internal function results

**Why:** External systems fail. Internal code is trusted (covered by tests). Distinguishing them prevents cascading failures.

**Session example:** Optimizer querying Laravel DB for allocation_weight. If DB is unreachable, defaults to 10% instead of crashing.

---

## 10. Commit Strategy - Logical Separation

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
- Optimizer integration to read from DB
- TradeExecutorService calculation updates
- All tested and verified
```

---

## 11. Testing the Golden Path Before Shipping

**Rule:** Test the golden path (happy path) end-to-end before declaring done.

**How to apply:**
1. Create a new ticker allocation
2. Update it via API
3. Run optimizer
4. Verify backtest trades use the new allocation
5. Verify live trading would use it (or test with paper trading)
6. Check dashboard displays correct data

**Why:** Unit tests pass but integration fails silently. End-to-end testing catches misaligned assumptions across layers.

**Session instance:**
- Set SPY 50%, QQQ 30%, IWM 20%
- Tested via curl
- Verified servers restart cleanly
- Confirmed endpoint returns correct format

---

## 12. Environment Variables & Defaults

**Rule:** All dynamic paths and credentials come from `.env`. Provide `.env.example` with sensible defaults.

**How to apply:**
```env
# .env.example
DB_DATABASE=../optimizer/optimized_params/strategy_params.db
PYTHON_PATH=../optimizer/venv/Scripts/python.exe
NIGHTLY_SCRIPT=../optimizer/nightly_optimizer.py
TRADING_TIMEFRAME=1Hour
```

**Why:** `.env` is gitignored. New developers copy `.env.example` and customize for their machine. Prevents hardcoded paths.

---

## 13. Progress Visibility in Parallel Operations

**Rule:** When parallelizing work, add progress indicators showing which item is being processed.

**How to apply:**
```python
def _optimize_with_ticker_label(symbol, timeframe, param_grid):
    print(f"\n[{symbol}] Starting optimization...")
    return optimize_ticker(symbol, timeframe, param_grid=param_grid)
```

**Why:** Parallel work feels like it hangs if there's no output. Ticker labels let you see progress in real-time.

---

## 14. API Route Organization

**Rule:** Group related routes by resource. Keep route definitions and controller methods aligned.

**How to apply:**
```php
// Tickers resource group
Route::get('/tickers', [TickerController::class, 'index']);
Route::post('/tickers', [AdminController::class, 'addTicker']);
Route::delete('/tickers/{symbol}', [AdminController::class, 'removeTicker']);
Route::put('/tickers/{symbol}/allocation', [TickerController::class, 'updateAllocation']);

// Strategies resource group
Route::get('/strategies', [StrategyController::class, 'index']);
Route::get('/strategies/{symbol}', [StrategyController::class, 'show']);
```

**Why:** RESTful organization makes the API predictable and easy to navigate.

---

## 15. Database Schema Design for Multi-Service Access

**Rule:** When multiple services access the same data, use a shared database with clear ownership semantics.

**How to apply:**
- One "source of truth" table (e.g., tickers table in Laravel DB)
- Each service reads/writes to its area
- No service-specific hacks or sync loops
- Use migrations to evolve schema

**Why:** Dual databases lead to sync issues and stale data. Single source avoids that.

**Session context:**
- Tickers table (Laravel) → source of truth for allocations
- Strategy parameters table (both) → shared
- Backtest trades table (Laravel) → historical record
- Optimizer reads allocations at runtime, doesn't cache

---

## Summary of Key Learnings

1. **Restart everything after config changes** - Non-negotiable
2. **Use relative paths** - Portable, tested on day 1
3. **Match backtest ↔ live trade sizing** - Data integrity
4. **Test endpoints immediately** - Catch misconfigurations fast
5. **Migrations for schema** - Version-controlled, reversible
6. **Parallelize long tasks** - Massive speedup with joblib
7. **Cross-service DB reads need error handling** - Graceful fallback
8. **Verify doc generation → storage → UI path chain** - Common failure point
9. **Separate concerns in commits** - Easier debugging, clearer history
10. **End-to-end golden path test** - Before shipping

---

## 16. Long-Running Tasks Bypass Framework Schedulers

**Rule:** Tasks longer than the framework's execution timeout should bypass the scheduler entirely. Use OS-level scheduling (Windows Task Scheduler, cron) instead.

**How to apply:**
- Identify timeout-prone tasks (>60s in PHP, depends on framework default)
- Create a wrapper script (PowerShell on Windows, bash on Linux)
- Register with OS scheduler, not the framework
- Keep the artisan command for manual one-off triggers only

**Why:** PHP's default execution timeout is 60 seconds. The nightly optimizer takes ~87 minutes. If called via Laravel scheduler, it hits the limit and fails. OS scheduler has no timeout, executes natively.

**Session example:**
```
BEFORE: OptimizeNightly command in Kernel.php → PHP timeout → repeated MAX_EXECUTION_TIME errors

AFTER: 
  - Removed from Kernel.php (comments only)
  - Created optimizer/run_nightly.ps1 (Windows wrapper)
  - Created optimizer/run_nightly.sh (Linux wrapper)
  - Registered via OS scheduler (Task Scheduler on Windows, cron on Linux)
  - Stays responsive to manual artisan triggers: php artisan optimize:nightly
```

**Trade executor still in Laravel?** Yes—it's 30 seconds max, well under the 60s limit. Only move to OS scheduler if timeout is blocking.

---

## 17. Wrapper Scripts for Cross-Platform Execution

**Rule:** Create thin wrapper scripts that activate venv, log output, and report completion. Let OS scheduler handle the timing.

**How to apply - Windows (run_nightly.ps1):**
```powershell
$ErrorActionPreference = "Stop"
$OptimizerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $OptimizerDir

$LogDir = Join-Path $OptimizerDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "nightly.log"

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LogFile "[$ts] Nightly optimizer starting..."

$Python = Join-Path $OptimizerDir "venv\Scripts\python.exe"
& $Python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM 2>&1 | Tee-Object -FilePath $LogFile -Append

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LogFile "[$ts] Optimizer finished (exit: $LASTEXITCODE)"
```

**How to apply - Linux (run_nightly.sh):**
```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/nightly.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nightly optimizer starting..." >> "$LOG"
source "$SCRIPT_DIR/venv/bin/activate"
python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM >> "$LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Optimizer finished (exit: $?)" >> "$LOG"
```

**Why:** 
- Activates venv before running Python (not inherited from OS)
- Logs all output with timestamps (critical for debugging)
- Uses script directory as working dir (portable, no hardcoded paths)
- Reports success/failure (exit code)

**Session setup:**
- Windows: `scripts/setup-optimizer-wts.ps1` registers the wrapper with Task Scheduler
- Linux: `scripts/setup-optimizer-cron.sh` registers the wrapper with cron
- Both create `logs/` directory at runtime

---

## 18. Self-Hosted Assets for External Dependencies

**Rule:** For critical UI libraries (Swagger UI, Chart.js, etc.), download and serve them locally instead of relying on CDNs.

**How to apply:**
```bash
cd backend/public
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

**Session context:**
- Swagger UI was spinning (waiting for unpkg.com resources)
- Downloaded all .js/.css files locally to `backend/public/`
- Updated `resources/views/swagger.blade.php` to use local paths
- UI loaded instantly after

---

## 19. Manual Trigger Capability for Automated Tasks

**Rule:** Keep the artisan command for any task that's moved to OS scheduler. Allow manual one-off runs without waiting for the schedule.

**How to apply:**
```bash
# Keep the command class
php artisan optimize:nightly  # Runs immediately, regardless of schedule

# But remove from automatic schedule in Kernel.php
// $schedule->command('optimize:nightly')->dailyAt('02:00');  // REMOVED

// Add a comment explaining why
// Nightly optimizer is now managed by OS scheduler (see scripts/)
// Manual trigger still available: php artisan optimize:nightly
```

**Why:**
- Developers need to test without waiting for 2 AM
- Urgent re-optimizations happen outside the schedule
- Keep the command code but change the *trigger*, not the functionality
- Fails gracefully if OS scheduler hasn't run yet

**Session example:**
- Optimizer normally: 2 AM UTC via Task Scheduler/cron
- On-demand: `php artisan optimize:nightly` anytime
- Useful during development/testing without modifying Kernel.php

---

## 20. UI-Based Manual Triggers for Backend Tasks

**Rule:** Expose manual trigger buttons in the UI for any automated task, alongside OS/framework scheduling. Make it discoverable (top of dashboard) and low-friction (single click + status message).

**How to apply:**
```javascript
// Backend endpoint for manual trigger
async function triggerOptimizer() {
  optimizerRunning = true
  optimizerMessage = 'Running optimizer...'
  try {
    const res = await fetch('/api/v1/admin/optimize/trigger', { method: 'POST' })
    const data = await res.json()
    optimizerMessage = res.ok ? '✓ Optimizer completed' : `✗ Error: ${data.error}`
  } catch (e) {
    optimizerMessage = `✗ Error: ${e instanceof Error ? e.message : 'Unknown error'}`
  } finally {
    optimizerRunning = false
    setTimeout(() => optimizerMessage = '', 3000)  // Auto-dismiss
  }
}
```

**UI elements:**
- Button with visual feedback (disabled while running, shows "Running..." text)
- Status message below button (green for success, red for error)
- Auto-dismiss after 3 seconds
- Responsive design (stacks on mobile)

**Why:**
- Developers + operators can test without waiting for scheduled times
- Emergency re-runs or parameter re-tuning don't require CLI
- Status feedback shows task succeeded without checking logs
- Encourages exploration (users can experiment safely)

**Session implementation:**
- Added `⚙️ Trigger Optimizer` and `📈 Execute Trades` buttons to dashboard header
- Calls existing backend endpoints: `POST /api/v1/admin/optimize/trigger` and `POST /api/v1/admin/trades/trigger`
- Status messages with auto-dismiss
- Mobile-responsive layout

---

## Summary of Key Learnings (Updated)

1. **Restart everything after config changes** - Non-negotiable
2. **Use relative paths** - Portable, tested on day 1
3. **Match backtest ↔ live trade sizing** - Data integrity
4. **Test endpoints immediately** - Catch misconfigurations fast
5. **Migrations for schema** - Version-controlled, reversible
6. **Parallelize long tasks** - Massive speedup with joblib
7. **Cross-service DB reads need error handling** - Graceful fallback
8. **Verify doc generation → storage → UI path chain** - Common failure point
9. **Separate concerns in commits** - Easier debugging, clearer history
10. **End-to-end golden path test** - Before shipping
11. **OS scheduler for long tasks** - Bypass framework timeouts (87-min optimizer via WTS/cron)
12. **Wrapper scripts** - Activate venv, log output, portable across platforms
13. **Self-host external assets** - Don't depend on CDNs for critical UI
14. **Keep manual trigger** - Even if automated via OS scheduler
15. **UI-based triggers for automated tasks** - Low-friction manual execution with status feedback

---

## Technical Debt Identified (for future)

- L5-Swagger generation is fragile; consider custom OpenAPI generator or manual maintenance
- Path resolution logic in `database.php` could be extracted to a utility class
- Optimizer allocation_weight parameter should be a model field, not environment-dependent
- Backtest trades table could use composite index on (symbol, optimization_run) for faster filtering
- Consider a simple status dashboard showing when optimizer last ran (WTS task logs are hard to parse)

---

**Document created:** 2026-04-21  
**Last updated:** 2026-04-21  
**Sessions covered:** 
- 2026-04-20: Allocation weights implementation
- 2026-04-21: OS-level scheduler setup + Swagger UI fixes + UI manual triggers
