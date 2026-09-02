# Handoff Report — UI Rendering & Client Interaction Decoupling Analysis (Milestone 1)

**Agent**: Explorer 2 (`teamwork_preview_explorer`)  
**Milestone**: Milestone 1 (Khata / People / Ledger Refactoring — Zone D, FC-03)  
**Target Files Analyzed**:
- `expense_tracker/templates.py` (specifically contact & ledger rendering logic)
- `expense_tracker/static/app.js` (drawer and contact interaction handlers)
- `expense_tracker/web.py` (associated API routes and POST endpoints)
**Date**: 2026-07-26  
**Status**: Read-Only Analysis & Refactoring Plan Complete  

---

## 1. Observation

### 1.1 Template Rendering Inventory (`expense_tracker/templates.py`)

`render_contacts_section` in `expense_tracker/templates.py` (lines 281–674, 394 lines) is a monolithic template function responsible for rendering the entire "People" (Khata) tab.

The table below catalogs every UI element, line range, and rendering responsibility inside `templates.py`:

| Line Range | Function / Section Name | Rendered UI Element | Inputs & Dependencies | Embedded Interactions / Handlers |
|---|---|---|---|---|
| 268–278 | `_contact_option_tags` | `<option>` tags for contact `<select>` dropdowns | `contacts: list[dict]`, `selected_id` | Pure option string generator |
| 281–316 | `render_contacts_section` (Header & Data Prep) | Tab header, summary totals (`total_owes_you`, `total_you_owe`), contact list partitioning (active vs. quiet) | `contacts`, `passthrough_candidates` | Calculates financial totals in Python |
| 318–369 | `_row` (Inner Helper) | Single contact card (`<div class="people-row contact-card">`) | `item: dict`, `quiet: bool` | Inline JS: `onclick='openLedgerDrawer({cid}, {js_name})'`, `onclick='openEditContactModal({cid}, {js_name}, {js_aliases}, {js_notes})'`, `onclick='openAddLedgerModal({cid}, {js_name})'` |
| 379–428 | Pass-through Block (`pt_html`) | Collapsible section for rolling money candidates | `passthrough_candidates: list[dict]` | Inline Form: `<form method="post" action="/ledger/passthrough/confirm">` |
| 430–485 | Tools Section (`tools_html`) | Forms for manual rolling money & opening balance | `contacts: list[dict]`, `today: str` | Inline Forms: `<form method="post" action="/ledger/rolling">`, `<form method="post" action="/ledger/opening">` with `onsubmit="return confirm(...)"` |
| 496–520 | `add_contact_modal` | Modal dialog for creating a new person | None | Inline Form: `<form method="post" action="/contacts/create">`, `onclick="closePeopleModal('modal-add-contact')"` |
| 522–550 | `edit_contact_modal` | Modal dialog for editing contact name/aliases/notes | None | Inline Form: `<form method="post" action="/contacts/edit">`, `onclick="closePeopleModal('modal-edit-contact')"` |
| 552–603 | `add_entry_modal` | Modal dialog for logging a ledger entry (+ Money) | None | Inline Form: `<form method="post" action="/ledger/add">`, `onclick="closePeopleModal('modal-add-ledger')"` |
| 605–628 | `drawer_html` | Slide-out drawer container for ledger history | None | Inline Form: `<form method="post" action="/ledger/settle">`, `onclick="closeLedgerDrawer()"`, `onclick="return confirmSettle()"` |
| 630–674 | Layout Outer HTML | Search toolbar, status filter buttons (`active`, `owes_you`, `you_owe`, `all`), grid wrappers | `active_html`, `quiet_block`, `tools_html`, modals | Inline JS: `oninput="filterPeopleList()"`, `onclick="filterPeopleStatus('active', this)"`, `onclick="openPeopleModal('modal-add-contact')"` |

---

### 1.2 Client-Side Interaction Inventory (`expense_tracker/static/app.js`)

`expense_tracker/static/app.js` (lines 662–926, 265 lines) contains client-side logic for the People drawer, modals, search, and filter mechanics.

The table below lists all client interaction handlers and global variables in `app.js`:

