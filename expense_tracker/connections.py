from __future__ import annotations

import sqlite3
from decimal import Decimal
from datetime import date
from .classifier import STOP_TOKENS, merchant_tokens


def get_connection_suggestions(conn: sqlite3.Connection) -> list[dict]:
    """Find potential matches between unlinked debits and credits.

    Criteria:
    1. The debit transaction date is on or before the credit transaction date.
    2. They share at least one significant merchant name token (e.g. 'Ananthu').
    3. They have not yet been fully connected/offset.
    """
    # Fetch active link balances to calculate remaining balances
    links_rows = conn.execute("select debit_id, credit_id, amount from transaction_links").fetchall()
    debit_offsets: dict[int, Decimal] = {}
    credit_offsets: dict[int, Decimal] = {}
    for link in links_rows:
        d_id, c_id, amt = link["debit_id"], link["credit_id"], Decimal(str(link["amount"]))
        debit_offsets[d_id] = debit_offsets.get(d_id, Decimal("0")) + amt
        credit_offsets[c_id] = credit_offsets.get(c_id, Decimal("0")) + amt

    # Fetch debits with remaining balance
    debits = conn.execute(
        """
        select t.id, t.txn_date, t.merchant_display, t.description, t.debit,
               c.category, c.expense_type, c.split_ratio, c.my_share
        from transactions t
        join classifications c on c.transaction_id = t.id
        where t.debit > 0
        order by t.txn_date asc, t.id asc
        """
    ).fetchall()

    # Fetch credits with remaining balance
    credits = conn.execute(
        """
        select t.id, t.txn_date, t.merchant_display, t.description, t.credit
        from transactions t
        where t.credit > 0
        order by t.txn_date asc, t.id asc
        """
    ).fetchall()

    linkable_debits = []
    for d in debits:
        total = Decimal(str(d["debit"]))
        offset = debit_offsets.get(d["id"], Decimal("0"))
        remaining = total - offset
        if remaining > 0:
            linkable_debits.append((d, remaining))

    linkable_credits = []
    for c in credits:
        total = Decimal(str(c["credit"]))
        offset = credit_offsets.get(c["id"], Decimal("0"))
        remaining = total - offset
        if remaining > 0:
            linkable_credits.append((c, remaining))

    suggestions = []
    for d_row, d_rem in linkable_debits:
        d_tokens = merchant_tokens(d_row["merchant_display"])
        if not d_tokens:
            continue
        
        # Calculate my_share / outstanding share if it was shared
        my_share = Decimal(str(d_row["my_share"]))
        share_remaining = max(Decimal("0"), my_share - debit_offsets.get(d_row["id"], Decimal("0")))

        for c_row, c_rem in linkable_credits:
            # Credit must be on or after the debit
            if c_row["txn_date"] < d_row["txn_date"]:
                continue
            
            c_tokens = merchant_tokens(c_row["merchant_display"])
            if not c_tokens:
                continue

            # Check for shared name tokens
            shared_name = d_tokens & c_tokens
            if shared_name:
                # Calculate confidence score / matching strength
                # E.g. exact amount match is highly confident
                is_exact_rem = (c_rem == d_rem)
                is_share_rem = (c_rem == share_remaining)
                
                # We suggest the connection if the name overlaps and dates are valid
                suggested_amount = min(c_rem, d_rem)
                
                suggestions.append({
                    "debit_id": d_row["id"],
                    "debit_date": d_row["txn_date"],
                    "debit_merchant": d_row["merchant_display"],
                    "debit_desc": d_row["description"],
                    "debit_remaining": float(d_rem),
                    "credit_id": c_row["id"],
                    "credit_date": c_row["txn_date"],
                    "credit_merchant": c_row["merchant_display"],
                    "credit_desc": c_row["description"],
                    "credit_remaining": float(c_rem),
                    "suggested_amount": float(suggested_amount),
                    "reason": "Exact match" if is_exact_rem else ("Shared expense share match" if is_share_rem else "Name overlap match")
                })

    return suggestions
