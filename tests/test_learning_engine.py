from __future__ import annotations

import sqlite3
import unittest
import json
from decimal import Decimal

from expense_tracker.db import init_db, add_manual_transaction
from expense_tracker.relationship_engine import (
    detect_and_update_suggestions,
    get_suggested_relationships,
    get_active_relationships,
    approve_relationship,
    reject_relationship,
    ignore_relationship,
    add_custom_relationship
)
from expense_tracker.learning_engine import LearningStatistics


class LearningEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_ignore_action_suppression(self) -> None:
        # Create matching transactions
        d_id = add_manual_transaction(
            self.conn,
            "2026-07-01",
            "Refundable Purchase XYZ",
            Decimal("350.00"),
            "debit",
            "Shopping",
            "Shopping",
            Decimal("1.00"),
            learn=False
        )
        c_id = add_manual_transaction(
            self.conn,
            "2026-07-02",
            "XYZ refund credited",
            Decimal("350.00"),
            "credit",
            "Shopping",
            "Shopping",
            Decimal("1.00"),
            learn=False
        )
        
        # Suggestions should detect a Refund
        detect_and_update_suggestions(self.conn)
        suggs = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs), 1)
        self.assertEqual(suggs[0]["relationship_type"], "Refund")
        rel_id = suggs[0]["relationship_id"]
        
        # Verify evidence_json is stored and structured
        self.assertIn("signals", suggs[0]["evidence"])
        self.assertIn("rule_scores", suggs[0]["evidence"])
        self.assertTrue(suggs[0]["evidence"]["signals"]["same_amount"])
        
        # Ignore the suggestion
        ignore_relationship(self.conn, rel_id)
        
        # Re-detecting suggestions should now exclude this pair
        detect_and_update_suggestions(self.conn)
        self.assertEqual(len(get_suggested_relationships(self.conn)), 0)
        
        # Ignore should show in feedback and statistics
        stats = LearningStatistics.get_aggregate_stats(self.conn)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["relationship_type"], "Refund")
        self.assertEqual(stats[0]["ignores"], 1)
        self.assertEqual(stats[0]["rejections"], 0) # Ignored is NOT a rejection

    def test_dynamic_rejection_suppression(self) -> None:
        # Pair 1: Debit & Credit
        d_id1 = add_manual_transaction(
            self.conn, "2026-07-01", "Amzn buy", Decimal("1500.00"), "debit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        c_id1 = add_manual_transaction(
            self.conn, "2026-07-02", "Amzn return", Decimal("1500.00"), "credit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        
        detect_and_update_suggestions(self.conn)
        suggs = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs), 1)
        rel_id = suggs[0]["relationship_id"]
        
        # Reject it
        reject_relationship(self.conn, rel_id)
        
        # Pair 2: Similar transactions with same merchant keys
        d_id2 = add_manual_transaction(
            self.conn, "2026-07-05", "Amzn buy", Decimal("800.00"), "debit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        c_id2 = add_manual_transaction(
            self.conn, "2026-07-06", "Amzn return", Decimal("800.00"), "credit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        
        # Re-detect suggestions. The feedback loop should dynamically suppress Refund suggestions for this merchant pair
        detect_and_update_suggestions(self.conn)
        suggs2 = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs2), 0) # Suppressed successfully!

    def test_dynamic_approval_boosting(self) -> None:
        # Pair 1: Approved
        d_id1 = add_manual_transaction(
            self.conn, "2026-07-01", "SBI HDFC transfer", Decimal("2000.00"), "debit", "Other", "Other", Decimal("1.00"), learn=False
        )
        c_id1 = add_manual_transaction(
            self.conn, "2026-07-02", "SBI arrival", Decimal("2000.00"), "credit", "Other", "Other", Decimal("1.00"), learn=False
        )
        
        detect_and_update_suggestions(self.conn)
        suggs = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs), 1)
        base_confidence = suggs[0]["confidence"]
        rel_id = suggs[0]["relationship_id"]
        
        # Approve it
        approve_relationship(self.conn, rel_id)
        
        # Pair 2: Next transfer
        d_id2 = add_manual_transaction(
            self.conn, "2026-07-05", "SBI HDFC transfer", Decimal("4000.00"), "debit", "Other", "Other", Decimal("1.00"), learn=False
        )
        c_id2 = add_manual_transaction(
            self.conn, "2026-07-06", "SBI arrival", Decimal("4000.00"), "credit", "Other", "Other", Decimal("1.00"), learn=False
        )
        
        # The next matching pair should get a dynamic boost
        detect_and_update_suggestions(self.conn)
        suggs2 = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs2), 1)
        boosted_confidence = suggs2[0]["confidence"]
        
        self.assertGreater(boosted_confidence, base_confidence)
        self.assertEqual(boosted_confidence, base_confidence + (1.0 - base_confidence) * 0.5)

    def test_edited_suggestion_feedback(self) -> None:
        # Debit & Credit
        d_id = add_manual_transaction(
            self.conn, "2026-07-01", "Merchant Refundable", Decimal("100.00"), "debit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        c_id = add_manual_transaction(
            self.conn, "2026-07-02", "Merchant Refund Credited", Decimal("100.00"), "credit", "Shopping", "Shopping", Decimal("1.00"), learn=False
        )
        
        detect_and_update_suggestions(self.conn)
        suggs = get_suggested_relationships(self.conn)
        self.assertEqual(len(suggs), 1)
        rel_id = suggs[0]["relationship_id"]
        
        # User edits it to Cashback instead of Refund
        members = [
            {"transaction_id": d_id, "role": "purchase", "amount": Decimal("100.00")},
            {"transaction_id": c_id, "role": "cashback", "amount": Decimal("100.00")}
        ]
        add_custom_relationship(self.conn, "Cashback", members, "Correction", prediction_id=rel_id)
        
        # Verify feedback entries
        feedbacks = self.conn.execute("select * from relationship_feedback").fetchall()
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0]["action"], "edited")
        self.assertEqual(feedbacks[0]["predicted_type"], "Refund")
        self.assertEqual(feedbacks[0]["actual_type"], "Cashback")
        keys = json.loads(feedbacks[0]["merchant_keys_json"])
        self.assertIn("merchant refundable", keys)
        self.assertIn("merchant refund credited", keys)

    def test_multi_transaction_installments(self) -> None:
        # Create 1 Debit loan to Rahul: Rs 10000
        d_id = add_manual_transaction(
            self.conn, "2026-07-01", "Loan to Rahul", Decimal("10000.00"), "debit", "Loan", "Loan", Decimal("1.00"), learn=False
        )
        # Create 3 credit repayments from Rahul over next few weeks: Rs 3000, 3000, 4000
        c1_id = add_manual_transaction(
            self.conn, "2026-07-05", "Rahul repayment 1", Decimal("3000.00"), "credit", "Loan", "Loan", Decimal("1.00"), learn=False
        )
        c2_id = add_manual_transaction(
            self.conn, "2026-07-10", "Rahul repayment 2", Decimal("3000.00"), "credit", "Loan", "Loan", Decimal("1.00"), learn=False
        )
        c3_id = add_manual_transaction(
            self.conn, "2026-07-15", "Rahul repayment 3", Decimal("4000.00"), "credit", "Loan", "Loan", Decimal("1.00"), learn=False
        )
        
        detect_and_update_suggestions(self.conn)
        suggs = get_suggested_relationships(self.conn)
        
        self.assertEqual(len(suggs), 1)
        sug = suggs[0]
        self.assertEqual(sug["relationship_type"], "Loan Returned")
        
        member_ids = [m["transaction_id"] for m in sug["members"]]
        self.assertEqual(len(member_ids), 4)
        self.assertIn(d_id, member_ids)
        self.assertIn(c1_id, member_ids)
        self.assertIn(c2_id, member_ids)
        self.assertIn(c3_id, member_ids)
        
        # Approve it and check that feedback has all 4 merchant keys
        approve_relationship(self.conn, sug["relationship_id"])
        
        feedbacks = self.conn.execute("select * from relationship_feedback").fetchall()
        self.assertEqual(len(feedbacks), 1)
        self.assertEqual(feedbacks[0]["action"], "approved")
        
        keys = json.loads(feedbacks[0]["merchant_keys_json"])
        self.assertEqual(len(keys), 2)
        self.assertIn("loan rahul", keys)
        self.assertIn("rahul repayment", keys)


if __name__ == "__main__":
    unittest.main()
