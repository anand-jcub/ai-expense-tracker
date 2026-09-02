# Feature coherence contracts

Used by the **architecture agent** completeness pass.  
When a feature is added or changed, **every surface listed under that feature must stay consistent**. Missing a listed surface is a **FAIL** (incomplete), same severity as an isolation break.

Update this file when you intentionally add a new multi-surface feature.

---

## How to read a contract

| Field | Meaning |
|-------|---------|
| **Trigger** | What the user did / what the change introduces |
| **Shared state** | The one source of truth (params, filters, flags) |
| **Must cover** | Surfaces that **must** consume the same state |
| **May ignore** | Surfaces that stay global / out of scope on purpose |
| **Proof** | How the agent verifies coverage (grep / read code) |

---

## FC-01 — Dashboard period filter (`start_date` / `end_date`)

**Trigger:** User selects a date range on Home, or default current-month range is applied.

**Shared state:** `start_date`, `end_date` (and optionally `exclude_business`, `use_my_share`) from the Home period form / query string.

### Must cover (same period)

| Surface | Location | Expected behavior |
|---------|----------|-------------------|
| Period metrics | Home: credits / debits / my expenses cards | Totals for selected range only |
| Monthly expense trend | Home chart | Monthly breakdown of personal spend / debits / credits |
| Category chart | Home chart | Same filtered rows |
| Top merchants chart | Home chart | Same filtered rows |
| Period empty state | Home “no spend data” | Based on same filtered totals |
| Any subsection labeled “this period” / “period” | Home pane | Same dates |
| Unified transactions ("All" / "Classified" tabs) | Transactions workspace | Render all in-period rows with ZERO hardcoded slice limits (no `[:40]` or `[:50]`) |
| Money Flow visualizer | Money Flow section | Render all in-period flow rows with ZERO hardcoded slice limits |

### Must cover if the UI implies period linkage

| Surface | Location | Expected behavior |
|---------|----------|-------------------|
| Attention strip counts (if period-scoped) | Home top | Either uses period **or** is explicitly labeled “all time” |
| Unified transactions when opened from Home period context | Transactions tab | Prefer same period when user arrives via dashboard Apply; if not, document as global |
| Review badge on nav | Sidebar | All-time is OK if badge is “needs review” not “period review” |

### May ignore (global by design)

| Surface | Why |
|---------|-----|
| People / khata balances | Person debt is not a spend-period chart |
| Full import history | Immutable bank log |
| Merchant rules list | Knowledge base |
| Auth / users | Unrelated |

### Proof checklist

- [ ] `period_rows = filter_dashboard_rows(..., start_date, end_date, ...)` feeds metrics + all three charts
- [ ] No second unfiltered `data["transactions"]` path used for those charts
- [ ] Checkbox `exclude_business` applied in the same `filter_dashboard_rows` call as dates
- [ ] Form GET preserves `start_date`/`end_date` when navigating tabs (or state is re-read from query)
- [ ] React `/app` Home (if it shows period charts) uses the same API params or documents divergence
- [ ] No hardcoded list slicing (`[:N]`) inside rendering templates (`templates.py`) for in-period collections

### Incomplete example (FAIL)

- Graphs use `period_rows` but a “Period transactions” table uses full `data["transactions"]`.
- Metrics use period filter but category chart uses all-time.

---

## FC-02 — Exclude business

**Trigger:** “Exclude business” checked (default on).

**Shared state:** `exclude_business` flag with period filter.

### Must cover

- Period metrics, pie, category chart, merchant chart (same `filter_dashboard_rows`)

### May ignore

- Khata ledger, raw bank import, classification type field itself

### Proof

- [ ] Single filter function applies business exclusion; no chart bypasses it

---

## FC-04 — Statement import visible everywhere

**Trigger:** Statement imported (UI PDF or WhatsApp mail).

**Shared state:** last import `{import_id, filename, start, end}` (`import_ingest` / `.last_import_{user}.json`).

### Must cover

| Surface | Expected |
|---------|----------|
| Home period | Default dates = last statement span (unless user picked dates) |
| Home metrics + charts | Same period (`filter_dashboard_rows`) |
| Money flow | Same `tx_source` as that period |
| Transactions / Last statement | Review + auto rows for that `import_id` |
| Recent imports | File listed |
| Export / search | All imported rows in DB |

### May ignore

- Khata nets (no auto-debt)
- React `/app`
- Cloud MCP until `sync-cloud`

### Proof

- [ ] No explicit dates → `start_date`/`end_date` from last import
- [ ] Money flow uses `tx_source` (period), not a second unfiltered list
- [ ] `tx_filter=last_statement` shows both needs_review and auto
- [ ] Classified / Shared / Last statement share one `workspace_rows` list
- [ ] Amount column is bank debit/credit, not my_share

---

## FC-03 — Khata contact identity / rename

**Trigger:** Contact rename, aliases edit, merge.

**Shared state:** `contacts.id` + aliases.

### Must cover

| Surface | Expected |
|---------|----------|
| People list card title | New name |
| Ledger drawer title | New name |
| `find_contact_by_text` for bank narration | Still matches via aliases |
| Settlement / balance API by name | Resolves same contact |
| Rolling / opening contact pickers | Show new name, same id |

### May ignore

- Historical bank `merchant_display` strings (immutable)

### Proof

