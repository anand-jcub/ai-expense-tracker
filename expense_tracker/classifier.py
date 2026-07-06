from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


DEFAULT_SPLIT_RATIO = Decimal("1.00")

CATEGORY_SEEDS = {
    "swiggy": ("Food", "Personal"),
    "zomato": ("Food", "Personal"),
    "bigbasket": ("Groceries", "Personal"),
    "bbdaily": ("Groceries", "Personal"),
    "netflix": ("Subscription", "Personal"),
    "spotify": ("Subscription", "Personal"),
    "amazon prime": ("Subscription", "Personal"),
    "uber": ("Transport", "Personal"),
    "ola": ("Transport", "Personal"),
    "rapido": ("Transport", "Personal"),
    "airtel": ("Utilities", "Personal"),
    "jio": ("Utilities", "Personal"),
    "bescom": ("Utilities", "Personal"),
    "kseb": ("Utilities", "Personal"),
}

STOP_TOKENS = {
    "upi",
    "paytm",
    "phonepe",
    "gpay",
    "googlepay",
    "razorpay",
    "payu",
    "billdesk",
    "pos",
    "imps",
    "neft",
    "rtgs",
    "inb",
    "ach",
    "ecs",
    "atm",
    "sbi",
    "statebank",
    "transfer",
    "to",
    "from",
    "ref",
    "txn",
    "rrn",
    "utr",
    "p2m",
    "p2p",
}


@dataclass(frozen=True)
class Classification:
    category: str | None
    expense_type: str
    split_ratio: Decimal
    status: str
    confidence: Decimal
    rule_id: int | None = None

    @property
    def needs_review(self) -> bool:
        return self.status == "needs_review"


def compact_merchant_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def merchant_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"\s+", value.lower().strip())
        if len(token) >= 2 and token not in STOP_TOKENS and not token.isdigit()
    }


def rule_match_score(merchant_key: str, rule_key: str) -> Decimal:
    if not merchant_key or not rule_key:
        return Decimal("0")
    if merchant_key == rule_key:
        return Decimal("1.00")

    merchant_compact = compact_merchant_key(merchant_key)
    rule_compact = compact_merchant_key(rule_key)
    if len(merchant_compact) >= 4 and merchant_compact == rule_compact:
        return Decimal("0.98")
    if min(len(merchant_compact), len(rule_compact)) >= 4 and (
        merchant_compact in rule_compact or rule_compact in merchant_compact
    ):
        return Decimal("0.90")

    merchant_parts = merchant_tokens(merchant_key)
    rule_parts = merchant_tokens(rule_key)
    if not merchant_parts or not rule_parts:
        return Decimal("0")
    if rule_parts.issubset(merchant_parts) or merchant_parts.issubset(rule_parts):
        longest = max(len(token) for token in merchant_parts | rule_parts)
        return Decimal("0.86") if longest >= 3 else Decimal("0")

    shared = merchant_parts & rule_parts
    if shared and max(len(token) for token in shared) >= 4:
        return Decimal("0.82")
    return Decimal("0")


def normalize_merchant(value: str) -> str:
    text = value.lower()
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"[^a-z0-9@.\-/ ]+", " ", text)
    text = re.sub(r"\b\d{4,}\b", " ", text)
    text = re.sub(r"\b[a-z]{2,}\d{3,}\b", " ", text)
    parts = re.split(r"[/\-*@. ]+", text)
    useful = [
        p
        for p in parts
        if len(p) > 1 and p not in STOP_TOKENS and not p.isdigit() and not any(ch.isdigit() for ch in p)
    ]
    if not useful:
        useful = [p for p in parts if p and p not in STOP_TOKENS]
    return " ".join(useful[:4]).strip()


def display_merchant(description: str, fallback: str = "Unknown merchant") -> str:
    key = normalize_merchant(description)
    if not key:
        return fallback
    return " ".join(word.capitalize() for word in key.split())


def seed_match(merchant_key: str) -> tuple[str, str] | None:
    for keyword, classification in CATEGORY_SEEDS.items():
        if keyword in merchant_key:
            return classification
    return None


def find_merchant_rule(conn, merchant_key: str):
    exact = conn.execute(
        """
        select id, merchant_key, category, expense_type, split_ratio, confidence
        from merchant_rules
        where merchant_key = ?
        """,
        (merchant_key,),
    ).fetchone()
    if exact:
        return exact, Decimal("1.00")

    best = None
    best_score = Decimal("0")
    rows = conn.execute(
        """
        select id, merchant_key, category, expense_type, split_ratio, confidence
        from merchant_rules
        order by match_count desc, updated_at desc
        """
    ).fetchall()
    for row in rows:
        score = rule_match_score(merchant_key, row["merchant_key"])
        if score > best_score:
            best = row
            best_score = score
    if best is not None and best_score >= Decimal("0.82"):
        return best, best_score
    return None, Decimal("0")


def classify_transaction(conn, merchant_key: str) -> Classification:
    row, match_score = find_merchant_rule(conn, merchant_key)
    if row:
        confidence = Decimal(str(row["confidence"])) * match_score
        return Classification(
            category=row["category"],
            expense_type=row["expense_type"],
            split_ratio=Decimal(str(row["split_ratio"])),
            status="auto",
            confidence=confidence.quantize(Decimal("0.01")),
            rule_id=row["id"],
        )

    seeded = seed_match(merchant_key)
    if seeded:
        category, expense_type = seeded
        return Classification(
            category=category,
            expense_type=expense_type,
            split_ratio=DEFAULT_SPLIT_RATIO,
            status="auto",
            confidence=Decimal("0.72"),
        )

    return Classification(
        category=None,
        expense_type="Personal",
        split_ratio=DEFAULT_SPLIT_RATIO,
        status="needs_review",
        confidence=Decimal("0"),
    )


def effective_share(amount: Decimal, expense_type: str, split_ratio: Decimal) -> Decimal:
    """Calculate the user's share of an expense.

    Split ratio is applied to any debit where split_ratio < 1, regardless
    of expense_type.  Transfer/Loan types return zero since they are not
    personal expenses.
    """
    debit_amount = abs(amount) if amount < 0 else Decimal("0")
    if expense_type in {"Transfer", "Loan"}:
        return Decimal("0.00")
    if split_ratio < 1:
        return (debit_amount * split_ratio).quantize(Decimal("0.01"))
    return debit_amount.quantize(Decimal("0.01"))
