## 2026-07-26T20:13:50Z
<USER_REQUEST>
You are Worker 2 (teamwork_preview_worker) for Milestone 3 of the Khata / People / Ledger refactoring project (Zone D, Feature FC-03).

Working directory: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_worker_m3_1

Mission:
Decouple UI render templates and client interaction handlers in `expense_tracker/templates.py` and `expense_tracker/static/app.js` according to the design plan in `c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_2\handoff.md`.

Detailed Tasks:
1. In `expense_tracker/templates.py`:
   - Modularize `render_contacts_section` into clear, single-responsibility sub-component helper functions (e.g. `_render_contact_card`, `_render_people_toolbar`, `_render_passthrough_suggestions`, `_render_people_tools`, `_render_add_contact_modal`, `_render_edit_contact_modal`, `_render_add_ledger_modal`, `_render_ledger_drawer`).
   - Add declarative `data-*` attributes (`data-action`, `data-contact-id`, `data-contact-name`, `data-aliases`, `data-notes`, `data-status`) to rendered HTML markup to decouple HTML buttons from inline `onclick` scripts.
2. In `expense_tracker/static/app.js`:
   - Implement clean client-side event delegation on `document` catching click events on `[data-action]` elements.
   - Maintain 100% backward-compatible `window` function wrappers (`window.openLedgerDrawer`, `window.openEditContactModal`, `window.openAddLedgerModal`, `window.closePeopleModal`, `window.closeLedgerDrawer`, `window.filterPeopleList`, `window.filterPeopleStatus`) so external or legacy callers continue to work seamlessly.
   - Retain all existing form action URLs (`/contacts/create`, `/contacts/edit`, `/ledger/add`, `/ledger/settle`, `/ledger/rolling`, `/ledger/opening`, `/ledger/passthrough/confirm`), form input names, modal IDs, and CSS class names.
3. Verification Requirements:
   - Run python compilation check: `.\venv\Scripts\python.exe -m py_compile expense_tracker/templates.py`
   - Run pytest suite: `.\venv\Scripts\python.exe -m pytest tests/test_contacts_ledger.py tests/test_core.py`
   - Run E2E test suite: `.\venv\Scripts\python.exe expense_tracker/e2e_test.py`
   - Run Architecture check: `.\venv\Scripts\python.exe .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03`
4. Document all changes and verification outputs in `.agents/teamwork_preview_worker_m3_1/handoff.md` and update `progress.md`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
</USER_REQUEST>
