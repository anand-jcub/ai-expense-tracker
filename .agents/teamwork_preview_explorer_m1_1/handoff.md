# Handoff Report — Baseline Analysis & Modular Refactoring Design for `expense_tracker/contacts.py`

## 1. Observation

A complete, line-by-line audit of `expense_tracker/contacts.py` (626 lines) and its callers (`web.py`, `templates.py`, `db.py`, `services.py`, `test_contacts_ledger.py`, `test_settlement.py`) was performed.

### Key Inventory of `contacts.py` Functions & Callers

| Function Name | Signature & Return Type | DB Interaction | Pure Domain Calculation | Callers / Dependencies |
|---|---|---|---|---|
| `utc_now` | `() -> str` | None | UTC timestamp formatting ISO 8601 | Internal, `db.py` |
| `split_aliases` | `(raw_aliases: str \| list[str]) -> list[str]` | None | String split, strip, lowercase, deduplicate | Internal, `db.py` |
| `_d` | `(value) -> Decimal` | None | Safe Decimal parsing default to 0 | Internal |
| `_table_cols` | `(conn: sqlite3.Connection, table: str) -> set[str]` | `PRAGMA table_info` | Metadata set creation | Internal |
| `_direction_of` | `(row) -> str` | Reads row dict/keys | Safe direction key extraction | Internal |
| `create_contact` | `(conn, name, aliases="", notes=None) -> int` | `INSERT INTO contacts` | Name clean, `split_aliases`, JSON dump | `web.py:914`, `tests` |
| `update_contact` | `(conn, contact_id, name, aliases="", notes=None) -> None` | `UPDATE contacts` | Name clean, `split_aliases`, JSON dump | `web.py:938` |
| `get_all_contacts` | `(conn) -> list[dict[str, Any]]` | `SELECT * FROM contacts WHERE merged_into_id IS NULL ...` | JSON parse aliases | `web.py:840, 888`, `db.py:869`, `tests` |
| `_token_in_text` | `(token: str, text: str) -> bool` | None | Word boundary regex check | Internal |
| `find_contact_by_text` | `(conn, text: str) -> dict \| None` | Calls `get_all_contacts` | Multi-token scoring algorithm & alias ranking | `db.py:313, 717`, `web.py:862`, internal |
| `add_ledger_entry` | `(conn, contact_id, direction, amount, purpose="other", transaction_id=None, is_passthrough=False, passthrough_pair_id=None, is_opening_balance=False, notes=None, entry_date=None, created_by="user") -> int` | Dynamic `INSERT INTO ledger_entries` with column check | Decimal validation, purpose defaulting, source determination | `web.py:963, 1013`, `tests`, internal |
| `add_rolling_entry` | `(conn, from_contact_id, to_contact_id, amount, entry_date=None, notes=None, created_by="user") -> dict` | `SELECT contacts`, calls `add_ledger_entry` (x2), calls `get_balance` (x2) | Contact ID equality check, default note templates | `web.py:1093`, `test_settlement.py` |
| `record_opening_balance` | `(conn, contact_id, amount, *, they_owe_you=True, entry_date=None, notes=None, created_by="user") -> dict` | `SELECT contacts`, calls `add_ledger_entry`, `get_balance` | Direction mapping based on `they_owe_you` | `web.py:1131`, `test_settlement.py` |
| `record_settlement` | `(conn, contact_id, amount=None, *, notes=None, entry_date=None, created_by="user") -> dict` | Calls `get_balance`, `add_ledger_entry` | Direction determination (`they_sent` vs `you_sent`), cap settlement amount at `abs(net)` | `web.py:1052`, `test_settlement.py` |
| `void_ledger_entry` | `(conn, entry_id, reason="voided by user") -> None` | Column check; `UPDATE` or `DELETE FROM ledger_entries` | Reason formatting | `web.py:1163`, `test_settlement.py` |
| `get_balance` | `(conn, contact_id) -> dict[str, Any]` | `SELECT direction, entry_type, amount, is_passthrough FROM ledger_entries ...` | Net calculation `you_sent - they_sent`, status mapping (`owes_you`/`you_owe`/`settled`) | `web.py:840, 862`, `db.py:869`, `test_settlement.py`, internal |
| `get_ledger` | `(conn, contact_id) -> dict[str, Any]` | `SELECT * FROM contacts`, `SELECT l.*, t.* FROM ledger_entries LEFT JOIN transactions` | Running balance math excluding pass-through, line item dictionary assembly | `web.py:815`, `test_contacts_ledger.py`, `test_settlement.py` |
| `get_all_balances` | `(conn) -> list[dict[str, Any]]` | Calls `get_all_contacts`, `get_balance` | Summary list aggregation | `web.py:303, 888`, `services.py:355` |
| `detect_passthrough_candidates` | `(conn) -> list[dict[str, Any]]` | Complex SQL JOIN query on `transactions` within 2 days excluding existing passthrough entries | Merchant matching via `find_contact_by_text` & tuple construction | `db.py:869`, `test_contacts_ledger.py` |
| `calculate_contact_balance` | Alias for `get_balance` | None | None | `test_contacts_ledger.py` |
| `get_contact_ledger` | Alias for `get_ledger` | None | None | `test_contacts_ledger.py` |

---

## 2. Logic Chain

### Domain Area Categorization

The functions in `contacts.py` strictly map into 3 explicit domain areas plus shared utilities:

#### Area 1: Contact Management (CRUD, FC-03 Aliases & Renaming)
- `create_contact`: Contact creation with JSON serialized aliases.
- `update_contact`: Contact details and alias updating.
- `get_all_contacts`: Soft-delete filtering (`merged_into_id IS NULL`) and contact retrieval.
- `split_aliases`: Parsing string or list of aliases into clean deduplicated lists.
- `_token_in_text`: Whole-word token regex matcher.
- `find_contact_by_text`: Contact search with token scoring and alias lookup rules.

