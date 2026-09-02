# Baseline Architecture & FC-01 Handoff Report

## 1. Observation

### 1.1 Architecture Check Baseline Execution
**Command executed:**
```powershell
.\venv\Scripts\python.exe .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones P,E --feature FC-01
```

**Verbatim Output & Result:**
- **Verdict:** `VERDICT: FAIL` (Exit Code 1)
- **Detected Changed Files in Working Copy:**
  - `[C] Classification (1 file(s))`: `expense_tracker/classifier.py`
  - `[D] Khata/People+UI (2 file(s))`: `expense_tracker/contacts.py`, `expense_tracker/static/app.js`
  - `[E] Dashboard spend (1 file(s))`: `expense_tracker/services.py`
  - `[H] Tests (3 file(s))`: `tests/test_contacts_ledger.py`, `tests/test_core.py`, `tests/test_khata_stress.py`
  - `[P] HTTP edge (shared) (3 file(s))`: `expense_tracker/db.py`, `expense_tracker/templates.py`, `expense_tracker/web.py`
- **Isolation Findings:**
  - `BLOCK: ISOLATION: multiple feature zones touched: C, D, E. Split the change or get explicit cross-zone approval.`
  - `BLOCK: ISOLATION: zones outside declared intent ['E', 'P']: ['C', 'D']`
  - `WARN:  ISOLATION: shared edge/persistence P with feature zones C, D, E. Keep handlers thin.`
  - `WARN:  CONTRACT: Balance formula touch — confirm zone D only`
  - `WARN:  CONTRACT: Possible Anand/Ananthu identity bleed — verify alias lists`
  - `WARN:  CONTRACT: Schema/data destructive change`
  - `WARN:  FC-01: Double-check no chart still binds unfiltered data['transactions'] for period UI`

- **Completeness Probe Matrix for FC-01:**
  - `[COVERED] FC-01: period_rows built with start/end + exclude_business`
  - `[COVERED] FC-01: metrics use period_totals from period_rows`
  - `[COVERED] FC-01: category chart uses period_rows / period_categories`
  - `[COVERED] FC-01: merchant chart uses period_rows / period_merchants`
  - `[COVERED] FC-01: credit/debit pie uses period_totals`

### 1.2 Inspection of Key Code Files & Contracts
- **`AGENTS.md` & `docs/architecture-map.md` Zone Mapping:**
  - **Zone P (Shared HTTP Edge & Persistence):** `expense_tracker/web.py`, `expense_tracker/templates.py`, `expense_tracker/db.py`
  - **Zone E (Dashboard Spend Analytics):** `expense_tracker/services.py`
  - **Zone C (Classification):** `expense_tracker/classifier.py`
  - **Zone D (Khata/People/Ledger):** `expense_tracker/contacts.py`, `expense_tracker/static/app.js`
- **`docs/feature-coherence.md` (FC-01 Contract):**
  - **Shared state:** `start_date`, `end_date`, `exclude_business`, `use_my_share` from Home period form or query string.
  - **Must cover surfaces (all driven by resolved period):** Period metrics, Credit/Debit pie chart, Category chart, Top merchants chart, Period empty state, and period-scoped tables/sub-tabs.
  - **Attention strip counts:** Allowed to remain all-time (or explicitly labeled all-time).
- **`expense_tracker/templates.py` (lines 1640–1780):**
  - `render_dashboard(...)` calculates `min_date` and `max_date` via `date_bounds(data["transactions"])`.
  - Default period when dates are missing is current calendar month (`start_date = month_start`, `end_date = month_end`).
  - Helper `_in_period(r)` filters rows based on `start_date` and `end_date`.
  - `tx_source` (lines 1733–1737) and `shared_source` (lines 1738–1742) apply `_in_period(r)` only if `period_explicit` is True, but on default month period `period_explicit` is False.

---

## 2. Logic Chain

1. **Why `architecture_check.py` Returned FAIL:**
   - The script inspects all modified and untracked files in the git workspace (`git diff` and `git ls-files`).
   - Pre-existing uncommitted modifications exist in files belonging to Zone C (`classifier.py`) and Zone D (`contacts.py`, `app.js`).
   - When `--intent-zones P,E` was specified, `architecture_check.py` detected modified files in zones C and D, which violates intent zone isolation (`zones outside declared intent ['E', 'P']: ['C', 'D']`).

2. **FC-01 Feature Completeness Status:**
   - The FC-01 contract requires 5 core surfaces (period_rows, period_totals, category chart, merchant chart, credit/debit pie) to consume the filtered date range.
   - All 5 completeness surfaces passed as `COVERED` during the probe.

3. **Architectural Guidelines for FC-01 Defect Fix:**
   - **Zone Boundaries:** Any bug fixes for date filtering must remain strictly inside **Zone E** (`expense_tracker/services.py`) and **Zone P** (`expense_tracker/templates.py`, `expense_tracker/web.py`, `expense_tracker/db.py`).
   - **No Cross-Zone Leakage:** Do NOT touch `contacts.py` (Zone D) or `classifier.py` (Zone C).
   - **Thin Handlers in Zone P:** Route handlers in `web.py` and template presentation logic in `templates.py` must stay thin, delegating date filtering logic to `services.py` (`filter_dashboard_rows` / `_in_period`).
   - **Consistency Across UI Surfaces:** Selected `start_date` and `end_date` must filter `transactions`, `shared`, and `pending` queues consistently without dropping valid in-period transactions. Attention strip counts on the Home tab must remain all-time as per FC-01 rules.

---

## 3. Caveats

- **Uncommitted Workspace Files:** The repository currently has uncommitted changes in `classifier.py`, `contacts.py`, `app.js`, and test files from previous work. To obtain a clean `VERDICT: PASS` during final M3 verification, those non-FC-01 files must not be touched or included in the FC-01 change set.
- **Read-Only Scope:** This exploration is strictly read-only; no code modifications were made to the application codebase.

---

## 4. Conclusion

- **Baseline Output:** The baseline architecture check command completed with exit code 1 (`VERDICT: FAIL`) due to pre-existing uncommitted files in zones C and D outside the declared intent zones (`P,E`).
- **Feature Contract FC-01:** FC-01 completeness probe passed 100% (5/5 surfaces `COVERED`).
- **Guidelines for Implementation:** The date range filtering defect must be addressed within Zone P (`web.py`, `templates.py`, `db.py`) and Zone E (`services.py`) only, keeping handlers thin and ensuring date range consistency across all dashboard charts and transaction sub-tabs while leaving attention strip counts all-time.

---

## 5. Verification Method

To verify the baseline output and architectural status:
1. Run the architecture check script:
   ```powershell
   .\venv\Scripts\python.exe .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones P,E --feature FC-01
   ```
2. Verify FC-01 coverage matrix shows 5 `COVERED` surfaces.
3. Inspect `docs/feature-coherence.md` (FC-01 section) and `AGENTS.md` to confirm zone assignment rules for Zone P and Zone E.
