# Ubuntu Backend Services Setup

## System Architecture

The SwingTrader system has three components working together:

```
┌─────────────────────────────────────────────────────────┐
│ systemd: swingtrader-backend.service                    │
│ └─> Keeps Laravel backend running 24/7 on port 9000     │
│     (auto-restarts if it crashes, survives reboots)     │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ uses
                          │
┌─────────────────────────────────────────────────────────┐
│ crontab: * * * * * artisan trades:execute-daily        │
│ └─> Runs every minute (when market is open)             │
│     Executes trades via CLI within running backend      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ systemd: swingtrader-optimizer.timer                    │
│ └─> Triggers nightly optimizer at 2:00 AM              │
│     Runs optimizer/run_nightly.sh (survives reboots)    │
└─────────────────────────────────────────────────────────┘
```

**How it works:**
1. **Backend service** keeps the Laravel API running 24/7 (handles requests, serves Swagger docs)
2. **Trade executor cron** runs every minute to execute trades using the running backend
3. **Optimizer timer** runs nightly at 2:00 AM to retrain strategy parameters

If the backend crashes, systemd restarts it automatically within 5 seconds. Both the backend and optimizer survive system reboots—no manual intervention needed.

---

## Overview

This document describes how to install the SwingTrader backend and nightly optimizer as systemd services on Ubuntu. These services will start automatically on reboot and restart if they crash.

### Services to Install
1. **swingtrader-backend.service** — Runs `php artisan serve` on port 9000 (persistent daemon)
2. **swingtrader-optimizer.service** — Runs the nightly optimizer (oneshot)
3. **swingtrader-optimizer.timer** — Schedules optimizer to run daily at 2:00 AM

---

## Installation

### Step 1: Create Service Files

Run these commands in your terminal (replace `Abcd1234` with your actual sudo password when prompted):

```bash
# Backend service
sudo bash -c 'cat > /etc/systemd/system/swingtrader-backend.service' <<'EOF'
[Unit]
Description=SwingTrader Laravel Backend
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=simple
User=dikesh
WorkingDirectory=/home/dikesh/data/dev/SwingTraderAndOptimizer/backend
ExecStartPre=/usr/bin/php artisan config:clear
ExecStartPre=/usr/bin/php artisan cache:clear
ExecStart=/usr/bin/php artisan serve --host=0.0.0.0 --port=9000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-backend

[Install]
WantedBy=multi-user.target
EOF
```

```bash
# Optimizer service
sudo bash -c 'cat > /etc/systemd/system/swingtrader-optimizer.service' <<'EOF'
[Unit]
Description=SwingTrader Nightly Optimizer (oneshot)
After=network.target

[Service]
Type=oneshot
User=dikesh
WorkingDirectory=/home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer
ExecStart=/bin/bash /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/run_nightly.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-optimizer
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
EOF
```

```bash
# Optimizer timer
sudo bash -c 'cat > /etc/systemd/system/swingtrader-optimizer.timer' <<'EOF'
[Unit]
Description=SwingTrader Nightly Optimizer Timer
Requires=swingtrader-optimizer.service

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
```

### Step 2: Enable and Start Services

```bash
# Reload systemd to pick up new service files
sudo systemctl daemon-reload

# Enable and start backend
sudo systemctl enable swingtrader-backend.service
sudo systemctl start swingtrader-backend.service

# Enable and start optimizer timer
sudo systemctl enable swingtrader-optimizer.timer
sudo systemctl start swingtrader-optimizer.timer
```

### Step 3: Clean Up Crontab

Remove the old commented-out optimizer cron entry (the trade executor cron stays):

```bash
crontab -l | grep -v '#0 8 \* \* \* /home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/run_nightly.sh' | crontab -
```

Verify the result:
```bash
crontab -l
# Should only show: * * * * * /usr/bin/php /home/dikesh/data/dev/SwingTraderAndOptimizer/backend/artisan trades:execute-daily >> /dev/null 2>&1
```

---

## Verification

### Check Backend Service

```bash
# Status
sudo systemctl status swingtrader-backend --no-pager

# Test API health
curl http://localhost:9000/api/health

# View logs (last 50 lines)
journalctl -u swingtrader-backend -n 50

# Follow logs in real-time
journalctl -u swingtrader-backend -f
```

### Check Optimizer Timer

