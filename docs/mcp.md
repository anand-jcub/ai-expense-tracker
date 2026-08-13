# MCP server — expense tracker

Phase 3: agents talk to your **same domain layer** (khata + dashboard filters), not a second database.

## Tools

| Tool | Purpose |
|------|---------|
| `list_users` | Local `expenses_*.db` usernames |
| `list_balances` | Who owes whom (nonzero by default) |
| `get_balance_for_person` | One person by name/id + plain-language answer |
| `get_person_ledger` | Ledger history (newest first) |
| `get_dashboard_summary` | Period spend (default: current month, exclude business) |
| `search_transactions` | Search bank rows (optional period) |
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

## Hosted / remote MCP (later)

1. Keep this stdio server for local agents.  
2. For remote: agents call HTTPS `Authorization: Bearer` APIs (`docs/api.md`) or add Streamable HTTP transport on the same tools.  
3. Never duplicate `get_balance` math outside Python domain.

## Smoke test (no MCP host)

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
$env:EXPENSE_MCP_USER="anand"
.\venv\Scripts\python.exe -c "from expense_tracker.mcp_server import list_balances, get_balance_for_person; print(list_balances()[:3]); print(get_balance_for_person('Ranjima'))"
```