| Line Range | Target / Function | Type | Responsibility | Connected DOM Elements / API Endpoint |
|---|---|---|---|---|
| 662–665 | Global State Variables | `window` Properties | Holds global UI state: `_drawerContactId`, `_drawerContactName`, `_drawerSettleNet`, `_peopleStatusFilter` | In-memory global state |
| 667–675 | `openPeopleModal` / `closePeopleModal` | Window Functions | Shows / hides modal overlays by clearing or setting `hidden` attribute | `#modal-add-contact`, `#modal-edit-contact`, `#modal-add-ledger` |
| 677–685 | `openAddLedgerModal` | Window Function | Populates modal inputs (`#ledger-modal-contact-id`, `#ledger-modal-contact-name`, `#ledger-modal-date`) and opens modal | `#modal-add-ledger` |
| 687–700 | `openEditContactModal` | Window Function | Populates edit inputs (`#edit-contact-id`, `#edit-contact-name`, `#edit-contact-aliases`, `#edit-contact-notes`) and opens modal | `#modal-edit-contact` |
| 702–707 | `closeLedgerDrawer` | Window Function | Hides `#ledger-drawer` and `#ledger-drawer-backdrop` | `#ledger-drawer`, `#ledger-drawer-backdrop` |
| 709–736 | `peopleQueryMatch` / `applyPeopleFilters` | Internal Functions | Filters `.people-row.contact-card` elements by `data-name`, `data-aliases`, and `data-status` | `#contact-search-input`, `#contacts-grid`, `.people-row` |
| 738–754 | `filterPeopleList` / `filterPeopleStatus` | Window Functions | Triggers `applyPeopleFilters()` when user types in search or clicks status filter pills | Search input, filter buttons |
| 756–770 | `confirmSettle` | Window Function | Validates settlement amount against `_drawerSettleNet` before form POST | `#drawer-settle-amount` |
| 779–880 | `openLedgerDrawer` | Window Function | Opens drawer, sets title, executes AJAX `fetch('/api/contacts/ledger?contact_id=...')`, builds history HTML rows dynamically | `/api/contacts/ledger`, `#drawer-entries-list`, `#drawer-balance-summary` |
| 883–887 | Backdrop Click Event | Event Listener | Listens for clicks directly on `.people-modal` backdrop to close modal | `.people-modal` |
| 889–926 | `closePeopleOverlays` / Esc Handler | Window Function & Listener | Intercepts `Escape` key to hierarchically close top-most active modal/drawer | `window.addEventListener('keydown', ...)` |

---

### 1.3 API Routes & Form Endpoints (`expense_tracker/web.py`)

The table below lists all backend web routes interacting with the Khata UI:

| HTTP Method | Route Path | `web.py` Handler Line | Python Handler Function | Backend Domain Function Called | Response / Action |
|---|---|---|---|---|---|
| GET | `/api/contacts/ledger` | 281, 806 | `handle_api_contact_ledger` | `contacts.get_ledger(conn, contact_id)` | JSON response `{contact, balance, entries}` |
| GET | `/api/contacts/balances` | 888 | Inline Handler | `contacts.get_all_balances(conn)` | JSON response `{contacts}` |
| POST | `/contacts/create` | 395, 914 | Inline Handler | `contacts.create_contact(conn, name, aliases, notes)` | Redirect `tab="contacts"` |
| POST | `/contacts/edit` | 397, 938 | Inline Handler | `contacts.update_contact(conn, contact_id, name, aliases, notes)` | Redirect `tab="contacts"` |
| POST | `/ledger/add` | 399, 945 | `handle_ledger_add` | `contacts.add_ledger_entry(...)` | Redirect `tab="contacts"` (or `"review"`) |
| POST | `/ledger/settle` | 403, 1042 | `handle_ledger_settle` | `contacts.record_settlement(...)` | Redirect `tab="contacts"` |
| POST | `/ledger/rolling` | 409, 410 | `handle_ledger_rolling` | `contacts.add_rolling_entry(...)` | Redirect `tab="contacts"` |
| POST | `/ledger/opening` | 411, 412 | `handle_ledger_opening` | `contacts.record_opening_balance(...)` | Redirect `tab="contacts"` |
| POST | `/ledger/passthrough/confirm` | 401, 402 | Inline Handler | `contacts.add_rolling_entry(...)` | Redirect `tab="contacts"` |

---

### 1.4 Identified Coupling & Architectural Code Smells

1. **Monolithic Template (`render_contacts_section`)**:
   - 394 lines of string formatting in `templates.py`. It mixes Python financial data partitioning, card rendering, pass-through suggestions HTML, tool forms, 3 full modal dialog definitions, and 1 slide-out drawer definition into a single giant function.
2. **Hardcoded Inline `onclick` Snippets**:
   - `templates.py` embeds JSON-dumped string literals into inline HTML handlers:
     - Line 354: `onclick='openLedgerDrawer({cid}, {js_name})'`
     - Line 364: `onclick='openEditContactModal({cid}, {js_name}, {js_aliases}, {js_notes})'`
     - Line 365: `onclick='openAddLedgerModal({cid}, {js_name})'`
   - This breaks Content Security Policy (CSP), requires complex python JSON serialization (`_json.dumps`) inside string templates, and couples markup directly to global JS function names.
