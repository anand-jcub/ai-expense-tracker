from __future__ import annotations

import sqlite3
import unittest
from decimal import Decimal

from expense_tracker.classifier import (
    DEFAULT_SPLIT_RATIO,
    classify_transaction,
    effective_share,
    normalize_merchant,
    rule_match_score,
)
from expense_tracker.db import add_manual_transaction, init_db, import_transactions, review_transaction
from expense_tracker.sbi_pdf import parse_table_rows
from expense_tracker.services import (
    credit_debit_totals,
    dashboard_totals,
    expenses_by_category,
    filter_editable_rows,
    filter_dashboard_rows,
    filter_review_rows,
    filter_transactions_by_text,
    people_from_split_ratio,
    sort_review_rows,
    split_ratio_from_people,
)
from expense_tracker.templates import (
    edit_batch_actions,
    review_batch_actions,
    render_edit_rows,
    render_review_rows,
)


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma foreign_keys = on")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_seeded_classifier(self) -> None:
        merchant = normalize_merchant("UPI/SWIGGY/Pay/123456789")
        result = classify_transaction(self.conn, merchant)
        self.assertEqual(result.category, "Food")
        self.assertEqual(result.status, "auto")

    def test_unknown_needs_review_then_learns(self) -> None:
        rows = [
            {
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "description": "UPI/Lulu Hypermarket/98765",
                "reference": "98765",
                "debit": Decimal("1200.00"),
                "credit": Decimal("0"),
                "balance": Decimal("50000.00"),
                "raw_text": "sample",
            }
        ]
        _, inserted, _ = import_transactions(self.conn, "sample.pdf", "abc123", rows, True)
        self.assertEqual(inserted, 1)
        tx = self.conn.execute("select id from transactions").fetchone()
        pending = self.conn.execute("select status from classifications").fetchone()
        self.assertEqual(pending["status"], "needs_review")
        review_transaction(self.conn, tx["id"], "Groceries", "Shared", Decimal("0.50"), learn=True)
        rule = self.conn.execute("select * from merchant_rules").fetchone()
        self.assertEqual(rule["category"], "Groceries")
        classification = self.conn.execute("select * from classifications").fetchone()
        self.assertEqual(Decimal(str(classification["my_share"])), Decimal("600.00"))

    def test_learning_sweeps_matching_pending_variants(self) -> None:
        rows = [
            {
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "description": "UPI/BB NOW/Order123",
                "reference": "123",
                "debit": Decimal("250.00"),
                "credit": Decimal("0"),
                "balance": Decimal("50000.00"),
                "raw_text": "sample 1",
            },
            {
                "txn_date": "2026-07-02",
                "value_date": "2026-07-02",
                "description": "UPI/BBNOW/Order456",
                "reference": "456",
                "debit": Decimal("300.00"),
                "credit": Decimal("0"),
                "balance": Decimal("49700.00"),
                "raw_text": "sample 2",
            },
        ]
        import_transactions(self.conn, "bbnow.pdf", "bbnow123", rows, True)
        pending_before = self.conn.execute(
            "select count(*) as count from classifications where status = 'needs_review'"
        ).fetchone()
        self.assertEqual(pending_before["count"], 2)

        first = self.conn.execute(
            "select id from transactions where description like '%BB NOW%'"
        ).fetchone()
        review_transaction(self.conn, first["id"], "Groceries", "Personal", Decimal("1"), learn=True)

        pending_after = self.conn.execute(
            "select count(*) as count from classifications where status = 'needs_review'"
        ).fetchone()
        self.assertEqual(pending_after["count"], 0)
        learned = self.conn.execute(
            """
            select c.category, c.status
            from transactions t
            join classifications c on c.transaction_id = t.id
            where t.description like '%BBNOW%'
            """
        ).fetchone()
        self.assertEqual(learned["category"], "Groceries")
        self.assertEqual(learned["status"], "auto")

    def test_effective_share(self) -> None:
        self.assertEqual(effective_share(Decimal("-100"), "Shared", Decimal("0.4")), Decimal("40.00"))
        self.assertEqual(effective_share(Decimal("-100"), "Transfer", Decimal("0.5")), Decimal("0.00"))
        # split_ratio now applies to any expense type, not just Shared
        self.assertEqual(effective_share(Decimal("-100"), "Personal", Decimal("0.5")), Decimal("50.00"))
        self.assertEqual(effective_share(Decimal("-100"), "Personal", Decimal("1")), Decimal("100.00"))

    def test_rule_matching_handles_spacing_variants(self) -> None:
        self.assertGreaterEqual(rule_match_score("bb now", "bbnow"), Decimal("0.82"))
        self.assertGreaterEqual(rule_match_score("mathew", "mathew jose"), Decimal("0.82"))
        # Should not match on a single shared token when distinct tokens exist on both sides
        self.assertLess(rule_match_score("sujith sbin sujithsugu", "ranjima sbin"), Decimal("0.80"))
        self.assertLess(rule_match_score("anil kumar", "vijay kumar shop"), Decimal("0.80"))

    def test_parse_sbi_table_rows(self) -> None:
        table = [
            [
                ["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],
                ["01/07/2026", "01/07/2026", "UPI/SWIGGY/ORDER", "123", "450.00", "", "10,000.00"],
                ["02/07/2026", "02/07/2026", "NEFT Salary", "456", "", "50,000.00", "60,000.00"],
            ]
        ]
        rows = parse_table_rows(table)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["txn_date"], "2026-07-01")
        self.assertEqual(rows[0]["debit"], Decimal("450.00"))
        self.assertEqual(rows[1]["credit"], Decimal("50000.00"))

    def test_review_row_shows_credit_amount(self) -> None:
        html = render_review_rows(
            [
                {
                    "id": 1,
                    "txn_date": "2026-07-02",
                    "merchant_display": "Salary",
                    "description": "NEFT Salary",
                    "amount_signed": Decimal("50000.00"),
                    "category": None,
                    "expense_type": "Personal",
                    "split_ratio": Decimal("0.50"),
                }
            ]
        )
        self.assertIn("+ ₹50,000.00", html)
        self.assertIn('name="split_people_1"', html)
        self.assertIn("<span>People</span>", html)
        self.assertIn('value="1"', html)
        self.assertIn('name="learn_1"', html)
        self.assertNotIn('name="learn_1" checked', html)
        self.assertNotIn('type="submit"', html)
        self.assertNotIn("₹0.00</td>", html)

    def test_review_batch_has_single_confirm_button(self) -> None:
        html = render_review_rows(
            [
                {
                    "id": 1,
                    "txn_date": "2026-07-02",
                    "merchant_display": "Salary",
                    "description": "NEFT Salary",
                    "amount_signed": Decimal("50000.00"),
                    "category": None,
                    "expense_type": "Personal",
                    "split_ratio": Decimal("1"),
                },
                {
                    "id": 2,
                    "txn_date": "2026-07-03",
                    "merchant_display": "Lulu",
                    "description": "UPI Lulu",
                    "amount_signed": Decimal("-1200.00"),
                    "category": None,
                    "expense_type": "Personal",
                    "split_ratio": Decimal("1"),
                },
            ]
        ) + review_batch_actions([{"id": 1}, {"id": 2}])
        self.assertEqual(html.count('type="submit"'), 1)
        self.assertIn("Confirm changes", html)

    def test_review_rows_can_be_sorted_by_date(self) -> None:
        rows = [
            {"id": 1, "txn_date": "2026-07-01"},
            {"id": 2, "txn_date": "2026-07-03"},
            {"id": 3, "txn_date": "2026-07-02"},
        ]
        newest = sort_review_rows(rows, "newest")
        oldest = sort_review_rows(rows, "oldest")
        self.assertEqual([row["id"] for row in newest], [2, 3, 1])
        self.assertEqual([row["id"] for row in oldest], [1, 3, 2])

        # Transactions with a matched rule should be placed last
        rows_with_rules = [
            {"id": 1, "txn_date": "2026-07-01", "rule_id": 8},
            {"id": 2, "txn_date": "2026-07-03", "rule_id": None},
            {"id": 3, "txn_date": "2026-07-02", "rule_id": None},
        ]
        newest_rules = sort_review_rows(rows_with_rules, "newest")
        self.assertEqual([row["id"] for row in newest_rules], [2, 3, 1])

    def test_review_rows_can_be_searched(self) -> None:
        rows = [
            {
                "id": 1,
                "txn_date": "2026-07-01",
                "merchant_display": "Swiggy",
                "description": "UPI Swiggy Order",
                "category": None,
                "expense_type": "Personal",
                "amount_signed": Decimal("-450"),
                "debit": Decimal("450"),
                "credit": Decimal("0"),
            },
            {
                "id": 2,
                "txn_date": "2026-07-02",
                "merchant_display": "Salary",
                "description": "NEFT Salary",
                "category": None,
                "expense_type": "Personal",
                "amount_signed": Decimal("50000"),
                "debit": Decimal("0"),
                "credit": Decimal("50000"),
            },
        ]
        self.assertEqual([row["id"] for row in filter_review_rows(rows, "swiggy")], [1])
        self.assertEqual([row["id"] for row in filter_review_rows(rows, "50000")], [2])
        self.assertEqual([row["id"] for row in filter_review_rows(rows, "")], [1, 2])

    def test_classified_rows_can_be_searched_for_editing(self) -> None:
        rows = [
            {
                "id": 1,
                "txn_date": "2026-07-01",
                "merchant_display": "Swiggy",
                "description": "UPI Swiggy Order",
                "category": "Food",
                "expense_type": "Personal",
                "status": "auto",
                "notes": "",
                "amount_signed": Decimal("-450"),
                "debit": Decimal("450"),
                "credit": Decimal("0"),
            },
            {
                "id": 2,
                "txn_date": "2026-07-02",
                "merchant_display": "Lulu",
                "description": "UPI Lulu",
                "category": None,
                "expense_type": "Personal",
                "status": "needs_review",
                "notes": "",
                "amount_signed": Decimal("-1200"),
                "debit": Decimal("1200"),
                "credit": Decimal("0"),
            },
            {
                "id": 3,
                "txn_date": "2026-07-03",
                "merchant_display": "Netflix",
                "description": "Card Netflix",
                "category": "Subscription",
                "expense_type": "Personal",
                "status": "reviewed",
                "notes": "family plan",
                "amount_signed": Decimal("-499"),
                "debit": Decimal("499"),
                "credit": Decimal("0"),
            },
        ]
        self.assertEqual([row["id"] for row in filter_editable_rows(rows, "")], [1, 3])
        self.assertEqual([row["id"] for row in filter_editable_rows(rows, "family")], [3])

    def test_edit_rows_render_current_values_and_single_save_button(self) -> None:
        rows = [
            {
                "id": 9,
                "txn_date": "2026-07-02",
                "merchant_display": "Swiggy",
                "description": "UPI Swiggy Order",
                "amount_signed": Decimal("-450.00"),
                "category": "Food",
                "expense_type": "Shared",
                "split_ratio": Decimal("0.50"),
                "status": "auto",
                "notes": "dinner split",
            }
        ]
        html = render_edit_rows(rows) + edit_batch_actions(rows)
        self.assertIn('name="edit_ids" value="9"', html)
        self.assertIn('name="edit_category_9"', html)
        self.assertIn('value="Food" selected', html)
        self.assertIn('name="edit_expense_type_9"', html)
        self.assertIn('name="edit_split_people_9"', html)
        self.assertIn('value="2"', html)
        self.assertIn('name="edit_notes_9" value="dinner split"', html)
        self.assertIn('name="edit_learn_9"', html)
        self.assertNotIn('name="edit_learn_9" checked', html)
        self.assertEqual(html.count('type="submit"'), 1)
        self.assertIn("Save classification edits", html)

    def test_auto_classification_can_be_corrected_without_changing_raw_transaction(self) -> None:
        rows = [
            {
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "description": "UPI/SWIGGY/ORDER",
                "reference": "123",
                "debit": Decimal("450.00"),
                "credit": Decimal("0"),
                "balance": Decimal("50000.00"),
                "raw_text": "sample",
            }
        ]
        import_transactions(self.conn, "swiggy.pdf", "swiggy123", rows, True)
        tx = self.conn.execute("select id, description from transactions").fetchone()
        review_transaction(
            self.conn,
            tx["id"],
            "Business",
            "Business",
            Decimal("1"),
            "client meal",
            learn=False,
        )
        stored = self.conn.execute(
            """
            select t.description, c.category, c.expense_type, c.status, c.notes
            from transactions t
            join classifications c on c.transaction_id = t.id
            where t.id = ?
            """,
            (tx["id"],),
        ).fetchone()
        self.assertEqual(stored["description"], "UPI/SWIGGY/ORDER")
        self.assertEqual(stored["category"], "Business")
        self.assertEqual(stored["expense_type"], "Business")
        self.assertEqual(stored["status"], "reviewed")
        self.assertEqual(stored["notes"], "client meal")

    def test_manual_debit_transaction_is_stored_and_classified(self) -> None:
        transaction_id = add_manual_transaction(
            self.conn,
            "2026-07-03",
            "Cash dinner with friends",
            Decimal("1000.00"),
            "debit",
            "Food",
            "Shared",
            split_ratio_from_people("2"),
            "manual cash",
            learn=False,
        )
        stored = self.conn.execute(
            """
            select t.txn_date, t.description, t.debit, t.credit, t.amount_signed,
                   t.raw_text, c.category, c.expense_type, c.split_ratio, c.my_share,
                   c.status, c.notes
            from transactions t
            join classifications c on c.transaction_id = t.id
            where t.id = ?
            """,
            (transaction_id,),
        ).fetchone()
        self.assertEqual(stored["txn_date"], "2026-07-03")
        self.assertEqual(stored["description"], "Cash dinner with friends")
        self.assertEqual(Decimal(str(stored["debit"])), Decimal("1000.00"))
        self.assertEqual(Decimal(str(stored["credit"])), Decimal("0"))
        self.assertEqual(Decimal(str(stored["amount_signed"])), Decimal("-1000.00"))
        self.assertIn("Manual transaction", stored["raw_text"])
        self.assertEqual(stored["category"], "Food")
        self.assertEqual(stored["expense_type"], "Shared")
        self.assertEqual(Decimal(str(stored["split_ratio"])), Decimal("0.5"))
        self.assertEqual(Decimal(str(stored["my_share"])), Decimal("500.00"))
        self.assertEqual(stored["status"], "reviewed")
        self.assertEqual(stored["notes"], "manual cash")

    def test_manual_credit_transaction_has_no_expense_share(self) -> None:
        transaction_id = add_manual_transaction(
            self.conn,
            "2026-07-03",
            "Friend settlement highnes",
            Decimal("500.00"),
            "credit",
            "Transfer",
            "Transfer",
            split_ratio_from_people("1"),
            learn=False,
        )
        stored = self.conn.execute(
            """
            select t.debit, t.credit, t.amount_signed, c.category, c.expense_type, c.my_share
            from transactions t
            join classifications c on c.transaction_id = t.id
            where t.id = ?
            """,
            (transaction_id,),
        ).fetchone()
        self.assertEqual(Decimal(str(stored["debit"])), Decimal("0"))
        self.assertEqual(Decimal(str(stored["credit"])), Decimal("500.00"))
        self.assertEqual(Decimal(str(stored["amount_signed"])), Decimal("500.00"))
        self.assertEqual(stored["category"], "Transfer")
        self.assertEqual(stored["expense_type"], "Transfer")
        self.assertEqual(Decimal(str(stored["my_share"])), Decimal("0.00"))

    def test_transactions_can_be_searched_by_person_text_case_insensitive(self) -> None:
        rows = [
            {
                "id": 1,
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "merchant_display": "Highnes",
                "description": "UPI/HIGHNES/Food split",
                "reference": "A1",
                "raw_text": "UPI HIGHNES Food split",
                "category": "Food",
                "expense_type": "Shared",
                "amount_signed": Decimal("-450"),
                "debit": Decimal("450"),
                "credit": Decimal("0"),
            },
            {
                "id": 2,
                "txn_date": "2026-07-02",
                "value_date": "2026-07-02",
                "merchant_display": "Highnes",
                "description": "Credit from highnes",
                "reference": "A2",
                "raw_text": "Credit from highnes",
                "category": "Transfer",
                "expense_type": "Transfer",
                "amount_signed": Decimal("200"),
                "debit": Decimal("0"),
                "credit": Decimal("200"),
            },
            {
                "id": 3,
                "txn_date": "2026-07-03",
                "value_date": "2026-07-03",
                "merchant_display": "Other",
                "description": "Different person",
                "reference": "A3",
                "raw_text": "Different person",
                "category": "Other",
                "expense_type": "Other",
                "amount_signed": Decimal("-100"),
                "debit": Decimal("100"),
                "credit": Decimal("0"),
            },
        ]
        matches = filter_transactions_by_text(rows, "hiGhNes")
        self.assertEqual([row["id"] for row in matches], [1, 2])
        credits, debits = credit_debit_totals(matches)
        self.assertEqual(credits, Decimal("200"))
        self.assertEqual(debits, Decimal("450"))

    def test_dashboard_filters_period_business_and_split_expense_basis(self) -> None:
        rows = [
            {
                "id": 1,
                "txn_date": "2026-07-01",
                "category": "Food",
                "expense_type": "Shared",
                "debit": Decimal("1000"),
                "credit": Decimal("0"),
                "my_share": Decimal("500"),
            },
            {
                "id": 2,
                "txn_date": "2026-07-02",
                "category": "Business",
                "expense_type": "Business",
                "debit": Decimal("300"),
                "credit": Decimal("0"),
                "my_share": Decimal("300"),
            },
            {
                "id": 3,
                "txn_date": "2026-07-03",
                "category": "Salary",
                "expense_type": "Personal",
                "debit": Decimal("0"),
                "credit": Decimal("2000"),
                "my_share": Decimal("0"),
            },
        ]
        period = filter_dashboard_rows(rows, "2026-07-01", "2026-07-02", exclude_business=True)
        self.assertEqual([row["id"] for row in period], [1])
        totals = dashboard_totals(period, use_my_share=True)
        self.assertEqual(totals["credit"], Decimal("0"))
        # Period debits is always the raw cash outflow (debit_total)
        self.assertEqual(totals["debit"], Decimal("1000"))
        self.assertEqual(totals["expense"], Decimal("500"))
        self.assertEqual(expenses_by_category(period, use_my_share=True), [("Food", Decimal("500"))])

    def test_people_count_converts_to_split_ratio(self) -> None:
        self.assertEqual(DEFAULT_SPLIT_RATIO, Decimal("1.00"))
        self.assertEqual(split_ratio_from_people(""), Decimal("1"))
        self.assertEqual(split_ratio_from_people("1"), Decimal("1"))
        self.assertEqual(split_ratio_from_people("2"), Decimal("0.5"))
        self.assertEqual(split_ratio_from_people("4"), Decimal("0.25"))
        self.assertEqual(people_from_split_ratio(None), 1)
        self.assertEqual(people_from_split_ratio(Decimal("1")), 1)
        self.assertEqual(people_from_split_ratio(Decimal("0.5")), 2)
        self.assertEqual(people_from_split_ratio(Decimal("0.25")), 4)

    def test_shared_people_count_controls_my_share(self) -> None:
        rows = [
            {
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "description": "UPI/Lulu Hypermarket/98765",
                "reference": "98765",
                "debit": Decimal("1000.00"),
                "credit": Decimal("0"),
                "balance": Decimal("50000.00"),
                "raw_text": "sample",
            }
        ]
        import_transactions(self.conn, "shared.pdf", "shared123", rows, True)
        tx = self.conn.execute("select id from transactions").fetchone()

        review_transaction(self.conn, tx["id"], "Groceries", "Shared", split_ratio_from_people("1"))
        one_person = self.conn.execute("select split_ratio, my_share from classifications").fetchone()
        self.assertEqual(Decimal(str(one_person["split_ratio"])), Decimal("1"))
        self.assertEqual(Decimal(str(one_person["my_share"])), Decimal("1000.00"))

        review_transaction(self.conn, tx["id"], "Groceries", "Shared", split_ratio_from_people("2"))
        two_people = self.conn.execute("select split_ratio, my_share from classifications").fetchone()
        self.assertEqual(Decimal(str(two_people["split_ratio"])), Decimal("0.5"))
        self.assertEqual(Decimal(str(two_people["my_share"])), Decimal("500.00"))

    def test_transaction_connection_offsets_and_suggestions(self) -> None:
        # Import a debit transaction: Send Ananthu 1500
        debit_rows = [
            {
                "txn_date": "2026-07-01",
                "value_date": "2026-07-01",
                "description": "UPI/DR/123/ANANTHU/SBIN/ananthu/UPI",
                "debit": Decimal("1500.00"),
                "credit": Decimal("0"),
                "balance": Decimal("4000.00"),
                "raw_text": "sample",
            }
        ]
        import_transactions(self.conn, "statement1.pdf", "hash1", debit_rows, True)
        
        # Import a credit transaction: Ananthu sends 1500 back
        credit_rows = [
            {
                "txn_date": "2026-07-02",
                "value_date": "2026-07-02",
                "description": "UPI/CR/124/ANANTHU/SBIN/ananthu/UPI",
                "debit": Decimal("0"),
                "credit": Decimal("1500.00"),
                "balance": Decimal("5500.00"),
                "raw_text": "sample2",
            }
        ]
        import_transactions(self.conn, "statement2.pdf", "hash2", credit_rows, True)
        
        # Query linkables and suggestions
        from expense_tracker.connections import get_connection_suggestions
        from expense_tracker.db import (
            add_transaction_link,
            remove_transaction_link,
            get_transaction_links,
            dashboard_data,
        )
        
        suggestions = get_connection_suggestions(self.conn)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["debit_merchant"], "Dr Ananthu Ananthu")
        self.assertEqual(suggestions[0]["credit_merchant"], "Cr Ananthu Ananthu")
        self.assertEqual(suggestions[0]["suggested_amount"], 1500.0)
        
        # Get transaction IDs
        txs = self.conn.execute("select id, debit, credit from transactions").fetchall()
        debit_id = [t["id"] for t in txs if t["debit"] > 0][0]
        credit_id = [t["id"] for t in txs if t["credit"] > 0][0]
        
        # Connect them
        link_id = add_transaction_link(self.conn, debit_id, credit_id, Decimal("1500.00"))
        
        # Suggestions should now be empty because both are fully linked
        self.assertEqual(len(get_connection_suggestions(self.conn)), 0)
        
        # Check active connections
        links = get_transaction_links(self.conn)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["link_id"], link_id)
        
        # Check dashboard aggregates: should offset debit and credit to 0!
        data = dashboard_data(self.conn)
        from expense_tracker.services import filter_dashboard_rows, dashboard_totals
        period_rows = filter_dashboard_rows(data["transactions"])
        totals = dashboard_totals(period_rows)
        self.assertEqual(totals["debit"], Decimal("0"))
        self.assertEqual(totals["credit"], Decimal("0"))
        self.assertEqual(totals["expense"], Decimal("0"))
        
        # Remove connection
        remove_transaction_link(self.conn, link_id)
        self.assertEqual(len(get_transaction_links(self.conn)), 0)
        
        # Re-check aggregates: should be back to 1500
        data2 = dashboard_data(self.conn)
        period_rows2 = filter_dashboard_rows(data2["transactions"])
        totals2 = dashboard_totals(period_rows2)
        self.assertEqual(totals2["debit"], Decimal("1500.00"))
        self.assertEqual(totals2["credit"], Decimal("1500.00"))


if __name__ == "__main__":
    unittest.main()
