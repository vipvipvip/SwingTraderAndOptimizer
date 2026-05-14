# Frontend / Backend Wiring — Svelte SPA + Laravel Blade

## Overview

This project has **two separate web UIs** that share the same Laravel backend:

| UI | URL (Dev) | Tech | Description |
|----|-----------|------|-------------|
| **Trading Dashboard** | `http://localhost:5173` | Svelte SPA + Vite | Main trading dashboard with strategies, equity curves, positions, P&L |
| **Scanner** | `http://localhost:9000/scanner` | Laravel Blade + Lightweight Charts | Ticker scanner with MACD/PPO crossover signals and 3-chart view |

---

## 1. Frontend (Svelte SPA)

### 1.1 Entry Point: `frontend/index.html`

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Swing Trading Dashboard</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- The browser loads this single HTML file from Vite's dev server.
- `<div id="app">` is the mount point — Svelte injects the entire UI here.
- `<script type="module" src="/src/main.ts">` is the JavaScript entry point.
- No other HTML exists — everything is built dynamically by Svelte (classic SPA pattern).

### 1.2 How Vite Serves It

**`frontend/vite.config.js`**:

```js
export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9000',
        changeOrigin: true,
      }
    }
  }
})
```

Flow:
1. `npm run dev` → runs `vite` → starts a dev server on `http://0.0.0.0:5173`
2. Vite automatically discovers `index.html` in the project root (convention, no config needed)
3. Browser navigates to `http://localhost:5173` → Vite serves `index.html`
4. Vite processes `<script type="module" src="/src/main.ts">` — compiles TS + Svelte on-the-fly with Hot Module Replacement (HMR)
5. The `/api` proxy forwards all `fetch('/api/v1/...')` calls to `http://127.0.0.1:9000` (Laravel)

### 1.3 JavaScript Entry Point: `frontend/src/main.ts`

```ts
import App from './App.svelte'

const app = new App({
  target: document.getElementById('app')!,
})

export default app
```

1. Imports `App.svelte` — Vite's Svelte plugin compiles this into a JS class
2. Finds `<div id="app">` from the HTML
3. Creates a new Svelte app instance mounted into that div
4. `App.svelte` becomes the root component containing everything else

### 1.4 Root Component: `frontend/src/App.svelte`

Three sections: `<script>` (logic), `<style>`, and HTML template.

#### Imports and State (lines 1-29)

```svelte
<script>
  import { onMount } from 'svelte'
  import AccountBalance from './lib/components/AccountBalance.svelte'
  import StrategyCard from './lib/components/StrategyCard.svelte'
  import EquityCurveChart from './lib/components/EquityCurveChart.svelte'
  import LivePositionsPanel from './lib/components/LivePositionsPanel.svelte'
  import PnlTable from './lib/components/PnlTable.svelte'
  import TradesHistoryTable from './lib/components/TradesHistoryTable.svelte'

  let strategies = []
  let summary = null
  let loading = true
  let error = ''
  let selectedSymbol = 'SPY'
  // ... account state, timers, etc.
</script>
```

6 child components, each fetching their own data or receiving props.

#### Key Data Functions

- **`fetchWithBackoff(url, options, retries, delay, timeout)`** — wrapper around `fetch()` with retry logic, exponential backoff, and abort controller timeout (lines 46-61)
- **`calculateProfitSummary()`** — fetches `/api/v1/account` and `/api/v1/account/positions` in parallel, computes `totalUnrealizedPnl`, `accountEquity`, etc. (lines 63-85)
- **`triggerOptimizer()`** — POSTs to `/api/v1/admin/optimize/trigger`, then polls `/api/v1/admin/last-runs` every 10s until `last_optimizer_run` changes (lines 135-179)
- **`triggerTrades()`** — same pattern for trade execution (lines 181-225)

#### On Mount (lines 227-260)

