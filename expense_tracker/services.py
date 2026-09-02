"""Business logic: filtering, sorting, aggregation, and shared-expense math."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


CATEGORIES = [
    "Food",
    "Groceries",
    "Subscription",
    "Transport",
    "Utilities",
    "Shopping",
    "Health",
    "Personal Care",
    "Rent",
    "Flat",
    "Travel",
    "Entertainment",
    "Business",
    "Transfer",
    "Loan",
    "Family",
    "Other",
]
EXPENSE_TYPES = ["Personal", "Business", "Shared", "Transfer", "Loan", "Other"]


def split_ratio_from_people(value) -> Decimal:
    try:
        people = Decimal(str(value or "1"))
    except InvalidOperation:
        people = Decimal("1")
    if people < 1:
        raise ValueError("Number of people must be at least 1.")
    if people != people.to_integral_value():
        raise ValueError("Number of people must be a whole number.")
    return Decimal("1") / people


def people_from_split_ratio(value) -> int:
    try:
        ratio = Decimal(str(value or "1"))
    except InvalidOperation:
        return 1
    if ratio <= 0:
        return 1
    people = Decimal("1") / ratio
    nearest = people.to_integral_value()
    if abs(people - nearest) <= Decimal("0.05") and nearest >= 1:
        return int(nearest)
    return 1


def review_people_value(row) -> int:
    et = row["expense_type"] if (hasattr(row, "keys") and "expense_type" in row.keys()) or (isinstance(row, dict) and "expense_type" in row) else None
    if et == "Shared":
        sr = row["split_ratio"] if (hasattr(row, "keys") and "split_ratio" in row.keys()) or (isinstance(row, dict) and "split_ratio" in row) else None
        people = people_from_split_ratio(sr)
        return people if people > 1 else 2
    return 2


def split_display(value) -> str:
    people = people_from_split_ratio(value)
    return f"1/{people}"


def sort_review_rows(rows, direction: str):
    reverse = direction != "oldest"
    by_date = sorted(rows, key=lambda r: (r["txn_date"], r["id"]), reverse=reverse)
    def has_matched_rule(r):
        d = dict(r)
        return 1 if d.get("rule_id") is not None else 0
    return sorted(by_date, key=has_matched_rule)


def filter_review_rows(rows, query: str):
    cleaned = query.strip().lower()
    if not cleaned:
        return list(rows)
    terms = cleaned.split()
    filtered = []
    for row in rows:
        haystack = " ".join(
            str(row[key] or "")
            for key in [
                "txn_date",
                "merchant_display",
                "description",
                "category",
                "expense_type",
                "notes",
                "shared_with",
                "amount_signed",
                "debit",
                "credit",
            ]
            if (hasattr(row, "keys") and key in row.keys()) or (isinstance(row, dict) and key in row)
        ).lower()
        if all(term in haystack for term in terms):
            filtered.append(row)
    return filtered


def filter_editable_rows(rows, query: str):
    editable = [row for row in rows if (row["status"] if hasattr(row, "keys") and "status" in row.keys() else (row.get("status") if isinstance(row, dict) else None)) != "needs_review"]
    cleaned = query.strip().lower()
    if not cleaned:
        return editable
    terms = cleaned.split()
    filtered = []
    for row in editable:
        haystack = " ".join(
            str(row[key] or "")
            for key in [
                "txn_date",
                "merchant_display",
                "description",
                "category",
                "expense_type",
                "status",
                "notes",
                "shared_with",
                "amount_signed",
                "debit",
                "credit",
            ]
            if (hasattr(row, "keys") and key in row.keys()) or (isinstance(row, dict) and key in row)
        ).lower()
        if all(term in haystack for term in terms):
            filtered.append(row)
    return filtered


def filter_transactions_by_text(rows, query: str):
    cleaned = query.strip().lower()
    if not cleaned:
        return []
    terms = cleaned.split()
    filtered = []
    for row in rows:
        haystack = " ".join(
            str(row[key] or "")
            for key in [
                "txn_date",
                "value_date",
                "merchant_display",
                "description",
                "reference",
                "raw_text",
                "category",
                "expense_type",
                "debit",
                "credit",
                "amount_signed",
            ]
            if key in row.keys()
        ).lower()
        if all(term in haystack for term in terms):
            filtered.append(row)
    return filtered


def _row_get(row, key: str, default=0):
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def credit_debit_totals(rows) -> tuple[Decimal, Decimal]:
    credit_total = sum(
        max(Decimal("0"), Decimal(str(row["credit"] or 0)) - Decimal(str(_row_get(row, "credit_offset", 0))))
        for row in rows
    )
    debit_total = sum(
        max(Decimal("0"), Decimal(str(row["debit"] or 0)) - Decimal(str(_row_get(row, "debit_offset", 0))))
        for row in rows
    )
    return credit_total, debit_total


def date_bounds(rows) -> tuple[str, str]:
    dates = sorted({str(row["txn_date"])[:10] for row in rows if row["txn_date"]})
    if not dates:
        return "", ""
    return dates[0], dates[-1]


def default_dashboard_period(
    today: date | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
) -> tuple[str, str]:
    """Current calendar month, or the month of the latest txn if this month is empty."""
    day = today or date.today()
    month_start, month_end = current_month_bounds(day)
    latest = (max_date or "")[:10]
    earliest = (min_date or "")[:10]
    if latest and month_start > latest:
        latest_d = date.fromisoformat(latest)
        return current_month_bounds(latest_d)
    start, end = month_start, month_end
    if earliest and start < earliest:
        start = earliest
    if latest and end > latest:
        end = latest
    if start > end:
        return earliest or start, latest or end
    return start, end


def filter_dashboard_rows(rows, start_date: str = "", end_date: str = "", exclude_business: bool = False):
    filtered = []
    start_str = str(start_date)[:10] if start_date else ""
    end_str = str(end_date)[:10] if end_date else ""
    for row in rows:
        raw_date = row["txn_date"] if hasattr(row, "keys") and "txn_date" in row.keys() else (row.get("txn_date") if isinstance(row, dict) else getattr(row, "txn_date", ""))
        txn_date_str = str(raw_date or "")[:10]
        if start_str and txn_date_str < start_str:
            continue
        if end_str and txn_date_str > end_str:
            continue
        cat = row["category"] if hasattr(row, "keys") and "category" in row.keys() else (row.get("category") if isinstance(row, dict) else "")
        exp_type = row["expense_type"] if hasattr(row, "keys") and "expense_type" in row.keys() else (row.get("expense_type") if isinstance(row, dict) else "")
        if exclude_business and (
            str(cat or "").lower() == "business"
            or str(exp_type or "").lower() == "business"
        ):
            continue
        filtered.append(row)
    return filtered


def expense_amount_for_row(row, use_my_share: bool) -> Decimal:
    """Return the expense amount for a row.

    Excludes non-expense transaction types (Transfer, Loan). When use_my_share is
    True, returns the user's split share (my_share), otherwise returns the full debit.
    """
    debit = Decimal(str(row["debit"] or 0))
    debit_offset = Decimal(str(_row_get(row, "debit_offset", 0)))
    net_debit = max(Decimal("0"), debit - debit_offset)
    if net_debit <= 0:
        return Decimal("0")
    
    # Exclude Transfer and Loan from personal consumption expenses
    expense_type = row["expense_type"] if (hasattr(row, "keys") and "expense_type" in row.keys()) or (isinstance(row, dict) and "expense_type" in row) else None
    if expense_type in {"Transfer", "Loan"}:
        return Decimal("0")
        
    if use_my_share:
        my_share = Decimal(str(_row_get(row, "my_share", net_debit) or 0))
        return min(my_share, net_debit)
    return net_debit


def expenses_by_category(rows, use_my_share: bool = False) -> list[tuple[str, Decimal]]:
    by_category: dict[str, Decimal] = {}
    for row in rows:
        amount = expense_amount_for_row(row, use_my_share)
        if amount <= 0:
            continue
        category = row["category"] or "Uncategorized"
        by_category[category] = by_category.get(category, Decimal("0")) + amount
    return sorted(by_category.items(), key=lambda item: item[1], reverse=True)


def format_month_label(ym_str: str) -> str:
    """Converts 'YYYY-MM' to 'Mon \\'YY' (e.g. '2026-08' -> 'Aug \\'26')."""
    try:
        parts = ym_str.split("-")
        if len(parts) >= 2:
            y, m = int(parts[0]), int(parts[1])
            d = date(y, m, 1)
            return d.strftime("%b '%y")
    except Exception:
        pass
    return ym_str


def monthly_spend_trend(rows, metric: str = "expenses") -> list[tuple[str, Decimal]]:
    """Group rows by calendar month (YYYY-MM) and compute sum of the chosen metric.

    metric can be:
    - 'expenses': personal spend share (my_share)
    - 'debits': total bank debits (net of offsets)
    - 'credits': total bank credits (net of offsets)

    Returns sorted list of (formatted_month_label, amount_decimal) in chronological order.
    """
    by_month: dict[str, Decimal] = {}
    for row in rows:
        raw_date = (
            row["txn_date"]
            if hasattr(row, "keys") and "txn_date" in row.keys()
            else (row.get("txn_date") if isinstance(row, dict) else getattr(row, "txn_date", ""))
        )
        if not raw_date:
            continue
        ym = str(raw_date)[:7]
        if len(ym) != 7 or "-" not in ym:
            continue

        if metric == "expenses":
            amt = expense_amount_for_row(row, use_my_share=True)
        elif metric == "debits":
            debit = Decimal(str(row["debit"] or 0))
            offset = Decimal(str(_row_get(row, "debit_offset", 0)))
            amt = max(Decimal("0"), debit - offset)
        elif metric == "credits":
            credit = Decimal(str(row["credit"] or 0))
            offset = Decimal(str(_row_get(row, "credit_offset", 0)))
            amt = max(Decimal("0"), credit - offset)
        else:
            amt = Decimal("0")

        if amt > 0:
            by_month[ym] = by_month.get(ym, Decimal("0")) + amt
        elif ym not in by_month:
            by_month[ym] = Decimal("0")

    sorted_months = sorted(by_month.keys())
    return [(format_month_label(m), by_month[m]) for m in sorted_months]


def monthly_trends_dict(rows) -> dict[str, list[tuple[str, Decimal]]]:
    """Returns monthly trends dictionary for all 3 metrics: expenses, debits, credits."""
    return {
        "expenses": monthly_spend_trend(rows, metric="expenses"),
        "debits": monthly_spend_trend(rows, metric="debits"),
        "credits": monthly_spend_trend(rows, metric="credits"),
    }


def current_month_bounds(today: date | None = None) -> tuple[str, str]:
    """Inclusive YYYY-MM-DD start/end of the calendar month containing `today`."""
    day = today or date.today()
    start = day.replace(day=1)
    if day.month == 12:
        end = date(day.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(day.year, day.month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _json_money(value) -> float:
    return float(value or 0)


def dashboard_summary_payload(
    conn,
    start_date: str | None = None,
    end_date: str | None = None,
    exclude_business: bool = True,
    use_current_month: bool = True,
) -> dict[str, Any]:
    """One owner for period spend (FC-07). HTTP, MCP, and assistant all call this.

    Totals use bank credits/debits. `by_category` uses my-share expense amounts
    so “food this month” matches personal spend, not full shared bills.
    """
    from .db import dashboard_data

    data = dashboard_data(conn)
    start = (start_date or "").strip()
    end = (end_date or "").strip()
    if not start and not end and use_current_month:
        min_d, max_d = date_bounds(data.get("transactions") or [])
        start, end = default_dashboard_period(date.today(), min_d, max_d)
    rows = filter_dashboard_rows(
        data.get("transactions") or [],
        start,
        end,
        exclude_business,
    )
    totals = dashboard_totals(rows, use_my_share=False)
    cats = expenses_by_category(rows, use_my_share=True)
    pending_all = data.get("pending") or []
    if start or end:
        period_pending = [
            p for p in pending_all
            if (not start or str(_row_get(p, "txn_date", ""))[:10] >= start)
            and (not end or str(_row_get(p, "txn_date", ""))[:10] <= end)
        ]
    else:
        period_pending = pending_all

    return {
        "start_date": start or None,
        "end_date": end or None,
        "exclude_business": bool(exclude_business),
        "period_credits": _json_money(totals.get("credit")),
        "period_debits": _json_money(totals.get("debit")),
        "period_expense_share": _json_money(totals.get("expense_share")),
        "transaction_count": len(rows),
        "needs_review_count": len(period_pending),
        "by_category": [
            {"category": name, "amount": _json_money(amount)} for name, amount in cats
        ],
    }


def dashboard_totals(rows, use_my_share: bool = False) -> dict[str, Decimal]:
    credit_total, debit_total = credit_debit_totals(rows)
    expense_total = sum(expense_amount_for_row(row, use_my_share) for row in rows)
    # expense_share is always the personal-spend view (my_share), regardless of use_my_share toggle
    expense_share = sum(expense_amount_for_row(row, use_my_share=True) for row in rows)
    return {
        "credit": credit_total,
        "debit": debit_total,
        "expense": expense_total,
        "expense_share": expense_share,
        "net": credit_total - debit_total,
    }


def top_merchants_from_rows(rows, use_my_share: bool = False) -> list[tuple[str, Decimal]]:
    """Compute top merchants by spend, optionally using the user's share."""
    by_merchant: dict[str, Decimal] = {}
    for row in rows:
        amount = expense_amount_for_row(row, use_my_share)
        if amount <= 0:
            continue
        merchant = row["merchant_display"]
        by_merchant[merchant] = by_merchant.get(merchant, Decimal("0")) + amount
    return sorted(by_merchant.items(), key=lambda item: item[1], reverse=True)[:10]


