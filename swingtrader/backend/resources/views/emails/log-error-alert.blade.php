SwingTrader Error Alert

{{ $count }} error(s) detected in application logs.

Time: {{ $timestamp->format('Y-m-d H:i:s') }} (last 4 hours)

---

Recent Errors:

{{ $errorList }}

---

Action Required:
1. Check the full logs at: backend/storage/logs/laravel.log
2. Review the error context
3. If API-related, verify external service status (Alpaca, database, etc.)
4. Test the affected feature manually

Dashboard: {{ env('APP_URL') }}

--
SwingTrader Monitoring System
