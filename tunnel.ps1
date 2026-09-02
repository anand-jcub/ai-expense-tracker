# Free public HTTPS URL for the local expense tracker (Cloudflare quick tunnel).
# No account, no deposit. Your PC must stay on while you use the link.
#
# Usage:  tunnel.cmd
#    or:  powershell -NoProfile -ExecutionPolicy Bypass -File .\tunnel.ps1
#
# URL changes each time you restart the tunnel (trycloudflare.com).
# ASCII-only script.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LocalUrl = "http://127.0.0.1:8765"
$HealthUrl = "http://127.0.0.1:8765/api/health"
$LogFile = Join-Path $Root "tunnel.log"
$PidFile = Join-Path $Root "tunnel.pid"
$UrlFile = Join-Path $Root "tunnel.url"

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Resolve-Cloudflared {
    $candidates = @(
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe",
        "$env:LOCALAPPDATA\Programs\cloudflared\cloudflared.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Refresh-Path
$Cloudflared = Resolve-Cloudflared

if (-not $Cloudflared) {
    Write-Host "Installing cloudflared (winget)..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $Cloudflared = Resolve-Cloudflared
}

if (-not $Cloudflared) {
    throw "cloudflared not found. Open a new terminal and re-run tunnel.cmd"
}

Write-Host ("cloudflared: " + $Cloudflared)

# Ensure local app is up
$appOk = $false
try {
    $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    if ($r.StatusCode -ge 200) { $appOk = $true }
} catch { $appOk = $false }

if (-not $appOk) {
    Write-Host "Local app not running. Starting it..."
    & (Join-Path $Root "start.ps1")
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -ge 200) { $appOk = $true; break }
        } catch { }
    }
}

if (-not $appOk) {
    throw "App is not listening on 8765. Run start.ps1 first, then tunnel.cmd again."
}

Write-Host "Local app OK: $LocalUrl"

# Stop previous tunnel
if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid) {
        try {
            Stop-Process -Id ([int]$oldPid) -Force -ErrorAction SilentlyContinue
        } catch { }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("Stopping existing cloudflared pid " + $_.Id)
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

if (Test-Path $LogFile) { Remove-Item $LogFile -Force -ErrorAction SilentlyContinue }
if (Test-Path $UrlFile) { Remove-Item $UrlFile -Force -ErrorAction SilentlyContinue }

Write-Host "Starting Cloudflare quick tunnel (free trycloudflare.com)..."
Write-Host "PC must stay on. URL changes each time you restart the tunnel."
Write-Host ""

# Hidden process so lock/watchdog do not flash a CMD window.
# --logfile captures the trycloudflare URL for us to print.
$proc = Start-Process -FilePath $Cloudflared -ArgumentList @(
    "tunnel", "--url", $LocalUrl, "--logfile", $LogFile, "--no-autoupdate"
) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
if (-not $proc -or -not $proc.Id) {
    throw "Failed to start cloudflared"
}
$tunnelPid = $proc.Id
$tunnelPid | Set-Content $PidFile -Encoding ascii
Write-Host ("Tunnel process pid " + $tunnelPid)

function Read-LogShared {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    try {
        # cloudflared keeps the log open; allow shared read
        $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        try {
            $sr = New-Object System.IO.StreamReader($fs)
            try { return $sr.ReadToEnd() } finally { $sr.Dispose() }
        } finally { $fs.Dispose() }
    } catch {
        return ""
    }
}

$publicUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $text = Read-LogShared $LogFile
    if ($text -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        $publicUrl = $Matches[0]
        break
    }
    $alive = Get-Process -Id $tunnelPid -ErrorAction SilentlyContinue
    if (-not $alive) {
        Write-Host "cloudflared exited early. Log:"
        Write-Host (Read-LogShared $LogFile)
        throw "Tunnel failed to start."
    }
}

if (-not $publicUrl) {
    Write-Host "Still waiting for URL. Latest log:"
    if (Test-Path $LogFile) { Get-Content $LogFile -Tail 40 }
    throw "Could not parse trycloudflare URL. Check tunnel.log"
}

$publicUrl | Set-Content $UrlFile -Encoding ascii

$py = Join-Path $Root "venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $Root "venv\Scripts\python.exe" }
if (Test-Path $py) {
    try {
        & $py -m expense_tracker.cloud_sync --register-live | Out-Host
    } catch {
        Write-Host "Could not register live URL with the Worker (phone will use last sync until sync-cloud)."
    }
}

Write-Host ""
Write-Host "=== Tunnel live ==="
Write-Host ("Public:  " + $publicUrl)
Write-Host ("Login:   " + $publicUrl + "/login")
Write-Host ("Health:  " + $publicUrl + "/api/health")
Write-Host ("Local:   " + $LocalUrl)
Write-Host ""
Write-Host "Stop with:  stop-tunnel.cmd"
Write-Host "(URL is also saved in tunnel.url)"
Write-Host ""

# Quick health check (may take a few seconds for edge to warm up)
Start-Sleep -Seconds 3
try {
    $h = Invoke-WebRequest -Uri ($publicUrl + "/api/health") -UseBasicParsing -TimeoutSec 30
    Write-Host ("Health check: " + $h.Content)
} catch {
    Write-Host "Health check not ready yet - open the Login URL in a browser in a few seconds."
}

if ($env:EXPENSE_BOOT -ne "1") {
    try { Start-Process $publicUrl } catch { }
}
