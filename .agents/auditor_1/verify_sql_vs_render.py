import sqlite3
from decimal import Decimal
import sys
import os

PROJECT_ROOT = r"C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from expense_tracker.db import connect, init_db, dashboard_data, add_manual_transaction
from expense_tracker.services import filter_dashboard_rows
from expense_tracker.templates import page

def verify_sql_vs_render_counts():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert test data across multiple dates
    # Date range 1: 2024-03-01 to 2024-03-10 (5 txns)
    # Date range 2: 2024-03-11 to 2024-03-20 (5 txns)
    # Date range 3: 2024-03-21 to 2024-03-31 (5 txns)
    for i in range(1, 6):
        add_manual_transaction(conn, f"2024-03-0{i}", f"Merchant {i}", Decimal("50"), "debit", "Food", "Personal")
    for i in range(11, 16):
        add_manual_transaction(conn, f"2024-03-{i}", f"Merchant {i}", Decimal("75"), "debit", "Shopping", "Personal")
    for i in range(21, 26):
        add_manual_transaction(conn, f"2024-03-{i}", f"Merchant {i}", Decimal("100"), "debit", "Bills", "Personal")

    start_date = "2024-03-11"
    end_date = "2024-03-20"

    # Direct SQL COUNT(*)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE substr(txn_date, 1, 10) >= ? AND substr(txn_date, 1, 10) <= ?",
        (start_date, end_date)
    )
    sql_count = cursor.fetchone()[0]

    # Dashboard data & services filtering
    data = dashboard_data(conn)
    filtered_rows = filter_dashboard_rows(data["transactions"], start_date, end_date, exclude_business=False)
    filtered_count = len(filtered_rows)

    print(f"SQL COUNT(*): {sql_count}")
    print(f"Render engine filtered count: {filtered_count}")

    assert sql_count == filtered_count, f"Mismatch: SQL count ({sql_count}) != Filtered count ({filtered_count})"
    print("VERIFICATION SUCCESS: Direct SQL COUNT(*) matches rendering engine filtered count exactly.")

if __name__ == "__main__":
    verify_sql_vs_render_counts()
