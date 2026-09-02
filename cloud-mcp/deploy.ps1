# Deploy expense-tracker-mcp-hub to Cloudflare (free Workers + KV).
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Invoke-Npx {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    cmd /c "npx --yes $Args"
    if ($LASTEXITCODE -ne 0) { throw "npx failed: $Args" }
}

Write-Host "Installing wrangler (local)..."
cmd /c "npm install --no-fund --no-audit"
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

# Auth check
$who = cmd /c "npx --yes wrangler whoami 2>&1"
Write-Host $who
if ($who -match "not authenticated|log in") {
    Write-Host "Logging into Cloudflare (browser)..."
    cmd /c "npx --yes wrangler login"
}

# Create KV if needed
$toml = Get-Content (Join-Path $Root "wrangler.toml") -Raw
if ($toml -notmatch 'id\s*=\s*"[a-f0-9]{32}"') {
    Write-Host "Creating KV namespace STORE..."
    $out = cmd /c "npx --yes wrangler kv namespace create STORE 2>&1"
    Write-Host $out
    if ($out -match 'id\s*=\s*"([a-f0-9]+)"') {
        $kid = $Matches[1]
    } elseif ($out -match '"id"\s*:\s*"([a-f0-9]+)"') {
        $kid = $Matches[1]
    } else {
        # try list
        $list = cmd /c "npx --yes wrangler kv namespace list 2>&1"
        Write-Host $list
        throw "Could not parse KV id from create output. Paste id into wrangler.toml manually."
    }
    $block = @"
[[kv_namespaces]]
binding = "STORE"
id = "$kid"
"@
    # remove commented placeholder block if present
    $toml = $toml -replace '(?s)# \[\[kv_namespaces\]\].*?# id = "REPLACE_ME"\r?\n', ''
    if ($toml -notmatch '\[\[kv_namespaces\]\]') {
        $toml = $toml.TrimEnd() + "`n`n" + $block + "`n"
    }
    [System.IO.File]::WriteAllText((Join-Path $Root "wrangler.toml"), $toml)
    Write-Host "Wrote KV id $kid to wrangler.toml"
}

# Secret MCP_KEY
$cfgPath = Join-Path $Root ".deploy-config.json"
$key = $null
if (Test-Path $cfgPath) {
    try { $key = (Get-Content $cfgPath -Raw | ConvertFrom-Json).key } catch { $key = $null }
}
if (-not $key) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 24
    $rng.GetBytes($bytes)
    $key = ([Convert]::ToBase64String($bytes) -replace '[+/=]', 'x')
}

Write-Host "Setting MCP_KEY secret..."
# pipe key to wrangler secret put
$key | cmd /c "npx --yes wrangler secret put MCP_KEY"
if ($LASTEXITCODE -ne 0) {
    Write-Host "If secret put failed interactively, run: npx wrangler secret put MCP_KEY"
}

Write-Host "Copying /app shell into cloud-mcp/public/app ..."
$dist = Join-Path (Split-Path $Root -Parent) "frontend\dist"
$pub = Join-Path $Root "public\app"
if (-not (Test-Path $dist)) { throw "frontend/dist missing. Run: cd frontend; npm run build" }
if (Test-Path $pub) { Remove-Item $pub -Recurse -Force }
New-Item -ItemType Directory -Path $pub -Force | Out-Null
Copy-Item -Path (Join-Path $dist "*") -Destination $pub -Recurse

Write-Host "Deploying worker..."
$deployOut = cmd /c "npx --yes wrangler deploy 2>&1"
Write-Host $deployOut

$url = $null
$deployText = ($deployOut | Out-String)
if ($deployText -match 'https://[a-z0-9.-]+\.workers\.dev') {
    $url = $Matches[0]
}

$existingCfg = $null
if (Test-Path $cfgPath) {
    try { $existingCfg = Get-Content $cfgPath -Raw | ConvertFrom-Json } catch {}
}

$cfg = @{
    url        = $(if ($url) { $url } elseif ($existingCfg -and $existingCfg.url) { $existingCfg.url } else { "https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev" })
    key        = $key
    username   = $(if ($existingCfg -and $existingCfg.username) { $existingCfg.username } else { "anand" })
    live_token = $(if ($existingCfg -and $existingCfg.live_token) { $existingCfg.live_token } else { $null })
}
$cfg | ConvertTo-Json | Set-Content $cfgPath -Encoding utf8

# Also write to parent for sync-cloud
$parentCfg = Join-Path (Split-Path $Root -Parent) "cloud-mcp\.deploy-config.json"
# already in cloud-mcp

Write-Host ""
Write-Host "=== Deployed ==="
Write-Host ("Worker:  " + $cfg.url)
Write-Host ("MCP:     " + $cfg.url.TrimEnd('/') + "/mcp?key=" + $key)
Write-Host ("Config:  " + $cfgPath)
Write-Host ""
Write-Host "Next: from repo root run  sync-cloud.cmd"
Write-Host "Then paste the MCP URL into Gemini Spark -> Connected apps."
