"""Assistant tools — wrap existing domain. No new money math."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from expense_tracker.contacts import find_contact_by_text, get_all_balances, get_balance, get_ledger
from expense_tracker.db import add_manual_transaction, dashboard_data, review_transaction
from expense_tracker.services import (
    CATEGORIES,
    EXPENSE_TYPES,
    dashboard_summary_payload,
    filter_dashboard_rows,
    split_ratio_from_people,
)

from . import pending as pending_store

READ_TOOLS = (
    "get_balance_for_person",
    "list_balances",
    "get_dashboard_summary",
    "search_transactions",
    "get_person_ledger",
    "find_sends_to_person",
    "find_person_transactions",
    "list_pending_reviews",
)
WRITE_TOOLS = (
    "propose_add_manual",
    "propose_categorize_transaction",
    "propose_edit_classification",
)


def gemini_declarations() -> list[dict[str, Any]]:
    return [
        {
            "name": "ask_books",
            "description": (
                "Query this user's bank spends and khata. Set scope bank or khata. "
                "period: this_month, last_month, last_7d, last_90d. "
                "text: merchant. category: Food etc. min_amount in INR (100000=1 lakh). "
                "agg: list, sum, top_merchants. person: contact name for khata. "
                "Returns a short answer plus up to 15 rows. Never invent numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "period": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "text": {"type": "string"},
                    "category": {"type": "string"},
                    "min_amount": {"type": "number"},
                    "agg": {"type": "string"},
                    "person": {"type": "string"},
                    "intent": {"type": "string"},
                },
            },
        },
        {
            "name": "get_balance_for_person",
            "description": (
                "Khata balance for one person by name or id. "
                "net > 0 means they owe the user; net < 0 means the user owes them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {"type": "string", "description": "Contact name, alias, or numeric id."},
                },
                "required": ["name_or_id"],
            },
        },
        {
            "name": "list_balances",
            "description": "List non-zero khata balances (who owes whom).",
            "parameters": {
                "type": "object",
                "properties": {
                    "nonzero_only": {"type": "boolean", "description": "Default true."},
                },
            },
        },
        {
            "name": "get_dashboard_summary",
            "description": (
                "Period spend summary (same filters as Home). "
                "Use for 'what did I spend on food this month' via by_category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    "exclude_business": {"type": "boolean"},
                    "category": {
                        "type": "string",
                        "description": "If set, also return that category's amount from by_category.",
                    },
                },
            },
        },
        {
            "name": "search_transactions",
            "description": "Search bank rows in a period. Prefer this over dumping everything.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "exclude_business": {"type": "boolean"},
                    "limit": {"type": "number"},
                },
            },
        },
        {
            "name": "find_person_transactions",
            "description": (
                "Search bank transactions and khata ledger for transfers with a person/contact. "
                "direction='received' for money they paid to you (CREDITS); "
                "direction='sent' for money you paid to them (DEBITS); "
                "direction='both' for all transfers. "
                "Use min_amount for threshold queries ('more than X'); "
                "use exact_amount for specific values like 50000 for '50k'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {"type": "string", "description": "Contact name, alias, or id."},
                    "direction": {
                        "type": "string",
                        "enum": ["both", "sent", "received"],
                        "description": "'received' = they paid you (credits); 'sent' = you paid them (debits); 'both' = all transfers.",
                    },
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "period": {"type": "string", "description": "e.g. 'this_month', 'last_month', 'all'"},
                    "min_amount": {
                        "type": "number",
                        "description": "INR threshold — only return transfers >= this.",
                    },
                    "exact_amount": {
                        "type": "number",
                        "description": "INR exact value ±5% — use for specific amounts like '50k'.",
                    },
                },
                "required": ["name_or_id"],
            },
        },
        {
            "name": "find_sends_to_person",
            "description": (
                "Find when you sent or paid money to a person (debits/you_sent). "
                "Prefer find_person_transactions with direction='sent' or 'received'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {"type": "string"},
                    "min_amount": {"type": "number"},
                    "exact_amount": {"type": "number"},
                },
                "required": ["name_or_id"],
            },
        },
        {
            "name": "get_person_ledger",
            "description": "Recent khata ledger lines for one contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {"type": "string"},
                    "limit": {"type": "number"},
                },
                "required": ["name_or_id"],
            },
        },
        {
            "name": "propose_add_manual",
            "description": (
                "Propose a manual expense/credit. Does NOT write. "
                "User must confirm. Default direction debit, type Personal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "txn_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "amount": {"type": "number"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                    "expense_type": {"type": "string"},
                    "direction": {"type": "string", "description": "debit or credit"},
                    "notes": {"type": "string"},
                    "split_people": {"type": "number"},
                },
                "required": ["amount", "description"],
            },
        },
        {
            "name": "list_pending_reviews",
            "description": (
                "List unclassified transactions from email statement imports (status='needs_review'). "
                "Can be filtered by date range (start_date, end_date). "
                "Use when user asks 'what needs review', 'review statement', 'review transactions', 'review uncategorized', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "limit": {"type": "number", "description": "Max items to return (default 10)"},
                },
            },
        },
        {
            "name": "propose_categorize_transaction",
            "description": (
                "Propose categorizing a pending statement transaction. Does NOT write directly — "
                "generates an interactive confirmation card for the user to confirm. "
                "Use when reviewing/categorizing unclassified transactions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "number", "description": "Transaction ID to categorize"},
                    "category": {"type": "string", "description": "Category (Food, Fuel, Groceries, Shopping, Utilities, Travel, Transfer, etc.)"},
                    "expense_type": {"type": "string", "enum": ["Personal", "Shared"], "description": "Personal or Shared (default Personal)"},
                    "split_people": {"type": "number", "description": "Number of split people if Shared (default 2)"},
                    "shared_with": {"type": "string", "description": "Partner/contact name if Shared"},
                    "learn": {"type": "boolean", "description": "Set True to remember category rule for this merchant for future imports"},
                    "notes": {"type": "string"},
                },
                "required": ["transaction_id", "category"],
            },
        },
        {
            "name": "propose_edit_classification",
            "description": (
                "Propose editing or recategorizing an existing or auto-classified transaction. "
                "Finds matching transaction by merchant query or date, and generates an interactive confirmation card. "
                "Use when user asks 'change Swiggy to Dining out', 'make Shell Shared with Highnes', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Merchant name or search term (e.g. Swiggy, Shell, Uber)"},
                    "date": {"type": "string", "description": "Optional date (YYYY-MM-DD)"},
                    "transaction_id": {"type": "number", "description": "Optional specific transaction ID"},
                    "new_category": {"type": "string", "description": "New category name"},
                    "new_expense_type": {"type": "string", "enum": ["Personal", "Shared"], "description": "Personal or Shared"},
                    "split_people": {"type": "number", "description": "Number of split people if Shared (default 2)"},
                    "shared_with": {"type": "string", "description": "Partner name if Shared"},
                    "learn": {"type": "boolean", "description": "Set True to update/remember rule for future transactions"},
                    "notes": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    ]


def run_tool(conn, username: str, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    args = args or {}
    if name == "ask_books":
        from .query import ask_books

        return ask_books(conn, args)
    if name == "get_balance_for_person":
        return _balance_for_person(conn, str(args.get("name_or_id") or ""))
    if name == "list_balances":
        return _list_balances(conn, bool(args.get("nonzero_only", True)))
    if name == "get_dashboard_summary":
        return _dashboard(conn, args)
    if name == "search_transactions":
        return _search(conn, args)
    if name == "get_person_ledger":
        return _ledger(conn, args)
    if name in {"find_person_transactions", "find_sends_to_person"}:
        return _find_person_transactions(conn, args)
    if name == "list_pending_reviews":
        return _list_pending_reviews(conn, args)
    if name == "propose_categorize_transaction":
        return _propose_categorize(conn, username, args)
    if name == "propose_edit_classification":
        return _propose_edit_classification(conn, username, args)
    if name == "propose_add_manual":
        return _propose_add(username, args)
    return {"error": f"Unknown tool {name!r}"}


def execute_pending(conn, username: str, item: dict[str, Any]) -> dict[str, Any]:
    action = item.get("action")
    payload = item.get("payload") or {}
    if action == "add_manual":
        txn_id = add_manual_transaction(
            conn,
            payload["txn_date"],
            payload["description"],
            Decimal(str(payload["amount"])),
            payload["direction"],
            payload["category"],
            payload["expense_type"],
            Decimal(str(payload["split_ratio"])),
            payload.get("notes"),
            False,
            uploaded_by=username,
        )
        return {"ok": True, "transaction_id": txn_id, "preview": payload}
    if action in {"review_transaction", "edit_classification"}:
        tid = int(payload["transaction_id"])
        cat = str(payload.get("category") or "Other")
        exp_type = str(payload.get("expense_type") or "Personal")
        split_ratio = Decimal(str(payload.get("split_ratio") or "1.0"))
        notes = payload.get("notes")
        learn = bool(payload.get("learn", False))
        shared_with = payload.get("shared_with")
        review_transaction(
            conn,
            transaction_id=tid,
            category=cat,
            expense_type=exp_type,
            split_ratio=split_ratio,
            notes=notes,
            learn=learn,
            shared_with=shared_with,
        )
        return {
            "ok": True,
            "transaction_id": tid,
            "reply": f"Saved {payload.get('merchant', 'transaction')} as {cat} ({exp_type}).",
            "preview": payload,
        }
    return {"error": f"Unknown pending action {action!r}"}


def _balance_for_person(conn, name_or_id: str) -> dict[str, Any]:
    raw = (name_or_id or "").strip()
    if not raw:
        return {"error": "name_or_id required"}
    contact = None
    cid: int | None = None
    if raw.isdigit():
        cid = int(raw)
        c = get_contact(conn, cid)
        if c:
            contact = c
    else:
        c = find_contact_by_text(conn, raw)
        if c:
            contact = c
            cid = int(c["id"])
    if not cid:
        return {"error": f"No contact matching {raw!r}", "matched": False}
    bal = get_balance(conn, cid)
    net = float(bal.get("net") or 0)
    name = (contact or {}).get("name") or raw
    if net > 0:
        answer = f"{name} owes you ₹{net:,.2f}."
    elif net < 0:
        answer = f"You owe {name} ₹{abs(net):,.2f}."
    else:
        answer = f"{name} is settled (₹0)."
    return {
        "contact_id": cid,
        "contact_name": name,
        "balance": bal,
        "answer": answer,
        "matched": True,
    }


def _list_balances(conn, nonzero_only: bool) -> dict[str, Any]:
    items = get_all_balances(conn)
    rows: list[dict[str, Any]] = []
    for item in items:
        b = item["balance"]
        net = float(b.get("net") or 0)
        if nonzero_only and net == 0:
            continue
        rows.append(
            {
                "contact_id": item["contact"]["id"],
                "contact_name": item["contact"]["name"],
                "net": net,
                "status": b.get("status"),
                "total_you_sent": float(b.get("total_you_sent") or 0),
                "total_they_sent": float(b.get("total_they_sent") or 0),
            }
        )
    return {"balances": rows, "count": len(rows)}


def _dashboard(conn, args: dict[str, Any]) -> dict[str, Any]:
    cat = (args.get("category") or "").strip()
    start = args.get("start_date")
    end = args.get("end_date")
    ex = bool(args.get("exclude_business", True))
    if cat.lower() == "business":
        ex = False
    use_curr = not (start or end)
    payload = dashboard_summary_payload(
        conn,
        start,
        end,
        ex,
        use_current_month=use_curr,
    )
    if cat:
        match = next(
            (c for c in payload.get("by_category") or [] if str(c.get("category") or "").lower() == cat.lower()),
            None,
        )
        payload["category_match"] = match
    return payload


def _search(conn, args: dict[str, Any]) -> dict[str, Any]:
    q = (args.get("query") or "").strip().lower()
    start = args.get("start_date")
    end = args.get("end_date")
    ex = bool(args.get("exclude_business", True))
    if "business" in q or (args.get("category") or "").lower() == "business" or (args.get("expense_type") or "").lower() == "business":
        ex = False
    limit = int(args.get("limit") or 15)
    data = dashboard_data(conn)
    rows = filter_dashboard_rows(data.get("transactions") or [], start, end, ex)
    matched = []
    for r in rows:
        desc = str(_row_val(r, "description") or "")
        merch = str(_row_val(r, "merchant_display") or "")
        cat = str(_row_val(r, "category") or "")
        blob = f"{desc} {merch} {cat}".lower()
        if not q or q in blob:
            matched.append(
                {
                    "date": _row_val(r, "txn_date"),
                    "description": desc,
                    "merchant": merch,
                    "category": cat,
                    "debit": float(_row_val(r, "debit") or 0),
                    "credit": float(_row_val(r, "credit") or 0),
                }
            )
            if len(matched) >= limit:
                break
    return {"matches": matched, "count": len(matched)}


def _ledger(conn, args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("name_or_id") or "").strip()
    limit = int(args.get("limit") or 10)
    cid: int | None = None
    if raw.isdigit():
        cid = int(raw)
    else:
        c = find_contact_by_text(conn, raw)
        if c:
            cid = int(c["id"])
    if not cid:
        return {"error": f"Contact {raw!r} not found", "matched": False}
    led = get_ledger(conn, cid)
    entries = (led.get("entries") or [])[:limit]
    return {
        "contact": led.get("contact"),
        "balance": led.get("balance"),
        "entries": entries,
        "matched": True,
    }


def parse_inr_amount(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if not s:
        return 0.0
    s_clean = s.replace(",", "").replace("₹", "").replace("inr", "").strip()
    m_lakh = re.search(r"([\d.]+)\s*(lakh?s?|lacs?)", s_clean)
    if m_lakh:
        try:
            return float(m_lakh.group(1)) * 100_000.0
        except ValueError:
            return 0.0
    m_k = re.search(r"([\d.]+)\s*k\b", s_clean)
    if m_k:
        try:
            return float(m_k.group(1)) * 1_000.0
        except ValueError:
            return 0.0
    m_thou = re.search(r"([\d.]+)\s*(thousand|k)", s_clean)
    if m_thou:
        try:
            return float(m_thou.group(1)) * 1_000.0
        except ValueError:
            return 0.0
    m = re.search(r"([\d.]+)", s_clean)
    if not m:
        try:
            return float(s_clean)
        except ValueError:
            return 0.0
    return float(m.group(1) or 0)


def _find_person_transactions(conn, args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("name_or_id") or "").strip()
    if not raw:
        return {"error": "name_or_id required"}

    direction = str(args.get("direction") or "both").lower()
    if direction not in {"sent", "received", "both"}:
        direction = "both"

    from .query import period_bounds
    start = str(args.get("start_date") or "").strip()
    end = str(args.get("end_date") or "").strip()
    period = str(args.get("period") or "").strip()
    if period or start or end:
        start_d, end_d = period_bounds(period or None, start or None, end or None)
    else:
        start_d, end_d = "2000-01-01", "2099-12-31"

    # --- Resolve contact ---
    cid: int | None = None
    contact: dict | None = None
    led: dict = {"entries": [], "contact": None}
    if raw.isdigit():
        cid = int(raw)
        led = get_ledger(conn, cid)
        contact = led.get("contact")
    else:
        contact = find_contact_by_text(conn, raw)
        if contact:
            cid = int(contact["id"])
            led = get_ledger(conn, cid)

    min_amt = parse_inr_amount(
        args.get("min_amount") if args.get("min_amount") is not None else (args.get("amount") or 0)
    )
    exact_amt = parse_inr_amount(args.get("exact_amount") or 0)
    name = (led.get("contact") or contact or {}).get("name") or raw

    terms = [s.lower() for s in [name] + list((contact or {}).get("aliases") or []) if s and len(s) >= 3]
    if not terms:
        terms = [raw.lower()]

    sent_hits: list[dict] = []
    received_hits: list[dict] = []

    # --- Bank pass ---
    try:
        from expense_tracker.db import dashboard_data as _dd
        data = _dd(conn)
        for t in (data.get("transactions") or []):
            d_str = str(_row_val(t, "txn_date") or "")
            if d_str and (d_str < start_d or d_str > end_d):
                continue
            debit = float(_row_val(t, "debit") or 0)
            credit = float(_row_val(t, "credit") or 0)
            merch = str(_row_val(t, "merchant_display") or "").lower()
            desc = str(_row_val(t, "description") or "").lower()
            blob = merch + " " + desc
            if not any(term in blob for term in terms):
                continue

            # Outgoing / debit
            if debit > 0 and direction in {"sent", "both"}:
                if exact_amt:
                    tol = max(exact_amt * 0.05, 50)
                    if not (exact_amt - tol <= debit <= exact_amt + tol):
                        continue
                elif min_amt and debit + 1e-9 < min_amt:
                    continue
                sent_hits.append({
                    "date": d_str,
                    "amount": debit,
                    "type": "debit (you sent)",
                    "description": _row_val(t, "merchant_display") or _row_val(t, "description"),
                    "source": "bank",
                })

            # Incoming / credit
            if credit > 0 and direction in {"received", "both"}:
                if exact_amt:
                    tol = max(exact_amt * 0.05, 50)
                    if not (exact_amt - tol <= credit <= exact_amt + tol):
                        continue
                elif min_amt and credit + 1e-9 < min_amt:
                    continue
                received_hits.append({
                    "date": d_str,
                    "amount": credit,
                    "type": "credit (they sent you)",
                    "description": _row_val(t, "merchant_display") or _row_val(t, "description"),
                    "source": "bank",
                })
    except Exception:
        pass

    # --- Khata pass ---
    for e in (led.get("entries") or []):
        if e.get("is_passthrough"):
            continue
        ed = str(e.get("entry_date") or "")
        if ed and (ed < start_d or ed > end_d):
            continue
        try:
            amt = float(e.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if exact_amt:
            tol = max(exact_amt * 0.05, 50)
            if not (exact_amt - tol <= amt <= exact_amt + tol):
                continue
        elif min_amt and amt + 1e-9 < min_amt:
            continue

        dir_str = str(e.get("direction") or "")
        if dir_str == "you_sent" and direction in {"sent", "both"}:
            sent_hits.append({
                "date": ed,
                "amount": amt,
                "type": "debit (khata - you sent)",
                "description": e.get("purpose"),
                "source": "khata",
            })
        elif dir_str == "they_sent" and direction in {"received", "both"}:
            received_hits.append({
                "date": ed,
                "amount": amt,
                "type": "credit (khata - they sent you)",
                "description": e.get("purpose"),
                "source": "khata",
            })

    sent_hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    received_hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)

    total_sent = sum(h["amount"] for h in sent_hits)
    total_received = sum(h["amount"] for h in received_hits)

    if direction == "received":
        if not received_hits:
            answer = f"No incoming credits or payments found from {name}."
        else:
            bits = [f"₹{h['amount']:,.0f} on {h['date']}" + (f" ({h['description']})" if h.get('description') else "") for h in received_hits[:10]]
            answer = f"{name} sent you (credits): " + "; ".join(bits) + f". (Total received: ₹{total_received:,.0f})."
    elif direction == "sent":
        if not sent_hits:
            answer = f"No outgoing debits or payments found sent to {name}."
        else:
            bits = [f"₹{h['amount']:,.0f} on {h['date']}" + (f" ({h['description']})" if h.get('description') else "") for h in sent_hits[:10]]
            answer = f"You sent {name} (debits): " + "; ".join(bits) + f". (Total sent: ₹{total_sent:,.0f})."
    else:
        if not sent_hits and not received_hits:
            answer = f"No transfers found with {name}."
        else:
            bits_rec = [f"₹{h['amount']:,.0f} on {h['date']}" for h in received_hits[:6]]
            bits_sent = [f"₹{h['amount']:,.0f} on {h['date']}" for h in sent_hits[:6]]
            parts = []
            if received_hits:
                parts.append(f"Received from {name} (credits): " + "; ".join(bits_rec))
            if sent_hits:
                parts.append(f"Sent to {name} (debits): " + "; ".join(bits_sent))
            answer = " | ".join(parts) + "."

    return {
        "contact_name": name,
        "direction": direction,
        "received_from_person": received_hits[:20],
        "total_received": total_received,
        "sent_to_person": sent_hits[:20],
        "total_sent": total_sent,
        "sends": sent_hits[:20] if direction == "sent" else (received_hits[:20] if direction == "received" else (sent_hits[:10] + received_hits[:10])),
        "answer": answer,
    }


def _propose_add(username: str, args: dict[str, Any]) -> dict[str, Any]:
    from datetime import date as date_cls

    description = str(args.get("description") or "").strip()
    if not description:
        return {"error": "description required"}
    try:
        amount = Decimal(str(args.get("amount")))
    except (InvalidOperation, TypeError):
        return {"error": "valid amount required"}
    if amount <= 0:
        return {"error": "amount must be greater than zero"}
    direction = str(args.get("direction") or "debit").strip().lower()
    if direction not in {"debit", "credit"}:
        return {"error": "direction must be debit or credit"}
    category = str(args.get("category") or "Other").strip() or "Other"
    if category not in CATEGORIES:
        category = "Other"
    expense_type = str(args.get("expense_type") or "Personal").strip() or "Personal"
    if expense_type not in EXPENSE_TYPES:
        expense_type = "Personal"
    txn_date = str(args.get("txn_date") or date_cls.today().isoformat()).strip()
    try:
        date_cls.fromisoformat(txn_date)
    except ValueError:
        return {"error": "txn_date must be YYYY-MM-DD"}
    try:
        split_ratio = split_ratio_from_people(args.get("split_people") or 1)
    except ValueError as exc:
        return {"error": str(exc)}
    notes = str(args.get("notes") or "").strip() or None
    payload = {
        "txn_date": txn_date,
        "description": description,
        "amount": float(amount),
        "direction": direction,
        "category": category,
        "expense_type": expense_type,
        "split_ratio": str(split_ratio),
        "notes": notes,
    }
    token = pending_store.issue(username, "add_manual", payload)
    verb = "Spend" if direction == "debit" else "Credit"
    return {
        "needs_confirm": True,
        "confirm_token": token,
        "title": f"{verb} ₹{amount:,.2f}",
        "preview": payload,
        "message": f"Add {direction} ₹{amount:,.2f} — {description} ({category}) on {txn_date}?",
    }


def _list_pending_reviews(conn, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 30))

    start_date = str(args.get("start_date") or "").strip()
    end_date = str(args.get("end_date") or "").strip()

    clauses = ["c.status = 'needs_review'"]
    params: list[Any] = []
    if start_date:
        clauses.append("t.txn_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("t.txn_date <= ?")
        params.append(end_date)

    where_str = " and ".join(clauses)

    query_sql = f"""
        select t.id, t.txn_date, t.merchant_display, t.description,
               t.amount_signed, t.debit, t.credit,
               c.category, c.expense_type, c.split_ratio, c.confidence, c.status
        from transactions t
        join classifications c on c.transaction_id = t.id
        where {where_str}
        order by t.txn_date desc, t.id desc
        limit ?
    """
    rows = conn.execute(query_sql, (*params, limit)).fetchall()

    count_sql = f"""
        select count(*) from classifications c
        join transactions t on c.transaction_id = t.id
        where {where_str}
    """
    total_row = conn.execute(count_sql, params).fetchone()
    total_count = total_row[0] if total_row else len(rows)

    items = []
    for r in rows:
        debit = float(_row_val(r, "debit") or 0)
        credit = float(_row_val(r, "credit") or 0)
        amt = debit if debit > 0 else credit
        items.append({
            "transaction_id": _row_val(r, "id"),
            "date": _row_val(r, "txn_date"),
            "merchant": _row_val(r, "merchant_display") or _row_val(r, "description"),
            "amount": amt,
            "direction": "debit" if debit > 0 else "credit",
            "suggested_category": _row_val(r, "category") or "Other",
            "suggested_expense_type": _row_val(r, "expense_type") or "Personal",
            "confidence": str(_row_val(r, "confidence") or "0.5"),
        })

    if not items:
        if start_date or end_date:
            answer = f"All caught up! No transactions need review between {start_date} and {end_date}."
        else:
            answer = "All caught up! No transactions currently need review."
    else:
        period_str = f" between {start_date} and {end_date}" if start_date or end_date else ""
        answer = f"You have {total_count} unclassified transaction(s) needing review{period_str}."

    return {
        "pending_count": total_count,
        "start_date": start_date or None,
        "end_date": end_date or None,
        "items": items,
        "answer": answer,
    }


def _propose_categorize(conn, username: str, args: dict[str, Any]) -> dict[str, Any]:
    raw_id = args.get("transaction_id")
    if not raw_id:
        return {"error": "transaction_id required"}
    try:
        tid = int(raw_id)
    except (TypeError, ValueError):
        return {"error": f"Invalid transaction_id: {raw_id}"}

    tx = conn.execute(
        """
        select t.id, t.txn_date, t.merchant_display, t.description, t.debit, t.credit,
               c.category as current_cat, c.expense_type as current_type
        from transactions t
        join classifications c on c.transaction_id = t.id
        where t.id = ?
        """,
        (tid,),
    ).fetchone()
    if not tx:
        return {"error": f"Transaction #{tid} not found"}

    cat_map = {c.lower(): c for c in CATEGORIES}
    category = cat_map.get(str(args.get("category") or _row_val(tx, "current_cat") or "Other").strip().lower(), "Other")

    exp_map = {e.lower(): e for e in EXPENSE_TYPES}
    expense_type = exp_map.get(str(args.get("expense_type") or _row_val(tx, "current_type") or "Personal").strip().lower(), "Personal")

    shared_with = str(args.get("shared_with") or "").strip() or None
    if shared_with:
        expense_type = "Shared"

    split_people = args.get("split_people")
    if expense_type == "Shared" and (not split_people or str(split_people) in ("0", "1")):
        split_people = 2
    elif expense_type != "Shared":
        split_people = 1

    try:
        split_ratio = split_ratio_from_people(split_people)
    except ValueError as exc:
        return {"error": str(exc)}

    learn = bool(args.get("learn", False))
    notes = str(args.get("notes") or "").strip() or None

    debit = float(_row_val(tx, "debit") or 0)
    credit = float(_row_val(tx, "credit") or 0)
    amt = debit if debit > 0 else credit
    merch = _row_val(tx, "merchant_display") or _row_val(tx, "description")
    txn_date = _row_val(tx, "txn_date")

    payload = {
        "transaction_id": tid,
        "category": category,
        "expense_type": expense_type,
        "split_ratio": str(split_ratio),
        "notes": notes,
        "learn": learn,
        "shared_with": shared_with,
        "merchant": merch,
        "amount": amt,
        "date": txn_date,
    }
    token = pending_store.issue(username, "review_transaction", payload)

    split_txt = f" (Split 1/{split_people})" if expense_type == "Shared" else ""
    partner_txt = f" with {shared_with}" if shared_with else ""
    learn_txt = " · Rule remembered" if learn else ""

    return {
        "needs_confirm": True,
        "confirm_token": token,
        "title": f"Categorize {merch} · ₹{amt:,.0f}",
        "preview": payload,
        "message": f"Set {merch} (₹{amt:,.0f} on {txn_date}) to {category} [{expense_type}{partner_txt}{split_txt}]{learn_txt}?",
    }


def _propose_edit_classification(conn, username: str, args: dict[str, Any]) -> dict[str, Any]:
    tid = args.get("transaction_id")
    query = str(args.get("query") or "").strip().lower()
    date_hint = str(args.get("date") or "").strip()

    if tid:
        try:
            tid = int(tid)
            tx = conn.execute(
                """
                select t.id, t.txn_date, t.merchant_display, t.description, t.debit, t.credit,
                       c.category as current_cat, c.expense_type as current_type, c.notes
                from transactions t
                join classifications c on c.transaction_id = t.id
                where t.id = ?
                """,
                (tid,),
            ).fetchone()
        except (TypeError, ValueError):
            return {"error": f"Invalid transaction id {tid}"}
    elif query:
        rows = conn.execute(
            """
            select t.id, t.txn_date, t.merchant_display, t.description, t.debit, t.credit,
                   c.category as current_cat, c.expense_type as current_type, c.notes
            from transactions t
            join classifications c on c.transaction_id = t.id
            order by t.txn_date desc, t.id desc
            limit 150
            """
        ).fetchall()
        matched = []
        for r in rows:
            merch = str(_row_val(r, "merchant_display") or "")
            desc = str(_row_val(r, "description") or "")
            cat = str(_row_val(r, "current_cat") or "")
            blob = f"{merch} {desc} {cat}".lower()
            if query in blob:
                d_str = str(_row_val(r, "txn_date") or "")
                if date_hint and date_hint not in d_str:
                    continue
                matched.append(r)
        if not matched:
            return {"error": f"Could not find any transaction matching {query!r}" + (f" on {date_hint}" if date_hint else "")}
        tx = matched[0]
        tid = _row_val(tx, "id")
    else:
        return {"error": "Either transaction_id or search query is required"}

    if not tx:
        return {"error": f"Transaction #{tid} not found"}

    cat_map = {c.lower(): c for c in CATEGORIES}
    new_cat = cat_map.get(str(args.get("new_category") or _row_val(tx, "current_cat") or "Other").strip().lower(), "Other")

    exp_map = {e.lower(): e for e in EXPENSE_TYPES}
    new_type = exp_map.get(str(args.get("new_expense_type") or _row_val(tx, "current_type") or "Personal").strip().lower(), "Personal")

    shared_with = str(args.get("shared_with") or "").strip() or None
    if shared_with:
        new_type = "Shared"

    split_people = args.get("split_people")
    if new_type == "Shared" and (not split_people or str(split_people) in ("0", "1")):
        split_people = 2
    elif new_type != "Shared":
        split_people = 1

    try:
        split_ratio = split_ratio_from_people(split_people)
    except ValueError as exc:
        return {"error": str(exc)}

    learn = bool(args.get("learn", False))
    notes = str(args.get("notes") or _row_val(tx, "notes") or "").strip() or None

    debit = float(_row_val(tx, "debit") or 0)
    credit = float(_row_val(tx, "credit") or 0)
    amt = debit if debit > 0 else credit
    merch = _row_val(tx, "merchant_display") or _row_val(tx, "description")
    txn_date = _row_val(tx, "txn_date")
    curr_cat = _row_val(tx, "current_cat") or "Uncategorized"

    payload = {
        "transaction_id": tid,
        "category": new_cat,
        "expense_type": new_type,
        "split_ratio": str(split_ratio),
        "notes": notes,
        "learn": learn,
        "shared_with": shared_with,
        "merchant": merch,
        "amount": amt,
        "date": txn_date,
    }
    token = pending_store.issue(username, "edit_classification", payload)

    split_txt = f" (Split 1/{split_people})" if new_type == "Shared" else ""
    partner_txt = f" with {shared_with}" if shared_with else ""
    learn_txt = " · Rule remembered" if learn else ""

    return {
        "needs_confirm": True,
        "confirm_token": token,
        "title": f"Update {merch} · ₹{amt:,.0f}",
        "preview": payload,
        "message": f"Change {merch} ({txn_date}) from {curr_cat} to {new_cat} [{new_type}{partner_txt}{split_txt}]{learn_txt}?",
    }


def _row_val(row, key: str):
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key)
    return None