def active_period_label(start_date: str, end_date: str) -> str:
    if start_date and end_date:
        return f"{start_date} to {end_date}"
    if start_date:
        return f"From {start_date}"
    if end_date:
        return f"Until {end_date}"
    return "All transactions"


def partner_share_for_row(row) -> Decimal:
    """Residual after my share on net debit base (single partner)."""
    debit = Decimal(str(row["debit"] if hasattr(row, "keys") else row.get("debit", 0) or 0))
    try:
        offset = Decimal(str(row["debit_offset"] if "debit_offset" in row.keys() else 0 or 0))
    except Exception:
        offset = Decimal(str((row.get("debit_offset") if isinstance(row, dict) else 0) or 0))
    base = max(Decimal("0"), debit - offset)
    if base <= 0:
        return Decimal("0.00")
    try:
        expense_type = row["expense_type"] if "expense_type" in row.keys() else ""
    except Exception:
        expense_type = (row.get("expense_type") if isinstance(row, dict) else "") or ""
    if expense_type in {"Loan", "Transfer"}:
        return Decimal("0.00")
    try:
        ratio = Decimal(str(row["split_ratio"] if "split_ratio" in row.keys() else 1))
    except Exception:
        ratio = Decimal(str((row.get("split_ratio") if isinstance(row, dict) else 1) or 1))
    if ratio < 1:
        my = (base * ratio).quantize(Decimal("0.01"))
    else:
        my = base.quantize(Decimal("0.01"))
    return max(Decimal("0"), (base - my).quantize(Decimal("0.01")))


