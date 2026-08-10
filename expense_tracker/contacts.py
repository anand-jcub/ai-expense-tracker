"""Contacts + simple khata ledger (no USB / merge graph).

Top-level public facade re-exporting and delegating domain logic, data access, and service layer.

Balance rule (matches product use cases):
  net = sum(you_sent) − sum(they_sent)  for non-passthrough, non-void rows
  net > 0 → they owe you
  net < 0 → you owe them
  is_passthrough=1 rows are history only and never move net.

Architecture Layering:
  1. Pure Domain & Financial Calculation Layer: Pure functions free of SQLite dependencies
     (string splitting, token matching, net calculation, running ledger assembly, settlement rules).
  2. Data Access Layer (DAL): Isolated SQL database functions for contacts and ledger tables.
  3. Service Orchestration Layer: Public API facade functions coordinating DAL and Domain logic.
"""

from __future__ import annotations

import logging
import sqlite3
from decimal import Decimal
from typing import Any

from .contacts_domain import calculators, dal, services
from .contacts_domain.calculators import (
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
    utc_now,
)
from .contacts_domain.dal import (
    _fetch_all_contacts,
    _fetch_candidate_transactions,
    _fetch_contact_by_id,
    _fetch_ledger_entries,
    _insert_contact_record,
    _insert_ledger_entry,
    _soft_void_ledger_entry,
    _table_cols,
    _update_contact_record,
)

logger = logging.getLogger(__name__)


# ── 1. Pure Domain Calculators Re-exports ─────────────────────────────────────
# (utc_now, split_aliases, _d, _direction_of, _token_in_text, _score_contact_match,
#  _match_contact_from_list, _parse_contact_aliases, _calculate_net_balance,
#  _build_running_ledger, _determine_settlement_params are imported above)


# ── 2. Data Access Layer (DAL) Re-exports ────────────────────────────────────
# (_table_cols, _fetch_all_contacts, _fetch_contact_by_id, _insert_contact_record,
#  _update_contact_record, _fetch_ledger_entries, _insert_ledger_entry,
#  _soft_void_ledger_entry, _fetch_candidate_transactions are imported above)


# ── 3. High-Level Service Orchestration Layer Facades ────────────────────────

def create_contact(
    conn: sqlite3.Connection,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> int:
    """Creates a new contact record with name validation and serialized aliases."""
    return services.create_contact(conn, name=name, aliases=aliases, notes=notes)


def update_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> None:
    """Updates contact name, aliases, and notes."""
    services.update_contact(conn, contact_id=contact_id, name=name, aliases=aliases, notes=notes)


def get_all_contacts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retrieves all active contacts with parsed alias lists."""
    return services.get_all_contacts(conn)


def find_contact_by_text(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Name/alias match with whole-token rules (Anand ≠ Ananthu).

    Prefers exact name, then longest token hit, then shorter hub names.
    """
    return services.find_contact_by_text(conn, text)


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
    return services.add_ledger_entry(
        conn,
        contact_id=contact_id,
        direction=direction,
        amount=amount,
        purpose=purpose,
        transaction_id=transaction_id,
        is_passthrough=is_passthrough,
        passthrough_pair_id=passthrough_pair_id,
        is_opening_balance=is_opening_balance,
        notes=notes,
        entry_date=entry_date,
        created_by=created_by,
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
    return services.add_rolling_entry(
        conn,
        from_contact_id=from_contact_id,
        to_contact_id=to_contact_id,
        amount=amount,
        entry_date=entry_date,
        notes=notes,
        created_by=created_by,
    )


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
    return services.record_opening_balance(
        conn,
        contact_id=contact_id,
        amount=amount,
        they_owe_you=they_owe_you,
        entry_date=entry_date,
        notes=notes,
        created_by=created_by,
    )


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
    return services.record_settlement(
        conn,
        contact_id=contact_id,
        amount=amount,
        notes=notes,
        entry_date=entry_date,
        created_by=created_by,
    )


def void_ledger_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    reason: str = "voided by user",
) -> None:
    """Voids (or deletes) a ledger entry by ID."""
    services.void_ledger_entry(conn, entry_id=entry_id, reason=reason)


def get_balance(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Net excludes pass-throughs and voided rows."""
    return services.get_balance(conn, contact_id=contact_id)


def get_ledger(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Returns contact info, current balance summary, and itemized running ledger entries."""
    return services.get_ledger(conn, contact_id=contact_id)


def get_all_balances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All contacts with balances (for People cards / summary API)."""
    return services.get_all_balances(conn)


def detect_passthrough_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """A→you→B candidates. Never auto-creates contacts.

    Optimized to pre-fetch active contacts once to prevent N+1 queries.
    """
    return services.detect_passthrough_candidates(conn)


# Backward-compatible aliases used by older call sites / tests
calculate_contact_balance = get_balance
get_contact_ledger = get_ledger