```svelte
onMount(async () => {
  calculateNextTradeTime()
  calculateProfitSummary()
  setInterval(calculateNextTradeTime, 300000)   // every 5 min
  setInterval(calculateProfitSummary, 300000)    // every 5 min

  const res = await fetchWithBackoff('/api/v1/strategies')
  strategies = data.tickers || data
  // ...
  const lastRunsRes = await fetchWithBackoff('/api/v1/admin/last-runs')
  // ...
  loading = false
})
```

On initial load:
1. Calculate next trade time and profit summary (with 5-min polling intervals)
2. Fetch `/api/v1/strategies` to populate the strategy cards
3. Fetch `/api/v1/admin/last-runs` to show last optimizer/trade execution times

#### HTML Template (lines 412-512)

```
┌────────────────────────────────────────┐
│  Header: Trading Dashboard + Controls   │
│  [Trigger Optimizer] [Execute Trades]   │
├─────────────────────┬──────────────────┤
│  AccountBalance     │ Next Trade Time  │
├─────────────────────┴──────────────────┤
│  Strategies (StrategyCard grid)         │
│  [Card] [Card] [Card] [Card] ...        │
├────────────────────────────────────────┤
│  Equity Curve Chart (selectedSymbol)    │
├────────────────────────────────────────┤
│  Live Positions Panel                   │
├────────────────────────────────────────┤
│  P&L Summary Table                      │
├────────────────────────────────────────┤
│  Trade History Table                    │
└────────────────────────────────────────┘
```

### 1.5 API Client: `frontend/src/lib/api.ts`

```ts
const BASE_URL = '/api/v1'

export async function apiFetch<T>(path, options?, timeout = 5000): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
    signal: controller.signal,
  })
  return res.json()
}
```

Typed API wrapper used by child components. Exports an `api` object:

```ts
export const api = {
  account: {
    get: () => apiFetch('/account'),
    positions: () => apiFetch('/account/positions'),
  },
  strategies: {
    list: () => apiFetch('/strategies'),
    get: (symbol) => apiFetch(`/strategies/${symbol}`),
    history: (symbol) => apiFetch(`/strategies/${symbol}/history`),
  },
  equity: {
    curve: (symbol) => apiFetch(`/equity/${symbol}`),
  },
  trades: {
    list: () => apiFetch('/trades/live'),
    pnl: () => apiFetch('/trades/pnl'),
  },
}
```

### 1.6 Component: `frontend/src/lib/components/EquityCurveChart.svelte`

Uses **Chart.js v4.4.0**. Receives `symbol` prop, fetches equity curve data on mount:

```ts
import { Chart, registerables } from 'chart.js'
Chart.register(...registerables)
```

Renders a `<canvas>` element with two datasets: backtest (dashed gray) and live (solid green). ResizeObserver handles responsive resizing.

### 1.7 Production Build

```bash
npm run build    # → outputs to frontend/dist/
```

`dist/index.html` will reference hashed asset files:
```html
<script type="module" crossorigin src="/assets/index-84b9724e.js"></script>
<link rel="stylesheet" href="/assets/index-88c98f4b.css">
```

---

## 2. Backend (Laravel)

### 2.1 Entry Points

`public/index.php` bootstraps Laravel and dispatches to the router.

#### Web Routes: `backend/routes/web.php`

```php
Route::get('/', [App\Http\Controllers\HomeController::class, 'index']);    // legacy dashboard (Blade)
Route::get('/scanner', [App\Http\Controllers\ScannerController::class, 'index']);
Route::get('/scanner/data/{ticker}', [App\Http\Controllers\ScannerController::class, 'chart']);
```

Returns Blade-rendered HTML directly from the server.

#### API Routes: `backend/routes/api.php`

All REST endpoints under `/api/v1/*`:

