# Push local expense data to Cloudflare MCP hub (cloud AI / Gemini Spark).
# Usage:  sync-cloud.cmd
# Needs cloud-mcp/.deploy-config.json OR env EXPENSE_MCP_URL + EXPENSE_MCP_KEY

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$cfgPath = Join-Path $Root "cloud-mcp\.deploy-config.json"
if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    if (-not $env:EXPENSE_MCP_URL -and $cfg.url) { $env:EXPENSE_MCP_URL = $cfg.url }
    if (-not $env:EXPENSE_MCP_KEY -and $cfg.key) { $env:EXPENSE_MCP_KEY = $cfg.key }
    if (-not $env:EXPENSE_MCP_USER -and $cfg.username) { $env:EXPENSE_MCP_USER = $cfg.username }
}

if (-not $env:EXPENSE_MCP_USER) { $env:EXPENSE_MCP_USER = "anand" }
$env:DATA_DIR = Join-Path $Root "data"

$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

& $py -m expense_tracker.cloud_sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Gemini Spark: Connected apps -> add:"
$url = $env:EXPENSE_MCP_URL.TrimEnd('/')
$key = $env:EXPENSE_MCP_KEY
Write-Host ("  " + $url + "/mcp?key=" + $key)
Write-Host "Phone when PC is off:"
Write-Host ("  " + $url + "/app/?key=" + $key)
