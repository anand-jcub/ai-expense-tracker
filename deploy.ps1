# One-shot Fly.io deploy (run in YOUR interactive PowerShell / Windows Terminal).
# This environment cannot open a browser for fly auth login.
#
# Usage:
#   cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
#   .\deploy.ps1
#
# First time: will open browser for Fly login if needed.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

if (-not (Get-Command flyctl -ErrorAction SilentlyContinue)) {
    Write-Host "Installing flyctl..."
    winget install --id Fly-io.flyctl -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "flyctl: $(flyctl version)"

# Auth
$who = $null
try {
    $who = flyctl auth whoami 2>$null
} catch { }
if (-not $who) {
    Write-Host "Logging into Fly.io (browser will open)..."
    flyctl auth login
    $who = flyctl auth whoami
}
Write-Host "Logged in as: $who"

# Unique app name if default taken
$App = "expense-tracker-anand"
$exists = flyctl apps list 2>$null | Select-String -SimpleMatch $App
if (-not $exists) {
    Write-Host "Creating app $App in region sin..."
    flyctl apps create $App --org personal 2>$null
    if ($LASTEXITCODE -ne 0) {
        $suffix = Get-Random -Maximum 9999
        $App = "expense-tracker-$suffix"
        Write-Host "Trying app name $App..."
        flyctl apps create $App --org personal
    }
}

# Ensure fly.toml app name matches
(Get-Content fly.toml -Raw) -replace 'app = ".*"', "app = `"$App`"" | Set-Content fly.toml -NoNewline

# Volume for SQLite (idempotent-ish)
Write-Host "Ensuring volume expensedata..."
$vols = flyctl volumes list -a $App 2>$null
if ($vols -notmatch "expensedata") {
    flyctl volumes create expensedata --region sin --size 1 -a $App -y
}

# Uncomment mounts in fly.toml if still commented
$toml = Get-Content fly.toml -Raw
if ($toml -match '(?s)# \[\[mounts\]\].*?#\s+destination = "/data"') {
    $toml = $toml -replace '# \[\[mounts\]\]', '[[mounts]]'
    $toml = $toml -replace '#\s+source = "expensedata"', '  source = "expensedata"'
    $toml = $toml -replace '#\s+destination = "/data"', '  destination = "/data"'
    Set-Content fly.toml $toml -NoNewline
}

Write-Host "Deploying (remote builder — no local Docker required)..."
flyctl deploy -a $App --remote-only

Write-Host ""
Write-Host "=== Done ==="
flyctl status -a $App
flyctl apps open -a $App
Write-Host "URL: https://$App.fly.dev"
Write-Host "Health: https://$App.fly.dev/api/health"
Write-Host "Login:  https://$App.fly.dev/login"
