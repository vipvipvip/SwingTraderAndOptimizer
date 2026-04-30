# Daily Monitoring Guide

Daily operations checklist to ensure the trading system runs smoothly.

---

## Quick Daily Check (2 minutes)

Run this every morning to verify the nightly optimizer completed:

```bash
# Check if optimizer ran successfully
journalctl -u swingtrader-optimizer -n 20

# Verify latest parameters were updated
curl http://localhost:9000/api/health | jq '.'
```

---

## Detailed Daily Schedule

### 🌙 Morning Check (After 2:00 AM UTC)

**Nightly Optimizer Should Have Run**

```bash
# 1. Check optimizer status
sudo systemctl status swingtrader-optimizer.timer --no-pager

# 2. View optimizer logs (last 50 lines)
journalctl -u swingtrader-optimizer -n 50

# 3. Check for any errors
journalctl -u swingtrader-optimizer | grep -i "error"
```

**If optimizer didn't run:**
- Check timer status: `sudo systemctl list-timers swingtrader-optimizer.timer`
- Check service logs: `journalctl -u swingtrader-optimizer -f`
- Verify database connection: `docker-compose logs postgres`
- Run manually to test: `sudo systemctl start swingtrader-optimizer.service`

---

### 📈 During Market Hours (9:30-16:00 ET, Weekdays Only)

**Trade Executor Should Run Every Minute**

```bash
# 1. Check backend is running
sudo systemctl status swingtrader-backend --no-pager

# 2. Verify trade executor cron is active
crontab -l | grep trades:execute-daily

# 3. Check for recent trade executions
journalctl -u swingtrader-backend -n 50 | grep -i "trade\|signal"

# 4. View current account equity (if you have a dashboard)
curl http://localhost:9000/api/health | jq '.'
```

**If trades aren't executing:**
- Verify cron is enabled: `crontab -l`
- Check backend logs: `journalctl -u swingtrader-backend -f`
- Test manually: `php backend/artisan trades:execute-daily`
- Verify market is open: Check Alpaca calendar

---

### 🌙 Evening Check (After 16:00 ET)

**Summarize Today's Activity**

```bash
# 1. Check total trades executed
journalctl -u swingtrader-backend | grep -c "ExecuteDailyTrades"

# 2. View backend errors (if any)
journalctl -u swingtrader-backend | grep -i "error" | head -10

# 3. Verify database is healthy
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT COUNT(*) as live_trades FROM live_trades WHERE DATE(entry_at) = CURRENT_DATE;"
```

---

## Service Health Checks

### Backend Service

```bash
# Status
sudo systemctl status swingtrader-backend --no-pager

# Logs (real-time)
journalctl -u swingtrader-backend -f

# Test health endpoint
curl http://localhost:9000/api/health
```

### Optimizer Timer

```bash
# Check if timer is active
sudo systemctl status swingtrader-optimizer.timer --no-pager

# List all timers
sudo systemctl list-timers

# View logs
journalctl -u swingtrader-optimizer -f
```

### Database

```bash
# Check if container is running
docker-compose ps

# View database logs
docker-compose logs postgres -f

# Connect to database
docker exec swingtrader-db psql -U swingtrader -d swingtrader

# Inside psql:
SELECT COUNT(*) as bars FROM bars;
SELECT COUNT(*) as trades FROM live_trades WHERE DATE(entry_at) = CURRENT_DATE;
```

---

## Common Issues & Fixes

### Backend Won't Start

```bash
# Check for port conflicts
lsof -i :9000

# View detailed logs
journalctl -u swingtrader-backend -n 100

# Try starting manually
cd backend && php artisan serve --host=0.0.0.0 --port=9000
```

### Optimizer Not Running

```bash
# Verify timer is enabled
sudo systemctl is-enabled swingtrader-optimizer.timer

# Check next run time
sudo systemctl list-timers swingtrader-optimizer.timer

# Run manually to test
sudo systemctl start swingtrader-optimizer.service
journalctl -u swingtrader-optimizer -f
```

### Database Connection Error

```bash
# Restart database
docker-compose down
docker-compose up -d

# Run migrations
php artisan migrate

# Verify connection
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1;"
```

### Trade Executor Not Running

```bash
# Verify cron is enabled
crontab -l

# Check cron logs
journalctl -u cron | tail -20

# Run manually to test
php backend/artisan trades:execute-daily
```

---

## Performance Metrics to Watch

| Metric | How to Check | Expected |
|--------|-------------|----------|
| Optimizer runtime | `journalctl -u swingtrader-optimizer` | 30-45 minutes |
| Trade executor frequency | `journalctl -u swingtrader-backend` | Every minute (390 times during market hours) |
| Database health | `docker exec swingtrader-db psql ... SELECT 1;` | Instant response |
| Backend response time | `curl -w "%{time_total}" http://localhost:9000/api/health` | <100ms |

---

## Weekly Checklist

- [ ] Optimizer ran successfully every night (7 times)
- [ ] No error logs in backend/database
- [ ] All services are enabled and will survive reboot
- [ ] No port conflicts or zombie processes
- [ ] Database backup exists (if applicable)

---

## See Also

- [How_System_Works.md](How_System_Works.md) — System architecture
- [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) — All useful commands
- [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) — Systemd service troubleshooting
- [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md) — Frontend service troubleshooting
