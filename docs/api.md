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

### Example

```powershell
$token = (Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/token `
  -ContentType application/json `
  -Body '{"username":"anand","password":"YOUR_PASSWORD","label":"cli"}').token

Invoke-RestMethod -Uri http://127.0.0.1:8765/api/settlement/summary `
  -Headers @{ Authorization = "Bearer $token" }
```

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
