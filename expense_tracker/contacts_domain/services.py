"""High-Level Service Orchestration Layer for Contacts and Khata Ledger."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .calculators import (
    _build_running_ledger,
    _calculate_net_balance,
    _d,
    _determine_settlement_params,
    _match_contact_from_list,
    _parse_contact_aliases,
    split_aliases,
    utc_now,
)
from .dal import (
    _fetch_all_contacts,
    _fetch_candidate_transactions,
    _fetch_contact_by_id,
    _fetch_ledger_entries,
    _insert_contact_record,
    _insert_ledger_entry,
    _soft_void_ledger_entry,
    _update_contact_record,
)

logger = logging.getLogger(__name__)


def create_contact(
    conn: sqlite3.Connection,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> int:
    """Creates a new contact record with name validation and serialized aliases."""
    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Contact name cannot be empty.")

    aliases_list = split_aliases(aliases)
    aliases_json = json.dumps(aliases_list)
    now = utc_now()

    cid = _insert_contact_record(
        conn=conn,
        name=name_clean,
        aliases_json=aliases_json,
        notes=notes,
        created_at=now,
    )
    logger.info("Created contact '%s' (id=%d)", name_clean, cid)
    return cid


def update_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> None:
    """Updates contact name, aliases, and notes."""
    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Contact name cannot be empty.")

    aliases_list = split_aliases(aliases)
    aliases_json = json.dumps(aliases_list)

    _update_contact_record(
        conn=conn,
        contact_id=int(contact_id),
        name=name_clean,
        aliases_json=aliases_json,
        notes=notes,
    )


def get_all_contacts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieves all active contacts with parsed alias lists."""
    raw_contacts = _fetch_all_contacts(conn)
    return [_parse_contact_aliases(c) for c in raw_contacts]


