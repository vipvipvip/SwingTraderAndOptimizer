# Cross-Platform Laravel Scheduler Setup

The Laravel Scheduler runs pending tasks every minute. This document covers Windows and Linux setup.

## Windows Setup

### Option 1: Task Scheduler (Recommended)

1. Open Command Prompt as Administrator
2. Navigate to the backend directory:
   ```bash
   cd "C:\data\Program Files\swing-trader-web\backend"
   ```
3. Run the setup script:
   ```bash
   setup-scheduler-windows.bat
   ```

4. Verify the task was created:
   - Press `Win + R`, type `taskschd.msc`, hit Enter
   - Navigate to **Task Scheduler Library**
   - Search for **LaravelScheduler**
   - Right-click → **Properties** → **Triggers** tab to verify it runs every minute

5. To remove the task later:
   ```bash
   schtasks /delete /tn "LaravelScheduler" /f
   ```

### Troubleshooting Windows

**Task runs but doesn't execute:**
- Verify PHP path: `where php`
- Check artisan is executable: `php artisan list`
- Check task history in Task Scheduler (right-click task → **View** → **History**)

**Permission denied:**
- Run Command Prompt as Administrator
- Ensure PHP is in PATH or use absolute path

---

## Linux Setup

Choose **one** of these options:

### Option 1: systemd Service + Timer (Recommended for systemd systems)

1. Copy service file to systemd:
   ```bash
   sudo cp setup-scheduler-linux-systemd.service /etc/systemd/system/laravel-scheduler.service
   sudo cp setup-scheduler-linux-systemd.timer /etc/systemd/system/laravel-scheduler.timer
   ```

2. **IMPORTANT:** Edit the service file to match your setup:
   ```bash
   sudo nano /etc/systemd/system/laravel-scheduler.service
   ```
   - Change `User=www-data` to your user (or keep www-data if Laravel runs as www-data)
   - Change `WorkingDirectory=/home/user/swing-trader-web/backend` to your actual path
   - Change `ExecStart=/usr/bin/php /home/user/swing-trader-web/backend/artisan schedule:run` to your PHP path and project path

3. Reload systemd and enable timer:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable laravel-scheduler.timer
   sudo systemctl start laravel-scheduler.timer
   ```

4. Verify it's running:
   ```bash
   sudo systemctl status laravel-scheduler.timer
   sudo systemctl status laravel-scheduler.service
   ```

5. View logs:
   ```bash
   sudo journalctl -u laravel-scheduler.service -f
   ```

6. To stop/disable later:
   ```bash
   sudo systemctl stop laravel-scheduler.timer
   sudo systemctl disable laravel-scheduler.timer
   ```

### Option 2: cron (Simple fallback for all Unix systems)

1. Open crontab editor:
   ```bash
   crontab -e
   ```

2. Add this line (replace paths with your actual paths):
   ```bash
   * * * * * /usr/bin/php /home/user/swing-trader-web/backend/artisan schedule:run >> /tmp/laravel-scheduler.log 2>&1
   ```

3. Verify cron is running:
   ```bash
   sudo service cron status
   ```

4. View logs:
   ```bash
   tail -f /tmp/laravel-scheduler.log
   ```

5. To remove later:
   ```bash
   crontab -e
   # Delete the line and save
   ```

---

## How It Works

The Laravel Scheduler invokes `php artisan schedule:run` **every minute**. Inside `app/Console/Kernel.php`, the `schedule()` method defines three tasks:

1. **Nightly Optimizer** (`optimize:nightly`)
   - Runs daily at 2:00 AM
   - Executes Python parameter optimizer
   - Updates strategy_parameters table with new MACD/SMA/BB combinations

2. **Daily Trade Execution** (`trades:execute-daily`)
   - Runs daily at 9:35 AM America/New_York (5 min after market open)
   - Fetches latest bars from Alpaca
   - Computes trading signals based on optimized parameters
   - Places orders if signal fires
   - Records trades to live_trades table

3. **Position Sync** (`positions:sync`)
   - Runs every 5 minutes during market hours (9:30 AM - 4:05 PM America/New_York)
   - Fetches open positions from Alpaca
   - Updates positions_cache with current qty, P&L, market value

---

## Verification

After setup, verify the scheduler is working:

### Windows
```bash
# SSH into machine or check Task Scheduler History
tasklist | findstr php
```

### Linux
```bash
# Check systemd status
sudo systemctl status laravel-scheduler.timer

# Or check cron logs
grep CRON /var/log/syslog  # Ubuntu/Debian
tail -f /var/log/cron      # RHEL/CentOS
```

### All Platforms
```bash
# Check Laravel logs for scheduled task execution
tail -f storage/logs/laravel.log | grep -i "scheduler\|optimize\|trades\|positions"
```

---

## Expected Log Output

When tasks run successfully, you should see in `storage/logs/laravel.log`:

```
[2026-04-18 02:00:00] local.INFO: Running scheduled command: 'optimize:nightly'
[2026-04-18 02:00:35] local.INFO: Nightly optimizer completed successfully
[2026-04-18 09:35:00] local.INFO: Running scheduled command: 'trades:execute-daily'
[2026-04-18 09:35:02] local.INFO: Synced 3 tickers: SPY, QQQ, IWM
[2026-04-18 09:35:00] local.INFO: Running scheduled command: 'positions:sync'
[2026-04-18 09:35:02] local.INFO: Synced 2 positions
```

If you don't see these logs, check:
1. Scheduler is running: `schtasks query /tn LaravelScheduler` (Windows) or `systemctl status laravel-scheduler.timer` (Linux)
2. Laravel logs are enabled: Check `config/logging.php` and `LOG_CHANNEL` in `.env`
3. PHP can execute artisan: `php artisan list` from backend directory
4. Timezone is correct in `.env`: `APP_TIMEZONE=America/New_York`

---

## Switching Between Windows and Linux

If moving the project between operating systems:

1. **Windows → Linux:** Run the systemd/cron setup from Option 2
2. **Linux → Windows:** Run `setup-scheduler-windows.bat` as Administrator

Both setups are independent; you only need one active per OS.
