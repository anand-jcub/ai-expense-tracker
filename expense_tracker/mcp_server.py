"""MCP server for the expense tracker (stdio).

Exposes read tools (and optional ledger write) over the same domain layer
as the HTTP app — no second balance engine.

Run (from repo root):
  .\\venv\\Scripts\\python.exe -m expense_tracker.mcp_server

Env:
  DATA_DIR           SQLite directory (default: ./data)
  EXPENSE_MCP_USER   Default username when tool arg omitted (e.g. anand)

Cursor / Claude Desktop config example: docs/mcp.md
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

# Repo root on path when run as script
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP

from expense_tracker.contacts import (
    add_ledger_entry,
    find_contact_by_text,
    get_all_balances,
    get_balance,
    get_ledger,
)
from expense_tracker.db import connect, dashboard_data
from expense_tracker.services import dashboard_totals, filter_dashboard_rows

mcp = FastMCP(
    "expense-tracker",
    instructions=(
        "Personal expense + khata tools. "
        "Balance sign: net > 0 means they owe the user; net < 0 means the user owes them. "
        "Pass-through/rolling amounts are excluded from net. "
        "Prefer list_balances / get_ledger for who-owes-whom; use get_dashboard_summary for spend charts."
    ),
)


def _data_dir() -> Path:
    raw = (os.environ.get("DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_ROOT / "data").resolve()


def _default_user() -> str | None:
    u = (os.environ.get("EXPENSE_MCP_USER") or "").strip().lower()
    return u or None


def _resolve_user(username: str | None) -> str:
    u = (username or "").strip().lower() or _default_user()
    if not u:
        raise ValueError(
            "username required (or set EXPENSE_MCP_USER env for a default user)."
        )
    return u


def _db_path(username: str) -> Path:
    return _data_dir() / f"expenses_{username.lower()}.db"


def _open(username: str):
    path = _db_path(username)
    if not path.is_file():
        raise FileNotFoundError(f"No database for user '{username}' at {path}")
    return connect(path)


def _month_bounds() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1).isoformat()
    if today.month == 12:
        from datetime import timedelta

        end = today.replace(year=today.year + 1, month=1, day=1)
        end = (end - timedelta(days=1)).isoformat()
    else:
        from datetime import timedelta

        end = today.replace(month=today.month + 1, day=1)
        end = (end - timedelta(days=1)).isoformat()
    return start, end


@mcp.tool()
def list_users() -> list[str]:
    """List usernames that have a local expenses_*.db database."""
    d = _data_dir()
    if not d.is_dir():
        return []
    users = []
    for f in sorted(d.glob("expenses_*.db")):
        name = f.stem.removeprefix("expenses_")
        if name:
            users.append(name)
    return users


@mcp.tool()
def list_balances(username: str | None = None, nonzero_only: bool = True) -> list[dict[str, Any]]:
    """List khata (who-owes-whom) balances for a user.

    net > 0: they owe you. net < 0: you owe them. Pass-through excluded.
    """
    user = _resolve_user(username)
    with _open(user) as conn:
        items = get_all_balances(conn)
    out = []
    for item in items:
        bal = item["balance"]
        net = float(bal.get("net") or 0)
        if nonzero_only and net == 0:
            continue
        out.append(
            {
                "contact_id": item["contact"]["id"],
                "contact_name": item["contact"]["name"],
                "net": net,
                "status": bal.get("status"),
                "they_owe_you": bal.get("they_owe_you"),
                "you_owe_them": bal.get("you_owe_them"),
                "entry_count": bal.get("entry_count"),
            }
        )
    out.sort(key=lambda r: abs(float(r["net"])), reverse=True)
    return out


@mcp.tool()
def get_balance_for_person(
    name_or_id: str,
    username: str | None = None,
) -> dict[str, Any]:
    """Get khata balance for one person by contact id or name/alias (e.g. Ranjima, Highnes)."""
    user = _resolve_user(username)
    with _open(user) as conn:
        contact = None
        if str(name_or_id).strip().isdigit():
            cid = int(str(name_or_id).strip())
            bal = get_balance(conn, cid)
            led = get_ledger(conn, cid)
            contact = led.get("contact")
        else:
            contact = find_contact_by_text(conn, name_or_id)
            if not contact:
                return {"error": f"No contact matching {name_or_id!r}"}
            bal = get_balance(conn, int(contact["id"]))
        return {
            "contact_id": bal.get("contact_id") or (contact or {}).get("id"),
            "contact_name": (contact or {}).get("name") or bal.get("contact_name"),
            "net": bal.get("net"),
            "status": bal.get("status"),
            "they_owe_you": bal.get("they_owe_you"),
            "you_owe_them": bal.get("you_owe_them"),
            "you_sent": bal.get("total_you_sent"),
            "they_sent": bal.get("total_they_sent"),
            "entry_count": bal.get("entry_count"),
            "answer": (
                f"{(contact or {}).get('name', 'They')} owes you ₹{bal['net']:,.2f}."
                if float(bal.get("net") or 0) > 0
                else (
                    f"You owe {(contact or {}).get('name', 'them')} ₹{abs(float(bal['net'])):,.2f}."
                    if float(bal.get("net") or 0) < 0
                    else f"{(contact or {}).get('name', 'Contact')} is settled (₹0)."
                )
            ),
        }


@mcp.tool()
def get_person_ledger(
    name_or_id: str,
    username: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Ledger history for a contact (newest first). Includes pass-through rows for audit."""
    user = _resolve_user(username)
    with _open(user) as conn:
        if str(name_or_id).strip().isdigit():
            cid = int(str(name_or_id).strip())
        else:
            contact = find_contact_by_text(conn, name_or_id)
            if not contact:
                return {"error": f"No contact matching {name_or_id!r}"}
            cid = int(contact["id"])
        payload = get_ledger(conn, cid)
    entries = list(reversed(payload.get("entries") or []))[: max(1, min(limit, 200))]
    slim = []
    for e in entries:
        slim.append(
            {
                "date": e.get("entry_date"),
                "direction": e.get("direction"),
                "amount": e.get("amount"),
                "purpose": e.get("purpose"),
                "is_passthrough": bool(e.get("is_passthrough")),
                "notes": e.get("notes"),
                "running_balance": e.get("running_balance"),
            }
        )
    bal = payload.get("balance") or {}
    return {
        "contact": {
            "id": (payload.get("contact") or {}).get("id"),
            "name": (payload.get("contact") or {}).get("name"),
        },
        "balance": {
            "net": bal.get("net"),
            "status": bal.get("status"),
        },
        "entries": slim,
    }


