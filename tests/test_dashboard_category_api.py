"""Tests for category-filtered transactions API endpoint (/api/transactions)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expense_tracker.db import add_manual_transaction, export_rows, init_db
from expense_tracker.web import ExpenseHandler


class DummyHandler(ExpenseHandler):
    def __init__(self, db_path: Path):
        self._test_db_path = db_path
        self._sent_json = None
        self._sent_status = None

    def _db_path_for(self, username: str) -> Path:
        return self._test_db_path

    def respond_json(self, payload: dict, status: int = 200) -> None:
        self._sent_json = payload
        self._sent_status = status


class DashboardCategoryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db_path = self.tmp / "expenses_testuser.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

        # 1. Food transaction
        add_manual_transaction(
            self.conn,
            "2026-10-05",
            "Swiggy Delivery",
            Decimal("450.00"),
            "debit",
            "Food",
            "Personal",
            Decimal("1.0"),
        )
        # 2. Another Food transaction (split)
        add_manual_transaction(
            self.conn,
            "2026-10-10",
            "Dinner Outing",
            Decimal("1200.00"),
            "debit",
            "Food",
            "Shared",
            Decimal("0.5"),
        )
        # 3. Transport transaction
        add_manual_transaction(
            self.conn,
            "2026-10-07",
            "Uber Ride",
            Decimal("320.00"),
            "debit",
            "Transport",
            "Personal",
            Decimal("1.0"),
        )
        # 4. Food transaction in a different month (September)
        add_manual_transaction(
            self.conn,
            "2026-09-20",
            "Zomato Sept",
            Decimal("280.00"),
            "debit",
            "Food",
            "Personal",
            Decimal("1.0"),
        )
        # 5. Business transaction (should be excluded by default when category filtered)
        add_manual_transaction(
            self.conn,
            "2026-10-08",
            "Team Client Lunch",
            Decimal("1500.00"),
            "debit",
            "Food",
            "Business",
            Decimal("1.0"),
        )
        self.conn.close()

    def test_category_filter_october_food(self):
        handler = DummyHandler(self.db_path)
        params = {
            "start_date": ["2026-10-01"],
            "end_date": ["2026-10-31"],
            "category": ["Food"],
        }
        handler.handle_api_transactions("testuser", params)
        self.assertIsNotNone(handler._sent_json)
        res = handler._sent_json
        self.assertEqual(res["category"], "Food")
        # Should return 2 October Food items (excluding September and excluding Business)
        self.assertEqual(res["count"], 2)
        txns = res["transactions"]
        merchants = [t["description"] for t in txns]
        self.assertIn("Swiggy Delivery", merchants)
        self.assertIn("Dinner Outing", merchants)
        self.assertNotIn("Zomato Sept", merchants)
        self.assertNotIn("Team Client Lunch", merchants)
        self.assertNotIn("Uber Ride", merchants)

    def test_category_filter_with_include_business(self):
        handler = DummyHandler(self.db_path)
        params = {
            "start_date": ["2026-10-01"],
            "end_date": ["2026-10-31"],
            "category": ["Food"],
            "exclude_business": ["0"],
        }
        handler.handle_api_transactions("testuser", params)
        res = handler._sent_json
        self.assertEqual(res["count"], 3)
        merchants = [t["description"] for t in res["transactions"]]
        self.assertIn("Team Client Lunch", merchants)

    def test_category_filter_no_silent_capping(self):
        # Insert 60 entries to verify no silent cap of 50
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        for i in range(60):
            add_manual_transaction(
                conn,
                f"2026-10-{i % 28 + 1:02d}",
                f"Grocery Store {i}",
                Decimal("100.00"),
                "debit",
                "Groceries",
                "Personal",
                Decimal("1.0"),
            )
        conn.close()

        handler = DummyHandler(self.db_path)
        params = {
            "start_date": ["2026-10-01"],
            "end_date": ["2026-10-31"],
            "category": ["Groceries"],
        }
        handler.handle_api_transactions("testuser", params)
        res = handler._sent_json
        self.assertEqual(res["count"], 60)
        self.assertEqual(len(res["transactions"]), 60)


if __name__ == "__main__":
    unittest.main()
