# Architecture map — AI Expense Tracker

Living map for the **architecture agent**. Update this when modules are intentionally restructured.

## Layers (allowed dependencies flow downward only)

```text
┌─────────────────────────────────────────────────────────┐
│  UI shells                                              │
│  templates.py + static/*   |   frontend/src (React)     │
└─────────────────┬───────────────────────┬───────────────┘
                  │                       │
                  ▼                       ▼
┌─────────────────────────────────────────────────────────┐
│  HTTP edge: web.py  (routing, sessions, request I/O)    │
└─────────────────┬───────────────────────────────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
┌───────────────┐    ┌───────────────────┐
│ Domain        │    │ Auth              │
│ contacts.py   │    │ auth.py           │
│ services.py   │    └───────────────────┘
│ classifier.py │
│ connections.py│
│ sbi_pdf.py    │
└───────┬───────┘
        ▼
┌───────────────┐
│ Persistence   │
│ db.py + SQLite│
└───────────────┘
```

## Zones (feature islands)

| Zone | Paths | Owns | Must not own |
|------|--------|------|----------------|
| **A. Auth** | `auth.py`, `users.db` | login, sessions, user list | expenses, ledger |
| **B. Import / bank** | `sbi_pdf.py`, import handlers in `web.py`/`db.py` | PDF parse, immutable `transactions` | person balances |
| **C. Classification** | `classifier.py`, review/edit in `web.py`/`templates.py` | category, type, split, rules | USB/khata formulas |
| **D. Khata / People** | `contacts.py`, People UI in `templates.py`/`static/app.js` | contacts, ledger, balances, rolling | spend charts |
| **E. Dashboard spend** | `services.py` dashboard helpers, Home pane | period totals, charts, exclude business | contact merge |
| **F. React shell** | `frontend/` | /app SPA | classic form posts |
| **G. Ops** | `start.ps1`, `run_forever.py`, `app.py` | process lifecycle | domain rules |
| **H. Tests** | `tests/` | regression | production data |

## Hard rules

1. **Sign convention (khata):** `net = you_sent − they_sent`; pass-through excluded. Do not reintroduce dual balance engines.
2. **Identity:** Anand (app user) ≠ Ananthu (contact). Ranji = Ranjima. Alias changes stay in zone D.
3. **Immutability:** never rewrite `transactions` rows for UX; only classifications / ledger.
4. **One balance source:** `contacts.get_balance` / ledger — not parallel formulas in templates or JS.
5. **UI shells:** classic `/` and React `/app` may share APIs; do not duplicate domain math in React.
6. **Schema:** additive migrations only unless explicitly approved; dual-write only for legacy columns.
7. **No feature creep in shared files:** `web.py` route handlers stay thin; domain logic stays in domain modules.

## Allowed cross-zone calls

| From → To | OK? | Notes |
|-----------|-----|--------|
| web → contacts / services / db / auth | Yes | Edge calls domain |
| contacts → db helpers | Minimal | Prefer pure SQL on conn |
| templates → services display helpers | Yes | Formatting only |
| services → contacts (household summary) | Yes | Thin adapter |
| classifier → contacts | Prefer no | shared_with resolve only |
| static app.js → domain math | No | display only |
| React → Python domain | Via HTTP APIs only | |
| tests → any | Yes | |

## Blast-radius red flags

- Touching `settlement.py` (removed) or re-adding dual balance paths
- Changing `get_balance` formula while also editing dashboard spend filters
- Editing `db.py` migrations in the same change as People UI polish
- Import path changes that rewrite ledger automatically
- Global CSS `section`/`button` rules that break People or Auth layouts
- Seed contacts changing aliases that conflate identities

## Completeness (related surfaces)

Isolation alone is not enough. When a feature is added, the architecture agent also
checks **feature coherence**: every surface that should share the same state does.

Authoritative contracts: **`docs/feature-coherence.md`** (FC-01, FC-02, …).

Example: dashboard **date range** must drive metrics + all period graphs (and any
other subsection that claims “this period”), not charts only.
