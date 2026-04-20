# Setup Laravel Scheduler on Windows 11 via Task Scheduler (PowerShell)
# Run as Administrator

param(
    [switch]$Remove
)

$ProjectPath = "C:\data\Program Files\swing-trader-web\backend"
$PHPPath = "C:\php\php.exe"
$TaskName = "LaravelScheduler"

if ($Remove) {
    Write-Host "Removing LaravelScheduler task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed." -ForegroundColor Green
    exit
}

Write-Host "Setting up Laravel Scheduler task..." -ForegroundColor Cyan

# Create action
$Action = New-ScheduledTaskAction -Execute $PHPPath -Argument "`"$ProjectPath\artisan`" schedule:run"

# Create trigger (every minute)
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$Trigger.Repetition.Duration = [timespan]::MaxValue

# Create settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# Register task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host "Task created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Scheduler status:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, @{Name="LastRunTime"; Expression={$_.LastRunTime}}, @{Name="NextRunTime"; Expression={$_.NextRunTime}}

Write-Host ""
Write-Host "To view logs: Get-ScheduledTaskInfo -TaskName 'LaravelScheduler'" -ForegroundColor Gray
Write-Host "To remove: .\setup-scheduler-windows.ps1 -Remove" -ForegroundColor Gray
