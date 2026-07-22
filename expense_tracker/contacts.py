"""Core domain logic for Contacts and Ledger Management."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_aliases(raw_aliases: str | list[str]) -> list[str]:
    if isinstance(raw_aliases, list):
        items = raw_aliases
    else:
        items = [a.strip() for a in raw_aliases.split(",") if a.strip()]
    cleaned = []
    for item in items:
        norm = item.strip().lower()
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def create_contact(
    conn: sqlite3.Connection,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> int:
    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Contact name cannot be empty.")
    
    aliases_list = split_aliases(aliases)
    aliases_json = json.dumps(aliases_list)
    now = utc_now()
    
    cur = conn.execute(
        """
        INSERT INTO contacts (name, aliases_json, notes, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name_clean, aliases_json, notes, now),
    )
    conn.commit()
    logger.info("Created contact '%s' (id=%d)", name_clean, cur.lastrowid)
    return cur.lastrowid


def update_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    name: str,
    aliases: str | list[str] = "",
    notes: str | None = None,
) -> None:
    name_clean = name.strip()
    if not name_clean:
        raise ValueError("Contact name cannot be empty.")
    
    aliases_list = split_aliases(aliases)
    aliases_json = json.dumps(aliases_list)
    
    conn.execute(
        """
        UPDATE contacts
        SET name = ?, aliases_json = ?, notes = ?
        WHERE id = ?
        """,
        (name_clean, aliases_json, notes, contact_id),
    )
    conn.commit()


def get_all_contacts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM contacts ORDER BY name ASC").fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d["aliases_json"])
        except Exception:
            d["aliases"] = []
        results.append(d)
    return results


