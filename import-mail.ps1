# Import statement PDFs using the password already saved in the tool.
# Usage:
#   import-mail.cmd
#   import-mail.cmd C:\path\statement.pdf
# Drop PDFs in data\inbox  or pass a path. Gmail optional (data\gmail_token.json).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (-not $env:EXPENSE_MCP_USER) { $env:EXPENSE_MCP_USER = "anand" }
$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m expense_tracker.mail_import @args
exit $LASTEXITCODE
