# Ubuntu Frontend Services Setup

## Overview

The frontend can be run in two modes, each with its own systemd service:

1. **Development Mode** — Vite dev server with hot reload (for active development)
2. **Production Mode** — Built app served by nginx (for 24/7 trading system)

Both modes are resilient: auto-start on boot, auto-restart on crash, managed by systemd.

---

## Architecture

### Development Mode
```
┌──────────────────────────────────────┐
│ systemd: swingtrader-fe-dev.service  │
│ └─> npm run dev on port 5173         │
│     (Vite dev server with hot reload)│
│     Auto-restart on crash            │
│     Survives reboots                 │
└──────────────────────────────────────┘
```

### Production Mode
```
┌──────────────────────────────────────┐
│ systemd: nginx.service               │
│ └─> /etc/nginx/sites-enabled/        │
│     swingtrader-fe.conf              │
│     - Serves built frontend on :5173 │
│     - Proxies /api → backend :9000   │
│     - Fast, optimized                │
│     (standard nginx systemd)          │
└──────────────────────────────────────┘
```

---

## Development Mode Setup

Use this during active feature development. Includes Vite hot reload for fast iteration.

### Step 1: Create Service File

```bash
sudo bash -c 'cat > /etc/systemd/system/swingtrader-fe-dev.service' <<'EOF'
[Unit]
Description=SwingTrader Frontend Dev Server (Vite)
After=network.target

[Service]
Type=simple
User=dikesh
WorkingDirectory=/home/dikesh/data/dev/SwingTraderAndOptimizer/frontend
ExecStart=/usr/bin/npm run dev
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=swingtrader-fe-dev
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/nvm/versions/node/v18.17.0/bin"

[Install]
WantedBy=multi-user.target
EOF
```

> **Note:** Adjust the `PATH` environment variable if Node is installed in a different location. Check with: `which npm`

### Step 2: Enable and Start

```bash
sudo systemctl daemon-reload
sudo systemctl enable swingtrader-fe-dev.service
sudo systemctl start swingtrader-fe-dev.service
```

### Step 3: Verify

```bash
sudo systemctl status swingtrader-fe-dev --no-pager
curl http://localhost:5173/
journalctl -u swingtrader-fe-dev -f
```

### Use Cases
- ✅ Active development with hot reload
- ✅ Debugging UI changes
- ✅ Testing new features iteratively

---

## Production Mode Setup

Use this for 24/7 operation. Frontend is pre-built and served via fast nginx reverse proxy.

### Step 1: Install Nginx (if not already installed)

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

### Step 2: Build Frontend

```bash
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/frontend
npm run build
```

This creates a `dist/` folder with optimized static files.

### Step 3: Create Nginx Configuration

```bash
sudo bash -c 'cat > /etc/nginx/sites-available/swingtrader-fe' <<'EOF'
# SwingTrader Frontend - Production
server {
    listen 5173;
    server_name _;

    # Serve frontend static files
    root /home/dikesh/data/dev/SwingTraderAndOptimizer/frontend/dist;
    index index.html;

    # Gzip compression for better performance
    gzip on;
    gzip_types text/plain text/css text/javascript application/json application/javascript;
    gzip_min_length 1000;

    # Static files (with caching)
    location ~ ^/(assets|css|js|img)/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # API proxy to backend
    location /api/ {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # SPA fallback - all non-matching routes go to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Deny access to dotfiles
    location ~ /\. {
        deny all;
    }
}
EOF
```

### Step 4: Enable Nginx Configuration

```bash
sudo ln -sf /etc/nginx/sites-available/swingtrader-fe /etc/nginx/sites-enabled/swingtrader-fe
sudo rm -f /etc/nginx/sites-enabled/default  # Optional: remove default site
sudo nginx -t  # Test configuration
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### Step 5: Verify

```bash
sudo systemctl status nginx --no-pager
curl http://localhost:5173/
journalctl -u nginx -f
```

### Use Cases
- ✅ 24/7 trading system
- ✅ Optimized performance
- ✅ Auto-restart via standard nginx systemd service
- ✅ API requests proxied to backend

---

## Switching Between Modes

### From Dev to Production

```bash
# Stop dev service
sudo systemctl stop swingtrader-fe-dev.service
sudo systemctl disable swingtrader-fe-dev.service

