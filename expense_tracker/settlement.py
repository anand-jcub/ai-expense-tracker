"""Unified Settlement Balance (USB): khata + virtual shared expenses.

See docs/unified-settlement-model.md for the full design.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

BANK_TOKENS = {
    "sibl", "sbin", "icic", "hdfc", "yesb", "utib", "dbss", "ppiw",
    "cnrb", "ubin", "axis", "payme", "paytm", "gpay", "phonepe",
}

MERCHANT_PREFIX_RE = re.compile(r"^(dr|cr)\s+", re.I)


def settlement_usb_enabled() -> bool:
    v = os.environ.get("SETTLEMENT_USB", "1").strip().lower()
    return v not in {"0", "false", "off", "no"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _d(value) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _row_get(row, key: str, default=None):
    try:
        if hasattr(row, "keys") and key in row.keys():
            return row[key]
    except Exception:
        pass
    if isinstance(row, dict):
        return row.get(key, default)
    return default


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SettlementLine:
    kind: str
    direction: str
    amount: Decimal
    date: str | None
    purpose: str | None
    transaction_id: int | None
    ledger_entry_id: int | None
    notes: str | None
    counts_toward_net: bool = True
    source: str | None = None


@dataclass
class SettlementBalance:
    contact_id: int
    contact_name: str
    net: Decimal
    net_balance: Decimal
    they_owe_you: Decimal
    you_owe_them: Decimal
    status: str
    ledger_net: Decimal
    virtual_shared_net: Decimal
    passthrough_excluded_net: Decimal
    total_you_sent: Decimal
    total_they_sent: Decimal
    entry_count: int
    lines: list[SettlementLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)


# ── Partner share (single net base) ──────────────────────────────────────────

def net_debit(row) -> Decimal:
    """Bank debit minus transaction_links offsets."""
    debit = _d(_row_get(row, "debit", 0))
    offset = _d(_row_get(row, "debit_offset", 0))
    return max(Decimal("0"), debit - offset)


def partner_share_for_row(row) -> Decimal:
    """Residual after my share on the same net base. Single partner only."""
    base = net_debit(row)
    if base <= 0:
        return Decimal("0.00")
    expense_type = _row_get(row, "expense_type") or ""
    if expense_type in {"Loan", "Transfer"}:
        return Decimal("0.00")
    ratio = _d(_row_get(row, "split_ratio", 1))
    if ratio < 1:
        my = (base * ratio).quantize(Decimal("0.01"))
    else:
        my = base.quantize(Decimal("0.01"))
    return max(Decimal("0"), (base - my).quantize(Decimal("0.01")))


# ── Identity / merge ─────────────────────────────────────────────────────────

def _contact_aliases(contact: dict) -> list[str]:
    raw = contact.get("aliases")
    if isinstance(raw, list):
        return [str(a).lower() for a in raw if a]
    try:
        return [str(a).lower() for a in json.loads(contact.get("aliases_json") or "[]") if a]
    except Exception:
        return []


def is_merchant_shaped(name: str, aliases: list[str] | None = None) -> bool:
    aliases = aliases or []
    if aliases:
        return False
    n = (name or "").strip().lower()
    if not n:
        return False
    tokens = re.split(r"\s+", n)
    if len(tokens) >= 2:
        return True
    if MERCHANT_PREFIX_RE.match(n):
        return True
    for t in tokens:
        if t in BANK_TOKENS:
            return True
    return False


def is_hub_contact(contact: dict) -> bool:
    aliases = _contact_aliases(contact)
    notes = (contact.get("notes") or "").strip()
    linked = (contact.get("linked_username") or "").strip()
    return bool(aliases or notes or linked)


def canonical_contact_id(conn: sqlite3.Connection, contact_id: int) -> int:
    seen: set[int] = set()
    cid = contact_id
    while cid and cid not in seen:
        seen.add(cid)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
        if "merged_into_id" not in cols:
            return cid
        row = conn.execute(
            "SELECT id, merged_into_id FROM contacts WHERE id = ?", (cid,)
        ).fetchone()
        if not row:
            return cid
        mid = row["merged_into_id"] if "merged_into_id" in row.keys() else None
        if mid is None:
            return int(row["id"])
        cid = int(mid)
    return contact_id


def merge_group_ids(conn: sqlite3.Connection, contact_id: int) -> set[int]:
    can = canonical_contact_id(conn, contact_id)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    ids = {can}
    if "merged_into_id" in cols:
        for r in conn.execute(
            "SELECT id FROM contacts WHERE merged_into_id = ? OR id = ?",
            (can, can),
        ):
            ids.add(int(r["id"]))
    else:
        ids.add(can)
    return ids


def _normalize_merchant_text(text: str) -> str:
    t = (text or "").lower().strip()
    t = MERCHANT_PREFIX_RE.sub("", t)
    for tok in BANK_TOKENS:
        t = re.sub(rf"\b{re.escape(tok)}\b", " ", t)
    t = re.sub(r"[^a-z0-9@.\s]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def resolve_contact(conn: sqlite3.Connection, text: str) -> dict[str, Any] | None:
    """Scored contact resolution. Prefer hubs/aliases over merchant-shaped fragments."""
    if not text or not str(text).strip():
        return None
    query = str(text).strip()
    q_lower = query.lower()
    q_norm = _normalize_merchant_text(query)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    has_merged = "merged_into_id" in cols
    has_linked = "linked_username" in cols

    rows = conn.execute("SELECT * FROM contacts ORDER BY id ASC").fetchall()
    candidates: list[tuple[float, dict]] = []

    for r in rows:
        c = dict(r)
        if has_merged and c.get("merged_into_id"):
            continue
        try:
            c["aliases"] = json.loads(c.get("aliases_json") or "[]")
        except Exception:
            c["aliases"] = []
        name = (c.get("name") or "").strip()
        name_l = name.lower()
        aliases = [str(a).lower() for a in c["aliases"] if a]
        hub = is_hub_contact(c)
        merchant = is_merchant_shaped(name, aliases)
        linked = (c.get("linked_username") or "").strip().lower() if has_linked else ""

        base = 0.0
        if name_l == q_lower:
            if hub:
                base = 100.0
            elif merchant:
                base = 55.0
            else:
                base = 80.0  # short person name, empty alias
        elif any(a == q_lower for a in aliases):
            base = 95.0
        elif linked and linked == q_lower:
            base = 90.0
        else:
            name_norm = _normalize_merchant_text(name)
            alias_norms = [_normalize_merchant_text(a) for a in aliases]
            if q_norm and (q_norm == name_norm or q_norm in alias_norms):
                base = 85.0
            else:
                # token containment
                q_tokens = set(re.split(r"\s+", q_norm)) - {""}
                a_tokens = set()
                for a in aliases:
                    a_tokens |= set(re.split(r"\s+", _normalize_merchant_text(a))) - {""}
                n_tokens = set(re.split(r"\s+", name_norm)) - {""}
                if q_tokens and (q_tokens <= a_tokens or q_tokens <= n_tokens or a_tokens & q_tokens):
                    base = 70.0
                elif q_lower in name_l or name_l in q_lower or any(a in q_lower or q_lower in a for a in aliases):
                    base = 40.0

        if base <= 0:
            continue

        score = base
        if hub:
            score += 15.0
        if merchant and not aliases:
            score -= 10.0
        score = max(0.0, min(100.0, score))
        candidates.append((score, c))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], x[1]["id"]))
    best_score, best = candidates[0]

    # Hub override: if top is fragment but a hub scores >= 70, prefer hub
    if not is_hub_contact(best) and is_merchant_shaped(best.get("name") or "", _contact_aliases(best)):
        for score, c in candidates:
            if is_hub_contact(c) and score >= 70:
                best = c
                best_score = score
                break

    # PT guard: never silent-pick name == merchant when a hub alias matches
    if best.get("name", "").lower() == q_lower and not is_hub_contact(best):
        for score, c in candidates:
            if is_hub_contact(c) and score >= 70:
                best = c
                best_score = score
                break

    if best_score < 40:
        return None

    best = dict(best)
    best["score"] = best_score
    best["canonical_id"] = canonical_contact_id(conn, int(best["id"]))
    return best


# ── Ledger helpers ───────────────────────────────────────────────────────────

def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _direction(row) -> str:
    return (row["direction"] if "direction" in row.keys() and row["direction"]
            else row["entry_type"] if "entry_type" in row.keys() else "") or ""


def posted_txn_ids_for_contact(conn: sqlite3.Connection, contact_id: int) -> set[int]:
    ids = merge_group_ids(conn, contact_id)
    placeholders = ",".join("?" * len(ids))
    has_void = _has_column(conn, "ledger_entries", "voided_at")
    sql = f"""
        SELECT transaction_id, purpose, is_passthrough
               {", voided_at" if has_void else ""}
        FROM ledger_entries
        WHERE contact_id IN ({placeholders})
          AND transaction_id IS NOT NULL
    """
    out: set[int] = set()
    for r in conn.execute(sql, tuple(ids)):
        if has_void and r["voided_at"]:
            continue
        if r["is_passthrough"]:
            continue
        if (r["purpose"] or "") == "settlement":
            continue
        out.add(int(r["transaction_id"]))
    return out


def _ledger_rows_for_contact(conn: sqlite3.Connection, contact_id: int, as_of: str | None = None):
    ids = merge_group_ids(conn, contact_id)
    placeholders = ",".join("?" * len(ids))
    has_void = _has_column(conn, "ledger_entries", "voided_at")
    has_source = _has_column(conn, "ledger_entries", "source")
    cols = "l.*"
    sql = f"""
        SELECT {cols}
        FROM ledger_entries l
        WHERE l.contact_id IN ({placeholders})
    """
    params: list[Any] = list(ids)
    if as_of:
        sql += " AND (l.entry_date IS NULL OR l.entry_date <= ?)"
        params.append(as_of)
    sql += " ORDER BY l.entry_date ASC, l.id ASC"
    return conn.execute(sql, params).fetchall(), has_void, has_source


# ── Core USB compute ─────────────────────────────────────────────────────────

def compute_unified_settlement(
    conn: sqlite3.Connection,
    contact_id: int,
    *,
    include_passthrough: bool = False,  # v1 always excludes PT from net
    include_virtual_shared: bool = True,
    as_of: str | None = None,
) -> SettlementBalance:
    _ = include_passthrough  # reserved; product always excludes PT from net
    can = canonical_contact_id(conn, contact_id)
    crow = conn.execute("SELECT * FROM contacts WHERE id = ?", (can,)).fetchone()
    if not crow:
        raise ValueError(f"Contact id {contact_id} not found.")
    contact_name = crow["name"]

    rows, has_void, has_source = _ledger_rows_for_contact(conn, can, as_of)
    warnings: list[str] = []
    lines: list[SettlementLine] = []

    total_you = Decimal("0")
    total_they = Decimal("0")
    pt_excl = Decimal("0")
    entry_count = 0

    for r in rows:
        if has_void and r["voided_at"]:
            continue
        direction = _direction(r)
        amt = _d(r["amount"])
        is_pt = bool(r["is_passthrough"])
        purpose = r["purpose"] or "other"
        source = r["source"] if has_source and "source" in r.keys() else None
        signed = amt if direction == "you_sent" else -amt if direction == "they_sent" else Decimal("0")

        if is_pt:
            pt_excl += signed
            lines.append(SettlementLine(
                kind="passthrough_excluded",
                direction=direction or "they_sent",
                amount=amt,
                date=r["entry_date"],
                purpose=purpose,
                transaction_id=r["transaction_id"],
                ledger_entry_id=r["id"],
                notes=r["notes"],
                counts_toward_net=False,
                source=source,
            ))
            continue

        entry_count += 1
        if direction == "you_sent":
            total_you += amt
        elif direction == "they_sent":
            total_they += amt

        kind = "settlement" if purpose == "settlement" else (
            "opening" if r["is_opening_balance"] else "ledger"
        )
        lines.append(SettlementLine(
            kind=kind,
            direction=direction or "you_sent",
            amount=amt,
            date=r["entry_date"],
            purpose=purpose,
            transaction_id=r["transaction_id"],
            ledger_entry_id=r["id"],
            notes=r["notes"],
            counts_toward_net=True,
            source=source,
        ))

    ledger_net = total_you - total_they

    virtual_net = Decimal("0")
    if include_virtual_shared:
        virtual_net, v_lines, v_warn = _virtual_shared_for_contact(conn, can, as_of)
        lines.extend(v_lines)
        warnings.extend(v_warn)

    net = ledger_net + virtual_net
    if net > 0:
        status = "owes_you"
    elif net < 0:
        status = "you_owe"
    else:
        status = "settled"

    bal = SettlementBalance(
        contact_id=can,
        contact_name=contact_name,
        net=net,
        net_balance=net,
        they_owe_you=max(net, Decimal("0")),
        you_owe_them=max(-net, Decimal("0")),
        status=status,
        ledger_net=ledger_net,
        virtual_shared_net=virtual_net,
        passthrough_excluded_net=pt_excl,
        total_you_sent=total_you,
        total_they_sent=total_they,
        entry_count=entry_count,
        lines=lines,
        warnings=warnings,
    )
    bal.breakdown = _breakdown_from_lines(bal)
    return bal


def _virtual_shared_for_contact(
    conn: sqlite3.Connection,
    contact_id: int,
    as_of: str | None = None,
) -> tuple[Decimal, list[SettlementLine], list[str]]:
    warnings: list[str] = []
    lines: list[SettlementLine] = []
    total = Decimal("0")
    can = canonical_contact_id(conn, contact_id)
    posted = posted_txn_ids_for_contact(conn, can)
    group = merge_group_ids(conn, can)

    has_sw_id = _has_column(conn, "classifications", "shared_with_contact_id")
    has_sw = _has_column(conn, "classifications", "shared_with")
    if not has_sw and not has_sw_id:
        return total, lines, warnings

    # Resolve name/aliases for text matching
    crow = conn.execute("SELECT * FROM contacts WHERE id = ?", (can,)).fetchone()
    names = {(crow["name"] or "").lower()}
    try:
        for a in json.loads(crow["aliases_json"] or "[]"):
            names.add(str(a).lower())
    except Exception:
        pass
    for gid in group:
        if gid == can:
            continue
        gr = conn.execute("SELECT name, aliases_json FROM contacts WHERE id = ?", (gid,)).fetchone()
        if gr:
            names.add((gr["name"] or "").lower())
            try:
                for a in json.loads(gr["aliases_json"] or "[]"):
                    names.add(str(a).lower())
            except Exception:
                pass

    offset_sql = """
        SELECT t.id as transaction_id, t.txn_date, t.debit, t.credit, t.merchant_display,
               c.expense_type, c.split_ratio, c.my_share, c.shared_with,
               coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0) as debit_offset
        FROM transactions t
        JOIN classifications c ON c.transaction_id = t.id
        WHERE t.debit > 0
          AND c.expense_type = 'Shared'
    """
    # Filter external if column exists
    if _has_column(conn, "transactions", "is_external"):
        offset_sql += " AND coalesce(t.is_external, 0) = 0"

    rows = conn.execute(offset_sql).fetchall()
    for r in rows:
        if as_of and r["txn_date"] and r["txn_date"] > as_of:
            continue
        tid = int(r["transaction_id"])
        if tid in posted:
            continue

        attributed = False
        if has_sw_id and _has_column(conn, "classifications", "shared_with_contact_id"):
            # re-fetch if needed — may not be in select
            pass
        # Check shared_with_contact_id via separate query if column exists
        if has_sw_id:
            swid_row = conn.execute(
                "SELECT shared_with_contact_id FROM classifications WHERE transaction_id = ?",
                (tid,),
            ).fetchone()
            swid = swid_row["shared_with_contact_id"] if swid_row else None
            if swid is not None and int(swid) in group:
                attributed = True

        if not attributed and has_sw:
            sw = (r["shared_with"] or "").strip().lower()
            if sw and (sw in names or any(n and n in sw for n in names if n)):
                # Prefer resolve_contact for accuracy
                match = resolve_contact(conn, r["shared_with"] or "")
                if match and match["canonical_id"] == can:
                    attributed = True
                elif sw in names:
                    attributed = True

        if not attributed:
            continue

        share = partner_share_for_row(r)
        if share <= 0:
            continue
        total += share
        lines.append(SettlementLine(
            kind="virtual_shared",
            direction="you_sent",
            amount=share,
            date=r["txn_date"],
            purpose="shared",
            transaction_id=tid,
            ledger_entry_id=None,
            notes=f"Open shared: {r['merchant_display']}",
            counts_toward_net=True,
            source="virtual",
        ))

    return total, lines, warnings


def _breakdown_from_lines(bal: SettlementBalance) -> dict[str, float]:
    return {
        "ledger_net": float(bal.ledger_net),
        "shared_open": float(bal.virtual_shared_net),
        "passthrough_excluded": float(bal.passthrough_excluded_net),
        "they_owe_you": float(bal.they_owe_you),
        "you_owe_them": float(bal.you_owe_them),
    }


def settlement_to_json(bal: SettlementBalance) -> dict[str, Any]:
    return {
        "contact_id": bal.contact_id,
        "contact_name": bal.contact_name,
        "net": float(bal.net),
        "net_balance": float(bal.net),
        "they_owe_you": float(bal.they_owe_you),
        "you_owe_them": float(bal.you_owe_them),
        "status": bal.status,
        "ledger_net": float(bal.ledger_net),
        "virtual_shared_net": float(bal.virtual_shared_net),
        "passthrough_excluded_net": float(bal.passthrough_excluded_net),
        "total_you_sent": float(bal.total_you_sent),
        "total_they_sent": float(bal.total_they_sent),
        "entry_count": bal.entry_count,
        "lines": [
            {
                k: (float(v) if isinstance(v, Decimal) else v)
                for k, v in asdict(line).items()
            }
            for line in bal.lines
        ],
        "warnings": list(bal.warnings),
        "breakdown": bal.breakdown or _breakdown_from_lines(bal),
    }


def summary_all_contacts(conn: sqlite3.Connection) -> list[SettlementBalance]:
    """USB for all non-merged contacts with non-zero net or any activity."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    if "merged_into_id" in cols:
        rows = conn.execute(
            "SELECT id FROM contacts WHERE merged_into_id IS NULL ORDER BY name"
        ).fetchall()
    else:
        rows = conn.execute("SELECT id FROM contacts ORDER BY name").fetchall()
    out: list[SettlementBalance] = []
    for r in rows:
        bal = compute_unified_settlement(conn, int(r["id"]))
        if bal.net != 0 or bal.entry_count > 0 or bal.virtual_shared_net != 0 or bal.passthrough_excluded_net != 0:
            out.append(bal)
    return out


