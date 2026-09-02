"""Deterministic answers when GEMINI_API_KEY is missing. Uses the same tools."""

from __future__ import annotations

import re
from typing import Any

from .query import ask_books, parse_question
from .tools import parse_inr_amount, run_tool

_OWE = re.compile(
    r"(?:how much (?:does|do)\s+)?(?P<name>.+?)\s+(?:owe me|owes me)\??$",
    re.I,
)
_OWE_ALT = re.compile(
    r"(?:balance|khata|owe[sd]?)\s+(?:for|with|to)?\s*(?P<name>.+?)\??$",
    re.I,
)
_SPEND = re.compile(
    r"(?:what (?:did|have) i spend|how much (?:did|have) i spend|spent?)\s+"
    r"(?:on\s+)?(?P<cat>[a-z ]+?)(?:\s+this month)?\??$",
    re.I,
)
_WHO = re.compile(r"who owes|who do i owe|balances?\b", re.I)
_SEND_THRESH = re.compile(
    r"(?:when did i |did i )?(?:send|sent|gave|give|paid?)\s+"
    r"(?P<name>[A-Za-z]{2,40})"
    r".*?(?:greater than|greate than|more than|over|above|>)\s*"
    r"(?P<amt>[\d,.]+(?:\s*(?:k\b|lakh?s?|lacs?))?)",
    re.I,
)
# Exact amount: "50k", "50000", "1 lakh" — no comparator word required
_SEND_EXACT = re.compile(
    r"(?:when did i |did i )?(?:send|sent|gave|give|paid?)\s+"
    r"(?P<name>[A-Za-z]{2,40})"
    r".*?(?P<amt>[\d,.]+\s*(?:k\b|lakh?s?|lacs?)\b|[1-9][\d,.]{3,})",
    re.I,
)
# Bare send with "when did i" / "did i" prefix but no amount
_SEND_BARE = re.compile(
    r"(?:when did i |did i )(?:send|sent|gave|give|paid?)\s+"
    r"(?P<name>[A-Za-z]{2,40})(?:\s|$|[?.])",
    re.I,
)


def try_local(conn, username: str, message: str) -> dict[str, Any] | None:
    text = (message or "").strip()
    if not text:
        return None

    spec = parse_question(conn, text)
    if spec:
        data = ask_books(conn, spec)
        if data.get("answer"):
            return {
                "reply": data["answer"],
                "source": "local",
                "cards": [],
                "tool_used": "ask_books",
                "data": data,
                "model": "local",
            }

    m = _OWE.search(text) or (
        _OWE_ALT.search(text) if "owe" in text.lower() or "balance" in text.lower() else None
    )
    if m and m.group("name"):
        name = m.group("name").strip(" ?.")
        name = re.sub(r"^(does|do|for|with|to)\s+", "", name, flags=re.I).strip()
        if name and name.lower() not in {"me", "i", "who"}:
            data = run_tool(conn, username, "get_balance_for_person", {"name_or_id": name})
            return {
                "reply": data.get("answer") or data.get("error") or "No answer.",
                "source": "local",
                "cards": [],
                "tool_used": "get_balance_for_person",
                "data": data,
            }

    sm = _SPEND.search(text)
    if sm:
        cat = (sm.group("cat") or "").strip()
        cat = re.sub(r"\bthis month\b", "", cat, flags=re.I).strip()
        data = run_tool(
            conn,
            username,
            "get_dashboard_summary",
            {"category": cat.title() if cat else None},
        )
        match = data.get("category_match") if cat else None
        if match:
            reply = (
                f"You spent ₹{float(match.get('amount') or 0):,.2f} on {match.get('category')} "
                f"from {data.get('start_date')} to {data.get('end_date')} "
                f"(personal share, business excluded)."
            )
        else:
            reply = (
                f"This month: ₹{float(data.get('period_expense_share') or 0):,.2f} personal spend, "
                f"₹{float(data.get('period_debits') or 0):,.2f} debits "
                f"({data.get('start_date')}–{data.get('end_date')})."
            )
        return {
            "reply": reply,
            "source": "local",
            "cards": [],
            "tool_used": "get_dashboard_summary",
            "data": data,
        }

    # --- Threshold send: "sent Highnes more than 1 lakh" ---
    smatch = _SEND_THRESH.search(text)
    if smatch and smatch.group("name"):
        name = smatch.group("name").strip(" ?.")
        name = re.sub(r"\s+(amount|rs|inr)$", "", name, flags=re.I).strip()
        amt = parse_inr_amount(smatch.group("amt") or 0)
        if ("lakh" in text.lower() or "lak" in text.lower() or "lac" in text.lower()) and amt and amt < 1000:
            amt *= 100_000
        data = run_tool(conn, username, "find_sends_to_person", {"name_or_id": name, "min_amount": amt})
        return {
            "reply": data.get("answer") or data.get("error") or "No answer.",
            "source": "local",
            "cards": [],
            "tool_used": "find_sends_to_person",
            "data": data,
            "model": "local",
        }

    # --- Exact-amount send: "sent Highnes 50k", "paid Ranjima 50000" ---
    smatch = _SEND_EXACT.search(text)
    if smatch and smatch.group("name"):
        name = smatch.group("name").strip(" ?.")
        name = re.sub(r"\s+(amount|rs|inr)$", "", name, flags=re.I).strip()
        amt = parse_inr_amount(smatch.group("amt") or 0)
        if ("lakh" in text.lower() or "lak" in text.lower() or "lac" in text.lower()) and amt and amt < 1000:
            amt *= 100_000
        data = run_tool(conn, username, "find_sends_to_person", {"name_or_id": name, "exact_amount": amt})
        return {
            "reply": data.get("answer") or data.get("error") or "No answer.",
            "source": "local",
            "cards": [],
            "tool_used": "find_sends_to_person",
            "data": data,
            "model": "local",
        }

    # --- Bare send with temporal prefix: "when did i send Highnes" ---
    smatch = _SEND_BARE.search(text)
    if smatch and smatch.group("name"):
        name = smatch.group("name").strip(" ?.")
        data = run_tool(conn, username, "find_sends_to_person", {"name_or_id": name})
        return {
            "reply": data.get("answer") or data.get("error") or "No answer.",
            "source": "local",
            "cards": [],
            "tool_used": "find_sends_to_person",
            "data": data,
            "model": "local",
        }

    if _WHO.search(text):
        data = run_tool(conn, username, "list_balances", {"nonzero_only": True})
        rows = data.get("contacts") or []
        if not rows:
            reply = "No open person balances."
        else:
            bits = []
            for r in rows[:8]:
                net = float(r.get("net") or 0)
                name = r.get("contact_name")
                if net > 0:
                    bits.append(f"{name} owes you ₹{net:,.2f}")
                else:
                    bits.append(f"you owe {name} ₹{abs(net):,.2f}")
            reply = "; ".join(bits) + "."
        return {
            "reply": reply,
            "source": "local",
            "cards": [],
            "tool_used": "list_balances",
            "data": data,
        }

    return None
