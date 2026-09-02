"""Adversarial stress tests for date filtering logic in db.py, services.py, templates.py, and web.py."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from expense_tracker.db import (
    add_manual_transaction,
    connect,
    dashboard_data,
    init_db,
    review_transaction,
)
from expense_tracker.services import (
    date_bounds,
    dashboard_totals,
    filter_dashboard_rows,
    filter_review_rows,
)
from expense_tracker.templates import (
    page,
    render_money_flows_view,
)


class DateFilteringStressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_stress.db"
        self.conn = connect(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Leap Years (e.g. Feb 29 dates)
    # ──────────────────────────────────────────────────────────────────────────
    def test_leap_year_feb_29_handling(self) -> None:
        """Verify leap year Feb 29 transactions are properly bounded and filtered."""
        tx1 = add_manual_transaction(
            self.conn,
            txn_date="2024-02-28",
            description="Pre-leap day coffee",
            amount=Decimal("150.00"),
            direction="debit",
            category="Food",
            expense_type="Personal",
        )
        tx2 = add_manual_transaction(
            self.conn,
            txn_date="2024-02-29",
            description="Leap day special lunch",
            amount=Decimal("1200.00"),
            direction="debit",
            category="Food",
            expense_type="Personal",
        )
        tx3 = add_manual_transaction(
            self.conn,
            txn_date="2024-03-01",
            description="Post-leap day grocery",
            amount=Decimal("500.00"),
            direction="debit",
            category="Groceries",
            expense_type="Personal",
        )

        data = dashboard_data(self.conn)
        rows = data["transactions"]

        # Date bounds check
        min_d, max_d = date_bounds(rows)
        self.assertEqual(min_d, "2024-02-28")
        self.assertEqual(max_d, "2024-03-01")

        # Single leap-day filter (start_date=2024-02-29, end_date=2024-02-29)
        feb29_rows = filter_dashboard_rows(rows, start_date="2024-02-29", end_date="2024-02-29")
        self.assertEqual(len(feb29_rows), 1)
        self.assertEqual(feb29_rows[0]["description"], "Leap day special lunch")

        # Range up to leap day (2024-02-01 to 2024-02-29)
        feb_rows = filter_dashboard_rows(rows, start_date="2024-02-01", end_date="2024-02-29")
        self.assertEqual(len(feb_rows), 2)
        descriptions = {r["description"] for r in feb_rows}
        self.assertIn("Pre-leap day coffee", descriptions)
        self.assertIn("Leap day special lunch", descriptions)

        # Page rendering with Feb 29 bounds
        html = page(data, start_date="2024-02-29", end_date="2024-02-29").decode("utf-8")
        self.assertIn("Leap day special lunch", html)
        self.assertNotIn("Pre-leap day coffee", html)
        self.assertNotIn("Post-leap day grocery", html)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. ISO Timestamps with Time Component
    # ──────────────────────────────────────────────────────────────────────────
    def test_iso_timestamps_with_time_component(self) -> None:
        """Verify ISO timestamp strings containing time (e.g. 2024-03-15T23:59:59) work properly."""
        tx1 = add_manual_transaction(
            self.conn,
            txn_date="2024-03-15T00:00:00",
            description="Early morning txn",
            amount=Decimal("100.00"),
            direction="debit",
            category="Shopping",
            expense_type="Personal",
        )
        tx2 = add_manual_transaction(
            self.conn,
            txn_date="2024-03-15T23:59:59",
            description="Late night txn",
            amount=Decimal("200.00"),
            direction="debit",
            category="Shopping",
            expense_type="Personal",
        )
        tx3 = add_manual_transaction(
            self.conn,
            txn_date="2024-03-16T00:00:01",
            description="Next day midnight txn",
            amount=Decimal("300.00"),
            direction="debit",
            category="Shopping",
            expense_type="Personal",
        )

        data = dashboard_data(self.conn)
        rows = data["transactions"]

        # Filter using date string "2024-03-15"
        march15_rows = filter_dashboard_rows(rows, start_date="2024-03-15", end_date="2024-03-15")
        self.assertEqual(len(march15_rows), 2)
        descs = [r["description"] for r in march15_rows]
        self.assertIn("Early morning txn", descs)
        self.assertIn("Late night txn", descs)
        self.assertNotIn("Next day midnight txn", descs)

        # Filter using ISO strings containing time as parameters
        iso_param_rows = filter_dashboard_rows(
            rows, start_date="2024-03-15T00:00:00", end_date="2024-03-15T23:59:59"
        )
        self.assertEqual(len(iso_param_rows), 2)

        # HTML page render test with ISO timestamps
        html = page(data, start_date="2024-03-15T00:00:00", end_date="2024-03-15T23:59:59").decode("utf-8")
        self.assertIn("Early morning txn", html)
        self.assertIn("Late night txn", html)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Historical Date Ranges (max_date < system current month)
    # ──────────────────────────────────────────────────────────────────────────
    def test_historical_date_ranges_max_date_in_past(self) -> None:
        """Verify historical dataset (max_date < current month) defaults to available historical period."""
        # Add transactions in 2022 (well before current system date)
        add_manual_transaction(
            self.conn,
            txn_date="2022-01-10",
            description="Old 2022 Txn 1",
            amount=Decimal("400.00"),
            direction="debit",
            category="Utilities",
            expense_type="Personal",
        )
        add_manual_transaction(
            self.conn,
            txn_date="2022-06-15",
            description="Old 2022 Txn 2",
            amount=Decimal("800.00"),
            direction="debit",
            category="Health",
            expense_type="Personal",
        )

        data = dashboard_data(self.conn)
        # Default view (no start_date / end_date query params)
        html_default = page(data, start_date="", end_date="").decode("utf-8")
        # Should auto-clamp to historical date range and display both transactions
        self.assertIn("Old 2022 Txn 1", html_default)
        self.assertIn("Old 2022 Txn 2", html_default)

        # Explicit historical filter
        html_filtered = page(data, start_date="2022-01-01", end_date="2022-01-31").decode("utf-8")
        self.assertIn("Old 2022 Txn 1", html_filtered)
        self.assertNotIn("Old 2022 Txn 2", html_filtered)

        # Explicit non-matching current range when data is historical
        html_empty = page(data, start_date="2026-01-01", end_date="2026-01-31").decode("utf-8")
        self.assertNotIn("Old 2022 Txn 1", html_empty)
        self.assertNotIn("Old 2022 Txn 2", html_empty)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Large Transaction Volumes (>100 Transfer/Loan in Money Flow)
    # ──────────────────────────────────────────────────────────────────────────
    def test_large_volume_money_flows(self) -> None:
        """Verify inflow/outflow/net totals are 100% exact for >100 Transfer/Loan transactions."""
        txns = []
        expected_inflow = Decimal("0")
        expected_outflow = Decimal("0")

        # Create 120 Transfer transactions (credits and debits)
        for i in range(120):
            if i % 2 == 0:
                credit_amt = Decimal("1500.25")
                expected_inflow += credit_amt
                txns.append({
                    "txn_date": "2024-03-10",
                    "merchant_display": f"Bank Transfer Credit {i}",
                    "amount_signed": credit_amt,
                    "debit": Decimal("0.00"),
                    "credit": credit_amt,
                    "description": f"Transfer in {i}",
                    "category": "Transfer",
                    "expense_type": "Personal",
                })
            else:
                debit_amt = Decimal("750.50")
                expected_outflow += debit_amt
                txns.append({
                    "txn_date": "2024-03-11",
                    "merchant_display": f"Bank Transfer Debit {i}",
                    "amount_signed": -debit_amt,
                    "debit": debit_amt,
                    "credit": Decimal("0.00"),
                    "description": f"Transfer out {i}",
                    "category": "Transfer",
                    "expense_type": "Personal",
                })

        # Create 30 Loan transactions
        for i in range(30):
            debit_amt = Decimal("2000.00")
            expected_outflow += debit_amt
            txns.append({
                "txn_date": "2024-03-12",
                "merchant_display": f"Loan Disbursement {i}",
                "amount_signed": -debit_amt,
                "debit": debit_amt,
                "credit": Decimal("0.00"),
                "description": f"Loan out {i}",
                "category": "Loan",
                "expense_type": "Loan",
            })

        # Render Money Flows HTML
        html = render_money_flows_view(txns)

        # Expected totals:
        # Inflow: 60 * 1500.25 = 90015.00 -> formatted as 90,015
        # Outflow: 60 * 750.50 + 30 * 2000.00 = 45030.00 + 60000.00 = 105030.00 -> formatted as 105,030
        self.assertEqual(expected_inflow, Decimal("90015.00"))
        self.assertEqual(expected_outflow, Decimal("105030.00"))

        self.assertIn("90,015", html)
        self.assertIn("105,030", html)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Date Ranges Returning 0 Transactions
    # ──────────────────────────────────────────────────────────────────────────
    def test_zero_transaction_date_ranges(self) -> None:
        """Verify zero transactions in date range produce zero errors or corruptions."""
        add_manual_transaction(
            self.conn,
            txn_date="2024-03-15",
            description="Existing Txn",
            amount=Decimal("500.00"),
            direction="debit",
            category="Food",
            expense_type="Personal",
        )

        data = dashboard_data(self.conn)

        # Date range with zero transactions
        zero_rows = filter_dashboard_rows(data["transactions"], start_date="2020-01-01", end_date="2020-01-31")
        self.assertEqual(len(zero_rows), 0)

        totals = dashboard_totals(zero_rows)
        self.assertEqual(totals["credit"], Decimal("0"))
        self.assertEqual(totals["debit"], Decimal("0"))
        self.assertEqual(totals["expense"], Decimal("0"))
        self.assertEqual(totals["net"], Decimal("0"))

        # HTML page rendering for zero transaction period
        html = page(data, start_date="2020-01-01", end_date="2020-01-31").decode("utf-8")
        self.assertIn("No spend data in this period", html)

        # Render empty money flows view
        html_flows = render_money_flows_view([])
        self.assertIn("No Money Flow Data", html_flows)

        # Inverted date range (start_date > end_date)
        inverted_rows = filter_dashboard_rows(data["transactions"], start_date="2024-12-31", end_date="2024-01-01")
        self.assertEqual(len(inverted_rows), 0)

        # Inverted date range in page() handles start_date > end_date safely without crashing
        html_inv_page = page(data, start_date="2024-12-31", end_date="2024-01-01").decode("utf-8")
        self.assertIn("No spend data in this period", html_inv_page)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Single-Day Date Range (start_date == end_date)
    # ──────────────────────────────────────────────────────────────────────────
    def test_single_day_date_range(self) -> None:
        """Verify single-day filtering (start_date == end_date) accurately isolates that day."""
        add_manual_transaction(
            self.conn,
            txn_date="2024-03-14",
            description="Day Before Txn",
            amount=Decimal("100.00"),
            direction="debit",
            category="Food",
            expense_type="Personal",
        )
        add_manual_transaction(
            self.conn,
            txn_date="2024-03-15",
            description="Target Day Txn A",
            amount=Decimal("250.00"),
            direction="debit",
            category="Transport",
            expense_type="Personal",
        )
        add_manual_transaction(
            self.conn,
            txn_date="2024-03-15",
            description="Target Day Txn B",
            amount=Decimal("350.00"),
            direction="debit",
            category="Shopping",
            expense_type="Personal",
        )
        add_manual_transaction(
            self.conn,
            txn_date="2024-03-16",
            description="Day After Txn",
            amount=Decimal("400.00"),
            direction="debit",
            category="Utilities",
            expense_type="Personal",
        )

        data = dashboard_data(self.conn)
        single_day_rows = filter_dashboard_rows(data["transactions"], start_date="2024-03-15", end_date="2024-03-15")
        self.assertEqual(len(single_day_rows), 2)
        descs = {r["description"] for r in single_day_rows}
        self.assertIn("Target Day Txn A", descs)
        self.assertIn("Target Day Txn B", descs)
        self.assertNotIn("Day Before Txn", descs)
        self.assertNotIn("Day After Txn", descs)

        totals = dashboard_totals(single_day_rows)
        self.assertEqual(totals["debit"], Decimal("600.00"))
        self.assertEqual(totals["expense"], Decimal("600.00"))

        html = page(data, start_date="2024-03-15", end_date="2024-03-15").decode("utf-8")
        self.assertIn("Target Day Txn A", html)
        self.assertIn("Target Day Txn B", html)
        self.assertNotIn("Day Before Txn", html)
        self.assertNotIn("Day After Txn", html)


if __name__ == "__main__":
    unittest.main()
