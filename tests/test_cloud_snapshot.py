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

    def test_person_vs_merchant_names(self) -> None:
        self.assertTrue(_looks_like_person("Highnes"))
        self.assertTrue(_looks_like_person("Anupriya"))
        self.assertFalse(_looks_like_person("Cr Google Utib"))
        self.assertFalse(_looks_like_person("Branch"))
        self.assertFalse(_looks_like_person("Kerala Yesb Chalokeral Payme"))


if __name__ == "__main__":
    unittest.main()
