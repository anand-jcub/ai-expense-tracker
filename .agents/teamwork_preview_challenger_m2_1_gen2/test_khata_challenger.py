"""Empirical Challenger Test Suite for Milestone 2 (Khata Domain Refactoring).

Tests contacts.py and expense_tracker/contacts_domain/ modules for edge cases,
stress conditions, unicode handling, settlement boundaries, pass-through voiding,
and running ledger calculation extremes.
"""

import json
import sqlite3
import unittest
from decimal import Decimal
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from expense_tracker import contacts
from expense_tracker.contacts_domain import calculators, dal, services


def create_in_memory_db() -> sqlite3.Connection:
    """Creates an in-memory SQLite database with full schema for contacts & ledger."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            aliases_json TEXT,
            notes TEXT,
            created_at TEXT,
            merged_into_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            transaction_id INTEGER,
            direction TEXT,
            entry_type TEXT,
            amount TEXT NOT NULL,
            purpose TEXT,
            is_passthrough INTEGER DEFAULT 0,
            passthrough_pair_id INTEGER,
            is_opening_balance INTEGER DEFAULT 0,
            notes TEXT,
            entry_date TEXT NOT NULL,
            source TEXT,
            created_by TEXT,
            created_at TEXT,
            voided_at TEXT,
            void_reason TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_date TEXT,
            credit REAL DEFAULT 0,
            debit REAL DEFAULT 0,
            merchant_display TEXT,
            description TEXT
        )
    """)
    return conn


class TestKhataUnicodeAndSpecialChars(unittest.TestCase):
    """1. Stress test Unicode / special characters in contact names, aliases, and matching."""

    def setUp(self):
        self.conn = create_in_memory_db()

    def tearDown(self):
        self.conn.close()

    def test_unicode_contact_creation_and_aliases(self):
        """Test Unicode names, Cyrillic, Devanagari, Emojis, Accents in create_contact & get_all_contacts."""
        cid1 = contacts.create_contact(
            self.conn,
            name="Алиса Ивановна",
            aliases=["алиса", "alice_cyrillic", "Алиса 🚀"],
            notes="Unicode test note 🌟"
        )
        cid2 = contacts.create_contact(
            self.conn,
            name="आनंद कुमार",
            aliases=["आनंद", "anand_devanagari"],
            notes="Devanagari contact"
        )
        cid3 = contacts.create_contact(
            self.conn,
            name="Café Owner René",
            aliases=["café", "rené", "café_alias"],
            notes="Accented characters"
        )

        all_c = contacts.get_all_contacts(self.conn)
        self.assertEqual(len(all_c), 3)

        c1 = [c for c in all_c if c["id"] == cid1][0]
        self.assertEqual(c1["name"], "Алиса Ивановна")
        self.assertIn("алиса", c1["aliases"])
        self.assertIn("алиса 🚀", c1["aliases"])

    def test_special_characters_in_aliases(self):
        """Test punctuation/special characters (+, -, @, $, ., /, quotes, brackets) in aliases."""
        cid = contacts.create_contact(
            self.conn,
            name="Bob Smith",
            aliases=["bob+work@gmail.com", "c++", "mr. b", "bob ($)", "bob/work"]
        )
        all_c = contacts.get_all_contacts(self.conn)
        c = [c for c in all_c if c["id"] == cid][0]
        self.assertIn("bob+work@gmail.com", c["aliases"])
        self.assertIn("c++", c["aliases"])
        self.assertIn("mr. b", c["aliases"])

    def test_unicode_and_special_char_contact_matching(self):
        """Test find_contact_by_text matching with Unicode and special characters."""
        cid1 = contacts.create_contact(self.conn, name="Café Owner", aliases=["café"])
        cid2 = contacts.create_contact(self.conn, name="Алиса", aliases=["alice_ru"])

        m1 = contacts.find_contact_by_text(self.conn, "Paid at Café Owner")
        self.assertIsNotNone(m1, "Failed to match 'Café Owner'")
        self.assertEqual(m1["id"], cid1)

        m2 = contacts.find_contact_by_text(self.conn, "Transferred to Алиса")
        self.assertIsNotNone(m2, "Failed to match Cyrillic 'Алиса'")
        self.assertEqual(m2["id"], cid2)

    def test_short_name_part_token_matching_bug(self):
        """Test token matching for short name parts (< 4 chars) like 'Ali', 'Max', 'Ram'."""
        cid = contacts.create_contact(self.conn, name="Ali Ram", aliases=[])
        matched = contacts.find_contact_by_text(self.conn, "paying Ali for coffee")
        self.assertIsNotNone(matched, "BUG: Contact with short name part 'Ali' (< 4 chars) failed token match!")
        if matched:
            self.assertEqual(matched["id"], cid)

    def test_non_ascii_token_boundary_regex_bug(self):
        """Test token boundary regex (_token_in_text) with Unicode characters."""
        cid = contacts.create_contact(self.conn, name="José", aliases=["josé"])
        matched = contacts.find_contact_by_text(self.conn, "Paid to Joséphine")
        # In ASCII regex (?![a-z0-9]), non-ASCII chars like 'p' in Cyrillic or words after 'é' trigger false positive boundary matches
        self.assertIsNone(matched, "BUG: 'José' matched inside 'Joséphine' due to ASCII-only regex boundary (?<![a-z0-9])")

    def test_cyrillic_substring_false_positive_bug(self):
        """Test Cyrillic word boundary in _token_in_text."""
        cid = contacts.create_contact(self.conn, name="Алиса", aliases=["алиса"])
        # Searching for 'алисавчера' (Alice yesterday concatenated)
        matched = contacts.find_contact_by_text(self.conn, "встретил алисавчера")
        self.assertIsNone(matched, "BUG: Cyrillic name 'алиса' matched inside concatenated word 'алисавчера'")


