# SwingTrader Documentation

Guide to `common/docs/`. The single source of truth for what's actually live is
**`AGENTS.md`** (repo root) — every doc here should agree with it; if one doesn't, trust
AGENTS.md and the code over the doc.

---

## Start here

- **[BUY_SELL_TRIGGERS.md](BUY_SELL_TRIGGERS.md)** — what causes each live strategy
  (CoreEG100, MTF Top-N stock+ETF legs, Daily Signal) to actually buy or sell, verified
  against the code. The fastest way to answer "why did/didn't this trade."
- **`AGENTS.md`** (repo root) — architecture, live strategy table, operating rules,
  known invariants. Read this first for anything beyond buy/sell logic.

## Strategy history & research

- **[TRADING_STRATEGIES.md](TRADING_STRATEGIES.md)** — per-strategy deep dive (universe,
  parameters, execution flow, backtests). ⚠️ Its CoreEW section (§1) still describes the
  retired weekly-ratchet gate ("variant S"), not CoreEG100 — use BUY_SELL_TRIGGERS.md or
  AGENTS.md for the current CoreEW trigger until this is refreshed.
- **[perf_explanations.md](perf_explanations.md)** — dated research log (exit-logic bugs,
  live-vs-backtest gaps, lookahead audits). Each entry is timestamped and later corrections
  are appended inline rather than rewriting history — read it as a log, not a current-state doc.
- **[HANDOFF_DailySignal_All3CO.md](HANDOFF_DailySignal_All3CO.md)** — Daily Signal
  all-3-CO service: settled-bar/quality-gate conventions, Slack format, verification steps.
- **[HANDOFF_CoreEW_rename.md](HANDOFF_CoreEW_rename.md)** — historical handoff from the
  CHAND→CoreEW rename + intraday drift-gate/gain-rake work. Superseded by CoreEG100; kept
  for context on how the current driver's predecessor worked.
- **[mtf-infra-refactor-plan.md](mtf-infra-refactor-plan.md)** — archived infra plan.

## Operations

- **[ALPACA_KEYS.md](ALPACA_KEYS.md)** — which `.env` file and account each key pair
  belongs to, and the exact failure mode when they're mixed up. Open this whenever keys rotate.
