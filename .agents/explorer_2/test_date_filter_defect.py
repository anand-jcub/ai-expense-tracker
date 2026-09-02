"""
Reproduction & Verification Script for Date Filtering Defects (explorer_2)
"""
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
import os
import sys

# Add project root to sys.path
PROJECT_ROOT = r"C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from expense_tracker.db import connect, init_db, dashboard_data, import_transactions, add_manual_transaction
from expense_tracker.services import filter_dashboard_rows, date_bounds
from expense_tracker.templates import page

def test_defect_1_shared_slicing():
    print("=== Testing Defect 1: Shared Expenses Pre-slicing (:15) ===")
    # Create temp in-memory DB
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert 20 shared transactions across March 2024 (10) and April 2024 (10)
    for i in range(1, 11):
        add_manual_transaction(
            conn, f"2024-04-{i:02d}", f"Shared April {i}", Decimal("100"), "debit",
            "Food", "Shared", split_ratio=Decimal("0.5")
        )
    for i in range(1, 11):
        add_manual_transaction(
            conn, f"2024-03-{i:02d}", f"Shared March {i}", Decimal("100"), "debit",
            "Food", "Shared", split_ratio=Decimal("0.5")
        )

    # Fetch dashboard data
    data = dashboard_data(conn)
    print(f"Total transactions in DB: {len(data['transactions'])}")
    print(f"Total shared rows returned by dashboard_data (sliced to :15): {len(data['shared'])}")

    # Suppose user filters for March 2024 ("2024-03-01" to "2024-03-31")
    start_date, end_date = "2024-03-01", "2024-03-31"
    
    # Direct DB count for March Shared
    march_shared_db = conn.execute(
        "SELECT COUNT(*) FROM transactions t JOIN classifications c ON c.transaction_id=t.id WHERE t.txn_date >= ? AND t.txn_date <= ? AND c.expense_type='Shared'",
        (start_date, end_date)
    ).fetchone()[0]

    # Shared rows derived from data["shared"] with period filter (as templates.py currently does)
    _in_period = lambda r: start_date <= str(r["txn_date"]) <= end_date
    shared_filtered_from_shared_key = [r for r in data["shared"] if _in_period(r)]

    # Shared rows derived from data["transactions"] with period filter
    shared_filtered_from_tx_key = [r for r in data["transactions"] if _in_period(r) and r["expense_type"] == "Shared"]

    print(f"March Shared DB Count: {march_shared_db}")
    print(f"March Shared Count via data['shared'][:15] (Templates logic): {len(shared_filtered_from_shared_key)}")
    print(f"March Shared Count via data['transactions'] (Correct logic): {len(shared_filtered_from_tx_key)}")
    if len(shared_filtered_from_shared_key) < march_shared_db:
        print("-> DEFECT CONFIRMED: Shared transactions missing because data['shared'] was pre-sliced to 15!")
    print()

def test_defect_2_inverted_clamping():
    print("=== Testing Defect 2: Inverted Date Range Clamping ===")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Insert March 2024 transactions (historical data)
    for i in range(1, 11):
        add_manual_transaction(
            conn, f"2024-03-{i:02d}", f"Txn {i}", Decimal("50"), "debit",
            "Food", "Personal"
        )

    data = dashboard_data(conn)
    min_date, max_date = date_bounds(data.get("transactions") or [])
    print(f"Data min_date: {min_date}, max_date: {max_date}")

    # Simulate templates.py logic when start_date and end_date are empty (initial page load today, e.g. Aug 2026)
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    month_end = (next_month - timedelta(days=1)).isoformat()

    start_date = month_start
    end_date = month_end

    # Fixed templates.py clamping logic:
    if max_date and month_start > max_date:
        start_date = min_date
        end_date = max_date
    else:
        start_date = month_start
        end_date = month_end
        if min_date and start_date < min_date:
            start_date = min_date
        if max_date and end_date > max_date:
            end_date = max_date
    if start_date and end_date and start_date > end_date:
        start_date = min_date

    print(f"Computed start_date: '{start_date}', end_date: '{end_date}'")
    period_rows = filter_dashboard_rows(data["transactions"], start_date, end_date)
    print(f"Total transactions in DB: {len(data['transactions'])}")
    print(f"Filtered period_rows count: {len(period_rows)}")
    if start_date > end_date:
        print("-> DEFECT CONFIRMED: Inverted date range (start_date > end_date) causes ALL transactions to disappear!")
    print()

def test_defect_3_timestamp_boundary():
    print("=== Testing Defect 3: Timestamp Boundary Comparison ===")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Add transaction with ISO timestamp (e.g. 2024-03-15T15:30:00)
    add_manual_transaction(
        conn, "2024-03-15T15:30:00", "Txn with timestamp", Decimal("100"), "debit",
        "Food", "Personal"
    )

    data = dashboard_data(conn)
    start_date, end_date = "2024-03-01", "2024-03-15"

    period_rows = filter_dashboard_rows(data["transactions"], start_date, end_date)
    print(f"Selected period: {start_date} to {end_date}")
    print(f"Row txn_date in DB: '{data['transactions'][0]['txn_date']}'")
    print(f"period_rows count: {len(period_rows)}")
    if len(period_rows) == 0:
        print("-> DEFECT CONFIRMED: Transaction on end_date with timestamp was excluded due to string comparison!")
    print()

if __name__ == "__main__":
    test_defect_1_shared_slicing()
    test_defect_2_inverted_clamping()
    test_defect_3_timestamp_boundary()
