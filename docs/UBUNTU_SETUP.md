# Ubuntu/Linux Setup Guide - SwingTraderAndOptimizer

Complete guide for setting up the trading system on **native Ubuntu/Linux** (not WSL or Windows).

**Status:** Production-ready on Ubuntu 22.04+ | Tested on native Linux

---

## Prerequisites

1. **Install Core Dependencies**
```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
  php-cli php-pgsql php-xml php-dom php-mbstring php-curl php-json php-fileinfo \
  nodejs npm \
  python3 python3-venv python3-pip \
  docker.io docker-compose \
  git curl
```

2. **Install Composer (Laravel dependency manager)**
```bash
curl -sS https://getcomposer.org/installer | php
sudo mv composer.phar /usr/local/bin/composer
sudo chmod +x /usr/local/bin/composer
```

3. **Configure Git**
```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

---

## Backend Setup

```bash
cd backend
cp .env.example .env
# Edit .env and set:
#   DB_HOST=127.0.0.1
#   DB_DATABASE=swingtrader
#   DB_USERNAME=swingtrader
#   DB_PASSWORD=swingtrader_dev_password
#   ALPACA_API_KEY=your_key_here
#   ALPACA_SECRET_KEY=your_secret_here
#   SLACK_WEBHOOK_URL=your_webhook_url

composer install
php artisan key:generate
php artisan migrate
```

---

## Frontend Setup

```bash
cd frontend
npm install
npm run dev     # For development
# Or: npm run build   # For production
```

---

## Python Optimizer Setup

```bash
cd optimizer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

---

## Database Setup (Docker)

```bash
cd backend
docker-compose up -d
# Wait for PostgreSQL to be ready (~10 seconds)
php artisan migrate
```

---

## Production Systemd Services

For 24/7 operation with auto-restart, use systemd services:

1. **Backend:** See [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md)
2. **Frontend:** See [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md)

---

## Manual Development Mode

If you prefer manual startup (not recommended for production):

```bash
# Terminal 1: Database
cd backend
docker-compose up

# Terminal 2: Backend
cd backend
php artisan serve --host=0.0.0.0 --port=9000

# Terminal 3: Frontend
cd frontend
npm run dev

# Terminal 4: Optimizer (runs daily at 2 AM, or manually)
cd optimizer
python3 nightly_optimizer.py
```

---

## Verify Installation

```bash
# Backend health check
curl http://localhost:9000/api/health

# Frontend
curl http://localhost:5173/

# Database connection
docker exec swingtrader-db psql -U swingtrader -d swingtrader -c "SELECT COUNT(*) FROM tickers;"
```

---

## Troubleshooting

**Port conflicts:**
```bash
lsof -i :9000   # Check port 9000
lsof -i :5173   # Check port 5173
```

**PostgreSQL not starting:**
```bash
docker-compose logs postgres
docker-compose down && docker-compose up -d
```

**Python venv issues:**
```bash
rm -rf optimizer/venv
python3 -m venv optimizer/venv
source optimizer/venv/bin/activate
pip install -r optimizer/requirements.txt
```

---

## See Also

- [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) — All available commands
- [How_System_Works.md](How_System_Works.md) — Architecture overview
- [Ubuntu-Backend-Services.md](Ubuntu-Backend-Services.md) — Systemd backend service
- [Ubuntu-Frontend-Services.md](Ubuntu-Frontend-Services.md) — Systemd frontend service
