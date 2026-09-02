# One-shot Google Cloud Run deploy. Run via:  deploy-gcp.cmd
# or: powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-gcp.ps1
# No local Docker required: uses gcloud run deploy --source (Cloud Build).
# ASCII-only to avoid PowerShell encoding parse errors.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Prefer gcloud.cmd: gcloud.ps1 is blocked when ExecutionPolicy is Restricted.
$script:GcloudCmd = $null

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Resolve-Gcloud {
    $candidates = @(
        "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $script:GcloudCmd = $c
            $env:Path = (Split-Path $c -Parent) + ";" + $env:Path
            return
        }
    }
    $cmd = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
    if ($cmd) { $script:GcloudCmd = $cmd.Source; return }
    $cmd = Get-Command gcloud -ErrorAction SilentlyContinue
    if ($cmd) { $script:GcloudCmd = $cmd.Source; return }
}

function Invoke-Gcloud {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)
    & $script:GcloudCmd @GcloudArgs
    return $LASTEXITCODE
}

Refresh-Path
Resolve-Gcloud

# --- gcloud install ---
if (-not $script:GcloudCmd) {
    Write-Host "Installing Google Cloud SDK (winget)..."
    winget install --id Google.CloudSDK -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    Resolve-Gcloud
}

if (-not $script:GcloudCmd) {
    throw "gcloud not found after install. Close this window, open a new terminal, and re-run deploy-gcp.cmd"
}

Write-Host ("gcloud: " + $script:GcloudCmd)
$ver = & $script:GcloudCmd --version 2>&1 | Select-Object -First 1
Write-Host $ver

# --- Auth ---
$acct = ""
try {
    $acct = (& $script:GcloudCmd auth list --filter=status:ACTIVE --format="value(account)" 2>$null | Select-Object -First 1)
} catch { $acct = "" }
if (-not $acct) {
    Write-Host "Logging into Google Cloud (browser will open)..."
    & $script:GcloudCmd auth login
    $acct = (& $script:GcloudCmd auth list --filter=status:ACTIVE --format="value(account)" | Select-Object -First 1)
}
Write-Host ("Logged in as: " + $acct)

# --- Project ---
$Project = (& $script:GcloudCmd config get-value project 2>$null)
if (-not $Project -or $Project -eq "(unset)") {
    Write-Host ""
    Write-Host "No default GCP project set."
    Write-Host "Listing projects..."
    & $script:GcloudCmd projects list
    Write-Host ""
    Write-Host "Create one at https://console.cloud.google.com/projectcreate if needed,"
    Write-Host "then set it:  gcloud config set project YOUR_PROJECT_ID"
    $Project = Read-Host "Enter GCP project ID to use"
    if (-not $Project) { throw "Project ID required." }
    & $script:GcloudCmd config set project $Project
}
Write-Host ("Project: " + $Project)

# Application default credentials help Cloud Build / some APIs
try {
    $adc = & $script:GcloudCmd auth application-default print-access-token 2>$null
    if (-not $adc -or $LASTEXITCODE -ne 0) {
        Write-Host "Setting application-default credentials (browser may open)..."
        & $script:GcloudCmd auth application-default login
    }
} catch {
    Write-Host "Setting application-default credentials (browser may open)..."
    & $script:GcloudCmd auth application-default login
}

# --- Config ---
$Region = "asia-south1"
$Service = "expense-tracker"
$Bucket = ($Project + "-expense-data").ToLower() -replace '[^a-z0-9\-]', '-'
if ($Bucket.Length -gt 63) { $Bucket = $Bucket.Substring(0, 63).TrimEnd('-') }

Write-Host "Enabling APIs (Cloud Run, Cloud Build, Artifact Registry, Storage)..."
& $script:GcloudCmd services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com --project $Project
if ($LASTEXITCODE -ne 0) {
    Write-Host "API enable failed. Link a billing account (free tier still applies within limits):"
    Write-Host "  https://console.cloud.google.com/billing/linkedaccount?project=$Project"
    throw "Could not enable APIs."
}

# --- GCS bucket for SQLite (durable; max-instances=1) ---
$bucketExists = $false
try {
    & $script:GcloudCmd storage buckets describe "gs://$Bucket" --project $Project 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $bucketExists = $true }
} catch { $bucketExists = $false }

if (-not $bucketExists) {
    Write-Host ("Creating bucket gs://" + $Bucket + " in " + $Region + "...")
    & $script:GcloudCmd storage buckets create "gs://$Bucket" --project $Project --location $Region --uniform-bucket-level-access
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Bucket create failed; deploying with ephemeral /tmp/data (demo only)."
        $Bucket = $null
    }
}

# --- Deploy ---
Write-Host "Deploying to Cloud Run (source build; first build can take 5-10 min)..."
$envVars = "ENV=production,COOKIE_SECURE=1,DATA_DIR=/data"

$deployArgs = @(
    "run", "deploy", $Service,
    "--source", ".",
    "--region", $Region,
    "--project", $Project,
    "--allow-unauthenticated",
    "--memory", "512Mi",
    "--cpu", "1",
    "--min-instances", "0",
    "--max-instances", "1",
    "--timeout", "300",
    "--set-env-vars", $envVars,
    "--quiet"
)

if ($Bucket) {
    $deployArgs += @(
        "--add-volume", "name=expensedata,type=cloud-storage,bucket=$Bucket",
        "--add-volume-mount", "volume=expensedata,mount-path=/data"
    )
    Write-Host ("Volume: gs://" + $Bucket + " -> /data (max-instances=1 for SQLite)")
} else {
    $idx = [array]::IndexOf($deployArgs, $envVars)
    if ($idx -ge 0) {
        $deployArgs[$idx] = "ENV=production,COOKIE_SECURE=1,DATA_DIR=/tmp/data"
    }
    Write-Host "WARNING: Ephemeral disk only. Data may reset when the instance scales to zero."
}

& $script:GcloudCmd @deployArgs
if ($LASTEXITCODE -ne 0) {
    throw "gcloud run deploy failed."
}

$Url = (& $script:GcloudCmd run services describe $Service --region $Region --project $Project --format="value(status.url)" 2>$null)
Write-Host ""
Write-Host "=== Done ==="
Write-Host ("URL:    " + $Url)
Write-Host ("Health: " + $Url + "/api/health")
Write-Host ("Login:  " + $Url + "/login")
Write-Host ""
Write-Host "Register a user on first visit (cloud DB starts empty unless you upload data/)."
if ($Bucket) {
    Write-Host ("Data bucket: gs://" + $Bucket)
    Write-Host "Optional: upload local SQLite after first run, e.g."
    Write-Host ("  gcloud storage cp data\\users.db gs://" + $Bucket + "/users.db")
}
try { Start-Process $Url } catch { }
