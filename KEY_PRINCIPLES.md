# Key Principles — AI Expense Tracker

## 1. Minimal Design & Taste
* **Minimal UI**: Keep all interfaces clean, lightweight, and clutter-free. Prefer less visual chrome and fewer decorative elements.
* **No Congestion**: One primary action per surface. Hide secondary or specialized actions until explicitly needed by the user.
* **Data-Smart, UI-Dumb**: Maintain a single owner for shared state; views and UI components consume state directly without duplicating logic or inventing custom filters.
* **Information Density with Purpose**: Focus on clean visual hierarchy (e.g. hero figures, visual distribution meters, concise cards) rather than overloaded dashboards.

## 2. Invariants & Correctness
* **No Silent Capping**: When rendering lists filtered by date or category, never apply hardcoded array slices inside template loops without explicit pagination.
* **Single Source of Truth**: Classifier rules and payee merchant display names are standardized centrally in expense_tracker/classifier.py.
* **Confirm Before Write (FC-08)**: Assistant-driven write operations (add manual, categorize, edit classification) must always generate a single-use confirmation token and require explicit user confirmation.
* **User Review Immutability**: Any transaction with `status = 'reviewed'` or explicit split ratio is immutable to automated batch re-classifications or PDF re-imports. All batch processes must respect `WHERE status != 'reviewed'`.

## 3. Coherence & Architecture Discipline
* **Shared Payloads (FC-07)**: Mobile, Web, Assistant, and Cloud MCP share identical spend and summary calculations via expense_tracker/services.py (dashboard_summary_payload).
* **Period Consistency (FC-01)**: All dashboard views and metrics adhere to identical period bounds and filter contracts across all surfaces.
* **Zone Isolation**: Stay inside the primary feature zone during changes; never modify unrelated features while repairing.