# Rebuild frontend
cd /home/dikesh/data/dev/SwingTraderAndOptimizer/frontend
npm run build

# Restart nginx
sudo systemctl restart nginx
sudo systemctl status nginx --no-pager
```

### From Production to Dev

```bash
# Stop nginx (or just disable the swingtrader-fe config)
sudo rm /etc/nginx/sites-enabled/swingtrader-fe
sudo systemctl restart nginx

# Start dev service
sudo systemctl enable swingtrader-fe-dev.service
sudo systemctl start swingtrader-fe-dev.service
```

---

## Verification & Troubleshooting

### Check Dev Mode Service

```bash
# Status
sudo systemctl status swingtrader-fe-dev --no-pager

# View logs
journalctl -u swingtrader-fe-dev -n 50

# Follow logs
journalctl -u swingtrader-fe-dev -f

# Test endpoint
curl http://localhost:5173/
```

### Check Production Mode (Nginx)

```bash
# Status
sudo systemctl status nginx --no-pager

# Check nginx config
sudo nginx -t

# View logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Test endpoint
curl http://localhost:5173/
curl http://localhost:5173/api/health  # Should proxy to backend
```

### Port Conflicts

If port 5173 is already in use:

```bash
# Find what's using it
lsof -i :5173

# Kill the process
kill -9 <PID>

# Or change port in:
# - Dev mode: npm run dev --host 0.0.0.0 --port 3000
# - Prod mode: listen 3000; in nginx config
```

### Npm Not Found

If systemd service can't find npm:

```bash
# Find npm location
which npm

# Add to PATH in service file:
# Environment="PATH=/path/to/node/bin:/usr/local/sbin:..."

# Or use absolute path:
# ExecStart=/usr/local/nvm/versions/node/v18.17.0/bin/npm run dev
```

### Frontend Can't Connect to Backend API

```bash
# Check backend is running
curl http://localhost:9000/api/health

# If using nginx, verify proxy in swingtrader-fe config:
sudo nginx -t
sudo grep -A 5 "location /api" /etc/nginx/sites-enabled/swingtrader-fe
```

---

## Reboot Test

Verify both frontend and backend survive reboot:

```bash
# Check which mode is enabled before reboot
sudo systemctl is-enabled swingtrader-fe-dev.service
sudo systemctl is-enabled nginx

# Reboot
sudo reboot

# After reboot, check status
sudo systemctl status swingtrader-fe-dev --no-pager  # if dev mode
sudo systemctl status nginx --no-pager               # if prod mode
curl http://localhost:5173/
curl http://localhost:9000/api/health
```

---

## Recommendations

| Use Case | Mode | Command |
|----------|------|---------|
| **Active Development** | Dev | `sudo systemctl start swingtrader-fe-dev` |
| **Live Trading System** | Production | `sudo systemctl restart nginx` |
| **Testing Before Deploy** | Both | Run dev, test, build, switch to prod |

---

## Summary

Both services are **independent** and can run separately:

- **Dev mode**: One systemd service (`swingtrader-fe-dev.service`) that runs npm
- **Production mode**: Standard nginx (already systemd-managed)

Only enable/start ONE at a time on port 5173 to avoid conflicts.

### Quick Reference

```bash
# Development
sudo systemctl enable swingtrader-fe-dev.service
sudo systemctl start swingtrader-fe-dev.service

# Production (requires: nginx installed, config created, frontend built)
sudo systemctl enable nginx
sudo systemctl start nginx

# Check logs
journalctl -u swingtrader-fe-dev -f
journalctl -u nginx -f
```
