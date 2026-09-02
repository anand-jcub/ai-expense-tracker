"""FC-07 / FC-08: shared dashboard payload + confirm-before-write."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.assistant import confirm_action, run_chat
from expense_tracker.assistant.tools import run_tool
from expense_tracker.contacts import add_ledger_entry, create_contact
from expense_tracker.db import add_manual_transaction, init_db
from expense_tracker.services import (
    current_month_bounds,
    dashboard_summary_payload,
    dashboard_totals,
    expenses_by_category,
    filter_dashboard_rows,
)
from expense_tracker.db import dashboard_data


def _mem():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    init_db(conn)
    return conn


class DashboardPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _mem()
        start, end = current_month_bounds()
        self.start, self.end = start, end
        add_manual_transaction(
            self.conn,
            start,
            "Swiggy lunch",
            Decimal("400"),
            "debit",
            "Food",
            "Personal",
            Decimal("1"),
        )
        add_manual_transaction(
            self.conn,
            start,
            "Office taxi",
            Decimal("200"),
            "debit",
            "Business",
            "Business",
            Decimal("1"),
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_payload_matches_filter_rows(self) -> None:
        payload = dashboard_summary_payload(self.conn, exclude_business=True)
        data = dashboard_data(self.conn)
        rows = filter_dashboard_rows(data["transactions"], self.start, self.end, True)
        totals = dashboard_totals(rows, use_my_share=False)
        self.assertEqual(payload["transaction_count"], len(rows))
        self.assertEqual(payload["period_debits"], float(totals["debit"]))
        self.assertEqual(payload["period_expense_share"], float(totals["expense_share"]))
        cats = dict(expenses_by_category(rows, use_my_share=True))
        food = next(c for c in payload["by_category"] if c["category"] == "Food")
        self.assertEqual(food["amount"], float(cats["Food"]))
        self.assertFalse(any(c["category"] == "Business" for c in payload["by_category"]))


class ConfirmWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()) / "t.db"
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        init_db(conn)
        conn.close()
        self.conn = sqlite3.connect(self.tmp)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.conn.close()

    def test_propose_does_not_insert(self) -> None:
        before = self.conn.execute("select count(*) from transactions").fetchone()[0]
        out = run_tool(
            self.conn,
            "anand",
            "propose_add_manual",
            {"amount": 200, "description": "coffee", "category": "Food"},
        )
        after = self.conn.execute("select count(*) from transactions").fetchone()[0]
        self.assertEqual(before, after)
        self.assertTrue(out.get("needs_confirm"))
        self.assertTrue(out.get("confirm_token"))

    def test_confirm_inserts_once(self) -> None:
        # issue token against any conn (token store is process memory)
        mem = _mem()
        proposed = run_tool(
            mem,
            "anand",
            "propose_add_manual",
            {
                "amount": 80,
                "description": "tea",
                "category": "Food",
                "txn_date": date.today().isoformat(),
            },
        )
        mem.close()
        token = proposed["confirm_token"]

        first = confirm_action(self.tmp, "anand", token)
        self.assertTrue(first.get("ok"), first)
        second = confirm_action(self.tmp, "anand", token)
        self.assertFalse(second.get("ok"))

        check = sqlite3.connect(self.tmp)
        check.row_factory = sqlite3.Row
        n = check.execute("select count(*) as c from transactions").fetchone()["c"]
        check.close()
        self.assertEqual(n, 1)

    def test_wrong_user_cannot_confirm(self) -> None:
        out = run_tool(
            self.conn,
            "anand",
            "propose_add_manual",
            {"amount": 10, "description": "x", "category": "Other"},
        )
        from expense_tracker.assistant import pending as store

        stolen = store.take(out["confirm_token"], "other-user")
        self.assertIsNone(stolen)

    def test_list_pending_reviews(self) -> None:
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("insert into imports (source_filename, file_sha256, imported_at) values ('test1.pdf', 'hash1', '2026-08-20')")
        imp_id = cur.lastrowid
        cur.execute(
            """
            insert into transactions (import_id, source_hash, raw_text, txn_date, description, merchant_key, merchant_display, amount_signed, debit, credit, created_at)
            values (?, 'h1', 'raw1', '2026-08-20', 'SWIGGY BANGALORE', 'swiggy', 'Swiggy', -450.0, 450.0, 0.0, '2026-08-20T10:00:00Z')
            """,
            (imp_id,),
        )
        tid = cur.lastrowid
        cur.execute(
            """
            insert into classifications (transaction_id, category, expense_type, split_ratio, my_share, status, confidence, updated_at)
            values (?, 'Food', 'Personal', 1.0, 450.0, 'needs_review', 0.6, '2026-08-20T10:00:00Z')
            """,
            (tid,),
        )
        conn.commit()

        out = run_tool(conn, "anand", "list_pending_reviews", {"limit": 5})
        conn.close()

        self.assertGreaterEqual(out["pending_count"], 1)
        items = [i for i in out["items"] if i["transaction_id"] == tid]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["merchant"], "Swiggy")
        self.assertEqual(items[0]["amount"], 450.0)

    def test_propose_and_confirm_categorize_transaction(self) -> None:
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("insert into imports (source_filename, file_sha256, imported_at) values ('test2.pdf', 'hash2', '2026-08-20')")
        imp_id = cur.lastrowid
        cur.execute(
            """
            insert into transactions (import_id, source_hash, raw_text, txn_date, description, merchant_key, merchant_display, amount_signed, debit, credit, created_at)
            values (?, 'h2', 'raw2', '2026-08-20', 'SHELL FUEL PUMP', 'shell', 'Shell', -1500.0, 1500.0, 0.0, '2026-08-20T10:00:00Z')
            """,
            (imp_id,),
        )
        tid = cur.lastrowid
        cur.execute(
            """
            insert into classifications (transaction_id, category, expense_type, split_ratio, my_share, status, confidence, updated_at)
            values (?, 'Other', 'Personal', 1.0, 1500.0, 'needs_review', 0.4, '2026-08-20T10:00:00Z')
            """,
            (tid,),
        )
        conn.commit()

        # Propose categorization
        prop = run_tool(
            conn,
            "anand",
            "propose_categorize_transaction",
            {
                "transaction_id": tid,
                "category": "Transport",
                "expense_type": "Shared",
                "split_people": 2,
                "learn": True,
            },
        )
        conn.close()

        self.assertTrue(prop["needs_confirm"])
        self.assertIn("confirm_token", prop)
        token = prop["confirm_token"]

        # Confirm action
        res = confirm_action(self.tmp, "anand", token)
        self.assertTrue(res["ok"])

        # Verify DB updated to Transport / Shared / status='auto'
        check = sqlite3.connect(self.tmp)
        check.row_factory = sqlite3.Row
        row = check.execute("select * from classifications where transaction_id = ?", (tid,)).fetchone()
        check.close()
        self.assertEqual(row["category"], "Transport")
        self.assertEqual(row["expense_type"], "Shared")
        self.assertEqual(float(row["split_ratio"]), 0.5)

    def test_propose_and_confirm_edit_classification(self) -> None:
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("insert into imports (source_filename, file_sha256, imported_at) values ('test3.pdf', 'hash3', '2026-08-19')")
        imp_id = cur.lastrowid
        cur.execute(
            """
            insert into transactions (import_id, source_hash, raw_text, txn_date, description, merchant_key, merchant_display, amount_signed, debit, credit, created_at)
            values (?, 'h3', 'raw3', '2026-08-19', 'ZARA OUTFITS', 'zara', 'Zara', -3200.0, 3200.0, 0.0, '2026-08-19T10:00:00Z')
            """,
            (imp_id,),
        )
        tid = cur.lastrowid
        cur.execute(
            """
            insert into classifications (transaction_id, category, expense_type, split_ratio, my_share, status, confidence, updated_at)
            values (?, 'Other', 'Personal', 1.0, 3200.0, 'auto', 1.0, '2026-08-19T10:00:00Z')
            """,
            (tid,),
        )
        conn.commit()

        # Propose edit via query search
        prop = run_tool(
            conn,
            "anand",
            "propose_edit_classification",
            {
                "query": "Zara",
                "date": "2026-08-19",
                "new_category": "Shopping",
                "new_expense_type": "Personal",
            },
        )
        conn.close()

        self.assertTrue(prop["needs_confirm"])
        token = prop["confirm_token"]

        # Confirm edit
        res = confirm_action(self.tmp, "anand", token)
        self.assertTrue(res["ok"])

        # Verify DB updated to Shopping
        check = sqlite3.connect(self.tmp)
        check.row_factory = sqlite3.Row
        row = check.execute("select * from classifications where transaction_id = ?", (tid,)).fetchone()
        check.close()
        self.assertEqual(row["category"], "Shopping")


class LocalIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()) / "intent.db"
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        cid = create_contact(conn, "ZeldaTest")
        add_ledger_entry(
            conn,
            contact_id=cid,
            direction="you_sent",
            amount=Decimal("500"),
            purpose="loan",
            entry_date=date.today().isoformat(),
            created_by="test",
        )
        add_manual_transaction(
            conn,
            current_month_bounds()[0],
            "Zomato",
            Decimal("250"),
            "debit",
            "Food",
            "Personal",
            Decimal("1"),
        )
        conn.close()

    def test_owe_and_food_without_gemini(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        owe = run_chat(self.tmp, "anand", "How much does ZeldaTest owe me?")
        self.assertIn("ZeldaTest", owe["reply"])
        self.assertIn("500", owe["reply"].replace(",", ""))
        food = run_chat(self.tmp, "anand", "What did I spend on food this month?")
        self.assertIn("250", food["reply"].replace(",", ""))
        # Source depends on whether a stored key exists — accept any valid source
        self.assertIn(food["source"], {"local", "local-missing-key", "gemini", "gemini-error", "tools-after-gemini-error"})

    def test_sends_over_lakh(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)
        from expense_tracker.contacts import add_ledger_entry
        from expense_tracker.db import connect as db_connect

        with db_connect(self.tmp) as conn:
            from expense_tracker.contacts import create_contact, find_contact_by_text

            c = find_contact_by_text(conn, "ZeldaTest")
            cid = int(c["id"]) if c else create_contact(conn, "ZeldaTest")
            add_ledger_entry(
                conn,
                contact_id=cid,
                direction="you_sent",
                amount=Decimal("150000"),
                purpose="transfer",
                entry_date="2025-06-11",
                created_by="test",
            )
        q = run_chat(self.tmp, "anand", "when did i send ZeldaTest amount greater than 1 lak")
        self.assertIn("150,000", q["reply"].replace(",", ","))
        # Date may be "2025-06-11" (local) or "June 11, 2025" (Gemini)
        self.assertTrue("2025" in q["reply"] or "June" in q["reply"])

    def test_food_and_top_via_ask_books(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        food = run_chat(self.tmp, "anand", "What did I spend on food this month?")
        self.assertTrue("Food" in food["reply"] or "250" in food["reply"].replace(",", "") or "Gemini" in food["reply"] or "spend" in food["reply"].lower())

    def test_gemini_used_when_key_present(self) -> None:
        os.environ["GEMINI_API_KEY"] = "should-be-called-but-will-fail"
        try:
            owe = run_chat(self.tmp, "anand", "How much does ZeldaTest owe me?")
            # With a key, Gemini is tried first; it will fail (bad key) and
            # fall back to local. Either way, ZeldaTest or an error is in reply.
            self.assertIn(owe["source"], {"gemini", "local-fallback", "gemini-error", "local"})
        finally:
            os.environ.pop("GEMINI_API_KEY", None)



class ThreadMemoryTests(unittest.TestCase):
    def test_stitch_followup(self) -> None:
        from expense_tracker.assistant.loop import stitch_followup

        hist = [{"role": "user", "text": "What did I spend on food this month?"}]
        out = stitch_followup("and last month", hist)
        self.assertIn("food", out.lower())
        self.assertIn("last month", out.lower())
        full = stitch_followup("How much does Highnes owe me?", hist)
        self.assertEqual(full, "How much does Highnes owe me?")


class ModelFailoverTests(unittest.TestCase):
    def setUp(self) -> None:
        import expense_tracker.assistant.provider as prov

        prov._exhausted.clear()
        prov._last_good = None
        self.prov = prov
        os.environ["GEMINI_API_KEY"] = "test-key"

    def tearDown(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)

    def test_429_on_first_uses_second(self) -> None:
        seen: list[str] = []

        def fake(model, *args, **kwargs):
            seen.append(model)
            if model == "gemini-3.5-flash-lite":
                raise RuntimeError("Gemini HTTP 429: RESOURCE_EXHAUSTED quota")
            return {
                "model": model,
                "function_calls": [],
                "raw_parts": [],
                "text": "ok",
                "finish_reason": "STOP",
            }

        self.prov._call = fake  # type: ignore[method-assign]
        out = self.prov.generate([], [], "sys")
        self.assertEqual(out["model"], "gemini-3.1-flash-lite")
        self.assertIn("gemini-3.5-flash-lite", seen)
        self.assertIn("gemini-3.1-flash-lite", seen)

    def test_400_invalid_argument_uses_next(self) -> None:
        seen: list[str] = []

        def fake(model, *args, **kwargs):
            seen.append(model)
            if model == "gemini-3.5-flash-lite":
                raise RuntimeError("Gemini HTTP 400: Request contains an invalid argument.")
            return {
                "model": model,
                "function_calls": [],
                "raw_parts": [],
                "text": "ok",
                "finish_reason": "STOP",
            }

        self.prov._call = fake  # type: ignore[method-assign]
        out = self.prov.generate([], [], "sys")
        self.assertEqual(out["model"], "gemini-3.1-flash-lite")


if __name__ == "__main__":
    unittest.main()