class TestKhataSettlementBoundaries(unittest.TestCase):
    """2. Stress test zero and negative settlement amounts and boundary conditions."""

    def setUp(self):
        self.conn = create_in_memory_db()
        self.cid = contacts.create_contact(self.conn, name="Settlement Test User")

    def tearDown(self):
        self.conn.close()

    def test_zero_settlement_amount(self):
        """Test record_settlement with amount = 0."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 100)
        with self.assertRaises(ValueError, msg="record_settlement should reject zero settlement amount"):
            contacts.record_settlement(self.conn, self.cid, amount=0)

    def test_negative_settlement_amount(self):
        """Test record_settlement with negative amounts (-50, '-100')."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 100)
        with self.assertRaises(ValueError, msg="record_settlement should reject negative settlement amount"):
            contacts.record_settlement(self.conn, self.cid, amount=-50)

    def test_invalid_settlement_amount_string(self):
        """Test record_settlement with invalid string ('invalid_amt')."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 100)
        with self.assertRaises(ValueError):
            contacts.record_settlement(self.conn, self.cid, amount="invalid_amt")

    def test_zero_and_negative_ledger_entry(self):
        """Test add_ledger_entry with zero and negative amounts."""
        with self.assertRaises(ValueError, msg="add_ledger_entry should reject 0 amount"):
            contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 0)
        with self.assertRaises(ValueError, msg="add_ledger_entry should reject negative amount"):
            contacts.add_ledger_entry(self.conn, self.cid, "you_sent", -25)

    def test_settlement_exceeding_net_balance_clamping(self):
        """Test record_settlement when requested settlement amount > net balance."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 100) # net = +100
        # Settle amount = 500 requested -> clamped to abs(net) = 100
        contacts.record_settlement(self.conn, self.cid, amount=500)
        bal = contacts.get_balance(self.conn, self.cid)
        self.assertEqual(bal["net"], 0.0, f"Expected 0.0 after clamped settlement, got {bal['net']}")

    def test_settlement_when_already_zero_balance(self):
        """Test record_settlement when net balance is 0."""
        res = contacts.record_settlement(self.conn, self.cid, amount=50)
        self.assertEqual(res["net"], 0.0)
        ledger = contacts.get_ledger(self.conn, self.cid)
        self.assertEqual(len(ledger["entries"]), 0)


