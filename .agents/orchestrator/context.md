# Context Summary

## Project Overview
AI Expense Tracker repository (`c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai`).
Defect report: When selecting a date period filter, transactions disappear from Money Flow and Transactions tabs.

## Key Files & Modules
- `expense_tracker/db.py`: Database queries for fetching transactions, stats, and filtered data.
- `expense_tracker/services.py`: Business logic, date filtering utilities, period processing.
- `expense_tracker/templates.py`: HTML template rendering for Money Flow, Transactions, Dashboard, and UI tabs.
- `docs/feature-coherence.md`: FC-01 contract specification for Dashboard period filtering consistency.
- `AGENTS.md`: Architectural zone rules (P = Shared edge, E = Dashboard spend analytics).

## Key Acceptance Criteria
1. Verification script matching rendered transaction count against SQL `COUNT(*)`.
2. Pytest suite passes 100%.
3. Architecture check passes (`--intent-zones P,E --feature FC-01`).
