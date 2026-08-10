"""Empirical Stress Tests for Khata Domain Logic (Milestone 2 Challenger)."""

import sqlite3
import pytest
from decimal import Decimal
from expense_tracker.db import init_db
from expense_tracker.contacts import (
    create_contact,
    get_all_contacts,
    find_contact_by_text,
    add_ledger_entry,
    add_rolling_entry,
    record_settlement,
    void_ledger_entry,
    get_balance,
    get_ledger,
    split_aliases,
)
from expense_tracker.contacts_domain.calculators import _token_in_text


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    yield connection
    connection.close()


def test_unicode_devanagari_and_emoji_aliases(conn):
    cid = create_contact(conn, name="आनंद कुमार", aliases=["anand.k@upi", "आनंद", "😀_emoji_alias"])
    matched = find_contact_by_text(conn, "आनंद")
    assert matched is not None
    assert matched["id"] == cid

    cid_emoji = create_contact(conn, name="Alice 🚀", aliases="rocket_alice, 🚀_alias")
    matched_emoji = find_contact_by_text(conn, "Alice 🚀")
    assert matched_emoji is not None
    assert matched_emoji["id"] == cid_emoji


def test_regex_special_characters_in_aliases(conn):
    regex_aliases = ["bob.*", "bob+test@gmail.com", "bob(hub)", "bob[1]", "^bob$"]
    cid = create_contact(conn, name="Bob Regex", aliases=regex_aliases)
    
    m1 = find_contact_by_text(conn, "bob+test@gmail.com")
    m2 = find_contact_by_text(conn, "bob(hub)")
    assert m1 is not None and m1["id"] == cid
    assert m2 is not None and m2["id"] == cid


def test_short_name_part_token_matching(conn):
    """Demonstrates issue where name parts <4 chars ('Ali') fail partial match."""
    cid = create_contact(conn, name="Ali Ram", aliases=[])
    matched = find_contact_by_text(conn, "paying Ali for coffee")
    # Finding Ali Ram when searching "paying Ali for coffee" fails because part length < 4 is skipped in _score_contact_match
    assert matched is not None and matched["id"] == cid


def test_zero_and_negative_settlement_validation(conn):
    cid = create_contact(conn, name="Charlie Settlement")
    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("1000"))

    with pytest.raises(ValueError, match="Settlement amount must be greater than zero"):
        record_settlement(conn, cid, amount=0)

    with pytest.raises(ValueError, match="Settlement amount must be greater than zero"):
        record_settlement(conn, cid, amount=-500)


def test_settlement_when_net_is_zero_silent_noop(conn):
    cid = create_contact(conn, name="Dave ZeroNet")
    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("500"))
    record_settlement(conn, cid)  # Net becomes 0.0

    # Explicit settlement of 100 on net=0 is silently ignored
    res = record_settlement(conn, cid, amount=100)
    ledger = get_ledger(conn, cid)
    settlement_entries = [e for e in ledger["entries"] if e.get("purpose") == "settlement"]
    assert len(settlement_entries) == 1  # Only initial settlement recorded


def test_rolling_entry_single_leg_void_asymmetry(conn):
    c_from = create_contact(conn, name="Person A")
    c_to = create_contact(conn, name="Person B")

    roll = add_rolling_entry(conn, from_contact_id=c_from, to_contact_id=c_to, amount=1000)
    leg1_id = roll["leg_from_id"]
    leg2_id = roll["leg_to_id"]

    void_ledger_entry(conn, leg1_id, reason="Voiding leg 1")

    ledger_b = get_ledger(conn, c_to)
    leg2_entry = next((e for e in ledger_b["entries"] if e["id"] == leg2_id), None)
    # Leg 2 remains unvoided even though leg 1 was voided
    assert leg2_entry is not None
    assert leg2_entry.get("voided_at") is None


def test_get_balance_non_existent_contact(conn):
    """get_ledger raises ValueError for missing contact, get_balance returns settled dict."""
    with pytest.raises(ValueError, match="Contact id 999999 not found"):
        get_ledger(conn, 999999)

    # get_balance does not raise error for missing contact
    bal = get_balance(conn, 999999)
    assert bal["contact_id"] == 999999
    assert bal["net"] == 0.0


def test_running_ledger_out_of_order_dates(conn):
    cid = create_contact(conn, name="Chronological Person")
    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("100"), entry_date="2026-07-15")
    add_ledger_entry(conn, contact_id=cid, direction="they_sent", amount=Decimal("30"), entry_date="2026-07-01")
    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("50"), entry_date="2026-07-10")

    ledger = get_ledger(conn, cid)
    dates = [e["entry_date"] for e in ledger["entries"]]
    running = [e["running_balance"] for e in ledger["entries"]]

    assert dates == ["2026-07-01", "2026-07-10", "2026-07-15"]
    assert running == [-30.0, 20.0, 120.0]
