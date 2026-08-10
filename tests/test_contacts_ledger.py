import pytest
import sqlite3
from decimal import Decimal
from expense_tracker.db import init_db, migrate_ledger_schema, _table_columns
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


def test_get_contact_ledger_api_shape(conn):
    """Drawer API expects entries as a list plus a flat balance object."""
    cid = create_contact(conn, "Dana")
    add_ledger_entry(
        conn,
        contact_id=cid,
        direction="you_sent",
        amount=Decimal("100"),
        purpose="loan",
        entry_date="2026-07-01",
    )
    payload = get_contact_ledger(conn, cid)
    assert isinstance(payload["entries"], list)
    assert len(payload["entries"]) == 1
    assert "net_balance" in payload["balance"]
    assert payload["entries"][0]["direction"] in ("you_sent", "they_sent")
    assert "running_balance" in payload["entries"][0]

    # Simulate what the fixed web handler returns
    api = {
        "contact": payload.get("contact"),
        "balance": payload.get("balance"),
        "entries": payload.get("entries") or [],
    }
    assert isinstance(api["entries"], list)
    assert api["entries"][0]["amount"] == 100.0


def test_legacy_schema_migration_backfills_direction():
    """Old DBs only had entry_type; migrate must add/fill direction."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE contacts (
            id integer primary key autoincrement,
            name text not null unique,
            aliases_json text not null default '[]',
            notes text,
            created_at text not null
        );
        CREATE TABLE ledger_entries (
            id integer primary key autoincrement,
            contact_id integer not null references contacts(id),
            transaction_id integer,
            entry_type text not null,
            amount numeric not null,
            purpose text,
            notes text,
            entry_date text,
            is_opening_balance integer default 0,
            is_passthrough integer default 0,
            passthrough_contact_id integer,
            created_at text not null,
            created_by text default 'user'
        );
        INSERT INTO contacts (name, aliases_json, created_at)
        VALUES ('Legacy Person', '[]', '2026-07-01T00:00:00+00:00');
        INSERT INTO ledger_entries (
            contact_id, entry_type, amount, purpose, entry_date, created_at, created_by
        ) VALUES (1, 'you_sent', 2500, 'loan', '2026-07-01', '2026-07-01T00:00:00+00:00', 'auto');
        """
    )
    connection.commit()

    # Partial migrate path used by init_db
    migrate_ledger_schema(connection)
    connection.commit()

    cols = _table_columns(connection, "ledger_entries")
    assert "direction" in cols
    assert "passthrough_pair_id" in cols

    row = connection.execute(
        "SELECT direction, entry_type, amount FROM ledger_entries WHERE id = 1"
    ).fetchone()
    assert row["direction"] == "you_sent"
    assert row["entry_type"] == "you_sent"

    bal = calculate_contact_balance(connection, 1)
    assert bal["net_balance"] == 2500.0
    assert bal["total_you_sent"] == 2500.0

    # New writes should succeed after migration
    eid = add_ledger_entry(
        connection,
        contact_id=1,
        direction="they_sent",
        amount=Decimal("500"),
        purpose="rolling",
        entry_date="2026-07-02",
    )
    assert eid > 0
    bal2 = calculate_contact_balance(connection, 1)
    assert bal2["net_balance"] == 2000.0
    connection.close()


def test_render_contacts_section_modular_components():
    from expense_tracker.templates import (
        render_contacts_section,
        _render_contact_card,
        _render_people_toolbar,
        _render_add_contact_modal,
        _render_edit_contact_modal,
        _render_add_ledger_modal,
        _render_ledger_drawer,
    )

    contacts_data = [
        {
            "contact": {"id": 1, "name": "Ananthu", "aliases": ["anandu"], "notes": "Friend"},
            "balance": {"net_balance": 1500, "entry_count": 3, "total_you_sent": 2000, "total_they_sent": 500},
        }
    ]

    card_html = _render_contact_card(contacts_data[0])
    assert 'data-action="open-drawer"' in card_html
    assert 'data-action="edit-contact"' in card_html
    assert 'data-action="add-ledger"' in card_html
    assert 'data-contact-id="1"' in card_html
    assert 'data-contact-name="Ananthu"' in card_html

    toolbar_html = _render_people_toolbar()
    assert 'data-action="search-contacts"' in toolbar_html
    assert 'data-action="filter-status"' in toolbar_html
    assert 'data-action="open-modal"' in toolbar_html

    add_modal_html = _render_add_contact_modal()
    assert 'id="modal-add-contact"' in add_modal_html
    assert 'data-action="close-modal"' in add_modal_html

    edit_modal_html = _render_edit_contact_modal()
    assert 'id="modal-edit-contact"' in edit_modal_html
    assert 'data-action="close-modal"' in edit_modal_html

    ledger_modal_html = _render_add_ledger_modal()
    assert 'id="modal-add-ledger"' in ledger_modal_html
    assert 'data-action="close-modal"' in ledger_modal_html

    drawer_html = _render_ledger_drawer()
    assert 'id="ledger-drawer"' in drawer_html
    assert 'data-action="close-drawer"' in drawer_html

    full_html = render_contacts_section(contacts_data, passthrough_candidates=[])
    assert "People" in full_html
    assert 'data-action="open-drawer"' in full_html

