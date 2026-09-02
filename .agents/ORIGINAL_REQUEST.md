# Original User Request

## 2026-07-26T13:42:11Z

Refactor and optimize the Khata / People / Ledger system in the AI Expense Tracker codebase for modular architecture, code cleanliness, and strict maintainability.

Working directory: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
Integrity mode: development

## Requirements

### R1. Modularize Khata & Ledger Domain Logic
Refactor expense_tracker/contacts.py into clean, single-responsibility domain functions with clear type hints, decoupled data-access layers, and explicit boundaries between contact management, ledger calculation, and pass-through tracking.

### R2. Decouple UI Render & Interaction Handlers
Clean up and modularize Khata UI template rendering in expense_tracker/templates.py and client-side drawer handlers in expense_tracker/static/app.js, ensuring crisp separation between data presentation, event handling, and server routes.

### R3. Zero Regression & Test Verification
Maintain 100% functional compatibility with existing ledger APIs, database schemas, and pass-through mechanics. Ensure all existing automated tests pass without modification.

## Acceptance Criteria

### Verification & Quality
- [ ] Automated Test Suite Pass: Running pytest passes all test modules (tests/test_contacts_ledger.py, tests/test_core.py).
- [ ] E2E Smoke Verification: Running python expense_tracker/e2e_test.py completes cleanly with 0 errors.
- [ ] Syntax & Compilation: All modified Python files pass python -m py_compile without warnings or syntax errors.
- [ ] Architecture Check: Running python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03 reports clean compliance without cross-zone leakage.

## 2026-08-10T06:26:01Z

Diagnose and fix the date filtering defect in the AI Expense Tracker where transactions are going missing from the Money Flow and Transactions tabs when a time period is selected.

Working directory: C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
Integrity mode: development

## Requirements

### R1. Investigate Date Filtering Defect
Trace the transaction flow from the database extraction (`db.py`), through the filtering utilities (`services.py`), to the UI rendering (`templates.py`). Identify exactly why data points are being dropped or hidden when a date range is applied.

### R2. Implement Correct Period Filtering
Fix the root cause so that the selected `start_date` and `end_date` correctly limit the `transactions`, `shared`, and `pending` queues for the sub-tabs, without inadvertently discarding valid in-period data.

### R3. Maintain Architectural Compliance
Ensure the fix complies with the `FC-01` contract (Dashboard period filter) in `docs/feature-coherence.md`. The Home tab's attention strip counts MUST remain all-time, while the charts and UI tabs should accurately reflect the selected period.

## Acceptance Criteria

### Verification
- [ ] Write a short Python verification script that fetches dashboard data with a specific date range and asserts that the count of transactions passed to the rendering engine exactly matches a direct SQL `COUNT(*)` query for that same date range.
- [ ] All automated tests (`pytest`) pass successfully.
- [ ] The architecture agent check (`python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones P,E --feature FC-01`) passes without reporting isolation leaks.

