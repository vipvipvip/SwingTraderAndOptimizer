# WSL2 Setup Guide - SwingTraderAndOptimizer

Complete guide for setting up the trading system on **Windows Subsystem for Linux 2 (WSL2)**.

**Status:** Fully compatible with WSL2 | Tested on Windows 11 with WSL2

---

## Prerequisites

### WSL Version (Critical)

Must use **WSL2** (not WSL1). Docker requires it.

```bash
# Check your WSL version
wsl --list --verbose

# If you see WSL1, upgrade to WSL2
# Follow: https://learn.microsoft.com/en-us/windows/wsl/install-manual#step-4---download-the-linux-kernel-update-package
```

### Docker Setup

- Install **Docker Desktop for Windows**
- Enable WSL2 integration in Docker Desktop settings:
  - Settings → Resources → WSL Integration → Enable integration with your distro
- Verify Docker works from WSL:

```bash
docker --version
docker run hello-world
```

### Enable Systemd (WSL2 Ubuntu 22.04+)

WSL2 now supports systemd. Edit `/etc/wsl.conf`:

```bash
sudo nano /etc/wsl.conf
```

Add these lines:

```ini
[boot]
systemd=true
```

Then restart WSL:

```bash
# From Windows PowerShell (run as Administrator):
wsl --shutdown

# Then reopen your WSL terminal
```

Verify systemd is running:

```bash
systemctl is-system-running
# Should return: "running" or "degraded"
```

---

## Quick Setup (Step-by-Step)

### Step 1: Clone Repository

```bash
cd /home/$USER
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer
```

### Step 2: Backend Setup

```bash
cd backend

# Create environment file
cp .env.example .env

# IMPORTANT: Update .env with your values
nano .env
# Set:
#   ALPACA_API_KEY=<your_key>
#   ALPACA_SECRET_KEY=<your_secret>
#   SLACK_WEBHOOK_URL=<your_webhook>
#   PYTHON_PATH=python3  # Use fallback (don't hardcode /home/dikesh/...)

# Install dependencies
composer install
php artisan key:generate
```

### Step 3: Frontend Setup

```bash
cd ../frontend
npm install
```

For development (hot reload):
```bash
npm run dev
```

For production (optimized build):
```bash
npm run build
```

### Step 4: Python Optimizer Setup

```bash
cd ../optimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

### Step 5: Database Setup

```bash
cd ../backend

# Start PostgreSQL in Docker
docker-compose up -d

# Wait for PostgreSQL to be ready (~10 seconds)
docker-compose ps

# Run migrations
php artisan migrate
```

### Step 6: Start Services

**Terminal 1 - Backend (Laravel):**
```bash
cd backend
php artisan serve --host=0.0.0.0 --port=9000
```

**Terminal 2 - Frontend (Vite):**
```bash
cd frontend
npm run dev
# Access at http://localhost:5173
```

**Terminal 3 - Monitor Database:**
```bash
cd backend
docker-compose logs -f postgres
```

### Step 7: Verify Everything Works

```bash
# Test backend
curl http://localhost:9000/api/health

# Test frontend (in browser)
http://localhost:5173

# Test database
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1;"
```

---

## Production Systemd Setup (Optional)

Once everything works, use systemd services for auto-start and auto-restart.

See: [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) and [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md)

The commands are identical on WSL2:

```bash
# Backend service
sudo systemctl enable swingtrader-backend.service
sudo systemctl start swingtrader-backend.service

# Optimizer timer
sudo systemctl enable swingtrader-optimizer.timer
sudo systemctl start swingtrader-optimizer.timer
```

---

## Key Differences from Native Linux

| Aspect | Native Linux | WSL2 |
|--------|--------------|------|
| Systemd | Available | Available (if enabled in wsl.conf) |
| Docker | Runs natively | Runs via Docker Desktop on Windows |
| File access | `/home/<user>/` | `/home/<user>/` (same) |
| Ports | Direct access | Automatically mapped to Windows |
| Performance | Native | Near-native (very fast) |
| Shutdown | `sudo shutdown` | `wsl --shutdown` (from Windows) |

---

## Environment Variables

The only change needed in `.env` is `PYTHON_PATH`:

```bash
# DON'T hardcode this (won't match your username):
# PYTHON_PATH=/home/dikesh/data/dev/SwingTraderAndOptimizer/optimizer/venv/bin/python3

