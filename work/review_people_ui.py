"""Static review helpers for People section markup."""
from expense_tracker.db import DATA_DIR, connect, dashboard_data
from expense_tracker.templates import render_contacts_section, page
from expense_tracker.auth import get_all_usernames
import re

with connect(DATA_DIR / "expenses_anand.db") as conn:
    data = dashboard_data(conn)
    section = render_contacts_section(
        data.get("contacts") or [],
        data.get("passthrough_candidates") or [],
    )
    full = page(
        data, None, None, "newest", "", "", "", "", "", False,
        current_user="anand", all_users=get_all_usernames(),
        partner_balances=[], tx_filter="needs_review",
    ).decode("utf-8")

print("section len", len(section))
print("active rows", section.count('data-quiet="0"'))
print("quiet rows", section.count('data-quiet="1"'))
print("modals hidden", section.count('people-modal" hidden'))
print("drawer hidden", 'people-drawer" hidden' in section or 'people-drawer' in section)

# issues: nested interactive? button inside button? no
# duplicate status text (meta says Owes you AND amount)
# money() may include ₹ already + amount also
from expense_tracker.templates import money
print("money sample", money(35600), money(100.0))

# Check if history JS escapes HTML - read app.js snippet mentally: notes not escaped
# Check purpose opening_balance sets is_opening_balance flag? form only sets purpose select, not checkbox
# BUG: purpose=opening_balance but is_opening_balance only set if purpose maps in add_ledger_entry
# contacts.add_ledger_entry: if is_opening_balance and purpose other -> opening_balance
# but purpose opening_balance alone does NOT set is_opening_balance=True unless checkbox
# Looking at add_ledger_entry - is_opening_balance is explicit flag. purpose can be opening_balance.
# get_ledger shows is_opening_balance for badge - may miss purpose-only opening rows for opening badge in UI
# actually purposeLabel checks purpose === 'opening_balance' - OK

# Filter bug: default active hides quiet; quiet panel separate - OK
# When filter owes_you, quiet rows settled stay hidden - OK
# When filter all, quiet panel opens - OK
# Search while on Balances filter won't find settled people unless panel open and filter changes - BUG: search with active filter won't find settled

# Nested buttons: people-row-main is button, actions are separate - OK

# CSS :has() may fail old browsers - minor

# Duplicate History button and row click - intentional redundancy on mobile maybe OK

# Contact options include ALL contacts including quiet - good for rolling

# Bank fragment noise still in active list if net != 0

# people-page max-width 720 but main content wider - looks left-aligned orphan

# Global .button styles vs people filters

# Tab pane may be hidden - #pane-contacts

# XSS: history notes injected raw in app.js
notes_raw = "notes injected without escape in openLedgerDrawer"

# Check full page cache bust
print("css v", "style.css?v=16" in full)
print("js v", "app.js?v=15" in full)

# Status line duplicates amount: "Owes you ₹35,600 · 9 entries" AND big ₹35,600
# meta uses money(net) which already has rupee

# Opening form doesn't set is_opening_balance=1 on purpose-only from + Money modal
# web handle_ledger_add: is_opening_balance = "is_opening_balance" in params - checkbox removed!
# So purpose=opening_balance is sent but is_opening_balance flag is False
# add_ledger_entry sets purpose as given; is_opening_balance stays 0
# BUG for starting balance via + Money modal

# Settle form placeholder only - empty amount = full settle - OK

# Modal people-simple-form is 2-col grid; people-span and fieldset span - fieldset has people-choice with grid-column 1/-1 - OK

# Radio labels: small inside span - OK

# Escape in meta line: line = f"Owes you {money(net)}" not esc'd - money is safe numeric format
# aliases in meta esc'd - OK

# Click on + Money inside row might bubble? separate buttons not inside main button - OK

issues = [
    "1. REDUNDANT COPY: row shows 'Owes you ₹X' in meta AND ₹X as amount — feels double",
    "2. SEARCH + FILTER: default Balances filter hides settled; search won't find settled people without switching Everyone",
    "3. + MONEY opening_balance purpose does not set is_opening_balance flag (checkbox removed)",
    "4. HISTORY XSS: notes/purpose inserted as HTML without escape in app.js",
    "5. BANK NOISE: merchant fragments with nonzero net still clutter primary list",
    "6. LAYOUT: people-page max-width 720px left-aligned in wide main — empty right half",
    "7. DUPLICATE ACTIONS: row click opens history AND History button — mobile has 3 targets",
    "8. QUIET panel: settled people not searchable from default view",
    "9. DRAWER: newest-first list but running_balance was computed oldest-first — 'Balance after' confusing when reversed",
    "10. SETTLE UX: amount field + Mark settled without clear 'full settle' one-tap for zeros-skill users",
    "11. NO EMPTY FILTER STATE message when Owes me/I owe filters yield no rows",
    "12. PT section: may show incomplete contact pickers; jargon still dense",
    "13. :has() CSS for selected radio fails on older browsers (minor)",
    "14. Avatar colors cycle by nth-child per-list not global — quiet panel restarts colors",
]
for i in issues:
    print(i)