@mcp.tool()
def get_dashboard_summary(
    username: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    exclude_business: bool = True,
    use_current_month: bool = True,
) -> dict[str, Any]:
    """Spend summary for a period (same filters as classic Home dashboard).

    If start/end omitted and use_current_month is true, uses current calendar month.
    """
    user = _resolve_user(username)
    if not start_date and not end_date and use_current_month:
        start_date, end_date = _month_bounds()
    with _open(user) as conn:
        data = dashboard_data(conn)
        rows = filter_dashboard_rows(
            data.get("transactions") or [],
            start_date or "",
            end_date or "",
            exclude_business,
        )
        totals = dashboard_totals(rows, use_my_share=False)
        pending = data.get("pending") or []
    return {
        "username": user,
        "start_date": start_date,
        "end_date": end_date,
        "exclude_business": exclude_business,
        "period_credits": float(totals.get("credit") or 0),
        "period_debits": float(totals.get("debit") or 0),
        "period_expense_share": float(totals.get("expense_share") or 0),
        "transaction_count": len(rows),
        "needs_review_count": len(pending),
    }


@mcp.tool()
def search_transactions(
    query: str = "",
    username: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    exclude_business: bool = True,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Search bank transactions (optional period filter). Empty query = most recent in period."""
    user = _resolve_user(username)
    with _open(user) as conn:
        data = dashboard_data(conn)
        rows = filter_dashboard_rows(
            data.get("transactions") or [],
            start_date or "",
            end_date or "",
            exclude_business,
        )
    q = (query or "").strip().lower()
    out: list[dict[str, Any]] = []
    for t in rows:
        if q:
            blob = " ".join(
                str(t[k] or "")
                for k in ("merchant_display", "description", "category", "expense_type")
                if hasattr(t, "keys") and k in t.keys() or isinstance(t, dict)
            ).lower()
            if isinstance(t, dict):
                blob = " ".join(
                    str(t.get(k) or "")
                    for k in ("merchant_display", "description", "category", "expense_type")
                ).lower()
            else:
                blob = " ".join(
                    str(t[k] if k in t.keys() else "")
                    for k in ("merchant_display", "description", "category", "expense_type")
                ).lower()
            if q not in blob:
                continue
        out.append(
            {
                "id": t["id"] if not isinstance(t, dict) else t.get("id"),
                "date": t["txn_date"] if not isinstance(t, dict) else t.get("txn_date"),
                "merchant": (
                    t["merchant_display"]
                    if not isinstance(t, dict)
                    else t.get("merchant_display")
                ),
                "debit": float(t["debit"] or 0) if not isinstance(t, dict) else float(t.get("debit") or 0),
                "credit": float(t["credit"] or 0) if not isinstance(t, dict) else float(t.get("credit") or 0),
                "category": t["category"] if not isinstance(t, dict) else t.get("category"),
                "type": t["expense_type"] if not isinstance(t, dict) else t.get("expense_type"),
            }
        )
        if len(out) >= max(1, min(limit, 100)):
            break
    return out


@mcp.tool()
def add_khata_entry(
    contact_name: str,
    amount: float,
    direction: str = "you_sent",
    purpose: str = "loan",
    entry_date: str | None = None,
    notes: str | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    """Add a khata ledger entry (who-owes-whom). Prefer purpose loan|food_split|trip|other.

    direction: you_sent (they owe you more) or they_sent (you owe them more).
    """
    user = _resolve_user(username)
    direction = (direction or "you_sent").strip().lower()
    if direction not in {"you_sent", "they_sent"}:
        return {"error": "direction must be you_sent or they_sent"}
    if amount <= 0:
        return {"error": "amount must be positive"}
    with _open(user) as conn:
        contact = find_contact_by_text(conn, contact_name)
        if not contact:
            return {"error": f"No contact matching {contact_name!r}"}
        eid = add_ledger_entry(
            conn,
            contact_id=int(contact["id"]),
            direction=direction,
            amount=Decimal(str(amount)),
            purpose=(purpose or "other").strip() or "other",
            entry_date=entry_date,
            notes=notes,
            created_by="mcp",
        )
        bal = get_balance(conn, int(contact["id"]))
    return {
        "ok": True,
        "ledger_entry_id": eid,
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "balance": {"net": bal.get("net"), "status": bal.get("status")},
    }


def main() -> None:
    # stdio for Cursor / Claude Desktop / local agents
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
