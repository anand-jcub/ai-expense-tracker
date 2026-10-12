"""Highnes Loan Ledger & Auto-Reconciliation Domain.

Tracks loans taken by Highnes in Anand's name:
  1. Clix Capital (₹5,695 / month via ACH/NACH)
  2. Branch International (~₹2,981 / month via UPI)
  3. SBI Loan EMI (₹4,820 / month)

Maintains an auditable ledger starting from an opening balance of ₹56,362 (as of Aug 31, 2026).
Whenever loan EMIs are debited from newly uploaded statements (Sept 1, 2026 onwards):
  - Checks if Highnes sent a matching reimbursement.
  - If reimbursed: links the two transactions with net zero debt addition.
  - If NOT reimbursed: adds the unpaid EMI debit to Highnes's outstanding balance.
"""

from __future__ import annotations

import logging
import sqlite3
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SHARE_KEY_FILE = "highnes_share_key"


def get_or_create_share_key(data_dir) -> str:
    """Secret for the read-only link Highnes can open. Stored only on this PC."""
    from pathlib import Path
    import secrets

    path = Path(data_dir) / SHARE_KEY_FILE
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_urlsafe(18)
    path.write_text(key, encoding="utf-8")
    return key


def share_key_matches(data_dir, given: str) -> bool:
    from pathlib import Path

    path = Path(data_dir) / SHARE_KEY_FILE
    if not path.is_file():
        return False
    return given.strip() == path.read_text(encoding="utf-8").strip()


OPENING_BALANCE: float = 56362.0
OPENING_DATE: str = "2026-08-31"
RECONCILIATION_START_DATE: str = "2026-09-01"

LOAN_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "id": "clix",
        "name": "Clix Capital",
        "expected_amount": 5695.0,
        "amount_tolerance": 2.0,
        "patterns": ["clix", "clix capital", "nach00000000006089"],
        "schedule": "Monthly (~7th)",
        "due_day": 7,
    },
    {
        "id": "branch",
        "name": "Branch International",
        "expected_amount": 2981.0,
        "amount_tolerance": 5.0,  # Accommodates 2979.0 - 2981.0
        "patterns": ["branch i", "branch", "branchonli", "brancho nli"],
        "schedule": "Monthly (~1st/end of month)",
        "due_day": 1,
    },
    {
        "id": "sbi",
        "name": "SBI Loan EMI",
        "expected_amount": 4820.0,
        "amount_tolerance": 2.0,
        "patterns": ["sbi loan emi"],
        "schedule": "Monthly (~17th)",
        "due_day": 17,
    },
]

HIGHNES_IDENTIFIERS: List[str] = [
    "highnes",
    "highnesj",
    "8078866770",
    "9955577992",
    "highnes.7@",
    "highnes.7-",
]


def init_highnes_ledger(conn: sqlite3.Connection) -> None:
    """Create the highnes_ledger table and seed the baseline opening balance."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS highnes_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date TEXT NOT NULL,
            entry_type TEXT NOT NULL,          -- 'opening_balance', 'loan_debit', 'reimbursement', 'manual_adjustment'
            loan_name TEXT,                    -- 'Clix Capital', 'Branch International', 'SBI Loan', or NULL
            amount REAL NOT NULL,              -- Positive: Highnes owes more; Negative: Highnes repaid
            txn_id INTEGER REFERENCES transactions(id),
            matched_txn_id INTEGER REFERENCES transactions(id),
            reconciliation_status TEXT NOT NULL DEFAULT 'unreimbursed', -- 'opening', 'matched', 'unreimbursed'
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_highnes_ledger_date ON highnes_ledger(entry_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_highnes_ledger_txn ON highnes_ledger(txn_id)"
    )

    # Seed baseline opening balance if not exists
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM highnes_ledger WHERE entry_type = 'opening_balance'"
    ).fetchone()
    if not row:
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO highnes_ledger (
                entry_date, entry_type, loan_name, amount,
                reconciliation_status, notes, created_at
            )
            VALUES (?, 'opening_balance', NULL, ?, 'opening', ?, ?)
            """,
            (
                OPENING_DATE,
                OPENING_BALANCE,
                "Verified baseline balance owed up to August 31, 2026",
                now,
            ),
        )
        conn.commit()
        logger.info("Seeded Highnes opening balance of ₹%.2f as of %s", OPENING_BALANCE, OPENING_DATE)


