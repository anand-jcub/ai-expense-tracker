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
    text_lower = text.lower()
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
    cur = conn.execute(
        """
        INSERT INTO ledger_entries (
            contact_id, transaction_id, direction, entry_type, amount, purpose,
            is_passthrough, passthrough_pair_id, is_opening_balance,
            notes, entry_date, created_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            transaction_id,
            direction,
            direction,
            str(amt),
            purpose,
            int(is_passthrough),
            passthrough_pair_id,
            int(is_opening_balance),
            notes,
            entry_date,
            created_by,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid


def calculate_contact_balance(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT coalesce(direction, entry_type) as direction, amount, is_passthrough, is_opening_balance
        FROM ledger_entries
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchall()
    
    total_sent = Decimal("0")
    total_received = Decimal("0")
    
    for r in rows:
        amt = Decimal(str(r["amount"]))
        # Option to exclude passthrough entries from personal net balance if desired,
        # but counting you_sent vs they_sent gives exact net ledger position
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
        
    rows = conn.execute(
        """
        SELECT l.*, coalesce(l.direction, l.entry_type) as direction, coalesce(l.entry_type, l.direction) as entry_type, t.merchant_display, t.description as tx_desc
        FROM ledger_entries l
        LEFT JOIN transactions t ON l.transaction_id = t.id
        WHERE l.contact_id = ?
        ORDER BY l.entry_date ASC, l.id ASC
        """,
        (contact_id,),
    ).fetchall()
    
    running_balance = Decimal("0")
    entries = []
    for r in rows:
        amt = Decimal(str(r["amount"]))
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
    """Detect potential A -> You -> B pass-through transactions within 2 days of matching amounts."""
    # Find recent unlinked credit & debit pairs with matching amounts within 2 days
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
        c_contact = find_contact_by_text(conn, r["credit_merchant"])
        if not c_contact:
            c_name = r["credit_merchant"] or "Unknown Sender"
            cid = create_contact(conn, c_name)
            c_contact = {"id": cid, "name": c_name}
            
        d_contact = find_contact_by_text(conn, r["debit_merchant"])
        if not d_contact:
            d_name = r["debit_merchant"] or "Unknown Recipient"
            did = create_contact(conn, d_name)
            d_contact = {"id": did, "name": d_name}

        candidates.append({
            "credit_tx_id": r["credit_tx_id"],
            "credit_date": r["credit_date"],
            "credit_amount": float(Decimal(str(r["credit_amount"]))),
            "credit_merchant": r["credit_merchant"],
            "credit_contact": c_contact["name"],
            "from_contact_id": c_contact["id"],
            "debit_tx_id": r["debit_tx_id"],
            "debit_date": r["debit_date"],
            "debit_amount": float(Decimal(str(r["debit_amount"]))),
            "debit_merchant": r["debit_merchant"],
            "debit_contact": d_contact["name"],
            "to_contact_id": d_contact["id"],
        })
    return candidates
