# Stop the Cloudflare tunnel started by tunnel.ps1
$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "tunnel.pid"

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile
    if ($oldPid) {
        $p = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host "Stopping tunnel pid $oldPid..."
            Stop-Process -Id ([int]$oldPid) -Force
        } else {
            Write-Host "No process for pid $oldPid"
        }
    }
    Remove-Item $PidFile -Force
}

Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ("Stopping cloudflared pid " + $_.Id)
    Stop-Process -Id $_.Id -Force
}

Remove-Item (Join-Path $Root "tunnel.url") -Force -ErrorAction SilentlyContinue
Write-Host "Tunnel stopped. Local app at http://127.0.0.1:8765 is unchanged."
