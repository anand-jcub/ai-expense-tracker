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

from expense_tracker.db import connect, dashboard_data, export_rows
from expense_tracker.services import dashboard_summary_payload, filter_dashboard_rows

mcp = FastMCP(
    "expense-tracker",
    instructions=(
        "Personal expense tools. "
        "Use get_dashboard_summary for spend charts and totals; search_transactions / export_transactions for transactions."
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
    """List khata (who-owes-whom) balances (decommissioned)."""
    return []


@mcp.tool()
def get_balance_for_person(
    name_or_id: str,
    username: str | None = None,
) -> dict[str, Any]:
    """Get khata balance for one person (decommissioned)."""
    return {"error": "Ledger has been decommissioned."}


@mcp.tool()
def get_person_ledger(
    name_or_id: str,
    username: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Ledger history for a contact (decommissioned)."""
    return {"error": "Ledger has been decommissioned.", "entries": []}


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
    with _open(user) as conn:
        payload = dashboard_summary_payload(
            conn,
            start_date=start_date,
            end_date=end_date,
            exclude_business=exclude_business,
            use_current_month=use_current_month,
        )
    payload["username"] = user
    return payload


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
def export_transactions(
    username: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    query: str = "",
    limit: int = 200,
    newest_first: bool = True,
) -> dict[str, Any]:
    """Full transaction export — same fields as dashboard CSV/JSON download.

    Includes classification (category, expense_type, split, notes, offsets).
    Prefer this over search_transactions when the agent needs complete rows.
    Use start_date/end_date/query to shrink the payload; default max 200 rows.
    """
    user = _resolve_user(username)
    with _open(user) as conn:
        rows = export_rows(conn)
    if newest_first:
        rows = list(reversed(rows))
    start = (start_date or "").strip()
    end = (end_date or "").strip()
    q = (query or "").strip().lower()
    cap = max(1, min(int(limit or 200), 2000))
    out: list[dict[str, Any]] = []
    for row in rows:
        d = str(row.get("txn_date") or "")
        if start and d < start:
            continue
        if end and d > end:
            continue
        if q:
            blob = " ".join(
                str(row.get(k) or "")
                for k in (
                    "merchant_display",
                    "description",
                    "category",
                    "expense_type",
                    "notes",
                    "reference",
                )
            ).lower()
            if q not in blob:
                continue
        item: dict[str, Any] = {}
        for k, v in dict(row).items():
            if isinstance(v, Decimal):
                item[k] = float(v)
            else:
                item[k] = v
        out.append(item)
        if len(out) >= cap:
            break
    return {
        "username": user,
        "count": len(out),
        "start_date": start or None,
        "end_date": end or None,
        "query": q or None,
        "transactions": out,
        "note": "Same columns as /export.json and dashboard Download JSON.",
    }


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
    """Add a khata ledger entry (decommissioned)."""
    return {"error": "Ledger has been decommissioned."}


def main() -> None:
    # stdio for Cursor / Claude Desktop / local agents
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