class TestKhataPassthroughAndVoiding(unittest.TestCase):
    """3. Stress test voiding pass-through entries and rolling entry pair management."""

    def setUp(self):
        self.conn = create_in_memory_db()
        self.c1 = contacts.create_contact(self.conn, name="Alice")
        self.c2 = contacts.create_contact(self.conn, name="Bob")

    def tearDown(self):
        self.conn.close()

    def test_add_rolling_entry_creation(self):
        """Verify rolling entry creates 2 pass-through legs with correct directions."""
        roll = contacts.add_rolling_entry(self.conn, self.c1, self.c2, 150.00)
        e1_id = roll["leg_from_id"]
        e2_id = roll["leg_to_id"]

        b1 = contacts.get_balance(self.conn, self.c1)
        b2 = contacts.get_balance(self.conn, self.c2)
        self.assertEqual(b1["net"], 0.0)
        self.assertEqual(b2["net"], 0.0)

    def test_voiding_rolling_entry_leg_1_orphan_bug(self):
        """Test voiding leg 1 (from_contact) of a rolling entry pair. Check if leg 2 remains active/orphaned."""
        roll = contacts.add_rolling_entry(self.conn, self.c1, self.c2, 200.00)
        leg1_id = roll["leg_from_id"]
        leg2_id = roll["leg_to_id"]

        contacts.void_ledger_entry(self.conn, leg1_id, reason="User cancelled rolling leg 1")

        l1_row = self.conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (leg1_id,)).fetchone()
        l2_row = self.conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (leg2_id,)).fetchone()

        self.assertIsNotNone(l1_row["voided_at"], "Leg 1 should be soft-voided")
        is_leg2_voided = l2_row["voided_at"] is not None
        self.assertTrue(
            is_leg2_voided,
            "BUG: Voiding leg 1 of rolling entry left leg 2 active (pair orphaned!)"
        )

    def test_voiding_rolling_entry_leg_2_orphan_bug(self):
        """Test voiding leg 2 (to_contact) of a rolling entry pair. Check if leg 1 remains active/orphaned."""
        roll = contacts.add_rolling_entry(self.conn, self.c1, self.c2, 300.00)
        leg1_id = roll["leg_from_id"]
        leg2_id = roll["leg_to_id"]

        contacts.void_ledger_entry(self.conn, leg2_id, reason="User cancelled rolling leg 2")

        l1_row = self.conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (leg1_id,)).fetchone()
        l2_row = self.conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (leg2_id,)).fetchone()

        self.assertIsNotNone(l2_row["voided_at"], "Leg 2 should be soft-voided")
        is_leg1_voided = l1_row["voided_at"] is not None
        self.assertTrue(
            is_leg1_voided,
            "BUG: Voiding leg 2 of rolling entry left leg 1 active (pair orphaned!)"
        )

    def test_voided_passthrough_candidate_rediscovery_bug(self):
        """Test if voiding a candidate passthrough entry allows candidate rediscovery."""
        # Insert credit tx (id=10) and debit tx (id=20) with matching amount 500
        self.conn.execute("INSERT INTO transactions (id, txn_date, credit, merchant_display) VALUES (10, '2026-07-01', 500.0, 'Alice')")
        self.conn.execute("INSERT INTO transactions (id, txn_date, debit, merchant_display) VALUES (20, '2026-07-01', 500.0, 'Bob')")
        self.conn.commit()

        # Candidates detected
        cands1 = contacts.detect_passthrough_candidates(self.conn)
        self.assertEqual(len(cands1), 1)

        # Mark candidate as passthrough entry
        e_id = contacts.add_ledger_entry(self.conn, self.c1, "they_sent", 500, transaction_id=10, is_passthrough=True)

        # Now void this passthrough entry
        contacts.void_ledger_entry(self.conn, e_id, reason="Mistake")

        # Re-detect passthrough candidates
        cands2 = contacts.detect_passthrough_candidates(self.conn)
        self.assertEqual(len(cands2), 1, "BUG: detect_passthrough_candidates ignored transaction with voided passthrough entry!")

    def test_voiding_normal_ledger_entry_impact_on_balance(self):
        """Test voiding a normal (non-passthrough) ledger entry updates net balance correctly."""
        e1 = contacts.add_ledger_entry(self.conn, self.c1, "you_sent", 100)
        e2 = contacts.add_ledger_entry(self.conn, self.c1, "they_sent", 40)
        b_before = contacts.get_balance(self.conn, self.c1)
        self.assertEqual(b_before["net"], 60.0)

        contacts.void_ledger_entry(self.conn, e1, reason="Duplicate entry")
        b_after = contacts.get_balance(self.conn, self.c1)
        self.assertEqual(b_after["net"], -40.0)


