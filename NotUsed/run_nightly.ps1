# Nightly Optimizer wrapper — called by Windows Task Scheduler
$ErrorActionPreference = "Stop"
$OptimizerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $OptimizerDir

$LogDir = Join-Path $OptimizerDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "nightly.log"

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LogFile "[$ts] Nightly optimizer starting..."

$Python = Join-Path $OptimizerDir "venv\Scripts\python.exe"
& $Python nightly_optimizer.py --timeframe 1Hour --tickers SPY QQQ IWM 2>&1 | Tee-Object -FilePath $LogFile -Append

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LogFile "[$ts] Optimizer finished (exit: $LASTEXITCODE)"
