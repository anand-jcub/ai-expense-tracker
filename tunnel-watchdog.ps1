# Keep local app + quick tunnel alive while the user is signed in (including lock).
# No console. Safe to run every 2 minutes.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:EXPENSE_BOOT = "1"

$HealthLocal = "http://127.0.0.1:8765/api/health"
$UrlFile = Join-Path $Root "tunnel.url"
$PidFile = Join-Path $Root "tunnel.pid"
$LogFile = Join-Path $Root "tunnel-watchdog.log"

function Write-Wd($msg) {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $msg
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

function Test-Url($u) {
    if (-not $u) { return $false }
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch {
        return $false
    }
}

$localOk = Test-Url $HealthLocal
if (-not $localOk) {
    Write-Wd "local down; start.ps1"
    try { & (Join-Path $Root "start.ps1") } catch { Write-Wd ("start failed: " + $_) }
    Start-Sleep -Seconds 3
    $localOk = Test-Url $HealthLocal
}

$cf = Get-Process cloudflared -ErrorAction SilentlyContinue
$public = $null
if (Test-Path $UrlFile) {
    $public = (Get-Content $UrlFile -ErrorAction SilentlyContinue | Select-Object -First 1)
}
$public = if ($public) { $public.Trim() } else { "" }
$pubOk = $false
if ($public) { $pubOk = Test-Url ($public.TrimEnd("/") + "/api/health") }

$needTunnel = (-not $cf) -or (-not $pubOk)
if ($needTunnel -and $localOk) {
    Write-Wd ("restart tunnel cf=" + [bool]$cf + " pubOk=" + $pubOk)
    try {
        & (Join-Path $Root "tunnel.ps1")
        Write-Wd "tunnel.ps1 done"
    } catch {
        Write-Wd ("tunnel failed: " + $_)
    }
}