def match_loan_debit(txn: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Determine if a debit transaction is one of Highnes's 3 loan EMIs."""
    debit = float(txn.get("debit") or 0)
    if debit <= 0:
        return None

    desc = (txn.get("description") or "").lower()
    merchant = (txn.get("merchant_display") or "").lower()
    text = f"{merchant} {desc}".strip()
    blank = text in {"", "no description", "no description no description"}

    # Some statement lines print the EMI amount with no narration (SBI on 17 Sep).
    if blank:
        for loan in LOAN_DEFINITIONS:
            if abs(debit - loan["expected_amount"]) <= loan["amount_tolerance"]:
                return loan

    for loan in LOAN_DEFINITIONS:
        for p in loan["patterns"]:
            if p in text:
                # Check amount tolerance
                if abs(debit - loan["expected_amount"]) <= loan["amount_tolerance"]:
                    return loan
                # Or pattern explicitly mentions loan EMI
                if "loan emi" in text or "clix capital" in text:
                    return loan
    return None


def is_highnes_credit(txn: Dict[str, Any]) -> bool:
    """Determine if a credit transaction originates from Highnes."""
    credit = float(txn.get("credit") or 0)
    if credit <= 0:
        return False

    desc = (txn.get("description") or "").lower()
    merchant = (txn.get("merchant_display") or "").lower()
    text = f"{merchant} {desc}"

    return any(identifier in text for identifier in HIGHNES_IDENTIFIERS)


def is_highnes_debit(txn: Dict[str, Any]) -> bool:
    """Determine if a debit transaction is direct money sent by Anand to Highnes (not a proxy loan EMI)."""
    debit = float(txn.get("debit") or 0)
    if debit <= 0:
        return False

    # Never treat proxy loan EMIs as personal ad-hoc transfers
    if match_loan_debit(txn):
        return False

    desc = (txn.get("description") or "").lower()
    merchant = (txn.get("merchant_display") or "").lower()
    text = f"{merchant} {desc}"

    return any(identifier in text for identifier in HIGHNES_IDENTIFIERS)


def reconcile_highnes_statement(
    conn: sqlite3.Connection,
    start_date: str = RECONCILIATION_START_DATE,
) -> Dict[str, Any]:
    """Audit loan debits & personal money transfers from start_date onwards against Highnes reimbursements.
    
    Returns a dictionary summarizing:
      - newly_reconciled: count of new records processed
      - matched: count of debits/transfers reimbursed by Highnes
      - unreimbursed: count of debits/transfers added to Highnes's debt
    """
    init_highnes_ledger(conn)
    cur = conn.cursor()

    # Get all transactions from start_date onwards
    cur.execute(
        """
        SELECT id, txn_date, debit, credit, merchant_display, description, reference
        FROM transactions
        WHERE txn_date >= ?
        ORDER BY txn_date ASC, id ASC
        """,
        (start_date,),
    )
    all_rows = [dict(r) for r in cur.fetchall()]

    # Existing ledger txn_ids to avoid duplicate posting
    cur.execute(
        "SELECT txn_id, matched_txn_id FROM highnes_ledger WHERE txn_id IS NOT NULL"
    )
    existing_records = cur.fetchall()
    processed_debit_ids = {r[0] for r in existing_records if r[0]}
    processed_credit_ids = {r[1] for r in existing_records if r[1]}

    # Also check if credit was posted directly
    cur.execute(
        "SELECT txn_id FROM highnes_ledger WHERE entry_type IN ('reimbursement', 'transfer_repaid') AND txn_id IS NOT NULL"
    )
    processed_credit_ids.update({r[0] for r in cur.fetchall() if r[0]})

    now_iso = datetime.now(timezone.utc).isoformat()
    newly_reconciled = 0
    matched_count = 0
    unreimbursed_count = 0

    # Separate candidates
    loan_debits = []
    personal_debits = []
    highnes_credits = []

    for r in all_rows:
        loan = match_loan_debit(r)
        if loan and r["id"] not in processed_debit_ids:
            loan_debits.append((r, loan))
        elif is_highnes_debit(r) and r["id"] not in processed_debit_ids:
            personal_debits.append(r)
        elif is_highnes_credit(r) and r["id"] not in processed_credit_ids:
            highnes_credits.append(r)

    # Phase 1: Match each loan debit with a Highnes credit
    used_credit_ids = set()

    for debit_txn, loan in loan_debits:
        debit_amt = float(debit_txn["debit"])
        debit_date_str = debit_txn["txn_date"]
        matched_credit = None

        # Look for a matching credit within +/- 10 days and matching amount
        for credit_txn in highnes_credits:
            if credit_txn["id"] in used_credit_ids:
                continue
            credit_amt = float(credit_txn["credit"])

            # Check amount match
            if abs(credit_amt - debit_amt) <= loan["amount_tolerance"]:
                # Check date proximity
                try:
                    d_date = datetime.strptime(debit_date_str[:10], "%Y-%m-%d")
                    c_date = datetime.strptime(credit_txn["txn_date"][:10], "%Y-%m-%d")
                    day_diff = abs((c_date - d_date).days)
                except Exception:
                    day_diff = 0

                if day_diff <= 10:
                    matched_credit = credit_txn
                    used_credit_ids.add(credit_txn["id"])
                    break

        if matched_credit:
            # Highnes sent matching reimbursement!
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'loan_debit', ?, ?, ?, ?, 'matched', ?, ?)
                """,
                (
                    debit_txn["txn_date"],
                    loan["name"],
                    debit_amt,
                    debit_txn["id"],
                    matched_credit["id"],
                    f"Reimbursed by Highnes on {matched_credit['txn_date']} (Txn #{matched_credit['id']})",
                    now_iso,
                ),
            )
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'reimbursement', ?, ?, ?, ?, 'matched', ?, ?)
                """,
                (
                    matched_credit["txn_date"],
                    loan["name"],
                    -debit_amt,
                    matched_credit["id"],
                    debit_txn["id"],
                    f"Reimbursement for {loan['name']} EMI (Txn #{debit_txn['id']})",
                    now_iso,
                ),
            )
            matched_count += 1
        else:
            # Highnes did NOT reimburse! Add to outstanding balance.
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'loan_debit', ?, ?, ?, NULL, 'unreimbursed', ?, ?)
                """,
                (
                    debit_txn["txn_date"],
                    loan["name"],
                    debit_amt,
                    debit_txn["id"],
                    f"Unreimbursed {loan['name']} EMI — added to Highnes balance owed",
                    now_iso,
                ),
            )
            unreimbursed_count += 1

        newly_reconciled += 1

    # Phase 2: Match personal ad-hoc money requests sent to Highnes
    for debit_txn in personal_debits:
        debit_amt = float(debit_txn["debit"])
        debit_date_str = debit_txn["txn_date"]
        matched_credit = None

        # Look for matching credit from Highnes that repays this transfer
        for credit_txn in highnes_credits:
            if credit_txn["id"] in used_credit_ids:
                continue
            credit_amt = float(credit_txn["credit"])

            # Check exact amount match within 45 days
            if abs(credit_amt - debit_amt) <= 1.0:
                try:
                    d_date = datetime.strptime(debit_date_str[:10], "%Y-%m-%d")
                    c_date = datetime.strptime(credit_txn["txn_date"][:10], "%Y-%m-%d")
                    day_diff = abs((c_date - d_date).days)
                except Exception:
                    day_diff = 0

                if day_diff <= 45:
                    matched_credit = credit_txn
                    used_credit_ids.add(credit_txn["id"])
                    break

        if matched_credit:
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'money_lent', 'Personal Transfer', ?, ?, ?, 'matched', ?, ?)
                """,
                (
                    debit_txn["txn_date"],
                    debit_amt,
                    debit_txn["id"],
                    matched_credit["id"],
                    f"Money sent to Highnes — repaid on {matched_credit['txn_date']} (Txn #{matched_credit['id']})",
                    now_iso,
                ),
            )
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'transfer_repaid', 'Personal Transfer', ?, ?, ?, 'matched', ?, ?)
                """,
                (
                    matched_credit["txn_date"],
                    -debit_amt,
                    matched_credit["id"],
                    debit_txn["id"],
                    f"Repayment for money sent on {debit_txn['txn_date']} (Txn #{debit_txn['id']})",
                    now_iso,
                ),
            )
            matched_count += 1
        else:
            # Unreimbursed! Added to total balance owed.
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'money_lent', 'Personal Transfer', ?, ?, NULL, 'unreimbursed', ?, ?)
                """,
                (
                    debit_txn["txn_date"],
                    debit_amt,
                    debit_txn["id"],
                    "Unreimbursed money sent to Highnes — added to balance owed",
                    now_iso,
                ),
            )
            unreimbursed_count += 1

        newly_reconciled += 1

    # Phase 3: Any remaining unused Highnes credits count as general balance repayments
    for credit_txn in highnes_credits:
        if credit_txn["id"] in used_credit_ids:
            continue
        credit_amt = float(credit_txn["credit"])
        if credit_amt > 0:
            cur.execute(
                """
                INSERT INTO highnes_ledger (
                    entry_date, entry_type, loan_name, amount, txn_id,
                    matched_txn_id, reconciliation_status, notes, created_at
                )
                VALUES (?, 'transfer_repaid', 'Direct Repayment', ?, ?, NULL, 'matched', ?, ?)
                """,
                (
                    credit_txn["txn_date"],
                    -credit_amt,
                    credit_txn["id"],
                    f"Direct repayment from Highnes on {credit_txn['txn_date']} (Txn #{credit_txn['id']})",
                    now_iso,
                ),
            )
            used_credit_ids.add(credit_txn["id"])
            matched_count += 1
            newly_reconciled += 1

    conn.commit()

    return {
        "newly_reconciled": newly_reconciled,
        "matched": matched_count,
        "unreimbursed": unreimbursed_count,
    }