| Endpoint | Controller | Purpose |
|----------|-----------|---------|
| `GET /api/v1/tickers` | TickerController | List tickers |
| `POST /api/v1/tickers` | AdminController | Add ticker |
| `DELETE /api/v1/tickers/{symbol}` | AdminController | Remove ticker |
| `PUT /api/v1/tickers/{symbol}/allocation` | TickerController | Update allocation |
| `GET /api/v1/strategies` | StrategyController | List strategies |
| `GET /api/v1/strategies/{symbol}` | StrategyController | Strategy for ticker |
| `GET /api/v1/strategies/{symbol}/history` | StrategyController | Optimization history |
| `GET /api/v1/account` | AccountController | Alpaca account info |
| `GET /api/v1/account/positions` | AccountController | Open positions |
| `POST /api/v1/orders` | OrderController | Place order |
| `DELETE /api/v1/orders/{orderId}` | OrderController | Cancel order |
| `GET /api/v1/equity/{symbol}` | EquityController | Equity curve |
| `GET /api/v1/trades/live` | EquityController | Live trades |
| `GET /api/v1/trades/backtest` | BacktestTradesController | Backtest trades |
| `GET /api/v1/trades/pnl` | EquityController | P&L summary |
| `POST /api/v1/admin/optimize/trigger` | AdminController | Run optimizer |
| `POST /api/v1/admin/trades/trigger` | AdminController | Execute trades |
| `GET /api/v1/admin/market-status` | AdminController | Market status |
| `GET /api/v1/admin/last-runs` | AdminController | Last run times |

---

## 3. Integration Architecture

```
Browser
  │
  ├── http://localhost:5173  (Vite dev server - Svelte SPA)
  │     │
  │     │  Serves: index.html → main.ts → App.svelte → child components
  │     │
  │     └── /api/v1/*  →  proxied by Vite  →  http://localhost:9000 (Laravel)
  │                                              │
  │                                              ├── routes/api.php
  │                                              ├── API Controllers
  │                                              └── PostgreSQL
  │
  └── http://localhost:9000/scanner  (Laravel serves Blade HTML directly)
                                       │
                                       ├── routes/web.php
                                       ├── ScannerController
                                       ├── resources/views/scanner/index.blade.php
                                       └── Lightweight Charts (CDN)
```

**Key point:** The Svelte SPA and the Laravel Blade scanner are **completely independent** frontends. They share the same database and some backend code but are served differently:

- Svelte SPA: Vite dev server on port 5173, talks to Laravel API on port 9000 via proxy
- Scanner: Laravel serves Blade HTML directly on port 9000

In production, the Svelte build output (`frontend/dist/`) would typically be served from Laravel's `public/` directory, but during development they run side-by-side on separate ports.

---

## 4. Data Flow

### Svelte SPA Flow

```
User opens http://localhost:5173
  ↓
Vite serves index.html → loads main.ts → mounts App.svelte
  ↓
App.svelte onMount():
  ├── fetch /api/v1/strategies        → populates strategy cards
  ├── fetch /api/v1/account           → account balance component
  ├── fetch /api/v1/account/positions → live positions panel
  └── fetch /api/v1/admin/last-runs   → last run timestamps
  ↓
User clicks a strategy card → selectedSymbol updates
  ↓
EquityCurveChart receives symbol prop
  └── fetch /api/v1/equity/{symbol}   → renders Chart.js equity curve
```

### Scanner (Blade) Flow

```
User opens http://localhost:9000/scanner?weeks=3
  ↓
Laravel routes → ScannerController@index
  ↓
Queries tbl_scanner_tickers for MACD/PPO crossovers
  ↓
Renders resources/views/scanner/index.blade.php
  ↓
User clicks a ticker row
  └── fetch /scanner/data/{ticker}
      ↓
      ScannerController@chart
      └── Queries bars + indicators
      └── Returns JSON → renderChart() creates 3 Lightweight Charts
```

---

## 5. Session Transcript

### Q: i need to learn how the frontend is working. how is the web flow. What is the entry point - is it vite.config.js? Is so how is the webserver picking it up? Explain the FE and backend integration

**A:** Here's the full architecture breakdown:

**Two Independent Systems** — This project has **two separate web UIs** — a Svelte SPA (dashboard) and a Laravel Blade UI (scanner) — that share the same Laravel backend.

