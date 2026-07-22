import sqlite3
import sys
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

db = ROOT / "data" / "expenses_anand.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

from expense_tracker.contacts import calculate_contact_balance, get_contact_ledger

print("=== ALL HIGHNES-NAMED CONTACTS + BALANCES ===")
for r in conn.execute(
    "SELECT id, name, aliases_json FROM contacts WHERE lower(name) LIKE '%highnes%' ORDER BY id"
):
    bal = calculate_contact_balance(conn, r["id"])
    print(dict(r), "=>", bal)

print("\n=== LEDGER ENTRIES FOR SEEDED Highnes (25) ===")
for r in conn.execute(
    "SELECT * FROM ledger_entries WHERE contact_id=25 ORDER BY entry_date, id"
):
    print(dict(r))

print("\n=== ALL Highnes* contact ledger totals ===")
for r in conn.execute(
    """
    SELECT ct.id, ct.name, count(l.id) n,
           sum(CASE WHEN coalesce(l.direction,l.entry_type)='you_sent' THEN l.amount ELSE 0 END) you_sent,
           sum(CASE WHEN coalesce(l.direction,l.entry_type)='they_sent' THEN l.amount ELSE 0 END) they_sent,
           sum(CASE WHEN l.is_passthrough=1 THEN 1 ELSE 0 END) pt_n
    FROM contacts ct
    LEFT JOIN ledger_entries l ON l.contact_id = ct.id
    WHERE lower(ct.name) LIKE '%highnes%'
    GROUP BY ct.id
    """
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

print("\n=== expense_type counts ===")
for r in conn.execute(
    "SELECT expense_type, count(*) n FROM classifications GROUP BY expense_type"
):
    print(dict(r))

print("\n=== sample Shared expenses ===")
for r in conn.execute(
    """
    SELECT t.id, t.txn_date, t.merchant_display, t.debit, t.credit,
           c.split_ratio, c.my_share, c.shared_with, c.category, c.status
    FROM transactions t
    JOIN classifications c ON c.transaction_id = t.id
    WHERE c.expense_type = 'Shared'
    ORDER BY t.txn_date DESC
    LIMIT 25
    """
):
    print(dict(r))

print("\n=== Highnes merchant transactions ===")
for r in conn.execute(
    """
    SELECT t.id, t.txn_date, t.merchant_display, t.debit, t.credit,
           c.expense_type, c.split_ratio, c.my_share, c.shared_with, c.category
    FROM transactions t
    JOIN classifications c ON c.transaction_id = t.id
    WHERE lower(t.merchant_display) LIKE '%highnes%'
       OR lower(t.description) LIKE '%highnes%'
    ORDER BY t.txn_date
    LIMIT 40
    """
):
    print(dict(r))

print("\n=== ledger purpose breakdown for Highnesj Sibl (1) ===")
for r in conn.execute(
    """
    SELECT coalesce(direction,entry_type) d, purpose, is_passthrough, count(*) n,
           round(sum(amount),2) s
    FROM ledger_entries WHERE contact_id=1
    GROUP BY 1,2,3
    """
):
    print(dict(r))

print("\n=== passthrough pairs sample ===")
for r in conn.execute(
    """
    SELECT l.id, ct.name, coalesce(l.direction,l.entry_type) d, l.amount,
           l.is_passthrough, l.passthrough_pair_id, l.purpose, l.transaction_id
    FROM ledger_entries l
    JOIN contacts ct ON ct.id=l.contact_id
    WHERE l.is_passthrough=1
    ORDER BY l.id LIMIT 20
    """
):
    print(dict(r))

print("\n=== classifications schema ===")
print([x[1] for x in conn.execute("PRAGMA table_info(classifications)")])
print("=== contacts schema ===")
print([x[1] for x in conn.execute("PRAGMA table_info(contacts)")])
print("=== ledger_entries schema ===")
print([x[1] for x in conn.execute("PRAGMA table_info(ledger_entries)")])
print("=== transactions schema ===")
print([x[1] for x in conn.execute("PRAGMA table_info(transactions)")])

print("\n=== users ===")
try:
    uconn = sqlite3.connect(ROOT / "data" / "users.db")
    uconn.row_factory = sqlite3.Row
    for r in uconn.execute("SELECT id, username FROM users"):
        print(dict(r))
except Exception as e:
    print(e)

print("\n=== total ledger stats ===")
for r in conn.execute(
    """
    SELECT count(*) n,
           sum(CASE WHEN coalesce(direction,entry_type)='you_sent' THEN amount ELSE 0 END) ys,
           sum(CASE WHEN coalesce(direction,entry_type)='they_sent' THEN amount ELSE 0 END) ts,
           sum(is_passthrough) pt
    FROM ledger_entries
    """
):
    print(dict(r))
