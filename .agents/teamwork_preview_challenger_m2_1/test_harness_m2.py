"""Adversarial Empirical Test Harness for Khata Domain Calculators.

Milestone 2 Challenger 1 Extended Test Suite.
"""

import os
import sys
import unittest
from decimal import Decimal

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from expense_tracker.contacts_domain.calculators import (
    _build_running_ledger,
    _calculate_net_balance,
    _d,
    _determine_settlement_params,
    _direction_of,
    _match_contact_from_list,
    _parse_contact_aliases,
    _score_contact_match,
    _token_in_text,
    split_aliases,
)


class TestSplitAliases(unittest.TestCase):

    def test_empty_inputs(self):
        self.assertEqual(split_aliases(""), [])
        self.assertEqual(split_aliases("   "), [])
        self.assertEqual(split_aliases(",, , "), [])
        self.assertEqual(split_aliases([]), [])
        self.assertEqual(split_aliases(["", "   "]), [])

    def test_whitespace_and_duplicates(self):
        result = split_aliases("  Alice , BOB , alice ,  bob  ,  Charlie  ")
        self.assertEqual(result, ["alice", "bob", "charlie"])

    def test_unicode_characters(self):
        result = split_aliases(" Ánand ,  Müller , 🤖 , áñänd ")
        self.assertEqual(result, ["ánand", "müller", "🤖", "áñänd"])

    def test_list_of_strings(self):
        result = split_aliases(["  Alice ", "BOB", "alice", "charlie"])
        self.assertEqual(result, ["alice", "bob", "charlie"])

    def test_list_with_embedded_commas(self):
        # Note: split_aliases treats list items literally without splitting them by comma
        result = split_aliases(["alice, bob", "charlie"])
        self.assertIn("alice, bob", result)

    def test_non_string_elements_in_list(self):
        with self.assertRaises(AttributeError):
            split_aliases([123, "alice"])  # 123 has no .strip()


class TestCalculateNetBalance(unittest.TestCase):

    def test_zero_entries(self):
        res = _calculate_net_balance(1, [])
        self.assertEqual(res["net"], 0.0)
        self.assertEqual(res["status"], "settled")
        self.assertEqual(res["you_sent"], 0.0)
        self.assertEqual(res["they_sent"], 0.0)
        self.assertEqual(res["entry_count"], 0)

    def test_mixed_positive_negative_amounts(self):
        rows = [
            {"amount": "100.50", "direction": "you_sent"},
            {"amount": "40.25", "direction": "they_sent"},
            {"amount": "20.00", "direction": "you_sent"},
        ]
        res = _calculate_net_balance(1, rows)
        self.assertEqual(res["you_sent"], 120.50)
        self.assertEqual(res["they_sent"], 40.25)
        self.assertEqual(res["net"], 80.25)
        self.assertEqual(res["status"], "owes_you")
        self.assertEqual(res["they_owe_you"], 80.25)
        self.assertEqual(res["you_owe_them"], 0.0)

    def test_you_owe_status(self):
        rows = [
            {"amount": "50.00", "direction": "you_sent"},
            {"amount": "150.00", "direction": "they_sent"},
        ]
        res = _calculate_net_balance(1, rows)
        self.assertEqual(res["net"], -100.00)
        self.assertEqual(res["status"], "you_owe")
        self.assertEqual(res["they_owe_you"], 0.0)
        self.assertEqual(res["you_owe_them"], 100.00)

    def test_passthrough_entries_in_raw_rows(self):
        """Test behavior when passthrough rows are passed directly to _calculate_net_balance."""
        rows = [
            {"amount": "100.00", "direction": "you_sent", "is_passthrough": 0},
            {"amount": "500.00", "direction": "you_sent", "is_passthrough": 1},
        ]
        res = _calculate_net_balance(1, rows)
        # Note: _calculate_net_balance relies on DAL filter coalesce(is_passthrough,0)=0
        self.assertEqual(res["net"], 600.0)

    def test_voided_entries_in_raw_rows(self):
        """Test behavior when voided rows are passed directly to _calculate_net_balance."""
        rows = [
            {"amount": "100.00", "direction": "you_sent"},
            {"amount": "50.00", "direction": "you_sent", "voided_at": "2026-01-01T00:00:00Z"},
        ]
        res = _calculate_net_balance(1, rows)
        # Note: _calculate_net_balance relies on DAL filter voided_at IS NULL
        self.assertEqual(res["net"], 150.0)