def get_highnes_ledger_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Calculate and return Highnes's current loan & transfer ledger status and breakdown."""
    init_highnes_ledger(conn)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, entry_date, entry_type, loan_name, amount, txn_id,
               matched_txn_id, reconciliation_status, notes, created_at
        FROM highnes_ledger
        ORDER BY entry_date ASC, id ASC
        """
    )
    raw_entries = [dict(r) for r in cur.fetchall()]

    running = 0.0
    entries = []
    unreimbursed_total = 0.0
    unreimbursed_loans_total = 0.0
    unreimbursed_transfers_total = 0.0
    unreimbursed_count = 0
    total_lent = 0.0
    total_repaid = 0.0

    for e in raw_entries:
        amt = float(e["amount"])
        running += amt
        e["running_balance"] = round(running, 2)

        if e["entry_type"] == "money_lent":
            total_lent += amt
            if e["reconciliation_status"] == "unreimbursed":
                unreimbursed_transfers_total += amt
                unreimbursed_total += amt
                unreimbursed_count += 1
        elif e["entry_type"] == "loan_debit":
            if e["reconciliation_status"] == "unreimbursed":
                unreimbursed_loans_total += amt
                unreimbursed_total += amt
                unreimbursed_count += 1
        elif e["entry_type"] in ("reimbursement", "transfer_repaid"):
            total_repaid += abs(amt)

        entries.append(e)

    # Check latest status for each of the 3 loans
    active_loans = []
    for loan in LOAN_DEFINITIONS:
        # Check last debit recorded in highnes_ledger or transactions
        cur.execute(
            """
            SELECT entry_date, amount, reconciliation_status, notes
            FROM highnes_ledger
            WHERE loan_name = ? AND entry_type = 'loan_debit'
            ORDER BY entry_date DESC
            LIMIT 1
            """,
            (loan["name"],),
        )
        last_entry = cur.fetchone()
        
        # If none in ledger, check most recent in transactions table
        last_txn_date = None
        last_status = "No statement debit yet"
        if last_entry:
            last_txn_date = last_entry[0]
            last_status = "Reimbursed" if last_entry[2] == "matched" else "Unpaid (Added to Balance)"
        else:
            # Fallback search for latest historical debit
            desc_match = "%" + loan["patterns"][0] + "%"
            cur.execute(
                """
                SELECT txn_date FROM transactions
                WHERE (lower(merchant_display) LIKE ? OR lower(description) LIKE ?) AND debit > 0
                ORDER BY txn_date DESC LIMIT 1
                """,
                (desc_match, desc_match),
            )
            hist = cur.fetchone()
            if hist:
                last_txn_date = hist[0]
                last_status = "Covered in baseline"

        active_loans.append({
            "id": loan["id"],
            "name": loan["name"],
            "monthly_emi": loan["expected_amount"],
            "schedule": loan["schedule"],
            "last_date": last_txn_date,
            "status": last_status,
        })

    upcoming = get_upcoming_loan_schedule(conn)

    return {
        "person_name": "Highnes",
        "opening_balance": OPENING_BALANCE,
        "opening_date": OPENING_DATE,
        "total_balance_owed": round(running, 2),
        "unreimbursed_total": round(unreimbursed_total, 2),
        "unreimbursed_loans_total": round(unreimbursed_loans_total, 2),
        "unreimbursed_transfers_total": round(unreimbursed_transfers_total, 2),
        "unreimbursed_count": unreimbursed_count,
        "total_lent": round(total_lent, 2),
        "total_repaid": round(total_repaid, 2),
        "active_loans": active_loans,
        "upcoming_schedule": upcoming,
        "next_due_loan": upcoming["next_loan"],
        "entries": list(reversed(entries)),  # Most recent first for display
    }


def highnes_reminders(summary: Dict[str, Any] | None) -> List[str]:
    """Short lines for the screen and the daily phone nudge."""
    if not summary:
        return []
    notes: List[str] = []
    schedule = summary.get("upcoming_schedule") or {}
    for loan in schedule.get("loans_schedule") or schedule.get("loans") or []:
        status = loan.get("status")
        name = loan.get("name") or "Loan"
        amount = float(loan.get("amount") or 0)
        rupees = f"₹{amount:,.0f}"
        if status == "overdue":
            notes.append(f"{name} {rupees} is not repaid")
        elif status == "due_today":
            notes.append(f"{name} {rupees} is due today")
        elif status == "due_soon":
            notes.append(f"{name} {rupees} is due {loan.get('due_date_short') or 'soon'}")
    if notes:
        return notes
    nxt = schedule.get("next_loan") or summary.get("next_due_loan")
    if nxt and int(nxt.get("days_away") or 99) <= 3:
        amount = float(nxt.get("amount") or 0)
        notes.append(
            f"{nxt.get('name') or 'Loan'} ₹{amount:,.0f} is due {nxt.get('due_date_short') or 'soon'}"
        )
    return notes


def maybe_notify_highnes_reminders(username: str = "anand") -> None:
    """One phone notification per day when a Highnes EMI is unpaid or due soon."""
    from pathlib import Path

    from .db import DATA_DIR, connect

    today = date.today().isoformat()
    stamp = Path(DATA_DIR) / ".highnes_reminder_day"
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == today:
        return
    db_path = Path(DATA_DIR) / "expenses_anand.db"
    if not db_path.is_file():
        return
    with connect(db_path) as conn:
        summary = get_highnes_ledger_summary(conn)
    notes = highnes_reminders(summary)
    if not notes:
        return
    try:
        from .notifications import send_push_notification_to_user

        sent = send_push_notification_to_user(
            username,
            "Highnes",
            notes[0] if len(notes) == 1 else f"{notes[0]}. {len(notes) - 1} more.",
            url="/#contacts",
            tag="highnes-reminder",
        )
    except Exception:
        logger.exception("Highnes reminder push failed")
        return
    if sent:
        stamp.write_text(today, encoding="utf-8")
        logger.info("Highnes reminder sent: %s", "; ".join(notes))


def get_upcoming_loan_schedule(
    conn: Optional[sqlite3.Connection] = None,
    ref_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Calculate upcoming loan EMI schedule, next due loan, and month status."""
    if ref_date is None:
        ref_date = date.today()

    cur_year = ref_date.year
    cur_month = ref_date.month

    reimbursed_loan_names = set()
    unreimbursed_loan_names = set()
    if conn:
        try:
            init_highnes_ledger(conn)
            cur = conn.cursor()
            month_str = f"{cur_year:04d}-{cur_month:02d}%"
            cur.execute(
                """
                SELECT loan_name, entry_type, reconciliation_status
                FROM highnes_ledger
                WHERE entry_date LIKE ? AND loan_name IS NOT NULL
                """,
                (month_str,),
            )
            for row in cur.fetchall():
                lname = row[0]
                status = row[2]
                if status == "matched":
                    reimbursed_loan_names.add(lname)
                elif status == "unreimbursed":
                    unreimbursed_loan_names.add(lname)
        except Exception as e:
            logger.warning("Failed to check month ledger status: %s", e)

    loan_items = []
    for loan in LOAN_DEFINITIONS:
        due_day = loan.get("due_day") or (1 if "branch" in loan["id"] else 7 if "clix" in loan["id"] else 17)
        try:
            due_date = date(cur_year, cur_month, due_day)
        except ValueError:
            due_date = date(cur_year, cur_month, 28)

        is_reimbursed = loan["name"] in reimbursed_loan_names
        is_unreimbursed_debit = loan["name"] in unreimbursed_loan_names

        days_away = (due_date - ref_date).days

        if is_reimbursed:
            status = "reimbursed"
            status_label = "Reimbursed ✓"
        elif is_unreimbursed_debit:
            status = "overdue"
            status_label = "Unpaid (+Debt) ⚠"
        elif days_away < 0:
            status = "pending_statement"
            status_label = f"Due was {due_date.strftime('%b %d')}"
        elif days_away == 0:
            status = "due_today"
            status_label = "Due Today!"
        elif days_away <= 3:
            status = "due_soon"
            status_label = f"Due in {days_away} day{'s' if days_away > 1 else ''}"
        else:
            status = "upcoming"
            status_label = f"Due {due_date.strftime('%b %d')}"

        loan_items.append({
            "id": loan["id"],
            "name": loan["name"],
            "amount": loan["expected_amount"],
            "due_day": due_day,
            "due_date": due_date.isoformat(),
            "due_date_formatted": due_date.strftime("%B %d, %Y"),
            "due_date_short": due_date.strftime("%b %d"),
            "days_away": days_away,
            "status": status,
            "status_label": status_label,
            "is_reimbursed": is_reimbursed,
        })

    # Sort loans by due_day
    loan_items.sort(key=lambda x: x["due_day"])

    # Find next due loan:
    # Priority: Next upcoming or due today in current month that is NOT yet reimbursed
    candidates = [l for l in loan_items if not l["is_reimbursed"] and l["days_away"] >= 0]
    candidates.sort(key=lambda x: x["days_away"])

    if candidates:
        next_loan = dict(candidates[0])
    else:
        # All loans in current month are past or reimbursed; next loan is next month's first loan (Branch on 1st)
        if cur_month == 12:
            next_year = cur_year + 1
            next_m = 1
        else:
            next_year = cur_year
            next_m = cur_month + 1

        branch_loan = next((l for l in LOAN_DEFINITIONS if "branch" in l["id"]), LOAN_DEFINITIONS[0])
        next_due_date = date(next_year, next_m, branch_loan.get("due_day", 1))
        days_away = (next_due_date - ref_date).days
        next_loan = {
            "id": branch_loan["id"],
            "name": branch_loan["name"],
            "amount": branch_loan["expected_amount"],
            "due_day": 1,
            "due_date": next_due_date.isoformat(),
            "due_date_formatted": next_due_date.strftime("%B %d, %Y"),
            "due_date_short": next_due_date.strftime("%b %d"),
            "days_away": days_away,
            "status": "upcoming",
            "status_label": f"Due {next_due_date.strftime('%b %d')}",
            "is_reimbursed": False,
        }

    da = next_loan["days_away"]
    if da == 0:
        next_loan["human_timeline"] = "Due today"
    elif da == 1:
        next_loan["human_timeline"] = "Due tomorrow"
    elif da > 1:
        next_loan["human_timeline"] = f"In {da} days"
    else:
        next_loan["human_timeline"] = f"Past due by {abs(da)} days"

    return {
        "next_loan": next_loan,
        "loans_schedule": loan_items,
        "current_month_name": ref_date.strftime("%B %Y"),
    }


