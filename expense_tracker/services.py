"""Business logic: filtering, sorting, aggregation, and shared-expense math."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


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
    "Travel",
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
    if abs(people - nearest) <= Decimal("0.0001") and nearest >= 1:
        return int(nearest)
    return 1


def review_people_value(row) -> int:
    if row["expense_type"] == "Shared":
        return people_from_split_ratio(row["split_ratio"])
    return 1


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
                "amount_signed",
                "debit",
                "credit",
            ]
            if key in row.keys()
        ).lower()
        if all(term in haystack for term in terms):
            filtered.append(row)
    return filtered


def filter_editable_rows(rows, query: str):
    editable = [row for row in rows if row["status"] != "needs_review"]
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
                "amount_signed",
                "debit",
                "credit",
            ]
            if key in row.keys()
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
    dates = sorted({str(row["txn_date"]) for row in rows if row["txn_date"]})
    if not dates:
        return "", ""
    return dates[0], dates[-1]


def filter_dashboard_rows(rows, start_date: str = "", end_date: str = "", exclude_business: bool = False):
    filtered = []
    for row in rows:
        txn_date = str(row["txn_date"])
        if start_date and txn_date < start_date:
            continue
        if end_date and txn_date > end_date:
            continue
        if exclude_business and (
            str(row["category"] or "").lower() == "business"
            or str(row["expense_type"] or "").lower() == "business"
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
        my_share = Decimal(str(row["my_share"] or 0))
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


def dashboard_totals(rows, use_my_share: bool = False) -> dict[str, Decimal]:
    credit_total, debit_total = credit_debit_totals(rows)
    expense_total = sum(expense_amount_for_row(row, use_my_share) for row in rows)
    return {
        "credit": credit_total,
        "debit": debit_total,
        "expense": expense_total,
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
