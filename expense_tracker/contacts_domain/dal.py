"""Data Access Layer (DAL) for contacts and ledger tables."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    """Reads table column names using SQLite PRAGMA info."""
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _fetch_all_contacts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Queries contacts table excluding soft-merged records."""
    cols = _table_cols(conn, "contacts")
    sql = "SELECT * FROM contacts"
    if "merged_into_id" in cols:
        sql += " WHERE merged_into_id IS NULL"
    sql += " ORDER BY name ASC"
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def _fetch_contact_by_id(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any] | None:
    """Fetches a single contact row by ID."""
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (int(contact_id),)).fetchone()
    return dict(row) if row else None


def _insert_contact_record(
    conn: sqlite3.Connection,
    name: str,
    aliases_json: str,
    notes: str | None,
    created_at: str,
) -> int:
    """Inserts a new contact record into database."""
    cur = conn.execute(
        """
        INSERT INTO contacts (name, aliases_json, notes, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name, aliases_json, notes, created_at),
    )
    conn.commit()
    return int(cur.lastrowid)


def _update_contact_record(
    conn: sqlite3.Connection,
    contact_id: int,
    name: str,
    aliases_json: str,
    notes: str | None,
) -> None:
    """Updates an existing contact record in database."""
    conn.execute(
        """
        UPDATE contacts
        SET name = ?, aliases_json = ?, notes = ?
        WHERE id = ?
        """,
        (name, aliases_json, notes, int(contact_id)),
    )
    conn.commit()


def _fetch_ledger_entries(
    conn: sqlite3.Connection,
    contact_id: int,
    include_transactions: bool = False,
    exclude_voided: bool = True,
) -> list[dict[str, Any]]:
    """Fetches ledger entry rows for a specific contact with dynamic schema handling."""
    cols = _table_cols(conn, "ledger_entries")
    if not include_transactions:
        sql = """
            SELECT coalesce(direction, entry_type) AS direction, amount, is_passthrough
            FROM ledger_entries
            WHERE contact_id = ?
              AND coalesce(is_passthrough, 0) = 0
        """
        if exclude_voided and "voided_at" in cols:
            sql += " AND (voided_at IS NULL OR voided_at = '')"
        rows = conn.execute(sql, (int(contact_id),)).fetchall()
    else:
        sql = """
            SELECT l.*,
                   coalesce(l.direction, l.entry_type) AS direction,
                   coalesce(l.entry_type, l.direction) AS entry_type,
                   t.merchant_display, t.description AS tx_desc
            FROM ledger_entries l
            LEFT JOIN transactions t ON l.transaction_id = t.id
            WHERE l.contact_id = ?
        """
        if exclude_voided and "voided_at" in cols:
            sql += " AND (l.voided_at IS NULL OR l.voided_at = '')"
        sql += " ORDER BY l.entry_date ASC, l.id ASC"
        rows = conn.execute(sql, (int(contact_id),)).fetchall()
    return [dict(r) for r in rows]


def _insert_ledger_entry(
    conn: sqlite3.Connection,
    contact_id: int,
    direction: str,
    amount: Decimal,
    purpose: str,
    transaction_id: int | None,
    is_passthrough: bool,
    passthrough_pair_id: int | None,
    is_opening_balance: bool,
    notes: str | None,
    entry_date: str,
    created_by: str,
    created_at: str,
) -> int:
    """Inserts a new ledger entry with dynamic schema inspection."""
    cols = _table_cols(conn, "ledger_entries")
    fields = ["contact_id", "transaction_id", "amount", "purpose", "notes", "entry_date", "created_by", "created_at"]
    values: list[Any] = [
        contact_id,
        transaction_id,
        str(amount),
        purpose,
        notes,
        entry_date,
        created_by,
        created_at,
    ]
    if "direction" in cols:
        fields.insert(2, "direction")
        values.insert(2, direction)
    if "entry_type" in cols:
        insert_at = fields.index("direction") + 1 if "direction" in fields else 2
        fields.insert(insert_at, "entry_type")
        values.insert(insert_at, direction)
    if "is_passthrough" in cols:
        fields.append("is_passthrough")
        values.append(int(is_passthrough))
    if "passthrough_pair_id" in cols:
        fields.append("passthrough_pair_id")
        values.append(passthrough_pair_id)
    if "is_opening_balance" in cols:
        fields.append("is_opening_balance")
        values.append(int(is_opening_balance))
    if "source" in cols:
        src = (
            "auto_passthrough"
            if is_passthrough
            else "settlement"
            if purpose == "settlement"
            else "auto_migrate"
            if created_by == "auto"
            else "user"
        )
        fields.append("source")
        values.append(src)

    placeholders = ", ".join("?" for _ in fields)
    col_sql = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO ledger_entries ({col_sql}) VALUES ({placeholders})",
        tuple(values),
    )
    conn.commit()
    return int(cur.lastrowid)


def _soft_void_ledger_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    reason: str,
    voided_at: str,
) -> None:
    """Soft-voids or deletes a ledger entry depending on table schema columns."""
    cols = _table_cols(conn, "ledger_entries")
    if "voided_at" in cols:
        conn.execute(
            """
            UPDATE ledger_entries
            SET voided_at = ?, void_reason = ?
            WHERE id = ?
            """,
            (voided_at, reason, int(entry_id)),
        )
        conn.commit()
        return
    conn.execute("DELETE FROM ledger_entries WHERE id = ?", (int(entry_id),))
    conn.commit()


def _fetch_candidate_transactions(
    conn: sqlite3.Connection,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Queries potential credit/debit transaction pairs within 2 days for pass-through detection."""
    rows = conn.execute(
        """
        SELECT
            c_tx.id AS credit_tx_id, c_tx.txn_date AS credit_date,
            c_tx.credit AS credit_amount, c_tx.merchant_display AS credit_merchant,
            d_tx.id AS debit_tx_id, d_tx.txn_date AS debit_date,
            d_tx.debit AS debit_amount, d_tx.merchant_display AS debit_merchant
        FROM transactions c_tx
        JOIN transactions d_tx
          ON c_tx.credit = d_tx.debit AND c_tx.credit > 0
        WHERE c_tx.id != d_tx.id
          AND abs(julianday(d_tx.txn_date) - julianday(c_tx.txn_date)) <= 2
          AND c_tx.id NOT IN (
              SELECT transaction_id FROM ledger_entries
              WHERE transaction_id IS NOT NULL AND is_passthrough = 1
          )
          AND d_tx.id NOT IN (
              SELECT transaction_id FROM ledger_entries
              WHERE transaction_id IS NOT NULL AND is_passthrough = 1
          )
        ORDER BY c_tx.txn_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
