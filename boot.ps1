# Start local app + public tunnel (phone Add). Used at Windows logon.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:EXPENSE_BOOT = "1"
& (Join-Path $Root "start.ps1")
& (Join-Path $Root "tunnel.ps1")
