## 2026-07-26T14:46:25Z
<USER_REQUEST>
You are Worker 2 for Milestone 3 (UI Render & Client Interaction Decoupling).
Your working directory is: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_worker_m3\

Context:
Read Explorer 2 handoff report at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_2\handoff.md, PROJECT.md, and AGENTS.md.

Task:
Refactor expense_tracker/templates.py and expense_tracker/static/app.js to decouple UI rendering from client JavaScript for Khata / People / Ledger views.

Requirements:
1. Componentize `render_contacts_section` in expense_tracker/templates.py into focused sub-component render functions:
   - `render_contact_card(item: dict, quiet: bool = False) -> str`
   - `render_people_toolbar() -> str`
   - `render_passthrough_suggestions(candidates: list[dict], contacts: list[dict]) -> str`
   - `render_people_tools(contacts: list[dict], today: str) -> str`
   - `render_add_contact_modal() -> str`
   - `render_edit_contact_modal() -> str`
   - `render_add_ledger_modal() -> str`
   - `render_ledger_drawer() -> str`
2. Decouple UI rendering from client JS:
   - Replace inline `onclick` string calls containing escaped JSON literals with declarative HTML5 `data-*` attributes (`data-action="open-drawer"`, `data-action="edit-contact"`, `data-action="add-ledger"`, `data-action="close-modal"`, `data-contact-id`, `data-contact-name`, `data-aliases`, `data-notes`).
3. Refactor client interaction in expense_tracker/static/app.js:
   - Implement event delegation using a delegated click handler (`document.addEventListener('click', ...)` or container handler) that inspects `[data-action]` elements and dispatches to handler logic.
   - Retain thin backward-compatibility functions on `window` (`window.openLedgerDrawer`, `window.openEditContactModal`, `window.openAddLedgerModal`, `window.closePeopleModal`, `window.filterPeopleList`, `window.filterPeopleStatus`) to prevent breakage for existing test scripts.
4. Maintain 100% backward compatibility:
   - Preserve all HTML element IDs (`#modal-add-contact`, `#modal-edit-contact`, `#modal-add-ledger`, `#ledger-drawer`, `#contact-search-input`, `#contacts-grid`), form input names, POST form actions, API endpoint URLs, and visual presentation.
5. Verification:
   - `python -m py_compile expense_tracker/templates.py`
   - `python -m pytest tests/test_contacts_ledger.py tests/test_core.py`
   - `python expense_tracker/e2e_test.py`
   - `python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Deliverables:
- Initialize progress.md in your working directory.
- Document all implementation details, component structures, data attributes, and test results in handoff.md.
- Send a completion message to orchestrator (ID: 0a0f5ba9-c2f1-4654-9a4e-33c9078ba339) with the path to handoff.md.
</USER_REQUEST>