def generate_whatsapp_reminder_url(
    loan: Dict[str, Any],
    total_owed: Optional[float] = None,
    phone_number: str = "918078866770",
    upi_id: str = "anand@sbi",
    passbook_url: str = "/ledger/highnes",
) -> str:
    """Build a direct WhatsApp click-to-chat URL with pre-filled reminder text."""
    name = loan.get("name") or "Loan EMI"
    amt = float(loan.get("amount") or 0)
    due_str = loan.get("due_date_formatted") or loan.get("due_date_short") or ""
    timeline = loan.get("human_timeline") or "soon"

    lines = [
        f"Hi Highnes, reminder for your loan EMI:",
        f"📌 *Loan:* {name}",
        f"💰 *Amount:* ₹{amt:,.2f}",
        f"📅 *Due Date:* {due_str} ({timeline})",
        "",
        "Please transfer this amount to my account so the bank auto-debit clears smoothly.",
    ]
    if upi_id:
        lines.append(f"📲 *UPI ID:* `{upi_id}`")
    if total_owed is not None:
        lines.append(f"📊 *Current Total Balance Owed:* ₹{total_owed:,.2f}")
    if passbook_url:
        lines.append(f"🔗 *Passbook:* {passbook_url}")
    lines.append("Thanks!")

    msg = "\n".join(lines)
    quoted = urllib.parse.quote(msg)
    clean_phone = "".join(c for c in phone_number if c.isdigit())
    return f"https://wa.me/{clean_phone}?text={quoted}"