3. **Global Scope Pollution in JavaScript (`app.js`)**:
   - `app.js` exposes 11 functions and 4 state variables directly on `window` (`window._drawerContactId`, `window._drawerContactName`, `window.openLedgerDrawer`, `window.openEditContactModal`, `window.openAddLedgerModal`, `window.filterPeopleList`, etc.).
4. **Dynamic InnerHTML Injection**:
   - `openLedgerDrawer` (lines 865–874) constructs raw HTML strings for ledger entries using string concatenation (`'<div class="people-hist-row...'`) and assigns them directly to `listEl.innerHTML`.
5. **Mixed POST vs. AJAX State Management**:
   - Drawer history is fetched dynamically via AJAX (`GET /api/contacts/ledger`), but modal operations (editing contact, logging money, marking settled) use standard form `POST` requests followed by page redirects.

---

## 2. Logic Chain

1. **Observational Premise**: `render_contacts_section` in `templates.py` constructs large HTML strings containing hardcoded `onclick` JS function calls, while `app.js` attaches those functions to `window`.
2. **Constraint Check**: According to `AGENTS.md` and `PROJECT.md`, work belongs to Zone D / FC-03. Modifying UI structure in `templates.py` and interaction logic in `app.js` must preserve 100% of existing HTTP endpoints, form field names, and visual layout.
3. **Deduction on Decoupling HTML from JS**:
   - Instead of injecting `onclick="openEditContactModal(1, 'Name', ...)"` into template strings, HTML elements should use declarative HTML5 `data-*` attributes (e.g. `data-action="edit-contact"`, `data-contact-id="1"`, `data-contact-name="Name"`).
   - In `app.js`, a single delegated event listener on `document` (or the `#pane-contacts` container) can catch click events, inspect `e.target.closest('[data-action]')`, and invoke the appropriate handler.
4. **Deduction on Template Modularization**:
   - `render_contacts_section` should act as an orchestrator calling focused sub-component renderers (`render_contact_card`, `render_people_toolbar`, `render_passthrough_suggestions`, `render_people_tools`, `render_add_contact_modal`, `render_edit_contact_modal`, `render_add_ledger_modal`, `render_ledger_drawer`).
   - Each sub-component renderer receives explicit props and returns clean HTML.

---

## 3. Caveats

- **Read-Only Constraint**: This report presents an audit and refactoring plan. No production source files have been modified.
- **Backward Compatibility for Global Aliases**: Older inline handlers or third-party test code might expect `window.filterContactCards` or `window.openLedgerDrawer`. The refactored `app.js` should maintain thin backward-compatibility facades while using modular internal functions.
- **Form POST Route Contracts**: Form field names (`contact_id`, `name`, `aliases`, `notes`, `direction`, `amount`, `purpose`, `entry_date`) must remain unchanged to ensure seamless compatibility with `expense_tracker/web.py`.

---

## 4. Conclusion & UI Component Breakdown / Decoupling Plan

### 4.1 Component Breakdown Matrix

We propose breaking down the monolithic `render_contacts_section` in `templates.py` into 8 modular sub-components:

| Component Name | Target Function Signature | Input Props | Responsibilities | Output HTML / Data Contract |
|---|---|---|---|---|
| **ContactCard** | `render_contact_card(item: dict, quiet: bool = False) -> str` | `item: dict` (contact & balance data), `quiet: bool` | Formats avatar, contact name, net balance tag, entries count, and action buttons | `<div class="people-row contact-card" data-contact-id="..." data-action="...">` |
| **PeopleToolbar** | `render_people_toolbar() -> str` | None | Renders search input (`#contact-search-input`), status filter pill buttons, and `+ Person` button | `<div class="people-toolbar">` with `data-filter` controls |
| **PassthroughSuggestions** | `render_passthrough_suggestions(candidates: list[dict], contacts: list[dict]) -> str` | `candidates: list[dict]`, `contacts: list[dict]` | Renders collapsible `<details>` card for AI-detected rolling money pairs | `<details class="people-tools">` with confirmation forms |
| **PeopleTools** | `render_people_tools(contacts: list[dict], today: str) -> str` | `contacts: list[dict]`, `today: str` | Renders manual rolling money form and starting balance form | `<details class="people-tools">` containing tool grid |
| **AddContactModal** | `render_add_contact_modal() -> str` | None | Renders modal markup for creating a new contact | `<div id="modal-add-contact" class="people-modal" hidden>` |
| **EditContactModal** | `render_edit_contact_modal() -> str` | None | Renders modal markup for editing name/aliases/notes | `<div id="modal-edit-contact" class="people-modal" hidden>` |
| **AddLedgerModal** | `render_add_ledger_modal() -> str` | None | Renders modal markup for logging money entry | `<div id="modal-add-ledger" class="people-modal" hidden>` |
| **LedgerDrawer** | `render_ledger_drawer() -> str` | None | Renders slide-out drawer container and backdrop | `<aside id="ledger-drawer" class="people-drawer" hidden>` |