class TestDetermineSettlementParams(unittest.TestCase):

    def test_amount_none_positive_net(self):
        settle_amt, direction = _determine_settlement_params(Decimal("100.00"), None)
        self.assertEqual(settle_amt, Decimal("100.00"))
        self.assertEqual(direction, "they_sent")

    def test_amount_none_negative_net(self):
        settle_amt, direction = _determine_settlement_params(Decimal("-100.00"), None)
        self.assertEqual(settle_amt, Decimal("100.00"))
        self.assertEqual(direction, "you_sent")

    def test_requested_amount_greater_than_net(self):
        settle_amt, direction = _determine_settlement_params(Decimal("100.00"), Decimal("150.00"))
        self.assertEqual(settle_amt, Decimal("100.00"))
        self.assertEqual(direction, "they_sent")

    def test_zero_amount_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            _determine_settlement_params(Decimal("100.00"), Decimal("0"))
        self.assertIn("must be greater than zero", str(ctx.exception))

    def test_negative_amount_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            _determine_settlement_params(Decimal("100.00"), Decimal("-20.00"))
        self.assertIn("must be greater than zero", str(ctx.exception))

    def test_negative_net_partial_settlement(self):
        settle_amt, direction = _determine_settlement_params(Decimal("-100.00"), Decimal("40.00"))
        self.assertEqual(settle_amt, Decimal("40.00"))
        self.assertEqual(direction, "you_sent")

    def test_zero_net_with_amount(self):
        settle_amt, direction = _determine_settlement_params(Decimal("0"), Decimal("50.00"))
        self.assertEqual(settle_amt, Decimal("0"))
        self.assertEqual(direction, "you_sent")


class TestAuxiliaryCalculators(unittest.TestCase):

    def test_token_in_text(self):
        self.assertTrue(_token_in_text("anand", "anand raj"))
        self.assertFalse(_token_in_text("anand", "ananthu"))
        self.assertTrue(_token_in_text("bob", "bob, alice"))
        self.assertFalse(_token_in_text("cat", "scat"))
        self.assertFalse(_token_in_text("", "text"))
        self.assertFalse(_token_in_text("token", ""))

    def test_parse_contact_aliases(self):
        valid = {"name": "Bob", "aliases_json": '["bobby", "robert"]'}
        res = _parse_contact_aliases(valid)
        self.assertEqual(res["aliases"], ["bobby", "robert"])

        corrupt = {"name": "Bob", "aliases_json": "INVALID_JSON"}
        res_corrupt = _parse_contact_aliases(corrupt)
        self.assertEqual(res_corrupt["aliases"], [])

    def test_build_running_ledger(self):
        contact = {"id": 1, "name": "Alice"}
        raw_entries = [
            {"amount": "100.00", "direction": "you_sent", "is_passthrough": 0},
            {"amount": "50.00", "direction": "they_sent", "is_passthrough": 0},
            {"amount": "200.00", "direction": "you_sent", "is_passthrough": 1},  # passthrough excluded from balance
            {"amount": "30.00", "direction": "you_sent", "is_passthrough": 0},
        ]
        balance = {"net": 80.0}
        ledger = _build_running_ledger(contact, raw_entries, balance)
        self.assertEqual(ledger["balance"]["contact_name"], "Alice")
        self.assertEqual(len(ledger["entries"]), 4)
        # Running balances:
        # 1: 100.0
        # 2: 50.0 (100 - 50)
        # 3: 50.0 (passthrough, running unchanged)
        # 4: 80.0 (50 + 30)
        running_bals = [e["running_balance"] for e in ledger["entries"]]
        self.assertEqual(running_bals, [100.0, 50.0, 50.0, 80.0])


if __name__ == "__main__":
    unittest.main()
