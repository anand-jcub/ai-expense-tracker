# HTTP API inventory (Phase 1)

Base URL: your host, e.g. `http://127.0.0.1:8765` or Cloud Run/Fly URL.

## Authentication

| Method | How |
|--------|-----|
| **Browser** | Login form → `session` cookie (`HttpOnly`) |
| **MCP / mobile / scripts** | `Authorization: Bearer <token>` |

### Create API token

```http
POST /api/token
Content-Type: application/json

{"username":"anand","password":"…","label":"mcp","days_valid":90}
```

Response:

```json
{
  "token": "exp_…",
  "token_type": "Bearer",
  "usage": "Authorization: Bearer <token>"
}
```

Store the token once; only a hash is kept server-side.

### Revoke token

```http
POST /api/token/revoke
Authorization: Bearer exp_…
```

### Health (no auth on PC; Worker `/api/health` needs the hub key)

Live PC: `{ "mode": "live", "writes": true }`  
Worker snapshot: `{ "mode": "snapshot", "writes": false, "syncedAt": "…" }`

Phone when the PC is off (same `/app`, Worker URL):

```text
https://expense-tracker-mcp-hub.<you>.workers.dev/app/?key=YOUR_MCP_KEY
```

That key is stored on the phone once. Home/Ask read the last `sync-cloud` glance. Add is disabled. Run `sync-cloud.cmd` after imports.

### Health (no auth)

```http
GET /api/health
```

---

## JSON APIs (auth required)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/settlement/summary` | All non-zero person balances (khata) |
| GET | `/api/settlement?contact_id=` | Balance for one contact |
| GET | `/api/settlement/by-name?q=` | Resolve name → balance + answer text |
| GET | `/api/contacts/ledger?contact_id=` | Contact + balance + ledger entries |
| GET | `/api/onboarding` | Setup checklist status |
| GET | `/api/export.json` | **Full transaction export** (same as dashboard Download JSON) |
| GET | `/api/export.csv` | Same rows as CSV download |
| GET | `/api/transactions` | Filtered export rows (default `limit=50`, newest first) |
| GET | `/api/dashboard/summary` | Period spend (same owner as MCP / Ask). Default: this month, exclude business |
| GET | `/api/meta` | Categories + expense types |
| POST | `/api/manual` | JSON add (same as form `/manual`) |
| POST | `/api/assistant/chat` | Gemini / local-intent Ask |
| POST | `/api/assistant/confirm` | Execute one pending money write |

### Transaction export query params

| Param | Used on | Meaning |
|-------|---------|---------|
| `start_date` / `start` | export + transactions | Inclusive `YYYY-MM-DD` |
| `end_date` / `end` | export + transactions | Inclusive `YYYY-MM-DD` |
| `q` / `query` | export + transactions | Substring on merchant, description, category, notes |
| `limit` | export + transactions | Cap rows (export max 5000; transactions max 500) |

Example (cloud AI / scripts over tunnel):

```http
GET /api/export.json?start_date=2026-06-01&limit=100
Authorization: Bearer exp_…
```

### Example

```powershell
$token = (Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/token `
  -ContentType application/json `
  -Body '{"username":"anand","password":"YOUR_PASSWORD","label":"cli"}').token

Invoke-RestMethod -Uri http://127.0.0.1:8765/api/settlement/summary `
  -Headers @{ Authorization = "Bearer $token" }
```

---

### Dashboard summary

```http
GET /api/dashboard/summary?start_date=2026-08-01&end_date=2026-08-31
```

`by_category` is personal-share spend. Khata balances stay on `/api/settlement/summary`.

### Assistant

```http
POST /api/assistant/chat
{"message":"How much does Highnes owe me?"}

POST /api/assistant/confirm
{"confirm_token":"…"}
```

Write tools return a confirmation card. Nothing is stored until `/api/assistant/confirm`.  
Needs `GEMINI_API_KEY` on the PC for full Ask; without it, balance and “food this month” still work locally.

Phone UI: `http://127.0.0.1:8765/app/` (or the tunnel URL + `/app/`). Add to Home Screen.

---

## Form / page routes (browser session)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Classic dashboard + People |
| GET | `/app/…` | React shell |
| POST | `/login` `/register` `/logout` | Auth |
| POST | `/import` `/manual` `/review` … | Bank / classification |
| POST | `/contacts/create` `/contacts/edit` | People |
| POST | `/ledger/add` `/ledger/rolling` `/ledger/opening` `/ledger/settle` … | Khata writes |
| GET | `/export.csv` `/export.json` | Exports |

---

## Conventions (for MCP / agents)

- **Balance sign:** `net > 0` → they owe you; `net < 0` → you owe them.
- **Pass-through / rolling:** stored but **excluded** from `net`.
- **Do not** reimplement math on the client; call these APIs.

## Next (Phase 3 MCP)

Thin MCP tools will wrap:

- `list_balances` → `/api/settlement/summary`
- `get_ledger` → `/api/contacts/ledger`
- `get_balance_by_name` → `/api/settlement/by-name`
