# New Server Setup

## Prerequisites

1. **Update hardcoded IP addresses** (IMPORTANT for network access)
   
   The application contains hardcoded IPs that must be updated for your deployment:
   
   ```bash
   # Find your server's IP
   MYIP=$(hostname -I | awk '{print $1}')
   echo "Your server IP: $MYIP"
   
   # Replace hardcoded 192.168.1.232 with your actual IP
   sed -i "s/192.168.1.232/$MYIP/g" frontend/vite.config.js
   sed -i "s/192.168.1.232/$MYIP/g" scripts/start-all.sh
   ```
   
   Files with hardcoded IPs:
   - `frontend/vite.config.js` — API proxy target
   - `scripts/start-all.sh` — Display output messages

## Backend

```bash
git clone https://github.com/vipvipvip/SwingTraderAndOptimizer.git
cd SwingTraderAndOptimizer/backend
cp .env.example .env
# edit .env: fill ALPACA_API_KEY, ALPACA_SECRET_KEY, SLACK_WEBHOOK_URL
composer install
php artisan key:generate
php artisan migrate     # only if starting from a fresh DB
```
