# SwingTrader Documentation

Complete guide to the automated swing trading platform.

---

## 📚 Core Documentation

### System Overview
- **[How_System_Works.md](How_System_Works.md)** — Architecture, data flow, and component breakdown. **Start here.**

### Setup & Deployment
- **[UBUNTU_SETUP.md](UBUNTU_SETUP.md)** — Ubuntu/Linux setup guide with dependencies and basic configuration
- **[WSL_SETUP.md](WSL_SETUP.md)** — Windows Subsystem for Linux 2 setup guide (fully compatible)
- **[Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md)** — Systemd service for Laravel backend (recommended for production)
- **[Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md)** — Systemd service for frontend (dev or production mode)

### Operations & Maintenance
- **[MONITORING.md](MONITORING.md)** — Daily health checks, troubleshooting, and common issues
- **[COMMAND_REFERENCE.md](COMMAND_REFERENCE.md)** — All useful commands for database, Docker, Python, Git, and systemd

### Development
- **[BEST_PRACTICES.md](BEST_PRACTICES.md)** — Development guidelines learned from session work
- **[TESTING.md](TESTING.md)** — Testing strategy and integration test information
- **[MARKET_HOURS_FILTERING.md](MARKET_HOURS_FILTERING.md)** — How market hours filtering works and the fix from 2026-04-30

### Future Plans
- **[DATABASE_PORTABILITY_PLAN.md](DATABASE_PORTABILITY_PLAN.md)** — Plan for making the database portable across systems (pending review)

---

## 🎯 Quick Navigation

**I want to...**

| Task | Document |
|------|----------|
| Understand how the system works | [How_System_Works.md](How_System_Works.md) |
| Set up on Windows (WSL2) | [WSL_SETUP.md](WSL_SETUP.md) |
| Set up on a new Ubuntu server | [UBUNTU_SETUP.md](UBUNTU_SETUP.md) + [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) |
| Run the frontend as a service | [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md) |
| Monitor daily operations | [MONITORING.md](MONITORING.md) |
| Run a specific command | [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) |
| Understand development rules | [BEST_PRACTICES.md](BEST_PRACTICES.md) |
| Debug market hours filtering | [MARKET_HOURS_FILTERING.md](MARKET_HOURS_FILTERING.md) |
| Write/run tests | [TESTING.md](TESTING.md) |

---

## 📋 Documentation Status

| Document | Status | Purpose |
|----------|--------|---------|
| How_System_Works.md | ✅ Current | System architecture and flow |
| UBUNTU_SETUP.md | ✅ Updated 2026-04-30 | Linux setup guide |
| WSL_SETUP.md | ✅ New 2026-04-30 | Windows WSL2 setup guide |
| Ubuntu-Backend-Services.md | ✅ Current | Production backend service |
| Ubuntu-Frontend-Services.md | ✅ Current | Production frontend service |
| MONITORING.md | ✅ Updated 2026-04-30 | Operations guide |
| COMMAND_REFERENCE.md | ✅ Current | Command reference |
| BEST_PRACTICES.md | ✅ Current | Development rules |
| TESTING.md | ✅ Current | Test strategy |
| MARKET_HOURS_FILTERING.md | ✅ Current | Market hours data handling |
| DATABASE_PORTABILITY_PLAN.md | 📋 Plan | Future work (pending review) |

---

## 🗑️ Removed (Legacy)

- `NEW_SERVER_SETUP.md` — Incomplete, SQLite-based (removed 2026-04-30)
- `FE-BE-Flow.md` — Referenced outdated API endpoints (removed 2026-04-30)

---

## 💡 System Summary

**SwingTrader** is a fully automated swing trading platform that:

1. **Fetches** 2 years of historical market data every night
2. **Optimizes** trading parameters (MACD, SMA, Bollinger Bands) using grid search
3. **Executes** trades every minute during market hours based on generated signals
4. **Tracks** performance with equity curves and P&L

**Key Features:**
- PostgreSQL database for persistent storage
- Laravel backend (port 9000) handling API and trade execution
- React/Vite frontend (port 5173) for dashboard
- Python optimizer for nightly parameter tuning
- Systemd services for auto-start and auto-restart
- Paper trading via Alpaca API

**Running 24/7 on systemd:**
- Backend service: `swingtrader-backend.service`
- Frontend service: `swingtrader-fe-dev.service` (dev) or nginx (production)
- Optimizer timer: `swingtrader-optimizer.timer` (runs daily at 2:00 AM)
- Trade executor: Cron job (runs every minute during market hours)

---

## 🔗 External Resources

- **Alpaca Trading API:** https://alpaca.markets/docs/
- **Laravel Documentation:** https://laravel.com/docs/
- **PostgreSQL Documentation:** https://www.postgresql.org/docs/
- **Systemd Documentation:** `man systemd`

---

## 📞 Support

For troubleshooting:
1. Check [MONITORING.md](MONITORING.md) for common issues
2. Review [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) for useful commands
3. Check service logs: `journalctl -u swingtrader-backend -f`
4. Verify database: `docker-compose ps`
