"""Add July Ranjima credit (txn 119) to khata if missing."""
from decimal import Decimal

from expense_tracker.db import DATA_DIR, connect
from expense_tracker.contacts import (
    add_ledger_entry,
    find_contact_by_text,
    get_balance,
    get_ledger,
)

TXN_ID = 119

with connect(DATA_DIR / "expenses_anand.db") as conn:
    tx = conn.execute(
        """
        SELECT id, txn_date, credit, debit, merchant_display, description
        FROM transactions WHERE id = ?
        """,
        (TXN_ID,),
    ).fetchone()
    if not tx:
        raise SystemExit(f"Transaction {TXN_ID} not found")
    print("txn", dict(tx))

    existing = conn.execute(
        """
        SELECT id, contact_id, direction, amount, is_passthrough, purpose, voided_at
        FROM ledger_entries WHERE transaction_id = ?
        """,
        (TXN_ID,),
    ).fetchall()
    print("existing ledger for txn", [dict(r) for r in existing])

    contact = find_contact_by_text(conn, "Ranjima")
    if not contact:
        raise SystemExit("Ranjima contact not found")
    cid = int(contact["id"])
    print("contact", contact["name"], cid)
    print("balance BEFORE", get_balance(conn, cid))

    # Skip if already posted non-void for this contact+txn
    for r in existing:
        if int(r["contact_id"]) == cid and not r["voided_at"]:
            print("Already on ledger — no change.")
            break
    else:
        credit = Decimal(str(tx["credit"] or 0))
        if credit <= 0:
            raise SystemExit("Not a credit txn")
        eid = add_ledger_entry(
            conn,
            contact_id=cid,
            direction="they_sent",
            amount=credit,
            purpose="other",
            transaction_id=TXN_ID,
            is_passthrough=False,
            notes=f"Bank credit: {tx['merchant_display']} / UPI 9497760612",
            entry_date=tx["txn_date"],
            created_by="user",
        )
        print("added ledger entry id", eid)

    print("balance AFTER", get_balance(conn, cid))
    print("--- ledger ---")
    for e in get_ledger(conn, cid)["entries"]:
        print(
            f"  {e.get('entry_date')} {e.get('direction')} ₹{e.get('amount')} "
            f"pt={e.get('is_passthrough')} txn={e.get('transaction_id')} "
            f"purpose={e.get('purpose')} notes={e.get('notes')}"
        )
