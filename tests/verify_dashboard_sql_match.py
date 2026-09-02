"""Standalone Python verification script for Acceptance Criterion #1.

Asserts that dashboard data fetched and filtered for rendering via filter_dashboard_rows
matches a direct SQL COUNT(*) query for the same date range and business filter options.
"""

from __future__ import annotations

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expense_tracker.db import connect, dashboard_data
from expense_tracker.services import filter_dashboard_rows


def run_verification():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        conn = connect(db_path)

        # 1. Insert an import record
        now = "2026-08-10T12:00:00Z"
        cur = conn.execute(
            "INSERT INTO imports (source_filename, file_sha256, imported_at) VALUES (?, ?, ?)",
            ("test_statement.pdf", "sha256_dummy_hash", now),
        )
        import_id = cur.lastrowid

        # 2. Insert sample transactions with various dates and types
        sample_transactions = [
            # (txn_date, desc, debit, credit, category, expense_type)
            # Before period (< 2026-03-01)
            ("2026-02-28", "Supermarket Jan", 500, 0, "Groceries", "Personal"),
            ("2026-02-28T23:59:59Z", "Midnight Snack", 150, 0, "Food", "Personal"),
            
            # Boundary Start (2026-03-01 with time components)
            ("2026-03-01T00:00:00Z", "Early Coffee", 100, 0, "Food", "Personal"),
            ("2026-03-01 08:30:00", "Morning Bus", 50, 0, "Transport", "Personal"),
            ("2026-03-01", "Lunch", 300, 0, "Food", "Personal"),
            
            # Inside period (2026-03-02 to 2026-03-30)
            ("2026-03-10T14:20:00Z", "Office Supplies", 1200, 0, "Business", "Business"),
            ("2026-03-15", "Salary Credit", 0, 50000, "Other", "Personal"),
            ("2026-03-20T19:00:00", "Dinner Shared", 800, 0, "Food", "Shared"),
            ("2026-03-25", "Client Consulting", 0, 15000, "Business", "Business"),

            # Boundary End (2026-03-31 with time components)
            ("2026-03-31T09:15:00Z", "Pharmacy", 450, 0, "Health", "Personal"),
            ("2026-03-31T23:59:59Z", "Late Subscription", 299, 0, "Subscription", "Personal"),

            # After period (> 2026-03-31)
            ("2026-04-01T00:00:01Z", "April Fool Gift", 1000, 0, "Shopping", "Personal"),
            ("2026-04-05", "April Utilities", 2500, 0, "Utilities", "Personal"),
        ]

        for i, (t_date, desc, debit, credit, cat, exp_type) in enumerate(sample_transactions, 1):
            amount_signed = credit - debit
            tx_cur = conn.execute(
                """
                INSERT INTO transactions (
                    import_id, source_hash, txn_date, description, debit, credit,
                    amount_signed, raw_text, merchant_key, merchant_display, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    f"hash_{i}",
                    t_date,
                    desc,
                    debit,
                    credit,
                    amount_signed,
                    desc,
                    desc.lower(),
                    desc,
                    now,
                ),
            )
            txn_id = tx_cur.lastrowid
            conn.execute(
                """
                INSERT INTO classifications (
                    transaction_id, category, expense_type, split_ratio, my_share,
                    status, confidence, updated_at
                ) VALUES (?, ?, ?, 1.0, ?, 'reviewed', 1.0, ?)
                """,
                (txn_id, cat, exp_type, debit if debit > 0 else 0, now),
            )
        conn.commit()

        # 3. Test Cases for Period Filtering
        test_cases = [
            # (start_date, end_date, exclude_business, description)
            ("2026-03-01", "2026-03-31", False, "March 2026 full month (include business)"),
            ("2026-03-01", "2026-03-31", True, "March 2026 full month (exclude business)"),
            ("2026-03-01", "2026-03-15", False, "March 1 to March 15 (include business)"),
            ("2026-03-31", "2026-03-31", False, "Single boundary date 2026-03-31 (include business)"),
            ("2026-02-01", "2026-02-28", False, "February 2026 (include business)"),
            ("2026-04-01", "2026-04-30", False, "April 2026 (include business)"),
            ("", "", False, "All-time (no bounds)"),
        ]

        print("=== DASHBOARD vs SQL COUNT(*) VERIFICATION ===")
        all_passed = True

        for start_d, end_d, excl_bus, label in test_cases:
            # Fetch dashboard data
            dash_data = dashboard_data(conn)
            all_rows = dash_data["transactions"]

            # Filter rows using domain service function passed to rendering
            period_rows = filter_dashboard_rows(
                all_rows, start_date=start_d, end_date=end_d, exclude_business=excl_bus
            )
            render_count = len(period_rows)

            # Direct SQL COUNT(*) query matching period filter logic
            sql_params = []
            where_clauses = []

            if start_d:
                where_clauses.append("substr(t.txn_date, 1, 10) >= ?")
                sql_params.append(start_d)
            if end_d:
                where_clauses.append("substr(t.txn_date, 1, 10) <= ?")
                sql_params.append(end_d)
            if excl_bus:
                where_clauses.append("lower(c.category) != 'business' AND lower(c.expense_type) != 'business'")

            where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            sql_query = f"""
                SELECT COUNT(*) FROM transactions t
                JOIN classifications c ON c.transaction_id = t.id
                {where_str}
            """
            
            sql_count = conn.execute(sql_query, sql_params).fetchone()[0]

            match = render_count == sql_count
            status_str = "PASS" if match else "FAIL"
            if not match:
                all_passed = False

            print(f"[{status_str}] Case: {label}")
            print(f"       Range: '{start_d}' to '{end_d}' | exclude_business={excl_bus}")
            print(f"       Render count: {render_count} | SQL count: {sql_count}")
            print("-" * 50)

            assert match, f"Mismatch for case '{label}': render_count={render_count} != sql_count={sql_count}"

        conn.close()
        print(f"\nALL {len(test_cases)} VERIFICATION TEST CASES PASSED SUCCESSFULLY!")
        return all_passed

    finally:
        if db_path.exists():
            try:
                db_path.unlink()
            except Exception:
                pass

if __name__ == "__main__":
    run_verification()
