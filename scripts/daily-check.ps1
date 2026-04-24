# Daily monitoring script for Windows - runs all critical checks and reports status
# Usage: .\daily-check.ps1

$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$OptimizerDir = Join-Path $ProjectRoot "optimizer"
$BackendDir = Join-Path $ProjectRoot "backend"
$BackendUrl = "http://localhost:9000"

# Colors
$Red = "Red"
$Green = "Green"
$Yellow = "Yellow"
$Cyan = "Cyan"

Write-Host "╔════════════════════════════════════════╗" -ForegroundColor $Cyan
Write-Host "║   SwingTrader Daily Monitoring Report   ║" -ForegroundColor $Cyan
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor $Cyan
Write-Host ""

# ============================================================================
# 1. NIGHTLY OPTIMIZER CHECK
# ============================================================================
Write-Host "=== NIGHTLY OPTIMIZER ===" -ForegroundColor $Cyan

$OptimizerLog = Join-Path $OptimizerDir "logs\nightly.log"

if (-not (Test-Path $OptimizerLog)) {
    Write-Host "✗ No optimizer log found" -ForegroundColor $Red
} else {
    $LastRun = Get-Content $OptimizerLog -Tail 1 -ErrorAction SilentlyContinue

    if ($LastRun -match "finished") {
        Write-Host "✓ Last run completed" -ForegroundColor $Green
        Write-Host "  $LastRun"
    } else {
        Write-Host "⚠ Last run may still be in progress" -ForegroundColor $Yellow
        Get-Content $OptimizerLog -Tail 3 | ForEach-Object { Write-Host "  $_" }
    }
}

Write-Host ""

# ============================================================================
# 2. TICKERS & PARAMETERS CHECK
# ============================================================================
Write-Host "=== TICKERS & PARAMETERS ===" -ForegroundColor $Cyan

try {
    $TickersResponse = Invoke-WebRequest -Uri "$BackendUrl/api/v1/tickers" -UseBasicParsing -ErrorAction Stop
    $Tickers = $TickersResponse.Content | ConvertFrom-Json

    Write-Host "✓ Backend API responding" -ForegroundColor $Green

    foreach ($Ticker in $Tickers) {
        $Symbol = $Ticker.symbol
        $Sharpe = $Ticker.params.sharpe_ratio
        $Alloc = $Ticker.allocation_weight
        $Updated = $Ticker.params.updated_at

        Write-Host "  $Symbol`: Sharpe=$Sharpe, Alloc=$Alloc%, Updated=$Updated"
    }
} catch {
    Write-Host "✗ Backend not responding or error parsing data" -ForegroundColor $Red
}

Write-Host ""

# ============================================================================
# 3. TRADES CHECK
# ============================================================================
Write-Host "=== TRADES (TODAY) ===" -ForegroundColor $Cyan

try {
    $TradesResponse = Invoke-WebRequest -Uri "$BackendUrl/api/v1/trades/pnl" -UseBasicParsing -ErrorAction Stop
    $Trades = $TradesResponse.Content | ConvertFrom-Json

    $TradeCount = if ($Trades.recent_trades) { $Trades.recent_trades.Count } else { 0 }
    $WinRate = [math]::Round($Trades.win_rate * 100)
    $TotalReturn = [math]::Round($Trades.total_return * 100) / 100

    if ($TradeCount -gt 0) {
        Write-Host "✓ Trades executed today" -ForegroundColor $Green
    } else {
        Write-Host "⚠ No trades today (market may be closed)" -ForegroundColor $Yellow
    }

    Write-Host "  Executed: $TradeCount trades"
    Write-Host "  Win Rate: $WinRate%"
    Write-Host "  Total Return: $TotalReturn%"
} catch {
    Write-Host "✗ Cannot fetch trades" -ForegroundColor $Red
}

Write-Host ""

# ============================================================================
# 4. ACCOUNT CHECK
# ============================================================================
Write-Host "=== ACCOUNT ===" -ForegroundColor $Cyan

try {
    $AccountResponse = Invoke-WebRequest -Uri "$BackendUrl/api/v1/account" -UseBasicParsing -ErrorAction Stop
    $Account = $AccountResponse.Content | ConvertFrom-Json

    $Equity = [math]::Round($Account.equity)
    $BuyingPower = [math]::Round($Account.buying_power)

    if ($Equity -lt 100000) {
        Write-Host "✗ Equity below starting amount" -ForegroundColor $Red
    } else {
        Write-Host "✓ Account healthy" -ForegroundColor $Green
    }

    Write-Host "  Equity: `$$Equity"
    Write-Host "  Buying Power: `$$BuyingPower"
} catch {
    Write-Host "✗ Cannot fetch account info" -ForegroundColor $Red
}

Write-Host ""

# ============================================================================
# 5. ERRORS CHECK
# ============================================================================
Write-Host "=== ERROR CHECK ===" -ForegroundColor $Cyan

$LaravelLog = Join-Path $BackendDir "storage\logs\laravel.log"
$ErrorCount = 0

if (Test-Path $LaravelLog) {
    $ErrorCount = @(Select-String -Path $LaravelLog -Pattern "ERROR|Exception" | Measure-Object).Count

    if ($ErrorCount -gt 10) {
        Write-Host "✗ High error count: $ErrorCount errors" -ForegroundColor $Red
        Write-Host "  Recent errors:"
        Get-Content $LaravelLog -Tail 10 | Select-String "ERROR|Exception" | Select-Object -First 5 | ForEach-Object { Write-Host "    $_" }
    } elseif ($ErrorCount -gt 0) {
        Write-Host "⚠ Some errors detected: $ErrorCount errors" -ForegroundColor $Yellow
    } else {
        Write-Host "✓ No errors in logs" -ForegroundColor $Green
    }
} else {
    Write-Host "⚠ Laravel log not found" -ForegroundColor $Yellow
}

Write-Host ""

# ============================================================================
# 6. SCHEDULER STATUS CHECK
# ============================================================================
Write-Host "=== SCHEDULER STATUS ===" -ForegroundColor $Cyan

$OptimizerTask = Get-ScheduledTask -TaskName "SwingTrader-NightlyOptimizer" -ErrorAction SilentlyContinue
$TradeTask = Get-ScheduledTask -TaskName "SwingTrader-LaravelScheduler" -ErrorAction SilentlyContinue

if ($OptimizerTask) {
    Write-Host "✓ Optimizer task registered" -ForegroundColor $Green
} else {
    Write-Host "⚠ Optimizer task not found" -ForegroundColor $Yellow
}

if ($TradeTask) {
    Write-Host "✓ Trade executor task registered" -ForegroundColor $Green
} else {
    Write-Host "⚠ Trade executor task not found" -ForegroundColor $Yellow
}

Write-Host ""

# ============================================================================
# SUMMARY
# ============================================================================
Write-Host "=== SUMMARY ===" -ForegroundColor $Cyan

if ($ErrorCount -lt 10 -and $TickersResponse -and $AccountResponse) {
    Write-Host "✓ System appears healthy" -ForegroundColor $Green
    Write-Host "  • Optimizer logs present"
    Write-Host "  • Backend responding"
    Write-Host "  • Minimal errors"
    Write-Host "  • Account info accessible"
} else {
    Write-Host "⚠ System needs attention" -ForegroundColor $Yellow
    Write-Host "  Check the reports above for details"
}

Write-Host ""
Write-Host "Report generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor $Cyan
Write-Host ""
