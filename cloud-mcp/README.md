# Expense Tracker — Cloud MCP (Gemini Spark)

Same pattern as **Second Brain**: Cloudflare Worker + Streamable HTTP MCP + key.

## Live endpoint

After deploy (already done on this account):

```text
https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev/mcp?key=YOUR_MCP_KEY
```

Your key is in **`.deploy-config.json`** (local only, not committed).  
Print the full URL:

```powershell
cd cloud-mcp
$c = Get-Content .deploy-config.json | ConvertFrom-Json
"$($c.url)/mcp?key=$($c.key)"
```

## Connect Gemini Spark

1. On this PC, after imports/reviews: **`sync-cloud.cmd`** (from repo root)  
2. Gemini Spark → **Connected apps** → **Add custom app link**  
3. Paste the `/mcp?key=…` URL  
4. Ask e.g. “What does Highnes owe me?” or “Show my recent grocery transactions”

## Sync data from PC

```cmd
sync-cloud.cmd
```

Pushes balances, ledgers, and **full transaction export** (same columns as dashboard download) into Worker KV.

Cloud AI works **even if the PC is off** until the next data change — then run sync again.

**Phone app (PC off):** after deploy + `sync-cloud.cmd`, open:

```text
https://expense-tracker-mcp-hub.anandjcub-sb.workers.dev/app/?key=YOUR_MCP_KEY
```

Same Home / Ask as `/app` on the PC. Add and Gemini stay on the desktop.

## Redeploy

```cmd
cd cloud-mcp
deploy.cmd
```

Requires Cloudflare login (`npx wrangler login` once).

## Tools

| Tool | Purpose |
|------|---------|
| `list_balances` | Khata balances |
| `get_balance_for_person` | One person |
| `get_person_ledger` | Ledger history |
| `get_dashboard_summary` | Period spend |
| `search_transactions` | Search bank rows |
| `export_transactions` | Full export fields |
| `get_sync_status` | Last sync time / counts |

Writes (`add_khata_entry`) stay on local MCP only (v1) to avoid split-brain with SQLite.
