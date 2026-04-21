<x-mail::message>
# SwingTrader Error Alert

**{{ $count }}** error(s) detected in application logs.

**Time:** {{ $timestamp->format('Y-m-d H:i:s') }} (last 30 minutes)

---

## Recent Errors:

@foreach($errors as $error)
```
{{ $error }}
```

@endforeach

---

**Action Required:**
1. Check the full logs at: `backend/storage/logs/laravel.log`
2. Review the error context
3. If API-related, verify external service status (Alpaca, database, etc.)
4. Test the affected feature manually

<x-mail::button :url="env('APP_URL')">
View Dashboard
</x-mail::button>

Thanks,<br>
SwingTrader Monitoring System
</x-mail::message>
