from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from expense_tracker import auth, db, services, web


class SharingTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory for test databases
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)
        
        # Patch the constants to use our temporary folder
        self.patcher1 = patch("expense_tracker.auth.USERS_DB_PATH", self.test_dir_path / "test_users.db")
        self.patcher2 = patch("expense_tracker.auth.DATA_DIR", self.test_dir_path)
        self.patcher3 = patch("expense_tracker.db.DATA_DIR", self.test_dir_path)
        self.patcher4 = patch("expense_tracker.db.DB_PATH", self.test_dir_path / "test_expenses.db")
        
        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()
        
        # Reset request context database path
        if hasattr(db.request_context, "db_path"):
            del db.request_context.db_path

    def tearDown(self) -> None:
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()
        
        if hasattr(db.request_context, "db_path"):
            del db.request_context.db_path
            
        self.test_dir.cleanup()

    def test_sharing_and_replication_flow(self) -> None:
        # 1. Register Alice and Bob
        auth.register_user("alice", "password123")
        auth.register_user("bob", "password456")
        
        usernames = auth.get_all_usernames()
        self.assertIn("alice", usernames)
        self.assertIn("bob", usernames)

        # 2. Setup Alice's database and insert a transaction
        alice_db_path = self.test_dir_path / "expenses_alice.db"
        db.request_context.db_path = alice_db_path
        
        conn_alice = db.connect()
        try:
            # Check schema update
            cursor = conn_alice.execute("pragma table_info(transactions)")
            cols = [col["name"] for col in cursor.fetchall()]
            self.assertIn("is_external", cols)
            self.assertIn("external_payer", cols)
            self.assertIn("shared_with", cols)

            # Insert an SBI import dummy
            import_id = db.get_or_create_shared_import(conn_alice)
            
            # Insert a grocery payment
            cursor = conn_alice.cursor()
            cursor.execute(
                """
                insert into transactions (
                    import_id, source_hash, txn_date, description, debit, credit, amount_signed, raw_text, merchant_key, merchant_display, created_at
                ) values (?, 'hash1', '2026-07-08', 'Swiggy Instamart Grocery', 1000.0, 0.0, -1000.0, 'raw swiggy', 'swiggy', 'Swiggy Instamart', '2026-07-08T12:00:00Z')
                """,
                (import_id,)
            )
            txn_id = cursor.lastrowid
            
            # Create classification
            conn_alice.execute(
                """
                insert into classifications (transaction_id, status, expense_type, updated_at)
                values (?, 'needs_review', 'Personal', '2026-07-08T12:00:00Z')
                """,
                (txn_id,)
            )
            conn_alice.commit()
            
            # 3. Call review_transaction to share it with Bob (2 people split -> 0.5 split ratio)
            # We mock the Handler current_user context
            mock_handler = MagicMock()
            mock_handler.current_user = "alice"
            
            db.review_transaction(
                conn_alice,
                transaction_id=txn_id,
                category="Groceries",
                expense_type="Shared",
                split_ratio=Decimal("0.5"),
                notes="Weekly groceries split",
                learn=False,
            )
            conn_alice.commit()
            
            # 4. Trigger replication manually (simulating web.py handler)
            web.ExpenseHandler.sync_shared_transaction(mock_handler, conn_alice, txn_id, "bob")
            conn_alice.commit()
            
        finally:
            conn_alice.close()
            
        # 5. Connect to Bob's database and verify replication
        bob_db_path = self.test_dir_path / "expenses_bob.db"
        db.request_context.db_path = bob_db_path
        
        conn_bob = db.connect()
        try:
            # Query replicated transaction
            row = conn_bob.execute(
                """
                select t.*, c.category, c.expense_type, c.split_ratio, c.my_share, c.notes
                from transactions t
                join classifications c on c.transaction_id = t.id
                where t.reference = ?
                """,
                ("shared_src:alice:1",)
            ).fetchone()
            
            self.assertIsNotNone(row)
            self.assertEqual(row["is_external"], 1)
            self.assertEqual(row["external_payer"], "alice")
            self.assertEqual(row["debit"], 1000.0)
            self.assertEqual(row["my_share"], 500.0)
            self.assertEqual(row["expense_type"], "Shared")
            self.assertIn("Shared by alice", row["notes"])
            
            # Check partner balances in Bob's DB
            # Bob has 1 external transaction shared by Alice (value 500.0)
            all_txs = conn_bob.execute(
                """
                select t.*, c.category, c.expense_type, c.split_ratio, c.my_share, c.notes
                from transactions t
                join classifications c on c.transaction_id = t.id
                """
            ).fetchall()
            
            balances = services.compute_partner_balances(all_txs, "bob")
            self.assertIn("alice", balances)
            self.assertEqual(balances["alice"]["you_owe"], Decimal("500.0"))
            self.assertEqual(balances["alice"]["owes_you"], Decimal("0"))
            self.assertEqual(balances["alice"]["net"], Decimal("-500.0")) # Bob owes Alice 500
            
        finally:
            conn_bob.close()
            
        # 6. Change Alice's transaction from Shared to Personal (should delete Bob's copy)
        db.request_context.db_path = alice_db_path
        conn_alice = db.connect()
        try:
            mock_handler = MagicMock()
            mock_handler.current_user = "alice"
            
            db.review_transaction(
                conn_alice,
                transaction_id=txn_id,
                category="Groceries",
                expense_type="Personal", # No longer shared!
                split_ratio=Decimal("1.0"),
                notes="Actually mine",
                learn=False,
            )
            conn_alice.commit()
            
            web.ExpenseHandler.sync_shared_transaction(mock_handler, conn_alice, txn_id, None)
            conn_alice.commit()
        finally:
            conn_alice.close()
            
        # 7. Connect to Bob's DB again and verify it has been deleted
        db.request_context.db_path = bob_db_path
        conn_bob = db.connect()
        try:
            row = conn_bob.execute("select id from transactions where reference = ?", ("shared_src:alice:1",)).fetchone()
            self.assertIsNone(row)
        finally:
            conn_bob.close()


if __name__ == "__main__":
    unittest.main()
