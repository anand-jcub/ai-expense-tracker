"""Smoke check simplified khata on live anand DB."""
from expense_tracker.db import DATA_DIR, connect, dashboard_data
from expense_tracker.contacts import get_balance, get_all_balances, get_ledger, find_contact_by_text
from expense_tracker.templates import page
from expense_tracker.auth import get_all_usernames

with connect(DATA_DIR / "expenses_anand.db") as conn:
    items = get_all_balances(conn)
    nonzero = [i for i in items if i["balance"]["net"] != 0]
    print("nonzero contacts", len(nonzero))
    for i in sorted(nonzero, key=lambda x: abs(x["balance"]["net"]), reverse=True)[:10]:
        b = i["balance"]
        print(f"  {i['contact']['name']:30} net={b['net']:>10} status={b['status']} entries={b['entry_count']}")
    h = find_contact_by_text(conn, "Highnes")
    print("find Highnes", h["name"] if h else None, h["id"] if h else None)
    if h:
        print("Highnes bal", get_balance(conn, h["id"]))
        led = get_ledger(conn, h["id"])
        print("ledger entries", len(led["entries"]))
    data = dashboard_data(conn)
    users = get_all_usernames()
    pb = [
        {
            "username": i["contact"]["name"],
            "contact_id": i["contact"]["id"],
            "they_owe_you": i["balance"]["they_owe_you"],
            "you_owe_them": i["balance"]["you_owe_them"],
            "net": i["balance"]["net"],
        }
        for i in get_all_balances(conn)
        if i["balance"]["net"] != 0
    ]
    html = page(
        data, None, None, "newest", "", "", "", "", "", False,
        current_user="anand", all_users=users, partner_balances=pb, tx_filter="needs_review",
    )
    print(
        "page bytes", len(html),
        "has merge modal", b"modal-manual-merge" in html,
        "has rolling", b"/ledger/rolling" in html,
    )

import expense_tracker.web as w  # noqa: E402
print("web import ok", hasattr(w.ExpenseHandler, "handle_ledger_rolling"))
print("no settlement module", end=" ")
try:
    import expense_tracker.settlement  # noqa: F401
    print("STILL PRESENT")
except ImportError:
    print("deleted OK")
