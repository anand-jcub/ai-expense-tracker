# One-shot Fly.io deploy. Run via:  deploy.cmd
# or: powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
# (ASCII-only script to avoid encoding parse errors.)
#
# Phone when PC is off does NOT use Fly. Use cloud-mcp\deploy.cmd (Cloudflare, free).

$ErrorActionPreference = "Stop"
Write-Host "This is Fly.io (needs a card). For the phone-when-PC-off app, stop and run:"
Write-Host "  cd cloud-mcp"
Write-Host "  .\deploy.cmd"
Write-Host ""
$go = Read-Host "Continue with Fly anyway? (y/N)"
if ($go -notmatch '^[yY]') { exit 0 }
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

Write-Host ("flyctl: " + (flyctl version))

$who = $null
try {
    $who = flyctl auth whoami 2>$null
} catch {
    $who = $null
}
if (-not $who) {
    Write-Host "Logging into Fly.io (browser will open)..."
    flyctl auth login
    $who = flyctl auth whoami
}
Write-Host ("Logged in as: " + $who)

$App = "expense-tracker-anand"
$exists = $false
try {
    $list = flyctl apps list 2>$null | Out-String
    if ($list -match [regex]::Escape($App)) { $exists = $true }
} catch {
    $exists = $false
}

if (-not $exists) {
    Write-Host ("Creating app " + $App + " in region sin...")
    flyctl apps create $App --org personal 2>$null
    if ($LASTEXITCODE -ne 0) {
        $suffix = Get-Random -Maximum 9999
        $App = "expense-tracker-" + $suffix
        Write-Host ("Trying app name " + $App + "...")
        flyctl apps create $App --org personal
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create Fly app. Check org name (try: flyctl orgs list)."
        }
    }
}

# Update app name in fly.toml (ASCII only)
$tomlPath = Join-Path $Root "fly.toml"
$toml = Get-Content $tomlPath -Raw
$toml = [regex]::Replace($toml, 'app\s*=\s*"[^"]*"', ('app = "' + $App + '"'))
# Ensure mounts are active
$toml = $toml -replace '#\s*\[\[mounts\]\]', '[[mounts]]'
$toml = $toml -replace '#\s*source\s*=\s*"expensedata"', '  source = "expensedata"'
$toml = $toml -replace '#\s*destination\s*=\s*"/data"', '  destination = "/data"'
[System.IO.File]::WriteAllText($tomlPath, $toml)

Write-Host "Ensuring volume expensedata..."
$vols = ""
try { $vols = flyctl volumes list -a $App 2>$null | Out-String } catch { $vols = "" }
if ($vols -notmatch "expensedata") {
    flyctl volumes create expensedata --region sin --size 1 -a $App -y
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Volume create failed or already exists; continuing..."
    }
}

Write-Host "Deploying (remote builder, no local Docker required)..."
flyctl deploy -a $App --remote-only
if ($LASTEXITCODE -ne 0) {
    throw "flyctl deploy failed."
}

Write-Host ""
Write-Host "=== Done ==="
flyctl status -a $App
Write-Host ("URL:    https://" + $App + ".fly.dev")
Write-Host ("Health: https://" + $App + ".fly.dev/api/health")
Write-Host ("Login:  https://" + $App + ".fly.dev/login")
try { flyctl apps open -a $App } catch { }