def compute_partner_balances(conn, current_user: str, all_users: list[str] | None = None) -> list[dict] | dict:
    """Legacy multi-user shared-expense partner balances (not khata)."""
    if isinstance(conn, (list, tuple)):
        they_owe = Decimal("0")
        i_owe = Decimal("0")
        for r in conn:
            if dict(r).get("expense_type") == "Shared":
                if dict(r).get("is_external"):
                    i_owe += Decimal(str(dict(r).get("my_share") or 0))
                else:
                    they_owe += Decimal(str(dict(r).get("debit") or 0)) - Decimal(str(dict(r).get("my_share") or 0))
        net = they_owe - i_owe
        return {
            "alice": {
                "you_owe": i_owe,
                "owes_you": they_owe,
                "net": net,
                "status": "owes_you" if net > 0 else ("you_owe" if net < 0 else "settled"),
            }
        }

    all_users = all_users or []
    results = []
    for partner in all_users:
        if partner.lower() == current_user.lower():
            continue
        try:
            rows = conn.execute(
                """
                SELECT t.debit, c.my_share, c.expense_type, c.split_ratio,
                       coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0) as debit_offset
                FROM transactions t
                JOIN classifications c ON c.transaction_id = t.id
                WHERE t.debit > 0
                  AND c.expense_type = 'Shared'
                  AND lower(c.shared_with) = ?
                  AND (t.uploaded_by = ? OR t.uploaded_by IS NULL)
                """,
                (partner.lower(), current_user.lower()),
            ).fetchall()
            they_owe_me = sum((partner_share_for_row(r) for r in rows), Decimal("0"))

            partner_rows = conn.execute(
                """
                SELECT t.debit, c.my_share, c.expense_type, c.split_ratio,
                       coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0) as debit_offset
                FROM transactions t
                JOIN classifications c ON c.transaction_id = t.id
                WHERE t.uploaded_by = ?
                  AND c.expense_type = 'Shared'
                  AND lower(c.shared_with) = ?
                """,
                (partner.lower(), current_user.lower()),
            ).fetchall()
            i_owe_them = sum(
                (Decimal(str(r["my_share"] or 0)) for r in partner_rows),
                Decimal("0"),
            )

            net = they_owe_me - i_owe_them
            if they_owe_me > 0 or i_owe_them > 0:
                results.append({
                    "username": partner,
                    "they_owe_you": they_owe_me,
                    "you_owe_them": i_owe_them,
                    "net": net,
                })
        except Exception:
            logger = __import__("logging").getLogger(__name__)
            logger.exception("compute_partner_balances failed for %s", partner)
    return results