- [ ] Update writes one contact row; list + drawer + selects read name from contacts
- [ ] Aliases kept for bank matching after rename

---

## FC-04 — Rolling / pass-through

**Trigger:** User posts rolling chain or confirms pass-through.

### Must cover

| Surface | Expected |
|---------|----------|
| Both contacts’ ledger history | Show PT legs |
| Both contacts’ **net** | Unchanged by pure PT |
| Pass-through candidate list | Drops confirmed pairs |

### Proof

- [ ] `is_passthrough=1` on both legs
- [ ] `get_balance` excludes PT

---

## FC-05 — Shared expense partner (`shared_with`)

**Trigger:** User sets partner on a Shared classification.

### Must cover

| Surface | Expected |
|---------|----------|
| Classification row storage | `shared_with` / contact id persisted |
| Shared expenses table (Rules pane) | Shows partner |
| Virtual/partner liability (if product still claims it) | Same partner id |

### May ignore

- Khata net until product explicitly posts ledger share

---

## FC-06 — React `/app` vs classic `/`

**Trigger:** Feature added to one shell that the product presents as “the app.”

### Must cover

- If classic Home shows period charts, React Home either:
  - uses the same APIs/filters, **or**
  - is clearly labeled “preview / partial” and listed under May ignore in this file
- Mobile `/app` v1 Home is **glance only** (totals + review count + top balances). It uses `GET /api/dashboard/summary` (FC-07), not a second filter.

### May ignore

- Classic charts / money-flow / full transaction workspace (desktop)
- People / ledger / graphs screens (registered, `enabled: false` until a later increment)

### Proof

- [ ] No silent dual behavior for the same user story without a note here
- [ ] `/app` nav comes from `frontend/src/features/registry.js`

---

## FC-07 — Mobile Home + Ask + future Graphs share one dashboard summary

**Trigger:** Mobile Home, assistant “food this month”, or a future Graphs screen needs period spend.

**Shared state:** `start_date`, `end_date`, `exclude_business` applied inside `services.dashboard_summary_payload`.

### Must cover

| Surface | Expected |
|---------|----------|
| `GET /api/dashboard/summary` | Payload from `dashboard_summary_payload` |
| MCP `get_dashboard_summary` | Same function |
| Assistant tool `get_dashboard_summary` | Same function |
| Mobile Home glance | Same API (current month, exclude business default) |
| Future Graphs | Same API / same params — do not fork filters |

### May ignore

- Classic Home HTML still calls `filter_dashboard_rows` directly (same filter function, not the JSON payload)
- Khata balances (period-independent)

### Proof

- [ ] MCP + HTTP + assistant do not re-copy filter math
- [ ] `by_category` uses `expenses_by_category` on the same filtered rows

---

## FC-08 — Assistant money writes require confirmation

**Trigger:** Ask proposes add/classify (or any cash mutation).

**Shared state:** single-use `confirm_token` bound to the user.

### Must cover

| Surface | Expected |
|---------|----------|
| `propose_add_manual` | Preview only — no `add_manual_transaction` until confirm |
| `POST /api/assistant/confirm` | Executes once, then token dies |
| Ask confirmation card | Confirm / Cancel; past cards disabled |

### May ignore

- `POST /api/manual` from the Add form (the form **is** the confirmation)

### Proof

- [ ] Unit test: propose does not insert; confirm inserts once; second confirm fails

---

## FC-09 — Live vs snapshot share the same mobile APIs

**Trigger:** Phone uses `/app` on the PC (live) or on the Worker (PC off).

**Shared state:** `GET /api/dashboard/summary` and `GET /api/settlement/summary` shapes. Snapshot `dashboard` comes from `dashboard_summary_payload` at sync time.

### Must cover

| Surface | Expected |
|---------|----------|
| Live Python `/api/dashboard/summary` | `dashboard_summary_payload` |
| `sync-cloud` snapshot `dashboard` | Same function |
| Worker `GET /api/dashboard/summary` | Glance only — do not parse `transactions` |
| Mobile Home | Same fields; shows “as of” when `mode=snapshot` |
| Worker Ask | Glance balances + `by_category` |
| Live Ask | Live SQLite tools |

### May ignore

- Gemini / Add / import when `mode=snapshot` (writes stay on PC)
- Worker period query params (glance is last synced month)

### Proof

- [ ] Worker REST does not `JSON.parse` the full snapshot key for Home
- [ ] Add is disabled in snapshot mode

---

## FC-10 — Ask reads go through `ask_books`

**Trigger:** Any Ask question about spends, merchants, dates, amounts, or khata.

**Shared state:** `expense_tracker.assistant.query.ask_books`.

### Must cover

| Surface | Expected |
|---------|----------|
| Local router | `parse_question` → `ask_books` |
| Gemini tool `ask_books` | Same function |
| Worker snapshot Ask | Glance `books` (90-day slim), same kinds of answers |

### May ignore

- MCP stdio tools (may keep older names)
- Classic `/` search

### Proof

- [ ] Empty Gemini after a tool uses the tool `answer`
- [ ] No full transaction dump in Gemini payloads

---

## Adding a new feature contract

When shipping a multi-surface feature, append **FC-NN** with:

1. Trigger  
2. Shared state  
3. Must cover table  
4. May ignore table  
5. Proof checklist  

The architecture agent treats missing “Must cover” updates as incomplete if the feature is already user-visible.
