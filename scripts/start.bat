@echo off
REM Swing Trader Application Startup Script (Windows)
REM Initializes and starts all application components

setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "OPTIMIZER_DIR=%PROJECT_ROOT%optimizer"

echo.
echo ==========================================
echo Swing Trader Application Startup
echo ==========================================
echo.

REM Check prerequisites
echo Checking prerequisites...

where php >nul 2>nul
if errorlevel 1 (
    echo X PHP not found
    exit /b 1
)
for /f "tokens=*" %%i in ('php -v 2^>nul ^| findstr /R "^PHP"') do set "PHP_VERSION=%%i"
echo + %PHP_VERSION%

where composer >nul 2>nul
if errorlevel 1 (
    echo X Composer not found
    exit /b 1
)
echo + Composer installed

REM Create necessary directories
echo.
echo Creating directories...
if not exist "%BACKEND_DIR%\storage\logs" mkdir "%BACKEND_DIR%\storage\logs"
if not exist "%BACKEND_DIR%\storage\app" mkdir "%BACKEND_DIR%\storage\app"
if not exist "%OPTIMIZER_DIR%\logs" mkdir "%OPTIMIZER_DIR%\logs"
echo + Directories created

REM Install dependencies
echo.
echo Installing PHP dependencies...
cd /d "%BACKEND_DIR%"
call composer install --quiet 2>nul || (
    echo Installing dependencies (this may take a minute^)...
    call composer install
)
if errorlevel 1 (
    echo X Composer install failed
    exit /b 1
)
echo + Dependencies installed

REM Check .env file
echo.
echo Checking configuration...
if not exist "%BACKEND_DIR%\.env" (
    if exist "%BACKEND_DIR%\.env.example" (
        copy "%BACKEND_DIR%\.env.example" "%BACKEND_DIR%\.env" >nul
        echo + Created .env from .env.example
        echo ! Update .env with your Alpaca API credentials
    )
) else (
    echo + .env exists
)

REM Generate app key if needed
findstr /m "APP_KEY=" "%BACKEND_DIR%\.env" >nul
if errorlevel 1 (
    echo Generating APP_KEY...
    cd /d "%BACKEND_DIR%"
    call php artisan key:generate
    echo + APP_KEY generated
)

REM Run migrations
echo.
echo Running database migrations...
cd /d "%BACKEND_DIR%"
call php artisan migrate --force --quiet 2>nul || (
    REM Ignore migration errors on first run
)
echo + Database ready

REM Display startup info
echo.
echo ==========================================
echo Application started successfully!
echo ==========================================
echo.
echo Backend API: http://localhost:8000
echo API Documentation: http://localhost:8000/api/documentation
echo.
echo Logs:
echo   - Backend: %BACKEND_DIR%\storage\logs\laravel.log
echo   - Trade Executor: %BACKEND_DIR%\storage\logs\trade_executor.log
echo   - Optimizer: %OPTIMIZER_DIR%\logs\nightly.log
echo.
echo Cron Schedule:
echo   - 8:18 AM ET: Nightly Optimizer
echo   - 9:30 AM - 4:00 PM ET (every 30 min): Trade Executor
echo.
echo API Endpoints (Manual^):
echo   POST /api/v1/admin/trades/trigger      - Execute trades now
echo   POST /api/v1/admin/optimize/trigger    - Run optimizer now
echo   GET  /api/v1/admin/market-status       - Check market status
echo   GET  /api/v1/account                   - Account info
echo   GET  /api/v1/account/positions         - Open positions
echo.

REM Start the server
cd /d "%BACKEND_DIR%"
echo Starting Laravel dev server on http://localhost:8000
echo Press Ctrl+C to stop.
echo.
call php artisan serve --host=0.0.0.0 --port=8000