def record_rolling_chain(
    conn: sqlite3.Connection,
    from_contact_id: int,
    to_contact_id: int,
    amount: Decimal | float | str,
    entry_date: str | None = None,
    notes: str | None = None,
    created_by: str = "user",
) -> dict[str, Any]:
    """Post a pure A → You → B rolling chain as two linked pass-through legs.

    - from_contact: money received from (they_sent, PT)
    - to_contact: money forwarded to (you_sent, PT)

    Neither contact's USB net should move for a pure roll (PT excluded from net).
    """
    from .contacts import add_ledger_entry

    from_id = canonical_contact_id(conn, int(from_contact_id))
    to_id = canonical_contact_id(conn, int(to_contact_id))
    if from_id == to_id:
        raise ValueError("From and To contacts must be different.")
    try:
        amt = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError("Invalid amount.")
    if amt <= 0:
        raise ValueError("Amount must be greater than zero.")

    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from_row = conn.execute("SELECT name FROM contacts WHERE id = ?", (from_id,)).fetchone()
    to_row = conn.execute("SELECT name FROM contacts WHERE id = ?", (to_id,)).fetchone()
    if not from_row or not to_row:
        raise ValueError("Contact not found.")

    note_from = notes or f"Rolling via me → {to_row['name']}"
    note_to = notes or f"Rolling via me ← {from_row['name']}"

    e1 = add_ledger_entry(
        conn,
        contact_id=from_id,
        direction="they_sent",
        amount=amt,
        purpose="rolling",
        is_passthrough=True,
        notes=note_from,
        entry_date=entry_date,
        created_by=created_by,
    )
    e2 = add_ledger_entry(
        conn,
        contact_id=to_id,
        direction="you_sent",
        amount=amt,
        purpose="rolling",
        is_passthrough=True,
        passthrough_pair_id=e1,
        notes=note_to,
        entry_date=entry_date,
        created_by=created_by,
    )
    # Ensure source stamp
    if _has_column(conn, "ledger_entries", "source"):
        conn.execute(
            "UPDATE ledger_entries SET source = 'user_rolling' WHERE id IN (?, ?)",
            (e1, e2),
        )
        conn.commit()

    logger.info(
        "Rolling chain %s: %s → you → %s amount=%s legs=%s,%s",
        entry_date, from_row["name"], to_row["name"], amt, e1, e2,
    )
    return {
        "from_contact_id": from_id,
        "from_contact_name": from_row["name"],
        "to_contact_id": to_id,
        "to_contact_name": to_row["name"],
        "amount": float(amt),
        "entry_date": entry_date,
        "leg_from_id": e1,
        "leg_to_id": e2,
        "from_balance": settlement_to_json(compute_unified_settlement(conn, from_id)),
        "to_balance": settlement_to_json(compute_unified_settlement(conn, to_id)),
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
    """One-click opening / stock balance for a person.

    they_owe_you=True  → you_sent (they owe you more)
    they_owe_you=False → they_sent (you owe them more)
    """
    from .contacts import add_ledger_entry

    cid = canonical_contact_id(conn, int(contact_id))
    try:
        amt = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError("Invalid amount.")
    if amt <= 0:
        raise ValueError("Amount must be greater than zero.")

    if not entry_date:
        entry_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    crow = conn.execute("SELECT name FROM contacts WHERE id = ?", (cid,)).fetchone()
    if not crow:
        raise ValueError("Contact not found.")

    direction = "you_sent" if they_owe_you else "they_sent"
    default_note = (
        f"Opening: {crow['name']} owes me ₹{amt}"
        if they_owe_you
        else f"Opening: I owe {crow['name']} ₹{amt}"
    )
    eid = add_ledger_entry(
        conn,
        contact_id=cid,
        direction=direction,
        amount=amt,
        purpose="loan",
        is_opening_balance=True,
        notes=notes or default_note,
        entry_date=entry_date,
        created_by=created_by,
    )
    if _has_column(conn, "ledger_entries", "source"):
        conn.execute(
            "UPDATE ledger_entries SET source = 'opening' WHERE id = ?",
            (eid,),
        )
        conn.commit()

    bal = compute_unified_settlement(conn, cid)
    return {
        "ledger_entry_id": eid,
        "contact_id": cid,
        "contact_name": crow["name"],
        "direction": direction,
        "amount": float(amt),
        "balance": settlement_to_json(bal),
    }


def suggest_loan_posts(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    """Suggest posting bank debits as khata loans when merchant matches a contact.

    Suggest-only: never writes ledger. UI posts via /ledger/add after user confirm.
    """
    # Txns already on ledger
    posted = {
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT transaction_id FROM ledger_entries WHERE transaction_id IS NOT NULL"
        ).fetchall()
        if r[0] is not None
    }
    rows = conn.execute(
        """
        SELECT t.id, t.txn_date, t.debit, t.merchant_display, t.description,
               c.expense_type, c.status, c.category
        FROM transactions t
        JOIN classifications c ON c.transaction_id = t.id
        WHERE t.debit > 0
        ORDER BY t.txn_date DESC, t.id DESC
        LIMIT 80
        """
    ).fetchall()

    out: list[dict[str, Any]] = []
    seen_contacts: set[int] = set()
    for r in rows:
        tid = int(r["id"])
        if tid in posted:
            continue
        et = (r["expense_type"] or "").strip()
        # Prefer Loan type, or needs_review debits that match people
        merchant = r["merchant_display"] or r["description"] or ""
        match = resolve_contact(conn, merchant)
        if not match:
            continue
        cid = int(match["canonical_id"])
        # Avoid flooding with same contact
        key = (cid, float(_d(r["debit"])))
        if cid in seen_contacts and et != "Loan":
            continue
        if et not in {"Loan", "Transfer", "Personal", "Other"} and r["status"] != "needs_review":
            continue
        # Skip pure merchants that are hubs but look like businesses with high confidence auto
        if et in {"Personal", "Business"} and r["status"] == "auto" and et != "Loan":
            # only surface if name strongly matches (score high)
            if float(match.get("score") or 0) < 85:
                continue
        if et == "Business" and float(match.get("score") or 0) < 95:
            continue
        seen_contacts.add(cid)
        out.append({
            "transaction_id": tid,
            "txn_date": r["txn_date"],
            "amount": float(_d(r["debit"])),
            "merchant_display": r["merchant_display"],
            "contact_id": cid,
            "contact_name": match.get("name") or "Contact",
            "expense_type": et,
            "match_score": match.get("score"),
            "direction": "you_sent",  # you paid them → they owe you
            "purpose": "loan",
        })
        if len(out) >= limit:
            break
    return out


def suggest_merge_groups(conn: sqlite3.Connection, limit: int = 8) -> list[dict[str, Any]]:
    """Suggest contact clusters that look like the same person (for People merge UI).

    Winner prefers hub contacts (aliases/notes); losers are merchant-shaped fragments
    that share a significant name token with the winner.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    has_merged = "merged_into_id" in cols
    sql = "SELECT * FROM contacts"
    if has_merged:
        sql += " WHERE merged_into_id IS NULL"
    sql += " ORDER BY id ASC"
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    for c in rows:
        try:
            c["aliases"] = json.loads(c.get("aliases_json") or "[]")
        except Exception:
            c["aliases"] = []
        c["hub"] = is_hub_contact(c)
        c["merchant"] = is_merchant_shaped(c.get("name") or "", c["aliases"])
        # Significant tokens (>=4 chars) from name + aliases
        bag: set[str] = set()
        for part in [c.get("name") or ""] + list(c["aliases"]):
            norm = _normalize_merchant_text(str(part))
            for tok in re.split(r"\s+", norm):
                if len(tok) >= 4 and tok not in BANK_TOKENS:
                    bag.add(tok)
        c["tokens"] = bag

    # Union-find by shared tokens (only link hub↔fragment or fragment↔fragment when tokens overlap)
    parent = {c["id"]: c["id"] for c in rows}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    by_id = {c["id"]: c for c in rows}
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            shared = a["tokens"] & b["tokens"]
            if not shared:
                # also: one name contained in the other (len>=5)
                na = (a.get("name") or "").lower()
                nb = (b.get("name") or "").lower()
                if len(na) >= 5 and len(nb) >= 5 and (na in nb or nb in na):
                    union(a["id"], b["id"])
                continue
            # Prefer clusters that include at least one merchant-shaped or hub
            if a["hub"] or b["hub"] or a["merchant"] or b["merchant"]:
                union(a["id"], b["id"])

    clusters: dict[int, list[dict]] = {}
    for c in rows:
        clusters.setdefault(find(c["id"]), []).append(c)

    suggestions: list[dict[str, Any]] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        # Winner: hub first, then more aliases, then lower id
        members_sorted = sorted(
            members,
            key=lambda c: (
                0 if c["hub"] else 1,
                -len(c.get("aliases") or []),
                0 if not c["merchant"] else 1,
                c["id"],
            ),
        )
        winner = members_sorted[0]
        losers = members_sorted[1:]
        # Skip pure-hub clusters with no fragments (optional noise)
        if not any(m["merchant"] or not m["hub"] for m in losers) and winner["hub"]:
            # still useful if multiple short names
            if all(m["hub"] for m in members):
                continue
        suggestions.append({
            "winner_id": winner["id"],
            "winner_name": winner["name"],
            "loser_ids": [m["id"] for m in losers],
            "loser_names": [m["name"] for m in losers],
            "size": len(members),
            "reason": "Shared name tokens / similar labels",
        })

    suggestions.sort(key=lambda s: -s["size"])
    return suggestions[:limit]


def format_settlement_answer(bal: SettlementBalance) -> str:
    """NL: net + short breakdown."""
    name = bal.contact_name
    net = bal.net
    money = lambda x: f"₹{abs(float(x)):,.2f}".replace(".00", "")

    if net > 0:
        head = f"{name} owes you {money(net)}"
    elif net < 0:
        head = f"You owe {name} {money(abs(net))}"
    else:
        head = f"{name} is settled (₹0)"

    parts = []
    if bal.ledger_net != 0:
        parts.append(f"ledger {money(bal.ledger_net) if bal.ledger_net > 0 else '−' + money(abs(bal.ledger_net))}")
    if bal.virtual_shared_net != 0:
        parts.append(f"open shared {money(bal.virtual_shared_net)}")
    else:
        parts.append("no open shared")
    if bal.passthrough_excluded_net != 0:
        parts.append(f"rolling excluded {money(bal.passthrough_excluded_net)}")

    return f"{head} ({'; '.join(parts)})."


# ── Materialize & settle ─────────────────────────────────────────────────────

def materialize_virtual_shares(conn: sqlite3.Connection, contact_id: int) -> int:
    """Post virtual shared lines as ledger entries (idempotent). Returns count inserted."""
    from .contacts import add_ledger_entry

    bal = compute_unified_settlement(conn, contact_id, include_virtual_shared=True)
    inserted = 0
    for line in bal.lines:
        if line.kind != "virtual_shared" or not line.transaction_id:
            continue
        # Check existing auto_shared
        if _has_column(conn, "ledger_entries", "source"):
            existing = conn.execute(
                """
                SELECT id FROM ledger_entries
                WHERE contact_id = ? AND transaction_id = ?
                  AND coalesce(source, '') = 'auto_shared'
                  AND (voided_at IS NULL OR voided_at = '')
                """,
                (bal.contact_id, line.transaction_id),
            ).fetchone() if _has_column(conn, "ledger_entries", "voided_at") else conn.execute(
                """
                SELECT id FROM ledger_entries
                WHERE contact_id = ? AND transaction_id = ?
                  AND coalesce(source, '') = 'auto_shared'
                """,
                (bal.contact_id, line.transaction_id),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT id FROM ledger_entries
                WHERE contact_id = ? AND transaction_id = ?
                  AND purpose IN ('shared', 'food_split')
                  AND coalesce(is_passthrough, 0) = 0
                """,
                (bal.contact_id, line.transaction_id),
            ).fetchone()
        if existing:
            continue
        eid = add_ledger_entry(
            conn,
            contact_id=bal.contact_id,
            direction="you_sent",
            amount=line.amount,
            purpose="shared",
            transaction_id=line.transaction_id,
            notes=line.notes,
            entry_date=line.date,
            created_by="auto",
        )
        if _has_column(conn, "ledger_entries", "source"):
            conn.execute(
                "UPDATE ledger_entries SET source = 'auto_shared' WHERE id = ?",
                (eid,),
            )
            conn.commit()
        inserted += 1
        logger.info("Materialized shared share entry %s for contact %s txn %s",
                     eid, bal.contact_id, line.transaction_id)
    return inserted