def find_contact_by_text(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Name/alias match with whole-token rules (Anand ≠ Ananthu).

    Prefers exact name, then longest token hit, then shorter hub names.
    """
    contacts = get_all_contacts(conn)
    return _match_contact_from_list(contacts, text)


def add_ledger_entry(
    conn: sqlite3.Connection,
    contact_id: int,
    direction: str,
    amount: Decimal | float | str,
    purpose: str = "other",
    transaction_id: int | None = None,
    is_passthrough: bool = False,
    passthrough_pair_id: int | None = None,
    is_opening_balance: bool = False,
    notes: str | None = None,
    entry_date: str | None = None,
    created_by: str = "user",
) -> int:
    """Creates a new ledger entry record."""
    try:
        amt = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValueError("Invalid amount specified for ledger entry.") from exc

    if amt <= 0:
        raise ValueError("Ledger entry amount must be greater than zero.")
    if direction not in {"you_sent", "they_sent"}:
        raise ValueError("Direction must be 'you_sent' or 'they_sent'.")
    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    purpose = (purpose or "other").strip() or "other"
    if is_opening_balance and purpose in {"other", ""}:
        purpose = "opening_balance"

    now = utc_now()
    return _insert_ledger_entry(
        conn=conn,
        contact_id=int(contact_id),
        direction=direction,
        amount=amt,
        purpose=purpose,
        transaction_id=transaction_id,
        is_passthrough=is_passthrough,
        passthrough_pair_id=passthrough_pair_id,
        is_opening_balance=is_opening_balance,
        notes=notes,
        entry_date=entry_date,
        created_by=created_by,
        created_at=now,
    )


def add_rolling_entry(
    conn: sqlite3.Connection,
    from_contact_id: int,
    to_contact_id: int,
    amount: Decimal | float | str,
    entry_date: str | None = None,
    notes: str | None = None,
    created_by: str = "user",
) -> dict[str, Any]:
    """A → you → B as two pass-through legs. Nets do not change."""
    if int(from_contact_id) == int(to_contact_id):
        raise ValueError("From and To contacts must be different.")

    from_row = _fetch_contact_by_id(conn, int(from_contact_id))
    to_row = _fetch_contact_by_id(conn, int(to_contact_id))
    if not from_row or not to_row:
        raise ValueError("Contact not found.")

    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    note_from = notes or f"Rolling via me → {to_row['name']}"
    note_to = notes or f"Rolling via me ← {from_row['name']}"

    e1 = add_ledger_entry(
        conn,
        contact_id=int(from_contact_id),
        direction="they_sent",
        amount=amount,
        purpose="rolling",
        is_passthrough=True,
        notes=note_from,
        entry_date=entry_date,
        created_by=created_by,
    )
    e2 = add_ledger_entry(
        conn,
        contact_id=int(to_contact_id),
        direction="you_sent",
        amount=amount,
        purpose="rolling",
        is_passthrough=True,
        passthrough_pair_id=e1,
        notes=note_to,
        entry_date=entry_date,
        created_by=created_by,
    )
    amt = float(_d(amount))
    return {
        "from_contact_id": int(from_contact_id),
        "from_contact_name": from_row["name"],
        "to_contact_id": int(to_contact_id),
        "to_contact_name": to_row["name"],
        "amount": amt,
        "entry_date": entry_date,
        "leg_from_id": e1,
        "leg_to_id": e2,
        "from_balance": get_balance(conn, int(from_contact_id)),
        "to_balance": get_balance(conn, int(to_contact_id)),
    }


def record_opening_balance(
    conn: sqlite3.Connection,
    contact_id: int,
    amount: Decimal | float | str,
    *,
    they_owe_you: bool = True,
    entry_date: str | None = None,
    notes: str | None = None,
    created_by: str = "user",
) -> dict[str, Any]:
    """Records an initial opening balance entry for a contact."""
    row = _fetch_contact_by_id(conn, int(contact_id))
    if not row:
        raise ValueError("Contact not found.")
    direction = "you_sent" if they_owe_you else "they_sent"
    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry_id = add_ledger_entry(
        conn,
        contact_id=int(contact_id),
        direction=direction,
        amount=amount,
        purpose="opening_balance",
        is_opening_balance=True,
        notes=notes or "Opening balance",
        entry_date=entry_date,
        created_by=created_by,
    )
    bal = get_balance(conn, int(contact_id))
    return {
        "entry_id": entry_id,
        "contact_id": int(contact_id),
        "contact_name": row["name"],
        "amount": float(_d(amount)),
        "direction": direction,
        "they_owe_you": they_owe_you,
        "balance": bal,
    }


def record_settlement(
    conn: sqlite3.Connection,
    contact_id: int,
    amount: Decimal | float | str | None = None,
    *,
    notes: str | None = None,
    entry_date: str | None = None,
    created_by: str = "user",
) -> dict[str, Any]:
    """Post a compensating entry for full or partial settle."""
    bal = get_balance(conn, int(contact_id))
    net = _d(bal["net"])
    if net == 0:
        return bal

    settle_amt, direction = _determine_settlement_params(net, amount)
    add_ledger_entry(
        conn,
        contact_id=int(contact_id),
        direction=direction,
        amount=settle_amt,
        purpose="settlement",
        notes=notes or "Settlement",
        entry_date=entry_date,
        created_by=created_by,
    )
    return get_balance(conn, int(contact_id))


def void_ledger_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    reason: str = "voided by user",
) -> None:
    """Voids (or deletes) a ledger entry by ID."""
    _soft_void_ledger_entry(conn, int(entry_id), reason, utc_now())


def get_balance(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Net excludes pass-throughs and voided rows."""
    rows = _fetch_ledger_entries(conn, int(contact_id), include_transactions=False, exclude_voided=True)
    return _calculate_net_balance(int(contact_id), rows)


def get_ledger(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Returns contact info, current balance summary, and itemized running ledger entries."""
    contact = _fetch_contact_by_id(conn, int(contact_id))
    if not contact:
        raise ValueError(f"Contact id {contact_id} not found.")

    contact = _parse_contact_aliases(contact)
    raw_entries = _fetch_ledger_entries(conn, int(contact_id), include_transactions=True, exclude_voided=True)
    balance = get_balance(conn, int(contact_id))
    return _build_running_ledger(contact, raw_entries, balance)


def get_all_balances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All contacts with balances (for People cards / summary API)."""
    out: list[dict[str, Any]] = []
    for c in get_all_contacts(conn):
        bal = get_balance(conn, int(c["id"]))
        bal["contact_name"] = c["name"]
        bal["username"] = c["name"]
        out.append({"contact": c, "balance": bal, **bal})
    return out


def detect_passthrough_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """A→you→B candidates. Never auto-creates contacts.

    Optimized to pre-fetch active contacts once to prevent N+1 queries.
    """
    contacts = get_all_contacts(conn)
    rows = _fetch_candidate_transactions(conn, limit=10)

    candidates = []
    for r in rows:
        c_contact = _match_contact_from_list(contacts, r["credit_merchant"] or "")
        d_contact = _match_contact_from_list(contacts, r["debit_merchant"] or "")
        candidates.append(
            {
                "credit_tx_id": r["credit_tx_id"],
                "credit_date": r["credit_date"],
                "credit_amount": float(_d(r["credit_amount"])),
                "credit_merchant": r["credit_merchant"],
                "credit_contact": (
                    c_contact["name"] if c_contact else (r["credit_merchant"] or "Unknown Sender")
                ),
                "from_contact_id": (c_contact["id"] if c_contact else None),
                "debit_tx_id": r["debit_tx_id"],
                "debit_date": r["debit_date"],
                "debit_amount": float(_d(r["debit_amount"])),
                "debit_merchant": r["debit_merchant"],
                "debit_contact": (
                    d_contact["name"] if d_contact else (r["debit_merchant"] or "Unknown Recipient")
                ),
                "to_contact_id": (d_contact["id"] if d_contact else None),
            }
        )
    return candidates
