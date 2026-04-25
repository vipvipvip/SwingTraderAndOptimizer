# New Server Setup

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