def record_settlement(
    conn: sqlite3.Connection,
    contact_id: int,
    amount: Decimal | None = None,
    transaction_id: int | None = None,
    notes: str | None = None,
    created_by: str = "user",
) -> SettlementBalance:
    """Materialize virtual shares, then insert compensating settlement entry."""
    from .contacts import add_ledger_entry

    can = canonical_contact_id(conn, contact_id)
    # Path A: materialize first
    materialize_virtual_shares(conn, can)
    bal = compute_unified_settlement(conn, can)
    net = bal.net
    if net == 0:
        return bal

    settle_amt = abs(net) if amount is None else _d(amount)
    if settle_amt <= 0:
        raise ValueError("Settlement amount must be greater than zero.")
    if settle_amt > abs(net) + Decimal("0.001"):
        raise ValueError(f"Amount exceeds outstanding balance of ₹{abs(net):.2f}")

    # they_sent if net > 0 (they repay you); you_sent if net < 0 (you repay them)
    direction = "they_sent" if net > 0 else "you_sent"
    # Never link original shared debit — repayment only; caller responsibility
    note = notes or ("Settled balance" if amount is None else f"Partial settlement ₹{settle_amt}")
    eid = add_ledger_entry(
        conn,
        contact_id=can,
        direction=direction,
        amount=settle_amt,
        purpose="settlement",
        transaction_id=transaction_id,
        notes=note,
        entry_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        created_by=created_by,
    )
    if _has_column(conn, "ledger_entries", "source"):
        conn.execute(
            "UPDATE ledger_entries SET source = 'settlement' WHERE id = ?",
            (eid,),
        )
        conn.commit()
    return compute_unified_settlement(conn, can)


