"""One owner for Ask reads: compact bank + khata answers. No full DB dump."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from expense_tracker.contacts import find_contact_by_text, get_all_balances, get_balance, get_ledger
from expense_tracker.db import dashboard_data
from expense_tracker.services import (
    CATEGORIES,
    current_month_bounds,
    dashboard_summary_payload,
    filter_dashboard_rows,
)


def parse_inr_amount(raw) -> float:
    """Accept 100000, 1,00,000, '1 lakh', '1.5 lak', '50k', '50 thousand'.

    NOTE: lakh/lac checked before 'k' to avoid 'lak' being treated as '1k'.
    """
    text = str(raw or "").strip().lower().replace(",", "")
    if not text:
        return 0.0
    # lakh / lac / lak must be checked before bare 'k' to avoid mismatch
    m_lakh = re.search(r"([\d.]+)\s*(lakh?s?|lacs?)", text)
    if m_lakh:
        return float(m_lakh.group(1)) * 100_000
    # Handle bare "k" (thousand) suffix — e.g. "50k"
    m_k = re.search(r"([\d.]+)\s*k\b", text)
    if m_k:
        return float(m_k.group(1)) * 1_000
    m = re.search(r"([\d.]+)\s*(thousand)?", text)
    if not m:
        try:
            return float(text)
        except ValueError:
            return 0.0
    n = float(m.group(1) or 0)
    if m.group(2):
        n *= 1_000
    return n




_LAKH = re.compile(r"lakh?s?|lacs?", re.I)


def period_bounds(kind: str | None = None, start: str | None = None, end: str | None = None) -> tuple[str, str]:
    today = date.today()
    if start or end:
        return (start or "2000-01-01"), (end or today.isoformat())
    k = (kind or "last_90d").lower()
    if k in {"this_month", "month"}:
        return current_month_bounds(today)
    if k in {"last_month"}:
        first = today.replace(day=1)
        last_m = first - timedelta(days=1)
        return last_m.replace(day=1).isoformat(), last_m.isoformat()
    if k in {"last_7d", "week"}:
        return (today - timedelta(days=7)).isoformat(), today.isoformat()
    if k in {"last_30d"}:
        return (today - timedelta(days=30)).isoformat(), today.isoformat()
    return (today - timedelta(days=90)).isoformat(), today.isoformat()


def ask_books(conn, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or {}
    start, end = period_bounds(spec.get("period"), spec.get("start_date"), spec.get("end_date"))
    scope = (spec.get("scope") or "auto").lower()
    person = str(spec.get("person") or spec.get("name_or_id") or "").strip()
    text = str(spec.get("text") or spec.get("query") or "").strip()
    category = str(spec.get("category") or "").strip()
    min_amt = float(spec.get("min_amount") or 0)
    max_amt = float(spec.get("max_amount") or 0)
    exact_amt = float(spec.get("exact_amount") or 0)
    agg = (spec.get("agg") or "list").lower()
    intent = str(spec.get("intent") or "")

    # Send queries: search bank + khata (not khata-only)
    if scope == "send" or (intent == "send"):
        return _find_sends_merged(conn, person, min_amt, exact_amt, spec)

    if person and scope == "auto":
        scope = "khata"
    if scope == "khata" or (person and any(w in intent for w in ("owe", "khata", "ledger"))):
        return _khata(conn, person, min_amt, spec)
    if category and agg == "sum" and not text:
        ex_biz = False if category.lower() == "business" else True
        payload = dashboard_summary_payload(conn, start, end, ex_biz, use_current_month=False)
        match = next(
            (c for c in payload.get("by_category") or [] if str(c.get("category") or "").lower() == category.lower()),
            None,
        )
        amt = float((match or {}).get("amount") or 0)
        answer = (
            f"You spent ₹{amt:,.2f} on {category} from {payload.get('start_date')} to {payload.get('end_date')} "
            f"(personal share, business excluded)."
            if ex_biz
            else f"You spent ₹{amt:,.2f} on Business from {payload.get('start_date')} to {payload.get('end_date')}."
        )
        return {"answer": answer, "rows": [match] if match else [], "start": start, "end": end}
    return _bank(conn, start, end, text, category, min_amt, max_amt, agg)



def parse_question(conn, message: str) -> dict[str, Any] | None:
    """Turn a user sentence into ask_books spec. None = let Gemini try."""
    text = (message or "").strip()
    if not text:
        return None
    low = text.lower()

    if re.search(r"\b(owe|owes|balance|who owes)\b", low):
        name = None
        m = re.search(r"(?:does|do)\s+([a-z]{2,30})\s+owe", low)
        if m:
            name = m.group(1)
        else:
            m = re.search(r"owe[s]?\s+(?:me\s+)?(?:for\s+|with\s+)?([a-z]{2,30})", low)
            if m and m.group(1) not in {"me", "i"}:
                name = m.group(1)
        if name:
            return {"scope": "khata", "person": name, "intent": "owe", "agg": "sum"}
        if "who" in low:
            return {"scope": "khata", "intent": "who", "agg": "list"}

    # Two-pass send detection — mirrors local_intent.py regexes for reliability
    _send_verb = re.search(r"\b(send|sent|gave|give|paid?)\b", low)
    if _send_verb:
        name_m = re.search(r"(?:send|sent|gave|give|paid?)\s+([A-Za-z]{2,40})", text, re.I)
        if name_m:
            name = name_m.group(1)
            # Threshold: "more than X", "greater than X"
            thresh_m = re.search(
                r"(?:greater than|greate than|more than|over|above|>)\s*"
                r"([\d,.]+\s*(?:k\b|lakh?s?|lacs?)\b|[\d,.]+)",
                text, re.I,
            )
            if thresh_m:
                amt = parse_inr_amount(thresh_m.group(1))
                return {"scope": "send", "person": name, "min_amount": amt, "exact_amount": 0, "intent": "send", "agg": "list"}
            # Exact amount: "50k", "50000", "1 lakh"
            exact_m = re.search(
                r"([\d,.]+\s*(?:k\b|lakh?s?|lacs?)\b|[1-9][\d,.]{3,})",
                text, re.I,
            )
            if exact_m:
                amt = parse_inr_amount(exact_m.group(1))
                return {"scope": "send", "person": name, "min_amount": 0, "exact_amount": amt, "intent": "send", "agg": "list"}
            # Bare send — no amount
            return {"scope": "send", "person": name, "min_amount": 0, "exact_amount": 0, "intent": "send", "agg": "list"}

    period = "last_90d"
    if "this month" in low or "this mth" in low:
        period = "this_month"
    elif "last month" in low:
        period = "last_month"
    elif "last week" in low or "7 day" in low:
        period = "last_7d"

    cat = ""
    for c in CATEGORIES:
        if c.lower() in low:
            cat = c
            break

    min_amt = 0.0
    am = re.search(r"(?:greater than|more than|over|above|>)\s*([\d,.]+(?:\s*(?:lakh?s?|lacs?))?)", low)
    if am:
        min_amt = parse_inr_amount(am.group(1))
        if _LAKH.search(text) and min_amt and min_amt < 1000:
            min_amt *= 100_000

    if re.search(r"\b(add|save|log|record)\b", low) and re.search(r"\d", low):
        return None

    agg = "list"
    if any(w in low for w in ("how much", "total", "spent", "spend")):
        agg = "sum"
    if any(w in low for w in ("top", "biggest", "largest", "most")):
        agg = "top_merchants"

    spendish = bool(
        cat
        or min_amt
        or re.search(r"\b(spend|spent|paid|upi|transaction|top|biggest|largest|swiggy|zomato)\b", low)
    )
    if not spendish:
        return None

    # Merchant / free text: drop filler words
    q = re.sub(
        r"\b(when|did|do|i|me|my|the|a|an|on|in|at|to|for|what|how|much|spend|spent|total|this|last|month|week|amount|greater|than|more|over|transaction|transactions|debit|debits|credit|credits|expense|expenses|category|categories|all|any|show|find|list|get)\b",
        " ",
        low,
    )
    q = re.sub(r"\s+", " ", q).strip()
    q = re.sub(r"[^\w\s]", "", q).strip()
    if cat:
        q = q.replace(cat.lower(), "").strip()
    if len(q) < 3:
        q = ""

    if cat or q or min_amt or period != "last_90d" or agg != "list":
        if not cat and not q and agg == "list" and period == "last_90d" and not min_amt:
            return None
        return {
            "scope": "bank",
            "period": period,
            "text": q[:40] if q else "",
            "category": cat,
            "min_amount": min_amt,
            "agg": agg,
            "intent": "bank",
        }
    return None


def _row_get(row, key: str, default=None):
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _bank(conn, start: str, end: str, text: str, category: str, min_amt: float, max_amt: float, agg: str) -> dict[str, Any]:
    data = dashboard_data(conn)
    ex = False if (category.lower() == "business" or "business" in text.lower()) else True
    rows = filter_dashboard_rows(data.get("transactions") or [], start, end, ex)
    q = text.lower()
    cat = category.lower()
    out = []
    total = 0.0
    by_merch: dict[str, float] = {}
    by_cat: dict[str, float] = {}
    for t in rows:
        debit = float(_row_get(t, "debit") or 0)
        credit = float(_row_get(t, "credit") or 0)
        amt = debit if debit else credit
        if min_amt and amt + 1e-9 < min_amt:
            continue
        if max_amt and amt > max_amt + 1e-9:
            continue
        merch = str(_row_get(t, "merchant_display") or "")
        desc = str(_row_get(t, "description") or "")
        cname = str(_row_get(t, "category") or "")
        if cat and cname.lower() != cat:
            continue
        if q and q not in (merch + " " + desc + " " + cname).lower():
            continue
        total += debit
        by_merch[merch or "Unknown"] = by_merch.get(merch or "Unknown", 0) + debit
        by_cat[cname or "Other"] = by_cat.get(cname or "Other", 0) + debit
        out.append(
            {
                "date": _row_get(t, "txn_date"),
                "merchant": merch,
                "debit": debit,
                "credit": credit,
                "category": cname,
            }
        )
    out.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    if agg == "sum":
        label = category or text or "spending"
        answer = f"{label} {start} to {end}: ₹{total:,.0f} across {len(out)} debits (business excluded)."
        return {"answer": answer, "totals": {"debit": total, "count": len(out)}, "rows": out[:8], "start": start, "end": end}
    if agg == "top_merchants":
        top = sorted(by_merch.items(), key=lambda kv: kv[1], reverse=True)[:8]
        if not top:
            answer = f"No matching spends {start} to {end}."
        else:
            bits = [f"{n} ₹{v:,.0f}" for n, v in top]
            answer = f"Top spends {start} to {end}: " + "; ".join(bits) + "."
        return {"answer": answer, "rows": [{"merchant": n, "debit": v} for n, v in top], "start": start, "end": end}
    if agg == "by_category":
        top = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)
        bits = [f"{n} ₹{v:,.0f}" for n, v in top[:8] if v]
        answer = f"By category {start} to {end}: " + ("; ".join(bits) if bits else "nothing") + "."
        return {"answer": answer, "rows": [{"category": n, "debit": v} for n, v in top], "start": start, "end": end}
    if not out:
        answer = f"No matching bank rows {start} to {end}."
    else:
        bits = []
        for r in out[:8]:
            amt = r['debit'] if r['debit'] else r['credit']
            t_type = "debit" if r['debit'] else "credit"
            bits.append(f"{r['date']} {r['merchant'] or ''} ₹{amt:,.0f} ({t_type})")
        answer = f"{len(out)} matching rows {start} to {end}: " + "; ".join(bits) + ("…" if len(out) > 8 else ".")
    return {"answer": answer, "rows": out[:15], "totals": {"debit": total, "count": len(out)}, "start": start, "end": end}


def _khata(conn, person: str, min_amt: float, spec: dict[str, Any]) -> dict[str, Any]:
    intent = str(spec.get("intent") or "")
    if intent == "who" or (not person and intent != "send"):
        items = []
        for item in get_all_balances(conn):
            bal = item["balance"]
            net = float(bal.get("net") or 0)
            if net == 0:
                continue
            name = item["contact"]["name"]
            items.append((name, net))
        items.sort(key=lambda r: abs(r[1]), reverse=True)
        if not items:
            return {"answer": "No open person balances.", "rows": []}
        bits = []
        for name, net in items[:8]:
            bits.append(f"{name} owes you ₹{net:,.0f}" if net > 0 else f"you owe {name} ₹{abs(net):,.0f}")
        return {"answer": "; ".join(bits) + ".", "rows": [{"contact_name": n, "net": v} for n, v in items[:8]]}

    contact = find_contact_by_text(conn, person) if person and not person.isdigit() else None
    if person and person.isdigit():
        cid = int(person)
        led = get_ledger(conn, cid)
        contact = led.get("contact")
    elif contact:
        cid = int(contact["id"])
        led = get_ledger(conn, cid)
    else:
        return {"answer": f"No contact matching {person!r}.", "rows": [], "error": "no contact"}

    name = (contact or {}).get("name") or person
    if intent in {"owe", "balance", "sum"} and spec.get("agg") == "sum" and intent != "send":
        bal = get_balance(conn, cid)
        net = float(bal.get("net") or 0)
        if net > 0:
            answer = f"{name} owes you ₹{net:,.2f}."
        elif net < 0:
            answer = f"You owe {name} ₹{abs(net):,.2f}."
        else:
            answer = f"{name} is settled (₹0)."
        return {"answer": answer, "rows": [], "contact_name": name, "net": net}

    hits = []
    want_dir = "you_sent" if intent == "send" else None
    for e in led.get("entries") or []:
        if e.get("is_passthrough"):
            continue
        try:
            amt = float(e.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if min_amt and amt + 1e-9 < min_amt:
            continue
        d = str(e.get("direction") or "")
        if want_dir and d != want_dir:
            continue
        hits.append({"date": e.get("entry_date"), "direction": d, "amount": amt, "purpose": e.get("purpose")})
    hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    if intent == "send":
        if not hits:
            thresh = f" of ₹{min_amt:,.0f}+" if min_amt else ""
            return {"answer": f"You have no khata sends to {name}{thresh}.", "rows": [], "contact_name": name}
        bits = [f"₹{h['amount']:,.0f} on {h['date']}" + (f" ({h['purpose']})" if h.get("purpose") else "") for h in hits[:8]]
        thresh = f" of ₹{min_amt:,.0f}+" if min_amt else ""
        return {"answer": f"You sent {name}{thresh}: " + "; ".join(bits) + ".", "rows": hits[:15], "contact_name": name}
    bits = [f"{h['date']} {h['direction']} ₹{h['amount']:,.0f}" for h in hits[:8]]
    return {
        "answer": f"{name} last khata lines: " + ("; ".join(bits) if bits else "none") + ".",
        "rows": hits[:15],
        "contact_name": name,
    }


def _find_sends_merged(
    conn,
    person: str,
    min_amt: float,
    exact_amt: float,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Search BOTH bank transactions and khata for money sent to a person.

    Bank pass: debits where merchant_display or description fuzzy-matches the contact.
    Khata pass: ledger you_sent entries for the contact.
    Merges results, labels source, returns combined answer.
    """
    # For send queries: default to all-time if no explicit period given.
    # A user asking "when did I send Highnes 50k" doesn't mean "in the last 90 days".
    if spec.get("period") or spec.get("start_date") or spec.get("end_date"):
        start, end = period_bounds(spec.get("period"), spec.get("start_date"), spec.get("end_date"))
    else:
        from datetime import date as _date
        start, end = "2000-01-01", _date.today().isoformat()


    contact = None
    cid: int | None = None
    led: dict = {"entries": [], "contact": None}

    if person and person.isdigit():
        cid = int(person)
        led = get_ledger(conn, cid)
        contact = led.get("contact")
    elif person:
        contact = find_contact_by_text(conn, person)
        if contact:
            cid = int(contact["id"])
            led = get_ledger(conn, cid)

    name = (led.get("contact") or contact or {}).get("name") or person

    # Build name/alias search terms
    terms = [
        s.lower()
        for s in [name] + list((contact or {}).get("aliases") or [])
        if s and len(s) >= 3
    ]
    if not terms:
        terms = [person.lower()] if person else []

    # --- Bank pass ---
    bank_hits: list[dict] = []
    data = dashboard_data(conn)
    for t in (data.get("transactions") or []):
        tx_date = str(_row_get(t, "txn_date") or "")
        if tx_date < start or tx_date > end:
            continue
        debit = float(_row_get(t, "debit") or 0)
        if debit <= 0:
            continue
        merch = str(_row_get(t, "merchant_display") or "").lower()
        desc = str(_row_get(t, "description") or "").lower()
        blob = merch + " " + desc
        if terms and not any(term in blob for term in terms):
            continue
        if exact_amt:
            tol = max(exact_amt * 0.05, 50)
            if not (exact_amt - tol <= debit <= exact_amt + tol):
                continue
        elif min_amt and debit + 1e-9 < min_amt:
            continue
        bank_hits.append({
            "date": tx_date,
            "amount": debit,
            "description": _row_get(t, "merchant_display") or _row_get(t, "description"),
            "source": "bank",
        })
    bank_hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)

    # --- Khata pass ---
    khata_hits: list[dict] = []
    for e in (led.get("entries") or []):
        if e.get("is_passthrough"):
            continue
        if str(e.get("direction") or "") != "you_sent":
            continue
        try:
            amt = float(e.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        entry_date = str(e.get("entry_date") or "")
        if entry_date and (entry_date < start or entry_date > end):
            continue
        if exact_amt:
            tol = max(exact_amt * 0.05, 50)
            if not (exact_amt - tol <= amt <= exact_amt + tol):
                continue
        elif min_amt and amt + 1e-9 < min_amt:
            continue
        khata_hits.append({
            "date": entry_date,
            "amount": amt,
            "description": e.get("purpose"),
            "source": "khata",
        })
    khata_hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)

    all_hits = bank_hits[:10] + khata_hits[:10]
    all_hits.sort(key=lambda r: str(r.get("date") or ""), reverse=True)

    thresh = (
        f" of ~₹{exact_amt:,.0f}" if exact_amt
        else (f" of ₹{min_amt:,.0f}+" if min_amt else "")
    )

    if not all_hits:
        if not contact and not (person or "").isdigit():
            answer = f"No contact matching {person!r} and no bank transactions found for that name."
        else:
            answer = f"No bank transactions or khata entries found for {name}{thresh}."
    else:
        src_label = (
            " (bank + khata)" if (bank_hits and khata_hits)
            else (" (bank)" if bank_hits else " (khata)")
        )
        parts = []
        for h in all_hits[:8]:
            src = " (khata)" if h["source"] == "khata" else ""
            desc_str = f" — {h['description']}" if h.get("description") else ""
            parts.append(f"₹{h['amount']:,.0f} on {h['date']}{desc_str}{src}")
        answer = f"You sent {name}{thresh}{src_label}: " + "; ".join(parts) + "."

    return {
        "answer": answer,
        "rows": all_hits[:15],
        "contact_name": name,
        "start": start,
        "end": end,
    }
