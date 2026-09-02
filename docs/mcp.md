# MCP server — expense tracker

Phase 3: agents talk to your **same domain layer** (khata + dashboard filters), not a second database.

## Gmail statement → app (not Gemini)

Bank emails a **password-protected PDF**. The **tool** already holds the statement password (saved on first UI import). Upload the PDF; unlock is automatic; transactions appear.

```cmd
import-mail.cmd
```

- Drop PDFs in `data\inbox` **or** pass a path: `import-mail.cmd C:\path\file.pdf`  
- Optional Gmail fetch: `data\gmail_token.json`  
- Re-run `sync-cloud.cmd` if you want Gemini Spark to *read* the new rows  

Gemini does **not** decrypt the PDF.

## Two tracks (like Second Brain)

| Track | For | How |
|-------|-----|-----|
| **1. Local stdio** | Cursor, Claude Desktop, Antigravity on this PC | `python -m expense_tracker.mcp_server` |
| **2. Cloudflare Worker** | **Gemini Spark / cloud AIs** | `https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev/mcp?key=…` |

### Cloud AI (Track 2) — do this

1. After imports on the PC: run **`sync-cloud.cmd`** (pushes balances + full transaction export to the Worker).  
2. Open Gemini Spark → **Connected apps** → add the URL from:

```powershell
$c = Get-Content .\cloud-mcp\.deploy-config.json | ConvertFrom-Json
"$($c.url)/mcp?key=$($c.key)"
```

3. Ask the cloud AI about balances or transactions.  
4. Re-run **`sync-cloud.cmd`** whenever local data changes.

Details: [cloud-mcp/README.md](../cloud-mcp/README.md).

## Tools

| Tool | Purpose |
|------|---------|
| `list_users` | Local `expenses_*.db` usernames |
| `list_balances` | Who owes whom (nonzero by default) |
| `get_balance_for_person` | One person by name/id + plain-language answer |
| `get_person_ledger` | Ledger history (newest first) |
| `get_dashboard_summary` | Period spend (default: current month, exclude business) |
| `search_transactions` | Quick search bank rows (optional period) |
| `export_transactions` | **Full export** — same columns as dashboard CSV/JSON download |
| `add_khata_entry` | Write a loan/split ledger line |

**Sign convention:** `net > 0` → they owe you; pass-through excluded from net.

## Run locally (stdio)

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
$env:EXPENSE_MCP_USER = "anand"
$env:DATA_DIR = "C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\data"
.\venv\Scripts\python.exe -m expense_tracker.mcp_server
```

## Cursor MCP config

Add to Cursor MCP settings (path may vary by Cursor version), e.g. `mcp.json`:

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "C:\\Users\\User\\Documents\\Codex\\2026-07-02\\i-want-to-build-an-ai\\venv\\Scripts\\python.exe",
      "args": ["-m", "expense_tracker.mcp_server"],
      "cwd": "C:\\Users\\User\\Documents\\Codex\\2026-07-02\\i-want-to-build-an-ai",
      "env": {
        "EXPENSE_MCP_USER": "anand",
        "DATA_DIR": "C:\\Users\\User\\Documents\\Codex\\2026-07-02\\i-want-to-build-an-ai\\data"
      }
    }
  }
}
```

## Claude Desktop

Same `command` / `args` / `env` under `mcpServers` in `claude_desktop_config.json`.

## Dependency

```powershell
.\venv\Scripts\pip.exe install "mcp[cli]"
```

Listed in `requirements.txt` as `mcp`.

## Cloud AI (like Second Brain — without a Worker yet)

Second Brain uses a Cloudflare Worker `/mcp?key=…`.  
This app can feed **cloud AI** the same way Custom GPT Actions / HTTP tools work: **tunnel URL + Bearer token**.

1. Keep the app + tunnel running (`start.ps1`, `tunnel.cmd`).  
2. Mint a token once (local or tunnel URL):

```powershell
$body = '{"username":"anand","password":"YOUR_PASSWORD","label":"cloud-ai","days_valid":90}'
$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/token `
  -ContentType application/json -Body $body
$r.token   # save this — exp_…
```

3. Point the cloud tool at your **public** base (from `tunnel.url`), e.g.:

| Tool purpose | Method | Path |
|--------------|--------|------|
| All / filtered export (JSON) | GET | `/api/export.json?start_date=2026-06-01&end_date=2026-08-13&limit=200` |
| CSV download | GET | `/api/export.csv` |
| Browse rows | GET | `/api/transactions?q=swiggy&limit=50` |
| Khata balances | GET | `/api/settlement/summary` |

Header on every call:

```http
Authorization: Bearer exp_…
```

Example:

```powershell
$base = Get-Content .\tunnel.url
$token = "exp_…"
Invoke-RestMethod -Uri "$base/api/export.json?limit=20" `
  -Headers @{ Authorization = "Bearer $token" }
```

That JSON is the **same export data** as the dashboard “Download JSON” button.

**vs Second Brain:** data still lives on this PC (tunnel must be up). A permanent Worker + cloud copy is a later optional step.

## Smoke test (no MCP host)

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
$env:EXPENSE_MCP_USER="anand"
.\venv\Scripts\python.exe -c "from expense_tracker.mcp_server import list_balances, get_balance_for_person, export_transactions; print(list_balances()[:3]); print(get_balance_for_person('Ranjima')); print(export_transactions(limit=3)['count'])"
```
