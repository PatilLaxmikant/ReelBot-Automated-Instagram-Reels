<#
.SYNOPSIS
    Register (or update) the daily reel-generation task in Windows Task Scheduler.

.DESCRIPTION
    Creates a task that runs run_daily.bat once a day. The task generates the
    reel scheduled for that weekday and leaves it in the review queue - it does
    not post to Instagram unless PUBLISH_MODE=auto in .env.

.PARAMETER Time
    Local time to run, HH:mm. Default 09:00.

.PARAMETER TaskName
    Scheduler task name. Default "ReelBot Daily".

.PARAMETER Remove
    Unregister the task instead of creating it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time 18:30
    powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Time = "09:00",
    [string]$TaskName = "ReelBot Daily",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$batch = Join-Path $projectRoot "run_daily.bat"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    }
    else {
        Write-Host "No scheduled task named '$TaskName'." -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path $batch)) {
    throw "Cannot find $batch - run this script from inside the project."
}

try {
    $startTime = [datetime]::ParseExact($Time, "HH:mm", $null)
}
catch {
    throw "-Time must look like 09:00 or 18:30 (24-hour). Got '$Time'."
}

$action = New-ScheduledTaskAction -Execute $batch -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $startTime

# StartWhenAvailable catches up a run missed while the machine was off/asleep;
# run_daily is idempotent per date, so a catch-up cannot double-post.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

# Run as the logged-in user so .env, fonts and the network profile all resolve.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Replacing existing task '$TaskName'." -ForegroundColor Yellow
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Generates the scheduled daily English-learning Reel and queues it for review." | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' - runs daily at $Time." -ForegroundColor Green
Write-Host ""
Write-Host "  Verify :  Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Test    :  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Logs    :  $projectRoot\logs\scheduler.log"
Write-Host "  Remove  :  powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove"
Write-Host ""
Write-Host "Reels are held for review. Approve with:  reelbot queue list" -ForegroundColor Cyan
