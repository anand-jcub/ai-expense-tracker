"""FC-09: cloud snapshot glance uses the same dashboard payload owner."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from expense_tracker.cloud_sync import _looks_like_person, build_snapshot
from expense_tracker.db import add_manual_transaction, init_db
from expense_tracker.services import dashboard_summary_payload


class SnapshotGlanceTests(unittest.TestCase):
    def test_dashboard_matches_payload(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        db = tmp / "expenses_snaptest.db"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        add_manual_transaction(
            conn,
            "2026-08-01",
            "Zomato",
            Decimal("99"),
            "debit",
            "Food",
            "Personal",
            Decimal("1"),
        )
        conn.close()

        import expense_tracker.cloud_sync as cs

        old = cs._data_dir
        cs._data_dir = lambda: tmp
        try:
            snap = build_snapshot("snaptest")
        finally:
            cs._data_dir = old

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        live = dashboard_summary_payload(conn, exclude_business=True)
        conn.close()

        self.assertIn("by_category", snap["dashboard"])
        self.assertEqual(snap["dashboard"]["period_debits"], live["period_debits"])
        self.assertEqual(snap["categories"][0], "Food")
        self.assertNotIn("raw_sql", snap)
        self.assertIn("people", snap)

    def test_business_exclusion_in_snapshot(self) -> None:
        """FC-02 & FC-09: transactions with category=Business or expense_type=Business are excluded."""
        tmp = Path(tempfile.mkdtemp())
        db = tmp / "expenses_biztest.db"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        # 1. Normal Food Personal
        add_manual_transaction(
            conn, "2026-08-01", "Restaurant", Decimal("500"), "debit", "Food", "Personal", Decimal("1")
        )
        # 2. Category=Business, Type=Personal (common in imports)
        add_manual_transaction(
            conn, "2026-08-02", "Office Supplies", Decimal("2000"), "debit", "Business", "Personal", Decimal("1")
        )
        # 3. Category=Transport, Type=Business
        add_manual_transaction(
            conn, "2026-08-03", "Cab for Client", Decimal("400"), "debit", "Transport", "Business", Decimal("1")
        )
        conn.close()

        import expense_tracker.cloud_sync as cs
        old = cs._data_dir
        cs._data_dir = lambda: tmp
        try:
            snap = build_snapshot("biztest")
        finally:
            cs._data_dir = old

        dash = snap["dashboard"]
        # Default dashboard excludes business
        cats = {c["category"]: c["amount"] for c in dash["by_category"]}
        self.assertIn("Food", cats)
        self.assertNotIn("Business", cats)
        self.assertNotIn("Transport", cats)
        self.assertEqual(dash["period_debits"], 500.0)


if __name__ == "__main__":
    unittest.main()