def generate_highnes_calendar_ics() -> str:
    """Generate RFC 5545 standard .ics calendar for Highnes's recurring loan EMIs."""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//AI Expense Tracker//Highnes Loan Reminders//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:Highnes Loan EMI Reminders
X-WR-TIMEZONE:Asia/Kolkata
BEGIN:VEVENT
UID:highnes-loan-branch@expensetracker
DTSTAMP:{now_utc}
DTSTART;VALUE=DATE:20260901
RRULE:FREQ=MONTHLY;BYMONTHDAY=1
SUMMARY:Highnes Loan EMI: Branch International (₹2,981)
DESCRIPTION:Monthly loan EMI taken by Highnes in Anand's name.\\nAmount: ₹2,981.00\\nDue: 1st of each month.\\nReimburse Anand on time.
BEGIN:VALARM
TRIGGER:-P2D
ACTION:DISPLAY
DESCRIPTION:Reminder: Highnes Branch EMI ₹2,981 due in 2 days
END:VALARM
BEGIN:VALARM
TRIGGER;RELATED=START:-PT0H
ACTION:DISPLAY
DESCRIPTION:Highnes Branch EMI ₹2,981 due today!
END:VALARM
END:VEVENT
BEGIN:VEVENT
UID:highnes-loan-clix@expensetracker
DTSTAMP:{now_utc}
DTSTART;VALUE=DATE:20260907
RRULE:FREQ=MONTHLY;BYMONTHDAY=7
SUMMARY:Highnes Loan EMI: Clix Capital (₹5,695)
DESCRIPTION:Monthly loan EMI taken by Highnes in Anand's name.\\nAmount: ₹5,695.00\\nDue: 7th of each month.\\nReimburse Anand on time.
BEGIN:VALARM
TRIGGER:-P2D
ACTION:DISPLAY
DESCRIPTION:Reminder: Highnes Clix Capital EMI ₹5,695 due in 2 days
END:VALARM
BEGIN:VALARM
TRIGGER;RELATED=START:-PT0H
ACTION:DISPLAY
DESCRIPTION:Highnes Clix Capital EMI ₹5,695 due today!
END:VALARM
END:VEVENT
BEGIN:VEVENT
UID:highnes-loan-sbi@expensetracker
DTSTAMP:{now_utc}
DTSTART;VALUE=DATE:20260917
RRULE:FREQ=MONTHLY;BYMONTHDAY=17
SUMMARY:Highnes Loan EMI: SBI Loan EMI (₹4,820)
DESCRIPTION:Monthly loan EMI taken by Highnes in Anand's name.\\nAmount: ₹4,820.00\\nDue: 17th of each month.\\nReimburse Anand on time.
BEGIN:VALARM
TRIGGER:-P2D
ACTION:DISPLAY
DESCRIPTION:Reminder: Highnes SBI Loan EMI ₹4,820 due in 2 days
END:VALARM
BEGIN:VALARM
TRIGGER;RELATED=START:-PT0H
ACTION:DISPLAY
DESCRIPTION:Highnes SBI Loan EMI ₹4,820 due today!
END:VALARM
END:VEVENT
END:VCALENDAR"""