# ── Dedupe & merge ───────────────────────────────────────────────────────────

def dedupe_ledger_conflicts(
    conn: sqlite3.Connection,
    contact_id: int,
    *,
    auto_apply: bool = True,
) -> dict[str, Any]:
    """Find and optionally void duplicate ledger economics for a contact merge group."""
    can = canonical_contact_id(conn, contact_id)
    ids = merge_group_ids(conn, can)
    placeholders = ",".join("?" * len(ids))
    has_void = _has_column(conn, "ledger_entries", "voided_at")

    rows = conn.execute(
        f"""
        SELECT * FROM ledger_entries
        WHERE contact_id IN ({placeholders})
        ORDER BY id ASC
        """,
        tuple(ids),
    ).fetchall()

    # Group by (txn, direction, amount)
    groups: dict[tuple, list] = {}
    for r in rows:
        if has_void and r["voided_at"]:
            continue
        key = (
            r["transaction_id"],
            _direction(r),
            str(_d(r["amount"])),
        )
        if key[0] is None:
            continue
        groups.setdefault(key, []).append(r)

    conflicts = []
    voided = 0
    for key, group in groups.items():
        if len(group) < 2:
            continue
        pt = [r for r in group if r["is_passthrough"]]
        non_pt = [r for r in group if not r["is_passthrough"]]
        conflict = {
            "transaction_id": key[0],
            "direction": key[1],
            "amount": float(_d(key[2])),
            "entry_ids": [r["id"] for r in group],
            "has_pt": bool(pt),
            "has_non_pt": bool(non_pt),
        }
        conflicts.append(conflict)
        if not auto_apply or not has_void:
            continue
        # Keep PT, void migrate/non-PT siblings
        if pt and non_pt:
            keep_id = min(r["id"] for r in pt)
            for r in group:
                if r["id"] == keep_id:
                    continue
                if r["is_passthrough"] and r["id"] != keep_id:
                    # duplicate PT — void higher ids
                    conn.execute(
                        "UPDATE ledger_entries SET voided_at = ?, void_reason = ? WHERE id = ?",
                        (utc_now(), "duplicate_passthrough", r["id"]),
                    )
                    voided += 1
                elif not r["is_passthrough"]:
                    conn.execute(
                        "UPDATE ledger_entries SET voided_at = ?, void_reason = ? WHERE id = ?",
                        (utc_now(), "duplicate_of_passthrough", r["id"]),
                    )
                    voided += 1
        elif len(non_pt) >= 2:
            # keep newest user or highest id
            keep = max(non_pt, key=lambda r: (1 if (r["created_by"] or "") == "user" else 0, r["id"]))
            for r in non_pt:
                if r["id"] == keep["id"]:
                    continue
                conn.execute(
                    "UPDATE ledger_entries SET voided_at = ?, void_reason = ? WHERE id = ?",
                    (utc_now(), "duplicate_non_pt", r["id"]),
                )
                voided += 1
        elif len(pt) >= 2:
            keep_id = min(r["id"] for r in pt)
            for r in pt:
                if r["id"] == keep_id:
                    continue
                conn.execute(
                    "UPDATE ledger_entries SET voided_at = ?, void_reason = ? WHERE id = ?",
                    (utc_now(), "duplicate_passthrough", r["id"]),
                )
                voided += 1

    if auto_apply and voided:
        conn.commit()
        logger.info("Dedupe voided %d ledger rows for contact %s", voided, can)

    remaining = [c for c in conflicts] if not auto_apply else []
    if auto_apply:
        # re-scan
        return dedupe_ledger_conflicts(conn, can, auto_apply=False) | {
            "voided_count": voided,
            "auto_applied": True,
            "contact_id": can,
        }

    return {
        "contact_id": can,
        "conflicts": conflicts,
        "voided_count": 0,
        "auto_applied": False,
        "unresolved": len(conflicts),
    }


