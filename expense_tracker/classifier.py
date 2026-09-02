from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


DEFAULT_SPLIT_RATIO = Decimal("1.00")

# ---------------------------------------------------------------------------
# CATEGORY_SEEDS — keyword → (category, expense_type)
# Keys are matched as substrings against the clean merchant_key produced by
# normalize_merchant().  Order matters for the first match — put more specific
# entries before shorter / more ambiguous ones.
# ---------------------------------------------------------------------------
CATEGORY_SEEDS: dict[str, tuple[str, str]] = {
    # ── Groceries / supermarket ─────────────────────────────────────────────
    "blinkit":      ("Groceries", "Personal"),
    "jiomart":      ("Groceries", "Personal"),
    "jiomartg":     ("Groceries", "Personal"),
    "bigbasket":    ("Groceries", "Personal"),
    "bbdaily":      ("Groceries", "Personal"),
    "bbnow":        ("Groceries", "Personal"),
    "bb now":       ("Groceries", "Personal"),
    "dunzo":        ("Groceries", "Personal"),
    "zepto":        ("Groceries", "Personal"),
    "dmart":        ("Groceries", "Personal"),
    "reliance fresh": ("Groceries", "Personal"),
    "innovati":     ("Groceries", "Personal"),   # Innovative Supermarket
    "lulu":         ("Groceries", "Personal"),
    "more supermarket": ("Groceries", "Personal"),
    # ── Food / restaurants ──────────────────────────────────────────────────
    "swiggy":       ("Food", "Personal"),
    "zomato":       ("Food", "Personal"),
    "zomato ltd":   ("Food", "Personal"),
    "wah chaii":    ("Food", "Personal"),
    "chai":         ("Food", "Personal"),
    "hotel":        ("Food", "Personal"),
    "restaurant":   ("Food", "Personal"),
    "cafe":         ("Food", "Personal"),
    "bakery":       ("Food", "Personal"),
    "althar":       ("Food", "Personal"),        # Althar Tea
    "madras":       ("Food", "Personal"),        # Madras Cafe / Madras Saravana etc.
    # ── Transport ───────────────────────────────────────────────────────────
    "uber":         ("Transport", "Personal"),
    "ola":          ("Transport", "Personal"),
    "rapido":       ("Transport", "Personal"),
    "redbus":       ("Transport", "Personal"),
    "irctc":        ("Transport", "Personal"),
    "indian rail":  ("Transport", "Personal"),
    "metro":        ("Transport", "Personal"),
    "fasttag":      ("Transport", "Personal"),
    "petrol":       ("Transport", "Personal"),
    "fuel":         ("Transport", "Personal"),
    # ── Utilities ───────────────────────────────────────────────────────────
    "airtel":       ("Utilities", "Personal"),
    "bsnl":         ("Utilities", "Personal"),
    "bescom":       ("Utilities", "Personal"),
    "kseb":         ("Utilities", "Personal"),
    "tata power":   ("Utilities", "Personal"),
    "msedcl":       ("Utilities", "Personal"),
    "electricity":  ("Utilities", "Personal"),
    "water bill":   ("Utilities", "Personal"),
    # ── Subscriptions ───────────────────────────────────────────────────────
    "netflix":      ("Subscription", "Personal"),
    "spotify":      ("Subscription", "Personal"),
    "amazon prime": ("Subscription", "Personal"),
    "prime video":  ("Subscription", "Personal"),
    "hotstar":      ("Subscription", "Personal"),
    "disney":       ("Subscription", "Personal"),
    "youtube premium": ("Subscription", "Personal"),
    "apple":        ("Subscription", "Personal"),
    "google":       ("Subscription", "Personal"),
    "github":       ("Subscription", "Personal"),
    "chatgpt":      ("Subscription", "Personal"),
    "openai":       ("Subscription", "Personal"),
    "xai":          ("Subscription", "Personal"),
    "grok":         ("Subscription", "Personal"),
    "jio prep":     ("Subscription", "Personal"),
    # ── Entertainment ───────────────────────────────────────────────────────
    "bookmyshow":   ("Entertainment", "Personal"),
    "bigtree":      ("Entertainment", "Personal"),   # BookMyShow parent
    "cinepolis":    ("Entertainment", "Personal"),
    "pvr":          ("Entertainment", "Personal"),
    "inox":         ("Entertainment", "Personal"),
    # ── Health ──────────────────────────────────────────────────────────────
    "pharmacy":     ("Health", "Personal"),
    "medplus":      ("Health", "Personal"),
    "apollo":       ("Health", "Personal"),
    "1mg":          ("Health", "Personal"),
    "practo":       ("Health", "Personal"),
    "dermavue":     ("Health", "Personal"),
    "informat":     ("Health", "Personal"),   # IKM Informatech clinic etc.
    "clinic":       ("Health", "Personal"),
    "hospital":     ("Health", "Personal"),
    "lab":          ("Health", "Personal"),
    # ── Shopping / e-commerce ───────────────────────────────────────────────
    "amazon":       ("Shopping", "Personal"),
    "flipkart":     ("Shopping", "Personal"),
    "myntra":       ("Shopping", "Personal"),
    "ajio":         ("Shopping", "Personal"),
    "nykaa":        ("Shopping", "Personal"),
    # ── Jio (telecom) — after jio prep & jiomart so those match first ───────
    "jio":          ("Utilities", "Personal"),
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
    "sbin",
    "dr",
    "cr",
    "via",
    "for",
    "no",
    "pay",
    "stati",
    "recur",
    "manda",
    "payme",
}