# DO this instead:
PYTHON_PATH=python3
```

The code has a fallback that defaults to `python` if `PYTHON_PATH` is not set, so just using `python3` works fine.

---

## Troubleshooting

### Docker Won't Start

```bash
# Check if Docker Desktop is running on Windows
# (It may need to be started from Windows)

# Verify WSL2 integration
docker --version
docker run hello-world

# If still failing, check Docker Desktop settings:
# Settings → Resources → WSL Integration → enable your distro
```

### Python3 Not Found

```bash
# Install Python
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

# Verify
python3 --version
which python3
```

### Systemd Commands Fail

```bash
# Check if enabled
cat /etc/wsl.conf | grep systemd

# If missing, add it:
echo -e "\n[boot]\nsystemd=true" | sudo tee -a /etc/wsl.conf

# Restart WSL
wsl --shutdown
# Then reopen WSL terminal
```

### Database Connection Error

```bash
# Check if Docker container is running
docker ps

# View logs
docker-compose logs postgres

# Restart database
docker-compose down
docker-compose up -d

# Wait and verify
sleep 10
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT 1;"
```

### Port Already in Use

```bash
# Find what's using port 9000
lsof -i :9000

# Find what's using port 5173
lsof -i :5173

# Kill the process (if needed)
kill -9 <PID>

# Or use a different port:
# Backend: php artisan serve --port=8000
# Frontend: npm run dev -- --port 3000
```

### Composer Dependency Issues

```bash
# Clear cache
cd backend
composer clear-cache
composer install
```

---

## Performance Tips

WSL2 has near-native Linux performance. A few optimization tips:

1. **Keep project in WSL filesystem**, not `/mnt/c/` (Windows):
   ```bash
   # Good (fast)
   /home/$USER/SwingTraderAndOptimizer

   # Bad (slower)
   /mnt/c/Users/YourName/SwingTraderAndOptimizer
   ```

2. **Use Docker for PostgreSQL** (already configured):
   ```bash
   docker-compose up -d
   ```

3. **Disable Windows Defender scans** on WSL folders (optional):
   - Settings → Privacy & Security → Virus & threat protection → Manage settings
   - Add WSL folder to exclusions

4. **Allocate enough resources** in Docker Desktop:
   - Settings → Resources → Memory (recommend 4GB+)
   - Settings → Resources → CPUs (recommend 4+)

---

## Accessing from Windows

While the project is fully in WSL, you can access it from Windows:

**From Windows Terminal/PowerShell:**
```powershell
wsl bash
cd ~/SwingTraderAndOptimizer
```

**From Windows File Explorer:**
- Press `Win+R` and type: `\\wsl$`
- Navigate to your distro and project folder

**From VS Code on Windows:**
- Install "Remote - WSL" extension
- Open folder from WSL: `code /home/$USER/SwingTraderAndOptimizer`

---

## See Also

- [How_System_Works.md](How_System_Works.md) — System architecture
- [UBUNTU_SETUP.md](UBUNTU_SETUP.md) — Native Linux setup (very similar)
- [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) — Systemd services
- [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) — Useful commands
- [MONITORING.md](MONITORING.md) — Daily operations

---

## Summary

✅ **WSL2 is fully compatible** with SwingTrader

**Required:**
- WSL2 (not WSL1)
- Docker Desktop for Windows
- Systemd enabled in `/etc/wsl.conf`

**Key change:**
- Update `.env`: `PYTHON_PATH=python3` (instead of hardcoded path)

**Result:**
- All 3 apps run smoothly: backend (9000), frontend (5173), optimizer (daily)
- Docker PostgreSQL works perfectly
- Systemd services survive reboot
- 100% WSL filesystem (no Windows folder mapping)
