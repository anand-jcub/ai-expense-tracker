"""List Ananthu-like contacts and their balances."""
from expense_tracker.db import DATA_DIR, connect
from expense_tracker.contacts import get_all_contacts, get_balance, get_ledger

with connect(DATA_DIR / "expenses_anand.db") as conn:
    contacts = get_all_contacts(conn)
    hits = []
    for c in contacts:
        name = (c.get("name") or "").lower()
        aliases = " ".join(c.get("aliases") or []).lower()
        blob = f"{name} {aliases}"
        if any(k in blob for k in ("ananth", "ananthu", "anandu", "anandhu")):
            hits.append(c)

    print(f"Found {len(hits)} Ananthu-like contacts\n")
    for c in hits:
        bal = get_balance(conn, c["id"])
        led = get_ledger(conn, c["id"])
        print("=" * 60)
        print(f"id={c['id']} name={c['name']!r}")
        print(f"  aliases={c.get('aliases')}")
        print(f"  notes={c.get('notes')}")
        print(f"  merged_into={c.get('merged_into_id')}")
        print(f"  balance net={bal['net']} you_sent={bal['total_you_sent']} they_sent={bal['total_they_sent']} entries={bal['entry_count']}")
        print(f"  ledger rows (incl PT): {len(led['entries'])}")
        for e in led["entries"][:12]:
            print(
                f"    {e.get('entry_date')} {e.get('direction')} ₹{e.get('amount')} "
                f"pt={e.get('is_passthrough')} purpose={e.get('purpose')} "
                f"txn={e.get('transaction_id')} created_by={e.get('created_by')} "
                f"notes={(e.get('notes') or '')[:50]}"
            )
        if len(led["entries"]) > 12:
            print(f"    ... +{len(led['entries']) - 12} more")

    # Bank txns that might map to these
    print("\n--- bank txns with ananth/anandu/ananthu ---")
    rows = conn.execute(
        """
        SELECT id, txn_date, debit, credit, merchant_display, description
        FROM transactions
        WHERE lower(merchant_display) LIKE '%ananth%'
           OR lower(merchant_display) LIKE '%anandu%'
           OR lower(description) LIKE '%ananth%'
           OR lower(description) LIKE '%anandu%'
           OR lower(coalesce(raw_text,'')) LIKE '%ananth%'
           OR lower(coalesce(raw_text,'')) LIKE '%anandu%'
        ORDER BY txn_date, id
        """
    ).fetchall()
    for r in rows:
        side = f"+{r['credit']}" if float(r["credit"] or 0) > 0 else f"-{r['debit']}"
        print(f"  txn={r['id']} {r['txn_date']} {side:>12}  {r['merchant_display']!r}")
