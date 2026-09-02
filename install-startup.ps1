# Register logon boot + a 2-minute hidden tunnel watchdog (survives PC lock).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 8)

$boot = Join-Path $Root "boot.cmd"
$bootAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ("/c `"{0}`"" -f $boot) -WorkingDirectory $Root
$bootTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "ExpenseTrackerPhone" -Action $bootAction -Trigger $bootTrigger -Settings $settings -Principal $principal -Force | Out-Null

$pyw = Join-Path $Root "venv\Scripts\pythonw.exe"
$wdPy = Join-Path $Root "tunnel_watchdog.py"
if (-not (Test-Path $pyw)) { $pyw = Join-Path $Root "venv\Scripts\python.exe" }
$wdAction = New-ScheduledTaskAction -Execute $pyw -Argument ("`"{0}`"" -f $wdPy) -WorkingDirectory $Root
$wdTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).Date) -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "ExpenseTrackerTunnelWatch" -Action $wdAction -Trigger $wdTrigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "ExpenseTrackerTunnelWatch" -ErrorAction SilentlyContinue

Write-Host "OK - app starts at sign-in; tunnel is checked every 2 minutes (including while locked)."
Write-Host "Set sleep to Never while plugged in, or lock will still drop the tunnel."
Write-Host "Remove with: uninstall-startup.cmd"
