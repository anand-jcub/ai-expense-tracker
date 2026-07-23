# Permanent launcher: one silent watchdog, no extra terminal windows.
# Uses pythonw.exe (windowless) + single-instance lock in run_forever.py.
#
# Usage:  .\start.ps1
# Stop:   .\stop.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Prefer windowless interpreter so no black console pops open
$PythonW = Join-Path $Root "venv\Scripts\pythonw.exe"
$Python = Join-Path $Root "venv\Scripts\python.exe"
if (Test-Path $PythonW) {
    $Launcher = $PythonW
} elseif (Test-Path $Python) {
    $Launcher = $Python
} else {
    $Launcher = "pythonw"
}

$Watchdog = Join-Path $Root "run_forever.py"

# Already answering?
try {
    $ok = Invoke-WebRequest -Uri "http://127.0.0.1:8765/login" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
    if ($ok.StatusCode -ge 200) {
        Write-Host "Already running at http://127.0.0.1:8765"
        exit 0
    }
} catch { }

# Stop leftovers (old watchdogs / servers) first
if (Test-Path (Join-Path $Root "stop.ps1")) {
    try { & (Join-Path $Root "stop.ps1") | Out-Null } catch { }
    Start-Sleep -Seconds 1
}

Write-Host "Starting silent watchdog (no console window)..."

# Detached from agent Job Object, no visible window (pythonw)
$cmd = '"' + $Launcher + '" "' + $Watchdog + '"'
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine      = $cmd
    CurrentDirectory = $Root
}

if ($null -eq $r -or $r.ReturnValue -ne 0) {
    Write-Host "WMI start failed (ReturnValue=$($r.ReturnValue)). Using Start-Process Hidden..."
    $proc = Start-Process -FilePath $Launcher -ArgumentList "run_forever.py" -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    $watchPid = $proc.Id
} else {
    $watchPid = $r.ProcessId
}

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/login" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -ge 200) { $ready = $true; break }
    } catch { }
}

if ($ready) {
    Write-Host "OK - open http://127.0.0.1:8765  (started pid $watchPid)"
    exit 0
}

Write-Host "Started (pid $watchPid) but port not ready yet. Check run_err.log"
exit 1
