"""Contacts + simple khata ledger (no USB / merge graph).

Balance rule (matches product use cases):
  net = sum(you_sent) − sum(they_sent)  for non-passthrough, non-void rows
  net > 0 → they owe you
  net < 0 → you owe them
  is_passthrough=1 rows are history only and never move net.
"""

from __future__ import annotations

import json
import logging
import re
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
    cleaned: list[str] = []
    for item in items:
        norm = item.strip().lower()
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def _d(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _direction_of(row) -> str:
    try:
        keys = row.keys() if hasattr(row, "keys") else []
        if "direction" in keys and row["direction"]:
            return str(row["direction"])
        if "entry_type" in keys and row["entry_type"]:
            return str(row["entry_type"])
    except Exception:
        pass
    if isinstance(row, dict):
        return str(row.get("direction") or row.get("entry_type") or "")
    return ""


# ── Contacts CRUD ────────────────────────────────────────────────────────────

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
    return int(cur.lastrowid)


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
    cols = _table_cols(conn, "contacts")
    sql = "SELECT * FROM contacts"
    if "merged_into_id" in cols:
        sql += " WHERE merged_into_id IS NULL"
    sql += " ORDER BY name ASC"
    rows = conn.execute(sql).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["aliases"] = json.loads(d.get("aliases_json") or "[]")
        except Exception:
            d["aliases"] = []
        results.append(d)
    return results


def _token_in_text(token: str, text: str) -> bool:
    """True if token appears as a whole word/token in text (not a bare substring).

    Prevents false merges like alias ``anand`` matching contact text ``ananthu``
    (Anand the app user ≠ Ananthu the person).
    """
    token = (token or "").strip().lower()
    text = (text or "").strip().lower()
    if not token or not text:
        return False
    if token == text:
        return True
    # Word boundary: not glued to another letter/digit on either side
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def find_contact_by_text(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Name/alias match with whole-token rules (Anand ≠ Ananthu).

    Prefers exact name, then longest token hit, then shorter hub names.
    """
    text_lower = (text or "").strip().lower()
    if not text_lower:
        return None

    contacts = get_all_contacts(conn)
    exact = [c for c in contacts if c["name"].lower() == text_lower]
    if exact:
        return exact[0]

    scored: list[tuple[int, int, dict]] = []
    for c in contacts:
        name = c["name"].lower()
        # Prefer matching the primary name token(s), not accidental substrings
        name_hit = 0
        if name and _token_in_text(name, text_lower):
            name_hit = len(name)
        else:
            # Multi-word bank names: score if any significant token hits
            for part in re.split(r"[^a-z0-9]+", name):
                if len(part) >= 4 and _token_in_text(part, text_lower):
                    name_hit = max(name_hit, len(part))
        if name_hit:
            scored.append((name_hit, -len(name), c))
            continue
        best_alias = 0
        for alias in c.get("aliases") or []:
            a = (alias or "").lower().strip()
            # Never treat bare "anand" as Ananthu (different person / app user)
            if a in {"anand"}:
                continue
            if a and _token_in_text(a, text_lower):
                best_alias = max(best_alias, len(a))
        if best_alias:
            scored.append((best_alias, -len(name), c))

    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


# ── Ledger writes ────────────────────────────────────────────────────────────

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
    cols = _table_cols(conn, "ledger_entries")
    fields = ["contact_id", "transaction_id", "amount", "purpose", "notes", "entry_date", "created_by", "created_at"]
    values: list[Any] = [
        contact_id,
        transaction_id,
        str(amt),
        purpose,
        notes,
        entry_date,
        created_by,
        now,
    ]
    # Dual-write direction + entry_type when present (legacy / current readers)
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

    from_row = conn.execute(
        "SELECT id, name FROM contacts WHERE id = ?", (int(from_contact_id),)
    ).fetchone()
    to_row = conn.execute(
        "SELECT id, name FROM contacts WHERE id = ?", (int(to_contact_id),)
    ).fetchone()
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
    row = conn.execute("SELECT id, name FROM contacts WHERE id = ?", (int(contact_id),)).fetchone()
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

    if amount is None or str(amount).strip() == "":
        settle_amt = abs(net)
    else:
        settle_amt = _d(amount)
        if settle_amt <= 0:
            raise ValueError("Settlement amount must be greater than zero.")
        if settle_amt > abs(net):
            settle_amt = abs(net)

    # If they owe you (net > 0), settlement is they_sent (money back to you).
    # If you owe them (net < 0), settlement is you_sent.
    direction = "they_sent" if net > 0 else "you_sent"
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
    cols = _table_cols(conn, "ledger_entries")
    if "voided_at" in cols:
        conn.execute(
            """
            UPDATE ledger_entries
            SET voided_at = ?, void_reason = ?
            WHERE id = ?
            """,
            (utc_now(), reason, int(entry_id)),
        )
        conn.commit()
        return
    conn.execute("DELETE FROM ledger_entries WHERE id = ?", (int(entry_id),))
    conn.commit()


# ── Balance / ledger reads ───────────────────────────────────────────────────

def get_balance(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    """Net excludes pass-throughs and voided rows."""
    cols = _table_cols(conn, "ledger_entries")
    sql = """
        SELECT coalesce(direction, entry_type) AS direction, amount, is_passthrough
        FROM ledger_entries
        WHERE contact_id = ?
          AND coalesce(is_passthrough, 0) = 0
    """
    if "voided_at" in cols:
        sql += " AND (voided_at IS NULL OR voided_at = '')"

    rows = conn.execute(sql, (int(contact_id),)).fetchall()
    you_sent = Decimal("0")
    they_sent = Decimal("0")
    for r in rows:
        amt = _d(r["amount"])
        if r["direction"] == "you_sent":
            you_sent += amt
        elif r["direction"] == "they_sent":
            they_sent += amt

    net = you_sent - they_sent
    if net > 0:
        status = "owes_you"
    elif net < 0:
        status = "you_owe"
    else:
        status = "settled"

    net_f = float(net)
    return {
        "contact_id": int(contact_id),
        "net": net_f,
        "net_balance": net_f,
        "you_sent": float(you_sent),
        "they_sent": float(they_sent),
        "total_sent": float(you_sent),
        "total_received": float(they_sent),
        "total_you_sent": float(you_sent),
        "total_they_sent": float(they_sent),
        "they_owe_you": float(max(net, Decimal("0"))),
        "you_owe_them": float(max(-net, Decimal("0"))),
        "status": status,
        "entry_count": len(rows),
        "ledger_net": net_f,
        "virtual_shared_net": 0.0,
        "passthrough_excluded_net": 0.0,
    }


def get_ledger(conn: sqlite3.Connection, contact_id: int) -> dict[str, Any]:
    contact_row = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (int(contact_id),)
    ).fetchone()
    if not contact_row:
        raise ValueError(f"Contact id {contact_id} not found.")

    contact = dict(contact_row)
    try:
        contact["aliases"] = json.loads(contact.get("aliases_json") or "[]")
    except Exception:
        contact["aliases"] = []

    cols = _table_cols(conn, "ledger_entries")
    sql = """
        SELECT l.*,
               coalesce(l.direction, l.entry_type) AS direction,
               coalesce(l.entry_type, l.direction) AS entry_type,
               t.merchant_display, t.description AS tx_desc
        FROM ledger_entries l
        LEFT JOIN transactions t ON l.transaction_id = t.id
        WHERE l.contact_id = ?
    """
    if "voided_at" in cols:
        sql += " AND (l.voided_at IS NULL OR l.voided_at = '')"
    sql += " ORDER BY l.entry_date ASC, l.id ASC"

    rows = conn.execute(sql, (int(contact_id),)).fetchall()
    running = Decimal("0")
    entries: list[dict[str, Any]] = []
    for r in rows:
        amt = _d(r["amount"])
        direction = _direction_of(r)
        is_pt = bool(r["is_passthrough"])
        # Running balance excludes pass-through (same rule as net)
        if not is_pt:
            if direction == "you_sent":
                running += amt
            elif direction == "they_sent":
                running -= amt

        entry = dict(r)
        entry["amount"] = float(amt)
        entry["direction"] = direction
        entry["running_balance"] = float(running)
        entries.append(entry)

    balance = get_balance(conn, int(contact_id))
    balance["contact_name"] = contact.get("name")
    return {
        "contact": contact,
        "balance": balance,
        "entries": entries,
    }


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
    """A→you→B candidates. Never auto-creates contacts."""
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
        LIMIT 10
        """
    ).fetchall()

    candidates = []
    for r in rows:
        c_contact = find_contact_by_text(conn, r["credit_merchant"] or "")
        d_contact = find_contact_by_text(conn, r["debit_merchant"] or "")
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


# Backward-compatible aliases used by older call sites / tests
calculate_contact_balance = get_balance
get_contact_ledger = get_ledger
