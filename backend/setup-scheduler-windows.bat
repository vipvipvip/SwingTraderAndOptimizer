@echo off
REM Setup Laravel Scheduler on Windows via Task Scheduler
REM Run this as Administrator

set PROJECT_PATH=C:\data\Program Files\swing-trader-web\backend
set PHP_PATH=C:\php\php.exe

echo Setting up Laravel Scheduler task...
schtasks /create /tn "LaravelScheduler" ^
    /tr "\"%PHP_PATH%\" \"%PROJECT_PATH%\artisan\" schedule:run" ^
    /sc minute /mo 1 /f

echo.
echo Task created successfully!
echo The scheduler will run every minute and execute pending scheduled tasks.
echo.
echo To verify: Open Task Scheduler and search for "LaravelScheduler"
echo To remove: schtasks /delete /tn "LaravelScheduler" /f