# 4-letter IFSC bank codes that appear in UPI descriptions (position after payee name)
_BANK_CODES = {
    "sbin", "hdfc", "icic", "yesb", "fdrl", "utib", "cnrb", "sibl", "nspb",
    "kkbk", "ubin", "sbip", "idfb", "axis", "kotak", "dcbl", "pmcb",
    "barb", "punb", "mahb", "bkid", "cbin", "alla", "orbc", "vijb",
    "stbp", "srcb", "pytm", "ratn", "finf", "airp", "ioba", "idib",
    "jiop", "ppiw",
}

# Maps truncated UPI payee names (as they appear in bank descriptions, uppercase)
# to their proper human-readable brand names.
_UPI_BRAND_MAP: dict[str, str] = {
    # Groceries
    "INNOVATI": "Innovative",
    "BBNOW":    "BB Now",
    "BIGBASKET": "BigBasket",
    "JIOMART":  "JioMart",
    "JIOMARTG": "JioMart",
    "BLINKIT":  "Blinkit",
    "ZEPTO":    "Zepto",
    "DMART":    "D-Mart",
    # Food
    "ZOMATO":   "Zomato",
    "ZOMATO L": "Zomato",
    "ZOMATO LTD": "Zomato",
    "SWIGGY":   "Swiggy",
    "SWIGGYIN": "Swiggy",
    # Transport
    "UBER":     "Uber",
    "RAPIDO":   "Rapido",
    "OLACABS":  "Ola",
    # Shopping
    "AMAZON P": "Amazon Pay",
    "AMAZON":   "Amazon",
    "FLIPKART": "Flipkart",
    "MYNTRA":   "Myntra",
    # Finance / Wallets
    "ONE97 CO": "Paytm",
    "ONE97":    "Paytm",
    "PHONEPE":  "PhonePe",
    # Healthcare
    "GG MEDS":  "GG Meds",
    "APOLLO":   "Apollo Pharmacy",
    "MEDPLUS":  "MedPlus",
    # Telecom
    "JIO":      "Jio",
    "AIRTEL":   "Airtel",
    "BSNL":     "BSNL",
    "VI ":      "Vi",
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
    if len(shared) >= 2 and max(len(token) for token in shared) >= 4:
        return Decimal("0.82")
    return Decimal("0")


def _is_upi_handle(token: str) -> bool:
    """Return True if the token looks like a UPI VPA handle (contains @) or
    is a run-together alphanumeric ID typically used as the UPI ID field."""
    if "@" in token:
        return True
    # UPI handles are usually long runs like 'bipinbalak', 'swiggyinst', 'altharatea'
    # They're all-lowercase, longer than 6 chars, no spaces
    if len(token) >= 7 and token.isalpha():
        return True
    return False


def _extract_upi_payee(raw: str) -> str | None:
    """Parse a UPI/DR/.../PAYEE/BANKCODE/vpa/... description and return the
    clean payee name, or None if not a recognised UPI format."""
    # Normalise: collapse whitespace inside segments that the bank breaks
    text = re.sub(r"[\r\n]+", " ", raw).strip()
    # Quick gate — must start with UPI/
    if not re.match(r"(?i)^upi/", text):
        return None
    # Split on /
    parts = [p.strip() for p in text.split("/")]
    # Expected: UPI, DR|CR, refno, PAYEE NAME, BANKCODE, vpa-handle, [suffix...]
    if len(parts) < 4:
        return None
    # parts[1] is DR or CR — skip
    # parts[2] is the numeric reference — skip
    # parts[3] is the payee name — THIS is what we want
    payee_raw = parts[3].strip()
    # Clean the payee: remove leading digits/special chars
    payee_clean = re.sub(r"^[\d\s]+", "", payee_raw).strip()
    if not payee_clean:
        return None

    # Check brand map first (match against uppercase key)
    brand = _UPI_BRAND_MAP.get(payee_clean.upper())
    if brand:
        return brand

    # Title-case the raw payee name — keep ALL parts including single-letter initials
    return " ".join(w.capitalize() for w in payee_clean.split())


def normalize_merchant(value: str) -> str:
    """Return a compact lowercase key suitable for fuzzy matching."""
    # For UPI transactions, extract payee name directly
    upi_payee = _extract_upi_payee(value)
    if upi_payee:
        return upi_payee.lower()

    # General path for NEFT, IMPS, POS, manual, etc.
    text = value.lower()
    text = re.sub(r"[\r\n]+", " ", text)
    # Strip leading bank-prefix noise (e.g. "NEFT*CHAS0INBX01*CHASH00052131772 *")
    text = re.sub(r"^(neft|imps|rtgs|pos|ach|ecs)[^a-z]*", "", text)
    text = re.sub(r"[^a-z0-9@.\-/ ]+", " ", text)
    # Remove pure numbers and reference-like tokens (alpha+3+ digits)
    text = re.sub(r"\b\d{4,}\b", " ", text)
    text = re.sub(r"\b[a-z]{1,3}\d{3,}\b", " ", text)
    parts = re.split(r"[/\-*@. ]+", text)
    useful = [
        p
        for p in parts
        if len(p) > 1
        and p not in STOP_TOKENS
        and p not in _BANK_CODES
        and not p.isdigit()
        and not any(ch.isdigit() for ch in p)
        and not _is_upi_handle(p)
    ]
    if not useful:
        # Fallback: only strip stop tokens and bank codes
        useful = [p for p in parts if p and p not in STOP_TOKENS and p not in _BANK_CODES]
    return " ".join(useful[:4]).strip()


def display_merchant(description: str, fallback: str = "Unknown merchant") -> str:
    """Return a human-readable merchant name for a transaction description."""
    # Fast path: UPI with a recognisable payee
    upi_payee = _extract_upi_payee(description)
    if upi_payee:
        return upi_payee

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
        status = "auto" if match_score == Decimal("1.00") else "needs_review"
        return Classification(
            category=row["category"],
            expense_type=row["expense_type"],
            split_ratio=Decimal(str(row["split_ratio"])),
            status=status,
            confidence=confidence.quantize(Decimal("0.01")),
            rule_id=row["id"],
        )

    seeded = seed_match(merchant_key)
    if seeded:
        category, expense_type = seeded
        split_ratio = Decimal("0.50") if expense_type == "Shared" else DEFAULT_SPLIT_RATIO
        return Classification(
            category=category,
            expense_type=expense_type,
            split_ratio=split_ratio,
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