def merge_contacts(
    conn: sqlite3.Connection,
    winner_id: int,
    loser_ids: list[int],
    *,
    merge_batch_id: str | None = None,
    auto_dedupe: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Merge loser contacts into winner; reassign ledger; union aliases; dedupe."""
    if not _has_column(conn, "contacts", "merged_into_id"):
        raise ValueError("Schema missing merged_into_id; run migrations.")

    winner_id = canonical_contact_id(conn, winner_id)
    batch = merge_batch_id or str(uuid.uuid4())
    winners_aliases: list[str] = []
    wrow = conn.execute("SELECT * FROM contacts WHERE id = ?", (winner_id,)).fetchone()
    if not wrow:
        raise ValueError(f"Winner contact {winner_id} not found.")
    try:
        winners_aliases = json.loads(wrow["aliases_json"] or "[]")
    except Exception:
        winners_aliases = []

    reassigned = 0
    for lid in loser_ids:
        lid = int(lid)
        if lid == winner_id:
            continue
        lrow = conn.execute("SELECT * FROM contacts WHERE id = ?", (lid,)).fetchone()
        if not lrow:
            continue
        try:
            laliases = json.loads(lrow["aliases_json"] or "[]")
        except Exception:
            laliases = []
        # also add loser name as alias
        for a in laliases + [lrow["name"]]:
            al = str(a).strip().lower()
            if al and al not in [x.lower() for x in winners_aliases]:
                winners_aliases.append(al)

        cur = conn.execute(
            "UPDATE ledger_entries SET contact_id = ? WHERE contact_id = ?",
            (winner_id, lid),
        )
        reassigned += cur.rowcount
        # reassign shared_with_contact_id if present
        if _has_column(conn, "classifications", "shared_with_contact_id"):
            conn.execute(
                "UPDATE classifications SET shared_with_contact_id = ? WHERE shared_with_contact_id = ?",
                (winner_id, lid),
            )
        conn.execute(
            "UPDATE contacts SET merged_into_id = ?, merge_batch_id = ? WHERE id = ?",
            (winner_id, batch, lid),
        )

    conn.execute(
        "UPDATE contacts SET aliases_json = ? WHERE id = ?",
        (json.dumps(winners_aliases), winner_id),
    )
    conn.commit()

    dedupe_result = {"conflicts": [], "voided_count": 0, "unresolved": 0}
    if auto_dedupe:
        dedupe_result = dedupe_ledger_conflicts(conn, winner_id, auto_apply=True)

    unresolved = dedupe_result.get("unresolved", 0)
    if unresolved and not force:
        # still report success of merge but flag
        pass

    bal = compute_unified_settlement(conn, winner_id)
    return {
        "winner_id": winner_id,
        "loser_ids": loser_ids,
        "merge_batch_id": batch,
        "reassigned_ledger_rows": reassigned,
        "dedupe": dedupe_result,
        "balance": settlement_to_json(bal),
        "warnings": (
            ["Unresolved ledger conflicts remain"] if unresolved else []
        ),
    }


def upgrade_passthrough_siblings(
    conn: sqlite3.Connection,
    contact_id: int,
    transaction_id: int,
    direction: str,
    amount: Decimal,
) -> str:
    """On PT confirm: upgrade matching non-PT sibling or report conflict.

    Returns 'upgraded' | 'none' | 'conflict'.
    """
    if not _has_column(conn, "ledger_entries", "voided_at"):
        return "none"
    group = merge_group_ids(conn, contact_id)
    placeholders = ",".join("?" * len(group))
    rows = conn.execute(
        f"""
        SELECT * FROM ledger_entries
        WHERE contact_id IN ({placeholders})
          AND transaction_id = ?
          AND coalesce(is_passthrough, 0) = 0
          AND voided_at IS NULL
        """,
        (*group, transaction_id),
    ).fetchall()
    if not rows:
        return "none"
    for r in rows:
        d = _direction(r)
        if d == direction and abs(_d(r["amount"]) - _d(amount)) <= Decimal("0.05"):
            conn.execute(
                """
                UPDATE ledger_entries
                SET is_passthrough = 1, purpose = 'rolling',
                    source = coalesce(source, 'auto_passthrough')
                WHERE id = ?
                """,
                (r["id"],),
            )
            conn.commit()
            return "upgraded"
    return "conflict"
