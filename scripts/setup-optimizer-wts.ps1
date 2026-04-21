# Setup Nightly Optimizer on Windows Task Scheduler
# RUN AS ADMINISTRATOR

param(
    [switch]$Remove
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OptimizerDir = Join-Path $ProjectRoot "optimizer"
$RunScript = Join-Path $OptimizerDir "run_nightly.ps1"
$TaskName = "SwingTrader-NightlyOptimizer"

if ($Remove) {
    Write-Host "Removing $TaskName..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed." -ForegroundColor Green
    exit
}

Write-Host "Setting up $TaskName..." -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray
Write-Host "Optimizer dir: $OptimizerDir" -ForegroundColor Gray
Write-Host "Run script: $RunScript" -ForegroundColor Gray

# Verify script exists
if (-not (Test-Path $RunScript)) {
    Write-Host "ERROR: $RunScript not found!" -ForegroundColor Red
    exit 1
}

# Create action: run PowerShell non-interactively with the script
$Argument = "-NonInteractive -NoProfile -File `"$RunScript`""
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument

# Create trigger: daily at 2:00 AM local time
$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "02:00"

# Create principal: SYSTEM with highest privileges (no timeout)
$Principal = New-ScheduledTaskPrincipal `
    -UserID "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Create settings: no timeout, allow on battery
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# Register the task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Force | Out-Null

Write-Host ""
Write-Host "Task created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Task Details:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, NextRunTime

Write-Host ""
Write-Host "Manual trigger (anytime): schtasks /run /tn $TaskName" -ForegroundColor Gray
Write-Host "View logs: tail -f '$OptimizerDir\logs\nightly.log'" -ForegroundColor Gray
Write-Host "Remove: .\setup-optimizer-wts.ps1 -Remove" -ForegroundColor Gray