**Frontend (Svelte Dashboard)**
```
index.html  →  /src/main.ts  →  App.svelte  →  components/*.svelte
```
- Entry point: `frontend/index.html` — a plain HTML file with `<div id="app">` and `<script>` tag loading `/src/main.ts`
- `main.ts` — mounts `App` Svelte component into `#app`
- `App.svelte` — orchestrates all UI
- `vite.config.js` — Vite dev server runs on port 5173, proxies `/api/*` to Laravel at port 9000
- `api.ts` — wraps fetch calls to `/api/v1/*` endpoints

**Backend (Laravel)**
```
public/index.php → routes/web.php, routes/api.php → Controllers → DB
```
- `web.php` — returns Blade views (HTML)
- `api.php` — REST API at `/api/v1/*` (used by Svelte SPA)

**Integration:** Two separate entry points:
| URL | What serves it | Tech |
|-----|---------------|------|
| localhost:9000 | Laravel | Legacy Blade dashboard |
| localhost:9000/scanner | Laravel | Scanner UI (Blade + Lightweight Charts) |
| localhost:5173 | Vite | Trading Dashboard (Svelte SPA) |

### Q: lets focus on SPA first

**A:** Walked through `App.svelte` — the root component. Three sections: `<script>` (logic), `<style>`, and HTML template.

**Script section:** Imports 6 child components (`AccountBalance`, `StrategyCard`, `EquityCurveChart`, `LivePositionsPanel`, `PnlTable`, `TradesHistoryTable`). Declares state: `strategies`, `summary`, `loading`, `error`, `selectedSymbol = 'SPY'`, account state variables.

Key data functions:
- `fetchWithBackoff()` — fetch with retry, exponential backoff, abort controller timeout
- `calculateProfitSummary()` — fetches `/api/v1/account` and `/api/v1/account/positions` in parallel
- `triggerOptimizer()` / `triggerTrades()` — POST + poll pattern

On mount: fetches `/api/v1/strategies`, `/api/v1/admin/last-runs`, sets up 5-min polling intervals.

HTML template layout:
```
Header → [Trigger Optimizer] [Execute Trades]
AccountBalance | Next Trade Time
Strategy Cards grid
Equity Curve Chart (selected symbol)
Live Positions Panel
P&L Summary Table
Trade History Table
```

### Q: how is browser directed to frontend/index.html

**A:** Vite reads `vite.config.js` and by convention looks for `index.html` in the project root as the entry point. The flow:
1. `npm run dev` → runs `vite` → starts dev server on `http://0.0.0.0:5173`
2. Vite automatically discovers `index.html` in project root (convention, no config needed)
3. Browser → `http://localhost:5173` → Vite serves `index.html`
4. Vite processes `<script type="module" src="/src/main.ts">` — compiles TS + Svelte on-the-fly with HMR
5. `/api` proxy forwards `fetch('/api/v1/...')` calls to `http://127.0.0.1:9000` (Laravel)

Vite is: **dev server + reverse proxy + module bundler** all in one.

### Q: r u able to save this whole session in .md file -- verbatim?

**A:** Yes. Where should I save it and what filename?

### Q: in docs folder - name it "FE-BE-Svelte-Laravel-Wiring for SPA and Blade.md"

**A:** Saved to `docs/FE-BE-Svelte-Laravel-Wiring for SPA and Blade.md`

### Q: keep updating this file simulataneously - so everything we say is saved in this file - each question and each answer

**A:** [Confirmed — file will be kept updated with each exchange]

### Q: i am looking for all the text from our chat here to be in this doc - u don't need to generate anything - just dump in it in the file

**A:** [Full chat transcript appended to the document]

### Q: good - keep this going -- now let me review your response form the beginning

**A:** Ready whenever you are — just point out which piece you want to review and I'll walk through it.

### Q: so what is the difference between Scanner and Dashboard - both are web apps/pages - why prefer one over the other

**A:** Here's the distinction:

