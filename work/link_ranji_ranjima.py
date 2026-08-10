"""Ensure Ranji == Ranjima: aliases + report fragment contacts."""
import json
from expense_tracker.db import DATA_DIR, connect
from expense_tracker.contacts import get_balance, get_ledger, find_contact_by_text

with connect(DATA_DIR / "expenses_anand.db") as conn:
    rows = conn.execute(
        """
        SELECT id, name, aliases_json, merged_into_id
        FROM contacts
        WHERE lower(name) LIKE '%ranji%'
           OR lower(coalesce(aliases_json, '')) LIKE '%ranji%'
        ORDER BY id
        """
    ).fetchall()
    print("=== contacts matching ranji* ===")
    for r in rows:
        try:
            aliases = json.loads(r["aliases_json"] or "[]")
        except Exception:
            aliases = []
        bal = get_balance(conn, r["id"])
        print(
            f"id={r['id']} name={r['name']!r} merged={r['merged_into_id']} "
            f"aliases={aliases} net={bal['net']} entries={bal['entry_count']}"
        )

    # Ensure canonical Ranjima has ranji aliases
    ranjima = conn.execute(
        "SELECT id, name, aliases_json FROM contacts WHERE lower(name) = 'ranjima' ORDER BY id LIMIT 1"
    ).fetchone()
    if not ranjima:
        raise SystemExit("No Ranjima contact")
    try:
        aliases = json.loads(ranjima["aliases_json"] or "[]")
    except Exception:
        aliases = []
    for a in ["ranjima", "ranji", "ms ranji", "9497760612", "ranjima sbin"]:
        if a not in aliases:
            aliases.append(a)
    conn.execute(
        "UPDATE contacts SET aliases_json = ? WHERE id = ?",
        (json.dumps(aliases), ranjima["id"]),
    )
    conn.commit()
    print(f"\nUpdated Ranjima id={ranjima['id']} aliases={aliases}")

    print("\n=== find_contact_by_text checks ===")
    for q in [
        "Ranjima",
        "ranji",
        "Ranji",
        "Ms Ranji",
        "Cr Ms Ranji Idib",
        "UPI/CR/Ms Ranji/IDIB/9497760612",
    ]:
        m = find_contact_by_text(conn, q)
        print(f"  {q!r:45} -> {m['name'] if m else None} (id={m['id'] if m else None})")

    print("\n=== Ranjima ledger ===")
    for e in get_ledger(conn, ranjima["id"])["entries"]:
        print(
            f"  {e.get('entry_date')} {e.get('direction')} ₹{e.get('amount')} "
            f"pt={e.get('is_passthrough')} txn={e.get('transaction_id')}"
        )
    print("balance", get_balance(conn, ranjima["id"]))
