import pytest
import sqlite3
from decimal import Decimal
from expense_tracker.db import init_db
from expense_tracker.contacts import (
    create_contact,
    get_all_contacts,
    add_ledger_entry,
    calculate_contact_balance,
    get_contact_ledger,
    detect_passthrough_candidates,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    yield connection
    connection.close()


def test_contact_creation(conn):
    cid = create_contact(conn, "Alice", "alice.1@upi, 9876543210", "Friend")
    assert cid > 0
    contacts = get_all_contacts(conn)
    names = [c["name"] for c in contacts]
    assert "Alice" in names


def test_balance_math(conn):
    cid = create_contact(conn, "Bob", "bob.2@upi")
    
    # You sent Bob 5000 (loan)
    add_ledger_entry(
        conn,
        contact_id=cid,
        transaction_id=None,
        direction="you_sent",
        amount=Decimal("5000"),
        purpose="loan",
        entry_date="2026-07-01",
        created_by="user",
    )
    
    # Bob sent you 2000 (repayment)
    add_ledger_entry(
        conn,
        contact_id=cid,
        transaction_id=None,
        direction="they_sent",
        amount=Decimal("2000"),
        purpose="rolling",
        entry_date="2026-07-02",
        created_by="user",
    )
    
    bal = calculate_contact_balance(conn, cid)
    assert bal["total_you_sent"] == 5000.0
    assert bal["total_they_sent"] == 2000.0
    assert bal["net_balance"] == 3000.0  # Bob owes you 3000


def test_opening_balance(conn):
    cid = create_contact(conn, "Charlie")
    
    # Pre-July opening balance: You owed Charlie 1500
    add_ledger_entry(
        conn,
        contact_id=cid,
        transaction_id=None,
        direction="they_sent",
        amount=Decimal("1500"),
        purpose="other",
        is_opening_balance=True,
        entry_date="2026-06-30",
        created_by="user",
    )
    
    bal = calculate_contact_balance(conn, cid)
    assert bal["net_balance"] == -1500.0  # You owe Charlie 1500
