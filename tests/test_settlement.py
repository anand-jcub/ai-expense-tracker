"""Tests for Unified Settlement Balance (USB)."""

from decimal import Decimal

import pytest
import sqlite3

from expense_tracker.db import init_db, review_transaction, import_transactions
from expense_tracker.contacts import (
    create_contact,
    add_ledger_entry,
    calculate_contact_balance,
)
from expense_tracker.settlement import (
    partner_share_for_row,
    compute_unified_settlement,
    settlement_to_json,
    resolve_contact,
    merge_contacts,
    dedupe_ledger_conflicts,
    record_settlement,
    materialize_virtual_shares,
    format_settlement_answer,
    canonical_contact_id,
)


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
    """Single net base: 1000 - 200 = 800; 50/50 → partner 400 (not 300)."""
    row = {
        "debit": 1000,
        "debit_offset": 200,
        "expense_type": "Shared",
        "split_ratio": "0.5",
    }
    assert partner_share_for_row(row) == Decimal("400.00")


def test_partner_share_unequal():
    row = {
        "debit": 900,
        "debit_offset": 0,
        "expense_type": "Shared",
        "split_ratio": Decimal("1") / Decimal("3"),
    }
    assert partner_share_for_row(row) == Decimal("600.00")


def test_partner_share_loan_zero():
    row = {
        "debit": 5000,
        "debit_offset": 0,
        "expense_type": "Loan",
        "split_ratio": "0.5",
    }
    assert partner_share_for_row(row) == Decimal("0.00")


def test_ledger_balance_excludes_passthrough(conn):
    cid = create_contact(conn, "Bob", "bob@upi")
    add_ledger_entry(conn, cid, "you_sent", Decimal("5000"), purpose="loan", entry_date="2026-07-01")
    add_ledger_entry(
        conn, cid, "they_sent", Decimal("10000"), purpose="rolling",
        is_passthrough=True, entry_date="2026-07-02",
    )
    bal = compute_unified_settlement(conn, cid)
    assert bal.ledger_net == Decimal("5000")
    assert bal.net == Decimal("5000")
    assert bal.passthrough_excluded_net == Decimal("-10000")
    assert bal.status == "owes_you"


def test_settlement_json_has_net_balance(conn):
    cid = create_contact(conn, "Dana")
    add_ledger_entry(conn, cid, "you_sent", Decimal("100"), purpose="loan", entry_date="2026-07-01")
    payload = settlement_to_json(compute_unified_settlement(conn, cid))
    assert payload["net"] == payload["net_balance"] == 100.0
    assert "breakdown" in payload
    assert isinstance(payload["entries"] if "entries" in payload else payload["lines"], list)


def test_resolve_prefers_hub_over_fragment(conn):
    # Highnes is seeded by init_db with aliases including highnesj sibl
    hub_row = conn.execute("SELECT id FROM contacts WHERE name = 'Highnes'").fetchone()
    hub = int(hub_row["id"])
    # Merchant-shaped fragment
    create_contact(conn, "Highnesj Sibl", "")
    match = resolve_contact(conn, "Highnesj Sibl")
    assert match is not None
    assert match["canonical_id"] == hub
    assert match["id"] == hub


def test_virtual_shared_and_suppress(conn):
    cid = create_contact(conn, "Alice", "alice")
    # Minimal import structure
    conn.execute(
        "INSERT INTO imports (source_filename, file_sha256, imported_at, password_used, transaction_count) "
        "VALUES ('t.pdf', 'abc', '2026-07-01', 0, 1)"
    )
    conn.execute(
        """
        INSERT INTO transactions (
            import_id, source_hash, txn_date, description, debit, credit, amount_signed,
            raw_text, merchant_key, merchant_display, created_at
        ) VALUES (1, 'h1', '2026-07-01', 'ZOMATO', 600, 0, -600, 'ZOMATO', 'zomato', 'Zomato', '2026-07-01')
        """
    )
    conn.execute(
        """
        INSERT INTO classifications (
            transaction_id, category, expense_type, split_ratio, my_share, status, confidence, updated_at,
            shared_with, shared_with_contact_id
        ) VALUES (1, 'Food', 'Shared', 0.5, 300, 'reviewed', 1, '2026-07-01', 'Alice', ?)
        """,
        (cid,),
    )
    conn.commit()

    bal = compute_unified_settlement(conn, cid)
    assert bal.virtual_shared_net == Decimal("300.00")
    assert bal.net == Decimal("300.00")

    # Materialize then virtual suppressed
    n = materialize_virtual_shares(conn, cid)
    assert n == 1
    bal2 = compute_unified_settlement(conn, cid)
    assert bal2.virtual_shared_net == Decimal("0")
    assert bal2.ledger_net == Decimal("300.00")