```bash
# List all timers
sudo systemctl list-timers

# Status of optimizer timer specifically
sudo systemctl status swingtrader-optimizer.timer --no-pager

# View next scheduled run
sudo systemctl list-timers swingtrader-optimizer.timer --all
```

### View Optimizer Logs

```bash
# Last 50 lines
journalctl -u swingtrader-optimizer -n 50

# Follow in real-time (after starting)
journalctl -u swingtrader-optimizer -f
```

### Test Optimizer Manually

```bash
# Run the optimizer service once (doesn't wait for 2 AM)
sudo systemctl start swingtrader-optimizer.service

# Watch logs as it runs
journalctl -u swingtrader-optimizer -f
```

---

## Reboot Test

To verify services survive a reboot:

```bash
# Reboot
sudo reboot

# After system comes back up
sudo systemctl status swingtrader-backend --no-pager
sudo systemctl list-timers swingtrader-optimizer.timer --no-pager
curl http://localhost:9000/api/health
```

---

## Troubleshooting

### Backend won't start

```bash
# Check for port conflicts
sudo lsof -i :9000

# View detailed error logs
journalctl -u swingtrader-backend -n 100

# Try starting manually to see errors
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/backend
php artisan serve --host=0.0.0.0 --port=9000
```

### Optimizer not running

```bash
# Check if timer is enabled
sudo systemctl is-enabled swingtrader-optimizer.timer

# Check next scheduled time
sudo systemctl list-timers swingtrader-optimizer.timer

# View timer logs
journalctl -u swingtrader-optimizer.timer -n 50

# Try running manually
sudo systemctl start swingtrader-optimizer.service
journalctl -u swingtrader-optimizer -f
```

### Restart a service

```bash
# Backend
sudo systemctl restart swingtrader-backend

# Optimizer (timer-based, use this for oneshot)
sudo systemctl start swingtrader-optimizer.service
```

### Disable services (if needed)

```bash
sudo systemctl disable swingtrader-backend.service
sudo systemctl disable swingtrader-optimizer.timer
sudo systemctl stop swingtrader-backend
sudo systemctl stop swingtrader-optimizer.timer
```

---

## Service Details

### Backend Service (`swingtrader-backend.service`)
- **Type:** simple daemon that stays running
- **Auto-restart:** Yes, restarts after 5 seconds if it crashes
- **User:** dikesh
- **Port:** 9000
- **Log location:** `journalctl -u swingtrader-backend`
- **Manual start:** `scripts/start-backend-only.sh` (still works as fallback)

### Optimizer Timer (`swingtrader-optimizer.timer`)
- **Type:** Timer that triggers a oneshot service
- **Schedule:** Daily at 2:00 AM (UTC timezone of system)
- **User:** dikesh
- **Log location:** `journalctl -u swingtrader-optimizer`
- **Timeout:** 3600 seconds (1 hour) to complete
- **Persistent:** Yes — if system was off at 2 AM, it catches up on next boot

---

## Configuration

### Change Optimizer Schedule

To run at a different time, edit `/etc/systemd/system/swingtrader-optimizer.timer`:

```bash
sudo nano /etc/systemd/system/swingtrader-optimizer.timer
```

Change the `OnCalendar` line. Examples:
- `*-*-* 03:00:00` — 3:00 AM daily
- `Mon-Fri *-*-* 02:00:00` — Weekdays only at 2:00 AM
- `*-*-* 02:00:00,14:00:00` — 2:00 AM and 2:00 PM daily

After editing:
```bash
sudo systemctl daemon-reload
sudo systemctl restart swingtrader-optimizer.timer
```

### Change Backend Port

To run on a different port, edit `/etc/systemd/system/swingtrader-backend.service`:

```bash
sudo nano /etc/systemd/system/swingtrader-backend.service
```

Change the `ExecStart` line, e.g., `--port=8000`

After editing:
```bash
sudo systemctl daemon-reload
sudo systemctl restart swingtrader-backend
```

---

## Summary

| Service | Purpose | Status Command | Logs |
|---------|---------|-----------------|------|
| `swingtrader-backend.service` | PHP artisan serve on port 9000 | `sudo systemctl status swingtrader-backend` | `journalctl -u swingtrader-backend -f` |
| `swingtrader-optimizer.timer` | Nightly optimizer at 2:00 AM | `sudo systemctl list-timers swingtrader-optimizer.timer` | `journalctl -u swingtrader-optimizer -f` |

Both services are **enabled** (start on reboot) and **active** (currently running) after installation.
