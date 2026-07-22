import sqlite3
from pathlib import Path
from decimal import Decimal

db = Path(__file__).resolve().parents[1] / "data" / "expenses_anand.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

print("=== CONTACTS ===")
for r in conn.execute("SELECT * FROM contacts ORDER BY name"):
    print(dict(r))

print("\n=== HIGHNES LEDGER ===")
h = conn.execute(
    "SELECT id, name FROM contacts WHERE lower(name) LIKE '%highnes%'"
).fetchone()
if h:
    cid = h["id"]
    print("contact_id", cid, h["name"])
    for r in conn.execute(
        "SELECT * FROM ledger_entries WHERE contact_id=? ORDER BY entry_date, id",
        (cid,),
    ):
        print(dict(r))
    from expense_tracker.contacts import calculate_contact_balance

    print("balance", calculate_contact_balance(conn, cid))
else:
    print("No Highnes contact")

print("\n=== SHARED / Highnes related txns ===")
for r in conn.execute(
    """
    SELECT t.id, t.txn_date, t.merchant_display, t.debit, t.credit,
           c.expense_type, c.split_ratio, c.my_share, c.shared_with, c.status
    FROM transactions t
    JOIN classifications c ON c.transaction_id = t.id
    WHERE lower(coalesce(c.shared_with,'')) LIKE '%ighnes%'
       OR lower(t.merchant_display) LIKE '%highnes%'
       OR lower(t.description) LIKE '%highnes%'
    ORDER BY t.txn_date DESC
    LIMIT 40
    """
):
    print(dict(r))

print("\n=== expense_type counts ===")
for r in conn.execute(
    "SELECT expense_type, count(*) n FROM classifications GROUP BY expense_type"
):
    print(dict(r))

print("\n=== shared_with values ===")
for r in conn.execute(
    """
    SELECT shared_with, count(*) n
    FROM classifications
    WHERE shared_with IS NOT NULL AND shared_with != ''
    GROUP BY shared_with
    """
):
    print(dict(r))

print("\n=== ledger purpose/direction counts ===")
for r in conn.execute(
    """
    SELECT coalesce(direction, entry_type) AS d, purpose, is_passthrough,
           count(*) AS n, round(sum(amount), 2) AS s
    FROM ledger_entries
    GROUP BY 1, 2, 3
    """
):
    print(dict(r))

print("\n=== sample Shared expenses ===")
for r in conn.execute(
    """
    SELECT t.id, t.txn_date, t.merchant_display, t.debit, t.credit,
           c.split_ratio, c.my_share, c.shared_with, c.category
    FROM transactions t
    JOIN classifications c ON c.transaction_id = t.id
    WHERE c.expense_type = 'Shared'
    ORDER BY t.txn_date DESC
    LIMIT 20
    """
):
    print(dict(r))

print("\n=== ledger linked to transactions ===")
for r in conn.execute(
    """
    SELECT l.id, l.contact_id, ct.name, coalesce(l.direction,l.entry_type) d,
           l.amount, l.purpose, l.is_passthrough, l.transaction_id,
           t.merchant_display, t.debit, t.credit
    FROM ledger_entries l
    JOIN contacts ct ON ct.id = l.contact_id
    LEFT JOIN transactions t ON t.id = l.transaction_id
    WHERE l.transaction_id IS NOT NULL
    ORDER BY l.id
    LIMIT 30
    """
):
    print(dict(r))

print("\n=== all ledger by contact summary ===")
for r in conn.execute(
    """
    SELECT ct.id, ct.name,
           sum(CASE WHEN coalesce(l.direction,l.entry_type)='you_sent' THEN l.amount ELSE 0 END) you_sent,
           sum(CASE WHEN coalesce(l.direction,l.entry_type)='they_sent' THEN l.amount ELSE 0 END) they_sent,
           count(*) n
    FROM contacts ct
    LEFT JOIN ledger_entries l ON l.contact_id = ct.id
    GROUP BY ct.id
    HAVING n > 0
    ORDER BY ct.name
    """
):
    print(dict(r))
