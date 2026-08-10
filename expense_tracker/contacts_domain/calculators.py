"""Pure Domain & Financial Calculation Layer.

Free of SQLite dependencies. Performs string splitting, token matching,
scoring, alias parsing, net balance arithmetic, running ledger assembly,
and settlement rule calculations.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def utc_now() -> str:
    """Returns current UTC timestamp formatted in ISO 8601 (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_aliases(raw_aliases: str | list[str]) -> list[str]:
    """Parses a comma-separated string or list of aliases into clean deduplicated strings."""
    if isinstance(raw_aliases, list):
        items = raw_aliases
    else:
        items = [a.strip() for a in str(raw_aliases or "").split(",") if a.strip()]
    cleaned: list[str] = []
    for item in items:
        norm = item.strip().lower()
        if norm and norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def _d(value: Any) -> Decimal:
    """Defensive Decimal converter defaulting to Decimal('0')."""
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _direction_of(row: Any) -> str:
    """Safely extracts direction key ('direction' or 'entry_type') from a row dict/Row object."""
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
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def _score_contact_match(c: dict[str, Any], text_lower: str) -> tuple[int, int] | None:
    """Scores a single contact against search text using token matching rules.

    Returns tuple (hit_score, -len(name)) if matched, or None if no match.
    """
    name = (c.get("name") or "").lower()
    name_hit = 0
    if name and _token_in_text(name, text_lower):
        name_hit = len(name)
    else:
        for part in re.split(r"[^a-z0-9]+", name):
            if len(part) >= 2 and _token_in_text(part, text_lower):
                name_hit = max(name_hit, len(part))
    if name_hit:
        return (name_hit, -len(name))

    best_alias = 0
    for alias in c.get("aliases") or []:
        a = (alias or "").lower().strip()
        if a in {"anand"}:
            continue
        if a and _token_in_text(a, text_lower):
            best_alias = max(best_alias, len(a))
    if best_alias:
        return (best_alias, -len(name))

    return None


def _match_contact_from_list(contacts: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    """Pure domain function matching text against a pre-fetched list of contacts."""
    text_lower = (text or "").strip().lower()
    if not text_lower:
        return None

    exact = [c for c in contacts if (c.get("name") or "").lower() == text_lower]
    if exact:
        return exact[0]

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for c in contacts:
        score = _score_contact_match(c, text_lower)
        if score is not None:
            scored.append((score[0], score[1], c))

    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def _parse_contact_aliases(contact: dict[str, Any]) -> dict[str, Any]:
    """Pure helper to parse JSON aliases string into a Python list on a contact dict."""
    res = dict(contact)
    try:
        res["aliases"] = json.loads(res.get("aliases_json") or "[]")
    except Exception:
        res["aliases"] = []
    return res


def _calculate_net_balance(contact_id: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure financial calculation of net balance and status from ledger rows."""
    you_sent = Decimal("0")
    they_sent = Decimal("0")
    for r in rows:
        amt = _d(r.get("amount") if isinstance(r, dict) else r["amount"])
        direction = _direction_of(r)
        if direction == "you_sent":
            you_sent += amt
        elif direction == "they_sent":
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


def _build_running_ledger(
    contact: dict[str, Any],
    raw_entries: list[dict[str, Any]],
    balance: dict[str, Any],
) -> dict[str, Any]:
    """Pure function computing itemized running balances for a contact ledger."""
    running = Decimal("0")
    entries: list[dict[str, Any]] = []
    for r in raw_entries:
        amt = _d(r.get("amount"))
        direction = _direction_of(r)
        is_pt = bool(r.get("is_passthrough"))
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

    balance["contact_name"] = contact.get("name")
    return {
        "contact": contact,
        "balance": balance,
        "entries": entries,
    }


def _determine_settlement_params(
    net: Decimal,
    amount: Decimal | float | str | None = None,
) -> tuple[Decimal, str]:
    """Pure domain logic calculating settlement amount and compensating direction."""
    if amount is None or str(amount).strip() == "":
        settle_amt = abs(net)
    else:
        settle_amt = _d(amount)
        if settle_amt <= 0:
            raise ValueError("Settlement amount must be greater than zero.")
        if settle_amt > abs(net):
            settle_amt = abs(net)

    direction = "they_sent" if net > 0 else "you_sent"
    return settle_amt, direction