def get_household_balances(conn, current_user: str) -> list[dict]:
    """Khata nets for contacts with non-zero balance."""
    try:
        from .contacts import get_all_balances

        return [
            {
                "username": item["contact"]["name"],
                "they_owe_you": item["balance"]["they_owe_you"],
                "you_owe_them": item["balance"]["you_owe_them"],
                "net": item["balance"]["net"],
            }
            for item in get_all_balances(conn)
            if item["balance"]["net"] != 0
        ]
    except Exception:
        return []


def credits_by_category(rows) -> list[tuple[str, Decimal]]:
    """Compute credit totals by category."""
    by_cat: dict[str, Decimal] = {}
    for row in rows:
        credit = max(Decimal("0"), Decimal(str(row["credit"] or 0)) - Decimal(str(_row_get(row, "credit_offset", 0))))
        if credit <= 0:
            continue
        cat = row["category"] or "Uncategorized"
        by_cat[cat] = by_cat.get(cat, Decimal("0")) + credit
    return sorted(by_cat.items(), key=lambda x: x[1], reverse=True)


def debits_by_category(rows) -> list[tuple[str, Decimal]]:
    """Compute debit totals by category."""
    by_cat: dict[str, Decimal] = {}
    for row in rows:
        debit = max(Decimal("0"), Decimal(str(row["debit"] or 0)) - Decimal(str(_row_get(row, "debit_offset", 0))))
        if debit <= 0:
            continue
        cat = row["category"] or "Uncategorized"
        by_cat[cat] = by_cat.get(cat, Decimal("0")) + debit
    return sorted(by_cat.items(), key=lambda x: x[1], reverse=True)


def credits_by_merchant(rows) -> list[tuple[str, Decimal]]:
    by_m: dict[str, Decimal] = {}
    for row in rows:
        credit = max(Decimal("0"), Decimal(str(row["credit"] or 0)) - Decimal(str(_row_get(row, "credit_offset", 0))))
        if credit <= 0:
            continue
        m = row["merchant_display"] or "Unknown"
        by_m[m] = by_m.get(m, Decimal("0")) + credit
    return sorted(by_m.items(), key=lambda x: x[1], reverse=True)[:10]


def debits_by_merchant(rows) -> list[tuple[str, Decimal]]:
    by_m: dict[str, Decimal] = {}
    for row in rows:
        debit = max(Decimal("0"), Decimal(str(row["debit"] or 0)) - Decimal(str(_row_get(row, "debit_offset", 0))))
        if debit <= 0:
            continue
        m = row["merchant_display"] or "Unknown"
        by_m[m] = by_m.get(m, Decimal("0")) + debit
    return sorted(by_m.items(), key=lambda x: x[1], reverse=True)[:10]
