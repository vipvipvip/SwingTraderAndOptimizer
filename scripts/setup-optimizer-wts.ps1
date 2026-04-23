# Setup Windows Task Scheduler for nightly optimizer
# Run as Administrator: powershell -ExecutionPolicy Bypass -File scripts/setup-optimizer-wts.ps1
# Remove task: powershell -ExecutionPolicy Bypass -File scripts/setup-optimizer-wts.ps1 -Remove

param(
    [switch]$Remove = $false
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$OptimizerScript = Join-Path $ProjectRoot "optimizer\run_nightly.ps1"
$TaskName = "SwingTrader-NightlyOptimizer"
$TaskPath = "\SwingTrader\"

if ($Remove) {
    Write-Host "[*] Removing scheduled task '$TaskName'..."
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "[OK] Task removed"
    } catch {
        Write-Host "[!] Task not found or error: $_"
    }
    exit 0
}

# Check if already registered
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "[OK] Task already registered: $TaskName"
    Write-Host "  Schedule: $($existingTask.Triggers)"
    Write-Host ""
    Write-Host "To remove: powershell -ExecutionPolicy Bypass -File scripts/setup-optimizer-wts.ps1 -Remove"
    exit 0
}

Write-Host "[*] Registering scheduled task: $TaskName"

# Verify script exists
if (-not (Test-Path $OptimizerScript)) {
    Write-Error "Optimizer script not found: $OptimizerScript"
    exit 1
}

# Create task action: run PowerShell script non-interactively
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -NoProfile -File ""$OptimizerScript"""

# Create task trigger: daily at 2:00 AM
$trigger = New-ScheduledTaskTrigger -Daily -At 02:00AM

# Create task principal: SYSTEM user with highest privilege
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Create task settings: allow task to run even if not logged in
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$true

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Nightly optimizer for swing trading strategy parameters" `
        -Force | Out-Null

    Write-Host "[OK] Task registered successfully"
    Write-Host ""
    Write-Host "Task Details:"
    Write-Host "  Name: $TaskName"
    Write-Host "  Script: $OptimizerScript"
    Write-Host "  Schedule: Daily at 02:00 AM"
    Write-Host "  Principal: SYSTEM (Highest privilege)"
    Write-Host ""
    Write-Host "To verify: schtasks query /tn ""$TaskName"""
    Write-Host "To manually trigger: schtasks run /tn ""$TaskName"""
    Write-Host "To remove: powershell -ExecutionPolicy Bypass -File scripts/setup-optimizer-wts.ps1 -Remove"

} catch {
    Write-Error "Failed to register task: $_"
    exit 1
}