---

### 4.2 Data-Attribute Event Contract

To decouple HTML rendering from JavaScript, all interactive elements will use declarative attributes:

```html
<!-- Example Refactored Contact Card Markup in templates.py -->
<div class="people-row contact-card"
     data-contact-id="12"
     data-contact-name="Ananthu"
     data-aliases="anandu, 98xxxxxxxx"
     data-notes="Friend"
     data-status="owes_you"
     data-quiet="0">
  <button type="button" class="people-row-main" data-action="open-drawer">
    <span class="people-avatar" aria-hidden="true">A</span>
    <span class="people-row-text">
      <span class="people-name">Ananthu</span>
      <span class="people-meta">Owes you ₹1,500 · 3 entries</span>
    </span>
    <span class="people-amt people-amt-pos">₹1,500</span>
  </button>
  <div class="people-row-actions">
    <button type="button" class="button subtle" data-action="edit-contact">Edit</button>
    <button type="button" class="button" data-action="add-ledger">+ Money</button>
    <button type="button" class="button subtle" data-action="open-drawer">History</button>
  </div>
</div>
```

---

### 4.3 Refactored Frontend Architecture (`app.js` / `KhataUI`)

In `app.js`, modal and drawer management will be encapsulated into a clean event-delegation controller:

```javascript
// Example Refactored Event Delegation Pattern in app.js
document.addEventListener('click', function (e) {
  var actionBtn = e.target.closest('[data-action]');
  if (!actionBtn) return;

  var action = actionBtn.getAttribute('data-action');
  var card = actionBtn.closest('.contact-card');
  var contactId = actionBtn.getAttribute('data-contact-id') || (card && card.getAttribute('data-contact-id'));
  var contactName = actionBtn.getAttribute('data-contact-name') || (card && card.getAttribute('data-name'));

  switch (action) {
    case 'open-drawer':
      KhataUI.openDrawer(contactId, contactName);
      break;
    case 'edit-contact':
      var aliases = actionBtn.getAttribute('data-aliases') || (card && card.getAttribute('data-aliases'));
      var notes = actionBtn.getAttribute('data-notes') || '';
      KhataUI.openEditModal(contactId, contactName, aliases, notes);
      break;
    case 'add-ledger':
      KhataUI.openAddLedgerModal(contactId, contactName);
      break;
    case 'close-modal':
      var modalId = actionBtn.getAttribute('data-modal-id');
      KhataUI.closeModal(modalId);
      break;
    case 'close-drawer':
      KhataUI.closeDrawer();
      break;
  }
});
```

---

## 5. Verification Method

To independently verify this analysis and ensure future implementation of Milestone 3 preserves system stability:

1. **Pytest Suite Execution**:
   ```powershell
   .\venv\Scripts\python.exe -m pytest tests/test_contacts_ledger.py tests/test_core.py
   ```
   *Expected result*: 25 passed in ~1.3 seconds with exit code `0`.

2. **End-to-End Smoke Verification**:
   ```powershell
   .\venv\Scripts\python.exe expense_tracker/e2e_test.py
   ```
   *Expected result*: `ALL TESTS PASSED` with exit code `0`.

3. **Python Byte-Compilation Check**:
   ```powershell
   .\venv\Scripts\python.exe -m py_compile expense_tracker/templates.py expense_tracker/static/app.js
   ```
   *Expected result*: Exit code `0` with zero syntax errors.

4. **Architecture Guardian Audit**:
   ```powershell
   .\venv\Scripts\python.exe .grok\skills\architecture-agent\scripts\architecture_check.py --intent-zones D --feature FC-03
   ```
   *Expected result*: `VERDICT: PASS` with 0 isolation or completeness violations.

**Invalidation Conditions**:
- Any Pytest test failures.
- Non-zero exit code from `e2e_test.py` or `py_compile`.
- Architecture check reporting isolation or feature contract completeness failures for Zone D / FC-03.