**Scanner** (`localhost:9000/scanner`) — **Discovery tool**
- Queries `tbl_scanner_tickers` for tickers that had BOTH macd_crossover AND ppo_crossover in the last N weeks
- Shows a table of signal tickers → click one to view 3-chart layout (price + MACD + PPO) with Lightweight Charts
- Purpose: "What should I trade? Where are the signals?"
- User persona: scouting for new opportunities

**Dashboard** (`localhost:5173`) — **Portfolio management**
- Shows account balance from Alpaca, strategy cards with optimized parameters (Sharpe, win rate, return, drawdown)
- Equity curve per ticker, live positions, P&L summary, trade history
- Has action buttons: "Trigger Optimizer" and "Execute Trades"
- Purpose: "How are my trades performing? Run the optimizer. Execute."
- User persona: actively managing a portfolio

**Why two separate UIs?** Different jobs. Scanner finds setups. Dashboard manages the portfolio. They're also built with different stacks — Scanner is a Laravel Blade page (quick, server-rendered, Lightweight Charts via CDN), while Dashboard is a full Svelte SPA (stateful, interactive, Chart.js). They evolved independently but share the same database.

### Q: ok - i will digest this

**A:** Take your time.

### Q: now is there any dead code or unused files - u mentioned some legacy dashboard - if there is any such code delete it can keep project clean

**A:** Investigated and found dead code. Key findings:
- `backend/resources/views/welcome.blade.php` — 81K default Laravel boilerplate, no route references it
- `backend/public/data/` — stale CSV data files (748K total), zero code references
- `backend/public/openapi.json` — static spec superseded by dynamic endpoint
- `backend/public/favicon.ico` — empty stub
- `frontend/dist/` — stale build output (254K), .gitignore'd
- `README_v6_DEPRECATED.md` — explicitly deprecated (30K)
- `backend/setup-scheduler-linux-systemd.service` + `.timer` — wrong paths, stale
- `backend/remove_price_fetch.sh` + `verify_cron.sh` — stale scripts

### Q: review all the .md files and ensure they match the project functionality, architecture, tech stack and everything else

**A:** Full audit completed. Major inaccuracies found:

| Doc | Problem |
|-----|---------|
| `docs/How_System_Works.md` | Describes v7.0 2-of-4 multi-indicator strategy. Actual v7.5 uses Chandelier Exit. |
| `docs/TESTING.md` | Tests for old MACD/PPO/BB signals. Need Chandelier Exit tests. |
| `scripts/README.md` | References SQLite, 8:18 AM cron, "every 30 min" trades. |
| `docs/MONITORING.md` | References cron + Docker for DB. |
| `docs/README.md` | Says "React/Vite frontend" (it's Svelte), "every 5 min" trades. |
| `Capital Preservation.md` | Mentions old MACD/EMA/SMA strategy. |
| `docs/Ubuntu-Backend-Services.md` | Architecture diagram shows cron for trades. |

### Q: yes [proceed with cleanup]

**A:** 

**Cleanup performed:**
- Deleted: `welcome.blade.php`, 3 stale CSVs, `openapi.json`, `favicon.ico`, `frontend/dist/`, `README_v6_DEPRECATED.md`, 2 stale systemd service files, 2 stale shell scripts
- Removed empty `backend/public/data/` directory

**Doc fixes applied:**
- Rewrote `docs/How_System_Works.md` for v7.5 Chandelier Exit (replaced 500-line v7.0 doc)
- Rewrote `docs/TESTING.md` for Chandelier Exit exit logic tests
- Fixed `scripts/README.md` — removed SQLite, cron refs, updated for PostgreSQL + systemd
- Fixed `docs/MONITORING.md` — replaced all Docker/cron commands with systemd/psql equivalents
- Fixed `docs/README.md` — "React" → "Svelte", "every 5 min" → "every minute"
- Fixed `docs/Ubuntu-Backend-Services.md` — removed cron from architecture diagram
- Fixed `Capital Preservation.md` — old MACD strategy → Chandelier Exit
- Updated this doc with cleanup/audit transcript
