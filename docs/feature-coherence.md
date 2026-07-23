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
| Credit/debit pie | Home chart | Same filtered rows |
| Category chart | Home chart | Same filtered rows |
| Top merchants chart | Home chart | Same filtered rows |
| Period empty state | Home “no spend data” | Based on same filtered totals |
| Any subsection labeled “this period” / “period” | Home pane | Same dates |

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

### Proof

- [ ] No silent dual behavior for the same user story without a note here

---

## Adding a new feature contract

When shipping a multi-surface feature, append **FC-NN** with:

1. Trigger  
2. Shared state  
3. Must cover table  
4. May ignore table  
5. Proof checklist  

The architecture agent treats missing “Must cover” updates as incomplete if the feature is already user-visible.