#### Area 2: Ledger Calculations (Running Balances, Settlements, Itemized Lines)
- `add_ledger_entry`: Core write primitive for ledger entries with dynamic schema support.
- `record_opening_balance`: Opening balance setup and direction mapping.
- `record_settlement`: Compensating settlement entry calculation and insertion.
- `void_ledger_entry`: Soft-void (or hard delete fallback) of ledger lines.
- `get_balance` / `calculate_contact_balance`: Core net balance calculator (`you_sent - they_sent` excluding pass-through and voided entries).
- `get_ledger` / `get_contact_ledger`: Full ledger history with running balance computation per non-passthrough line.
- `get_all_balances`: Aggregated balance cards for all active contacts.

#### Area 3: Pass-through Tracking (Rolling Entries, Cross-references)
- `add_rolling_entry`: Two-legged pass-through ledger entry creator ($A \to \text{You} \to B$) linking `passthrough_pair_id`.
- `detect_passthrough_candidates`: Transaction pattern matcher identifying candidate pass-through pairs within a 2-day window.

#### Shared Utilities
- `utc_now`: Standard ISO timestamp generator.
- `_d`: Defensive Decimal converter.
- `_table_cols`: DB schema inspection helper.
- `_direction_of`: Schema fallback direction key parser.

---

### Data Access vs. Pure Domain Logic Decoupling Analysis

Currently, database query execution (`conn.execute`) and pure domain calculation (Decimal arithmetic, string parsing, token scoring, status mapping, running balance accumulation) are tightly coupled inside single function bodies.

To decouple them cleanly:

1. **Data Access Layer (DAL)**: Focuses strictly on SQL parameter binding, schema checks, dynamic column construction, and returning raw `sqlite3.Row` or list of dicts.
   - `db_create_contact(conn, name, aliases_json, notes, created_at) -> int`
   - `db_update_contact(conn, contact_id, name, aliases_json, notes) -> None`
   - `db_fetch_contacts(conn) -> list[dict]`
   - `db_fetch_contact_by_id(conn, contact_id) -> dict | None`
   - `db_insert_ledger_entry(conn, fields, values) -> int`
   - `db_fetch_raw_balance_rows(conn, contact_id) -> list[dict]`
   - `db_fetch_raw_ledger_entries_with_tx(conn, contact_id) -> list[dict]`
   - `db_void_ledger_entry(conn, entry_id, reason, now) -> None`
   - `db_fetch_passthrough_transaction_pairs(conn) -> list[dict]`

2. **Pure Domain Logic Layer**: Operates purely on python datatypes (dicts, lists, Decimals, strings) without touching `sqlite3.Connection`:
   - `domain_split_aliases(raw_aliases: str | list[str]) -> list[str]`
   - `domain_token_in_text(token: str, text: str) -> bool`
   - `domain_match_contact_by_text(contacts: list[dict], text: str) -> dict | None`
   - `domain_calculate_balance(contact_id: int, rows: list[dict]) -> dict[str, Any]`
   - `domain_compute_running_ledger(contact: dict, rows: list[dict], balance: dict) -> dict[str, Any]`
   - `domain_calculate_settlement(net_balance: float | Decimal, amount: float | Decimal | None) -> tuple[Decimal, str]`

3. **Public Facade Layer (`expense_tracker/contacts.py`)**:
   - Retains 100% exact signatures of all public functions (`create_contact`, `update_contact`, `get_all_contacts`, `get_balance`, `get_ledger`, `add_ledger_entry`, `add_rolling_entry`, `record_settlement`, `record_opening_balance`, `void_ledger_entry`, `detect_passthrough_candidates`, `get_all_balances`).
   - Delegates data fetching to DAL and calculations to Domain modules.
   - Ensures zero breaking changes for `web.py`, `templates.py`, `services.py`, `db.py`, and test suites.

---

## 3. Modular Architecture Proposal

We propose organizing the refactored code under internal submodules inside `expense_tracker/contacts_domain/` (or structured internal modules) while `expense_tracker/contacts.py` remains the backward-compatible entry point:

```
expense_tracker/
├── contacts.py                   # Public facade (100% backward compatible exports)
└── contacts_domain/
    ├── __init__.py               # Re-exports domain components
    ├── dal.py                    # Low-level SQLite queries & PRAGMA column checks
    ├── contact_management.py     # Contact CRUD, alias processing, token scoring
    ├── ledger_calculations.py    # Net balance, running balances, settlements, opening balances
    └── passthrough_tracking.py   # Rolling entries & candidate transaction matching
```

---

## 4. Caveats

- **Read-Only Scope**: This analysis and architectural design is read-only for M1. No modifications were made to `expense_tracker/contacts.py` during this milestone.
- **Dynamic Schema Inspection**: Existing code relies on dynamic column checks (`_table_cols`) for backward compatibility with unmigrated DB schemas (`direction` vs `entry_type`, `voided_at`, `merged_into_id`). The refactored DAL must preserve this dynamic schema tolerance.

---

## 5. Conclusion

`expense_tracker/contacts.py` can be refactored cleanly into a modular architecture separating Data Access (DAL) from Pure Domain Logic across the 3 target areas (Contact Management, Ledger Calculations, Pass-through Tracking). The public facade in `contacts.py` will guarantee 100% backward compatibility for all existing callers in `web.py` and `templates.py`.

---

## 6. Verification Method

- **Syntax & Compilation**: `python -m py_compile expense_tracker/contacts.py`
- **Unit & Integration Tests**: `pytest tests/test_contacts_ledger.py tests/test_settlement.py`
- **Architecture Guardian Audit**: `python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03`