def find_contact_by_text(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Resolve contact by scored matching (prefer hubs/aliases over merchant fragments)."""
    try:
        from .settlement import resolve_contact

        return resolve_contact(conn, text)
    except Exception:
        # Fallback legacy first-match
        text_lower = (text or "").lower()
        contacts = get_all_contacts(conn)
        for c in contacts:
            if c["name"].lower() in text_lower:
                return c
            for alias in c["aliases"]:
                if alias in text_lower:
                    return c
        return None


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
    try:
        amt = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError("Invalid amount specified for ledger entry.")
    
    if amt <= 0:
        raise ValueError("Ledger entry amount must be greater than zero.")
    
    if direction not in {"you_sent", "they_sent"}:
        raise ValueError("Direction must be 'you_sent' or 'they_sent'.")
    
    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    now = utc_now()
    # Dual-write direction + entry_type for legacy and current readers.
    # Schema is normalized by migrate_ledger_schema() on connect/init_db.
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(ledger_entries)").fetchall()
    }
    fields = ["contact_id", "transaction_id", "amount", "purpose", "notes", "entry_date", "created_by", "created_at"]
    values: list[Any] = [
        contact_id,
        transaction_id,
        str(amt),
        purpose or "other",
        notes,
        entry_date,
        created_by,
        now,
    ]
    if "direction" in cols:
        fields.insert(2, "direction")
        values.insert(2, direction)
    if "entry_type" in cols:
        # Keep entry_type adjacent to direction when both exist
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
        src = "user"
        if created_by == "auto":
            src = "auto_migrate"
        if is_passthrough:
            src = "auto_passthrough"
        if purpose == "settlement":
            src = "settlement"
        if purpose == "shared" and created_by == "auto":
            src = "auto_shared"
        fields.append("source")
        values.append(src)

    placeholders = ", ".join("?" for _ in fields)
    col_sql = ", ".join(fields)
    cur = conn.execute(
        f"INSERT INTO ledger_entries ({col_sql}) VALUES ({placeholders})",
        tuple(values),
    )
    conn.commit()
    return cur.lastrowid


def calculate_contact_balance(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Balance for a contact. Uses USB (excl. pass-through) when SETTLEMENT_USB is on."""
    try:
        from .settlement import compute_unified_settlement, settlement_usb_enabled

        if settlement_usb_enabled():
            bal = compute_unified_settlement(
                conn, contact_id, include_virtual_shared=True
            )
            return {
                "contact_id": bal.contact_id,
                "net_balance": float(bal.net),
                "net": float(bal.net),
                "total_sent": float(bal.total_you_sent),
                "total_received": float(bal.total_they_sent),
                "total_you_sent": float(bal.total_you_sent),
                "total_they_sent": float(bal.total_they_sent),
                "status": bal.status,
                "entry_count": bal.entry_count,
                "ledger_net": float(bal.ledger_net),
                "virtual_shared_net": float(bal.virtual_shared_net),
                "passthrough_excluded_net": float(bal.passthrough_excluded_net),
            }
    except Exception:
        logger.debug("USB balance fallback to legacy for contact %s", contact_id, exc_info=True)

    # Legacy path (includes pass-through)
    has_void = "voided_at" in {
        r[1] for r in conn.execute("PRAGMA table_info(ledger_entries)").fetchall()
    }
    sql = """
        SELECT coalesce(direction, entry_type) as direction, amount, is_passthrough, is_opening_balance
        FROM ledger_entries
        WHERE contact_id = ?
    """
    if has_void:
        sql += " AND (voided_at IS NULL OR voided_at = '')"
    rows = conn.execute(sql, (contact_id,)).fetchall()

    total_sent = Decimal("0")
    total_received = Decimal("0")
    for r in rows:
        amt = Decimal(str(r["amount"]))
        if r["direction"] == "you_sent":
            total_sent += amt
        elif r["direction"] == "they_sent":
            total_received += amt

    net_balance = total_sent - total_received
    status = "settled"
    if net_balance > 0:
        status = "owes_you"
    elif net_balance < 0:
        status = "you_owe"

    return {
        "contact_id": contact_id,
        "net_balance": float(net_balance),
        "total_sent": float(total_sent),
        "total_received": float(total_received),
        "total_you_sent": float(total_sent),
        "total_they_sent": float(total_received),
        "status": status,
        "entry_count": len(rows),
    }


def get_contact_ledger(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    contact_row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not contact_row:
        raise ValueError(f"Contact id {contact_id} not found.")
    
    contact = dict(contact_row)
    try:
        contact["aliases"] = json.loads(contact["aliases_json"])
    except Exception:
        contact["aliases"] = []
        
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ledger_entries)").fetchall()}
    has_void = "voided_at" in cols
    try:
        from .settlement import merge_group_ids, settlement_usb_enabled

        group = merge_group_ids(conn, contact_id)
        usb = settlement_usb_enabled()
    except Exception:
        group = {contact_id}
        usb = False

    placeholders = ",".join("?" * len(group))
    sql = f"""
        SELECT l.*, coalesce(l.direction, l.entry_type) as direction,
               coalesce(l.entry_type, l.direction) as entry_type,
               t.merchant_display, t.description as tx_desc
        FROM ledger_entries l
        LEFT JOIN transactions t ON l.transaction_id = t.id
        WHERE l.contact_id IN ({placeholders})
    """
    if has_void:
        sql += " AND (l.voided_at IS NULL OR l.voided_at = '')"
    sql += " ORDER BY l.entry_date ASC, l.id ASC"
    rows = conn.execute(sql, tuple(group)).fetchall()

    running_balance = Decimal("0")
    entries = []
    for r in rows:
        amt = Decimal(str(r["amount"]))
        is_pt = bool(r["is_passthrough"])
        # Running balance excludes pass-through when USB is on
        if not (usb and is_pt):
            if r["direction"] == "you_sent":
                running_balance += amt
            else:
                running_balance -= amt

        entry_dict = dict(r)
        entry_dict["amount"] = float(amt)
        entry_dict["running_balance"] = float(running_balance)
        entries.append(entry_dict)

    balance_summary = calculate_contact_balance(conn, contact_id)

    return {
        "contact": contact,
        "balance": balance_summary,
        "entries": entries,
    }


def detect_passthrough_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Detect potential A -> You -> B pass-throughs. Never auto-creates contacts."""
    rows = conn.execute(
        """
        SELECT 
            c_tx.id as credit_tx_id, c_tx.txn_date as credit_date, c_tx.credit as credit_amount, c_tx.merchant_display as credit_merchant,
            d_tx.id as debit_tx_id, d_tx.txn_date as debit_date, d_tx.debit as debit_amount, d_tx.merchant_display as debit_merchant
        FROM transactions c_tx
        JOIN transactions d_tx ON c_tx.credit = d_tx.debit AND c_tx.credit > 0
        WHERE c_tx.id != d_tx.id
          AND abs(julianday(d_tx.txn_date) - julianday(c_tx.txn_date)) <= 2
          AND c_tx.id NOT IN (SELECT transaction_id FROM ledger_entries WHERE transaction_id IS NOT NULL AND is_passthrough = 1)
          AND d_tx.id NOT IN (SELECT transaction_id FROM ledger_entries WHERE transaction_id IS NOT NULL AND is_passthrough = 1)
        ORDER BY c_tx.txn_date DESC
        LIMIT 10
        """
    ).fetchall()

    candidates = []
    for r in rows:
        c_contact = find_contact_by_text(conn, r["credit_merchant"] or "")
        d_contact = find_contact_by_text(conn, r["debit_merchant"] or "")
        candidates.append({
            "credit_tx_id": r["credit_tx_id"],
            "credit_date": r["credit_date"],
            "credit_amount": float(Decimal(str(r["credit_amount"]))),
            "credit_merchant": r["credit_merchant"],
            "credit_contact": (c_contact["name"] if c_contact else (r["credit_merchant"] or "Unknown Sender")),
            "from_contact_id": (c_contact["id"] if c_contact else None),
            "debit_tx_id": r["debit_tx_id"],
            "debit_date": r["debit_date"],
            "debit_amount": float(Decimal(str(r["debit_amount"]))),
            "debit_merchant": r["debit_merchant"],
            "debit_contact": (d_contact["name"] if d_contact else (r["debit_merchant"] or "Unknown Recipient")),
            "to_contact_id": (d_contact["id"] if d_contact else None),
            "needs_link": c_contact is None or d_contact is None,
        })
    return candidates