class TestKhataLedgerCalculationExtremes(unittest.TestCase):
    """4. Stress test running ledger balance calculations under extreme inputs."""

    def setUp(self):
        self.conn = create_in_memory_db()
        self.cid = contacts.create_contact(self.conn, name="Extremes Test User")

    def tearDown(self):
        self.conn.close()

    def test_uppercase_or_mixedcase_direction_bug(self):
        """Test if direction in uppercase ('YOU_SENT', 'They_Sent') breaks net balance calculation."""
        self.conn.execute(
            "INSERT INTO ledger_entries (contact_id, direction, amount, entry_date) VALUES (?, ?, ?, ?)",
            (self.cid, "YOU_SENT", "100.00", "2026-01-01")
        )
        self.conn.commit()

        bal = contacts.get_balance(self.conn, self.cid)
        self.assertEqual(bal["net"], 100.0, "BUG: Uppercase direction 'YOU_SENT' was ignored in net balance calculation!")

    def test_extreme_decimal_amounts_precision(self):
        """Test very large monetary amounts and high precision fractional decimals."""
        large_amt = Decimal("100000000000000.50")
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", large_amt)
        bal = contacts.get_balance(self.conn, self.cid)
        self.assertEqual(Decimal(str(bal["net"])), large_amt)

    def test_fractional_decimal_precision_loss(self):
        """Test repeating decimal values (0.1 + 0.2) and small fractional amounts."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", "0.10")
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", "0.20")
        contacts.add_ledger_entry(self.conn, self.cid, "they_sent", "0.30")
        bal = contacts.get_balance(self.conn, self.cid)
        self.assertEqual(bal["net"], 0.0)

    def test_high_volume_running_ledger(self):
        """Test running balance accuracy across 1,000 ledger entries."""
        expected_running = Decimal("0")
        for i in range(1, 1001):
            amt = Decimal(f"{i}.50")
            if i % 2 == 1:
                contacts.add_ledger_entry(self.conn, self.cid, "you_sent", amt, entry_date="2026-01-01")
                expected_running += amt
            else:
                contacts.add_ledger_entry(self.conn, self.cid, "they_sent", amt, entry_date="2026-01-01")
                expected_running -= amt

        ledger = contacts.get_ledger(self.conn, self.cid)
        self.assertEqual(len(ledger["entries"]), 1000)
        final_entry_running = ledger["entries"][-1]["running_balance"]
        self.assertEqual(Decimal(str(final_entry_running)), expected_running)

    def test_date_ordering_in_running_ledger(self):
        """Test entry_date sorting when dates have different formats (YYYY-MM-DD vs YYYY-M-D)."""
        contacts.add_ledger_entry(self.conn, self.cid, "you_sent", 100, entry_date="2026-10-05")
        contacts.add_ledger_entry(self.conn, self.cid, "they_sent", 40, entry_date="2026-02-01")

        ledger = contacts.get_ledger(self.conn, self.cid)
        dates = [e["entry_date"] for e in ledger["entries"]]
        self.assertEqual(dates, ["2026-02-01", "2026-10-05"])


if __name__ == "__main__":
    unittest.main()
