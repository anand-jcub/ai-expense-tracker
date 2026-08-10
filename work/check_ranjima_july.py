"""Find July Ranjima credits and current ledger state."""
from expense_tracker.db import DATA_DIR, connect
from expense_tracker.contacts import find_contact_by_text, get_balance, get_ledger

with connect(DATA_DIR / "expenses_anand.db") as conn:
    c = find_contact_by_text(conn, "Ranjima")
    print("contact", dict(c) if c else None)
    if c:
        print("balance", get_balance(conn, c["id"]))
        led = get_ledger(conn, c["id"])
        print("ledger entries", len(led["entries"]))
        for e in led["entries"]:
            print(
                f"  {e.get('entry_date')} {e.get('direction')} amt={e.get('amount')} "
                f"pt={e.get('is_passthrough')} purpose={e.get('purpose')} "
                f"txn={e.get('transaction_id')} notes={e.get('notes')}"
            )

    print("--- July txns matching ranjima ---")
    rows = conn.execute(
        """
        SELECT t.id, t.txn_date, t.debit, t.credit, t.merchant_display, t.description,
               t.amount_signed, c.category, c.expense_type, c.status, c.notes
        FROM transactions t
        LEFT JOIN classifications c ON c.transaction_id = t.id
        WHERE (
            lower(t.merchant_display) LIKE '%ranjima%'
            OR lower(t.description) LIKE '%ranjima%'
            OR lower(coalesce(t.raw_text, '')) LIKE '%ranjima%'
        )
          AND t.txn_date >= '2026-07-01' AND t.txn_date < '2026-08-01'
        ORDER BY t.txn_date, t.id
        """
    ).fetchall()
    print("count", len(rows))
    for r in rows:
        print(dict(r))

    # Also any ledger already linked to those txns
    print("--- ledger rows linked to those txns ---")
    if rows:
        ids = [r["id"] for r in rows]
        ph = ",".join("?" * len(ids))
        linked = conn.execute(
            f"""
            SELECT id, contact_id, transaction_id, direction, amount, purpose,
                   is_passthrough, entry_date, notes, voided_at
            FROM ledger_entries
            WHERE transaction_id IN ({ph})
            """,
            ids,
        ).fetchall()
        for r in linked:
            print(dict(r))
        if not linked:
            print("(none)")

    print("--- all July credits ---")
    rows2 = conn.execute(
        """
        SELECT t.id, t.txn_date, t.credit, t.merchant_display, t.description
        FROM transactions t
        WHERE t.credit > 0
          AND t.txn_date >= '2026-07-01' AND t.txn_date < '2026-08-01'
        ORDER BY t.txn_date, t.id
        """
    ).fetchall()
    for r in rows2:
        desc = (r["description"] or "")[:70]
        print(
            f"{r['id']:4} {r['txn_date']} +{float(r['credit']):>10,.2f}  "
            f"{(r['merchant_display'] or '')[:40]:40} {desc}"
        )