- **[services_doc/](services_doc/)** — the current systemd unit files (source of truth for
  what's enabled/disabled/schedule); start with **[services_doc/README.md](services_doc/README.md)**
  for the full inventory (every unit's live status, schedule, and purpose, cross-checked
  against `systemctl`/`crontab` directly) — plus service-specific docs: `mtf_daily_runner.md`
  (MTF Top-N architecture), `earnings_screener.md`, `sec_research_guide.md`,
  `comprehensive_research.md`, `advanced_research.md`.

## Setup & commands

- **[UBUNTU_SETUP.md](UBUNTU_SETUP.md)** / **[COMMAND_REFERENCE.md](COMMAND_REFERENCE.md)**
  — ⚠️ **Pre-restructure.** Both predate the move of backend/frontend/scanner/optimizer into
  `swingtrader/` and predate CoreEW/MTF — paths (`cd backend`, `cd optimizer`,
  `tbl_etf_tickers_1hour`) and the optimizer/every-minute-executor sections throughout no
  longer match the codebase. Kept for whoever eventually rewrites them for the current
  layout; don't run commands from either without checking the real path first. For accurate
  current commands, prefer `services_doc/` (systemd) and `AGENTS.md` (console commands per
  driver).

## Development

- **[BEST_PRACTICES.md](BEST_PRACTICES.md)** — general engineering practices (cache/restart
  discipline, migrations, commit hygiene, error handling at service boundaries). Cleaned up
  2026-09-27 to drop the sections that were entirely about the retired nightly optimizer.
- **[FE-BE-Svelte-Laravel-Wiring for SPA and Blade.md](FE-BE-Svelte-Laravel-Wiring%20for%20SPA%20and%20Blade.md)**
  — how the Svelte SPA and Laravel Blade sides wire together (entry points, routes, data flow).
- **[How-to-debug-scripts.md](How-to-debug-scripts.md)** — `debugpy` attach workflow for the
  Python venvs (stock-analyzer, scanner, optimizer).
- **[stats-helper.md](stats-helper.md)** — plain-English guide to the significance tests used
  to judge whether a strategy's backtest edge is real (paired t-test, bootstrap CI, binomial,
  Cohen's d).

## Stock research (R&D Adoption Framework)

- **[Stock-Research/SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md](Stock-Research/SEC_FILING_METHODOLOGY_WITH_ACTUAL_DATA.md)**
  — the SEC-filing-first methodology behind the `stock-analysis` skill.
- **[Stock-Research/VSCODE_AUTOMATION_PROMPT_COMPLETE.md](Stock-Research/VSCODE_AUTOMATION_PROMPT_COMPLETE.md)**
  — the automation prompt built on that methodology.
- **[Stock-Research/RnD/](Stock-Research/RnD/)** — working notes from an Aug 2026 BDX/ZBRA/SMTC
  research pass; catalyst dates in it have since passed. Superseded by the formalized
  `stock-analysis` skill — treat as historical, not a live watchlist.

---

## Removed 2026-09-27

**Described the dead pre-CoreEW/MTF architecture** (superseded by AGENTS.md + `services_doc/`):
`How_System_Works.md`, `MONITORING.md`, `TESTING.md`, `MARKET_HOURS_FILTERING.md` — all
described the pre-CoreEW/MTF architecture (Chandelier+LinReg strategy, nightly grid-search
optimizer, trade executor firing every minute via `php artisan schedule:run`), none of which
is still live. `MARKET_HOURS_FILTERING.md` was additionally a postmortem for a pipeline
(`optimizer/data_fetcher.py`, `tbl_etf_tickers_1hour`) since replaced by the scanner service's
partitioned tables.

**Junk/misplaced/superseded:**
- `Key docs common docs TRADING.txt` — unstructured chat-dump; listed CHAND as live
  (pre-dates even the retired variant-S era) and duplicated TRADING_STRATEGIES.md/ALPACA_KEYS.md.
- `secure_backup_options.md` — about securing an unrelated Azure MySQL backup script
  (`backup-mysql.sh`/`db-list.csv`), not this project's Postgres `swingtrader-db`.
- `Github-SSH-COMMANDS.md` — one-time WSL git-auth fix; superseded now that git auth goes
  through the GitHub CLI token.
- `stock-analyzer/` — empty directory, never populated, no git history.

Previously removed: `NEW_SERVER_SETUP.md` (incomplete, SQLite-based), `FE-BE-Flow.md`
(outdated API endpoints) — both removed 2026-04-30.

---

## System Summary

**SwingTrader** finds and trades entries across three independent live strategies, all on
$1M/$100K Alpaca paper accounts:

1. **CoreEG100** — whole-book equal-weight QQQ/VTI/VTV, gated all-in/all-out by an index
   EMA(100) crossover. Checked every 5 min, trades only on a state flip.
2. **MTF Top-N** — daily rotation into the top-10 stocks / top-3 ETFs by weekly EMA/SMA gap
   score, once/day at 10:25 ET, with a daily-ATR ratchet exit on the stock leg.
3. **Daily Signal** — Slack-only alert (no orders) when a ticker completes all three of
   weekly/daily/hourly EMA(10)>SMA(40), once/day at 17:00 ET.

See [BUY_SELL_TRIGGERS.md](BUY_SELL_TRIGGERS.md) for exactly how each one decides, and
`AGENTS.md` for everything else (operating rules, key routing, known invariants, server
uptime reality).

**Infrastructure:** PostgreSQL (`swingtrader-db`, Docker) · Laravel backend (port 9000) ·
Svelte/Vite frontend (port 5173) · systemd services/timers for everything scheduled (see
`services_doc/`) — there is no framework-level (`php artisan schedule:run`) trade execution
anymore; every live driver is either an OS cron entry (CoreEG100) or a systemd timer (MTF,
Daily Signal, scanner ingestion).

---

## External Resources

- **Alpaca Trading API:** https://alpaca.markets/docs/
- **Laravel Documentation:** https://laravel.com/docs/
- **PostgreSQL Documentation:** https://www.postgresql.org/docs/
- **Systemd Documentation:** `man systemd`