def test_shared_with_persist(conn):
    cid = int(conn.execute("SELECT id FROM contacts WHERE name = 'Highnes'").fetchone()["id"])
    conn.execute(
        "INSERT INTO imports (source_filename, file_sha256, imported_at, password_used, transaction_count) "
        "VALUES ('t.pdf', 'xyz', '2026-07-01', 0, 1)"
    )
    conn.execute(
        """
        INSERT INTO transactions (
            import_id, source_hash, txn_date, description, debit, credit, amount_signed,
            raw_text, merchant_key, merchant_display, created_at
        ) VALUES (1, 'h2', '2026-07-02', 'SWIGGY', 400, 0, -400, 'SWIGGY', 'swiggy', 'Swiggy', '2026-07-02')
        """
    )
    conn.execute(
        """
        INSERT INTO classifications (
            transaction_id, category, expense_type, split_ratio, my_share, status, confidence, updated_at
        ) VALUES (1, NULL, 'Personal', 1.0, 400, 'needs_review', 0, '2026-07-02')
        """
    )
    conn.commit()
    review_transaction(
        conn, 1, "Food", "Shared", Decimal("0.5"), None, False,
        shared_with="Highnes",
    )
    row = conn.execute(
        "SELECT shared_with, shared_with_contact_id, expense_type FROM classifications WHERE transaction_id=1"
    ).fetchone()
    assert row["shared_with"] == "Highnes"
    assert row["shared_with_contact_id"] == cid
    assert row["expense_type"] == "Shared"


def test_merge_and_dedupe(conn):
    hub = int(conn.execute("SELECT id FROM contacts WHERE name = 'Highnes'").fetchone()["id"])
    frag = create_contact(conn, "Highnesj Sibl", "")
    conn.execute(
        "INSERT INTO imports (source_filename, file_sha256, imported_at, password_used, transaction_count) "
        "VALUES ('t.pdf', 'm1', '2026-07-01', 0, 1)"
    )
    conn.execute(
        """
        INSERT INTO transactions (
            import_id, source_hash, txn_date, description, debit, credit, amount_signed,
            raw_text, merchant_key, merchant_display, created_at
        ) VALUES (1, 'hm', '2026-07-01', 'UPI', 0, 8000, 8000, 'UPI', 'highnes', 'Highnesj Sibl', '2026-07-01')
        """
    )
    conn.commit()
    add_ledger_entry(
        conn, frag, "they_sent", Decimal("8000"), purpose="other",
        transaction_id=1, entry_date="2026-07-01", created_by="auto",
    )
    add_ledger_entry(
        conn, frag, "they_sent", Decimal("8000"), purpose="rolling",
        transaction_id=1, is_passthrough=True, entry_date="2026-07-02", created_by="user",
    )
    result = merge_contacts(conn, hub, [frag], auto_dedupe=True)
    assert result["winner_id"] == hub
    assert canonical_contact_id(conn, frag) == hub
    bal = compute_unified_settlement(conn, hub)
    # After void migrate twin, only PT remains (excluded) → net 0
    assert bal.net == Decimal("0")
    assert bal.passthrough_excluded_net == Decimal("-8000")


def test_record_settlement_partial(conn):
    cid = create_contact(conn, "Eve")
    add_ledger_entry(conn, cid, "you_sent", Decimal("1000"), purpose="loan", entry_date="2026-07-01")
    bal = record_settlement(conn, cid, amount=Decimal("400"))
    assert bal.net == Decimal("600")
    assert bal.status == "owes_you"


def test_format_answer(conn):
    cid = int(conn.execute("SELECT id FROM contacts WHERE name = 'Highnes'").fetchone()["id"])
    add_ledger_entry(conn, cid, "you_sent", Decimal("12500"), purpose="loan", entry_date="2026-07-01")
    bal = compute_unified_settlement(conn, cid)
    text = format_settlement_answer(bal)
    assert "Highnes owes you" in text
    assert "12,500" in text or "12500" in text


def test_calculate_contact_balance_uses_usb(conn):
    cid = create_contact(conn, "Frank")
    add_ledger_entry(conn, cid, "you_sent", Decimal("100"), purpose="loan", entry_date="2026-07-01")
    add_ledger_entry(
        conn, cid, "they_sent", Decimal("50"), purpose="rolling",
        is_passthrough=True, entry_date="2026-07-02",
    )
    bal = calculate_contact_balance(conn, cid)
    # USB excludes PT
    assert bal["net_balance"] == 100.0
