"""Tests for simplified khata balance (ledger excl. pass-through)."""

from decimal import Decimal

import pytest
import sqlite3

from expense_tracker.db import init_db
from expense_tracker.contacts import (
    create_contact,
    add_ledger_entry,
    get_balance,
    get_ledger,
    add_rolling_entry,
    record_opening_balance,
    record_settlement,
    void_ledger_entry,
)
from expense_tracker.services import partner_share_for_row


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    yield connection
    connection.close()


def test_partner_share_equal_split():
    row = {
        "debit": 1000,
        "debit_offset": 0,
        "expense_type": "Shared",
        "split_ratio": "0.5",
    }
    assert partner_share_for_row(row) == Decimal("500.00")


def test_partner_share_with_offset():
    row = {
        "debit": 1000,
        "debit_offset": 200,
        "expense_type": "Shared",
        "split_ratio": "0.5",
    }
    assert partner_share_for_row(row) == Decimal("400.00")


def test_ledger_balance_excludes_passthrough(conn):
    cid = create_contact(conn, "Bob", "bob@upi")
    add_ledger_entry(conn, cid, "you_sent", Decimal("5000"), purpose="loan", entry_date="2026-07-01")
    add_ledger_entry(
        conn, cid, "they_sent", Decimal("10000"), purpose="rolling",
        is_passthrough=True, entry_date="2026-07-02",
    )
    bal = get_balance(conn, cid)
    assert bal["net"] == 5000.0
    assert bal["status"] == "owes_you"
    assert bal["entry_count"] == 1


def test_balance_json_has_net_balance(conn):
    cid = create_contact(conn, "Dana")
    add_ledger_entry(conn, cid, "you_sent", Decimal("100"), purpose="loan", entry_date="2026-07-01")
    payload = get_balance(conn, cid)
    assert payload["net"] == payload["net_balance"] == 100.0


def test_rolling_does_not_move_nets(conn):
    # Avoid seeded contact names (Highnes/Ranjima may already exist)
    a = create_contact(conn, "RollFrom-A")
    b = create_contact(conn, "RollTo-B")
    result = add_rolling_entry(conn, a, b, Decimal("20000"), entry_date="2026-07-02")
    assert result["amount"] == 20000.0
    assert get_balance(conn, a)["net"] == 0.0
    assert get_balance(conn, b)["net"] == 0.0
    # Still visible in ledger history
    assert len(get_ledger(conn, a)["entries"]) == 1
    assert len(get_ledger(conn, b)["entries"]) == 1
    assert get_ledger(conn, a)["entries"][0]["is_passthrough"] == 1


def test_opening_balance_they_owe_you(conn):
    cid = create_contact(conn, "Opening-Person")
    result = record_opening_balance(
        conn, cid, Decimal("15000"), they_owe_you=True, entry_date="2026-06-30"
    )
    assert result["amount"] == 15000.0
    bal = get_balance(conn, cid)
    assert bal["net"] == 15000.0
    assert bal["status"] == "owes_you"


def test_settlement_full(conn):
    cid = create_contact(conn, "Loan-Buddy")
    add_ledger_entry(conn, cid, "you_sent", Decimal("1500"), purpose="loan", entry_date="2026-07-01")
    bal = record_settlement(conn, cid)
    assert bal["net"] == 0.0
    assert bal["status"] == "settled"


def test_void_entry(conn):
    cid = create_contact(conn, "Seema")
    eid = add_ledger_entry(conn, cid, "you_sent", Decimal("80"), purpose="loan", entry_date="2026-07-01")
    assert get_balance(conn, cid)["net"] == 80.0
    void_ledger_entry(conn, eid)
    assert get_balance(conn, cid)["net"] == 0.0
