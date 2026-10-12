"""Match pending review rows to bill/receipt emails and set category.

Only when a merchant token AND the rupee amount both appear in the mail.
Uses the same category seeds as statement classification. Does not touch khata.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from .auth import get_gmail_imap
from .classifier import STOP_TOKENS, effective_share, seed_match
from .db import DATA_DIR, connect, utc_now
from .mail_import import _close_imap, _connect_imap, _extract_rfc822, _uid_list

logger = logging.getLogger(__name__)

_SUBJECTS = ("bill", "invoice", "receipt", "payment", "order")


def _tokens(merchant: str, description: str) -> list[str]:
    raw = f"{merchant} {description}".lower()
    parts = re.split(r"[^a-z0-9]+", raw)
    out: list[str] = []
    for p in parts:
        if len(p) < 4 or p in STOP_TOKENS or p.isdigit():
            continue
        if p not in out:
            out.append(p)
        if len(out) >= 4:
            break
    return out


def _amount_in(text: str, debit: Decimal) -> bool:
    """Amount must look like money, not an order id or a stray digit."""
    n = int(debit)
    if n <= 0:
        return False
    return bool(
        re.search(
            rf"(?:₹|rs\.?|inr)\s*{n}(?:\.00)?(?!\d)|(?<!\d){n}\.00(?!\d)",
            text,
            re.I,
        )
    )


def _load_pending(username: str, limit: int = 40) -> list[dict[str, Any]]:
    path = DATA_DIR / f"expenses_{username}.db"
    if not path.is_file():
        return []
    with connect(path) as conn:
        rows = conn.execute(
            """
            select t.id, t.txn_date, t.merchant_display, t.description,
                   t.debit, t.amount_signed, t.merchant_key
            from transactions t
            join classifications c on c.transaction_id = t.id
            where c.status = 'needs_review' and cast(t.debit as float) > 0
            order by t.txn_date desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _apply(username: str, txn_id: int, category: str, expense_type: str, note: str, amount_signed) -> None:
    path = DATA_DIR / f"expenses_{username}.db"
    now = utc_now()
    share = effective_share(Decimal(str(amount_signed or 0)), expense_type, Decimal("1"))
    with connect(path) as conn:
        conn.execute(
            """
            update classifications
            set category = ?, expense_type = ?, split_ratio = '1', my_share = ?,
                status = 'auto', confidence = 0.8, notes = ?, updated_at = ?
            where transaction_id = ? and status = 'needs_review'
            """,
            (category, expense_type, str(share), note[:240], now, txn_id),
        )
        conn.commit()


def _fetch_text(fetched) -> str:
    chunks: list[bytes] = []
    for item in fetched or []:
        if isinstance(item, tuple):
            for piece in item:
                if isinstance(piece, (bytes, bytearray)) and len(piece) > 20:
                    chunks.append(bytes(piece))
        elif isinstance(item, (bytes, bytearray)) and len(item) > 20:
            chunks.append(bytes(item))
    return b"\n".join(chunks).decode("utf-8", errors="ignore")


def _collect_mails(client, cap: int = 25) -> list[dict[str, str]]:
    uids: list[str] = []
    for subj in _SUBJECTS:
        try:
            typ, data = client.uid("SEARCH", "SUBJECT", subj)
        except Exception:
            continue
        if typ == "OK":
            for uid in _uid_list(data)[-8:]:
                if uid not in uids:
                    uids.append(uid)
    uids = uids[-cap:]
    mails: list[dict[str, str]] = []
    for uid in reversed(uids):
        try:
            typ, fetched = client.uid(
                "FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)] BODY.PEEK[TEXT]<0.4000>)"
            )
        except Exception:
            break
        if typ != "OK":
            continue
        text = _fetch_text(fetched)
        if not text.strip():
            continue
        subj = ""
        m = re.search(r"(?im)^subject:\s*(.+)$", text)
        if m:
            subj = m.group(1).strip()
        mails.append({"subject": subj, "text": text.lower()})
    return mails


def categorize_pending_from_mail(username: str) -> list[dict[str, Any]]:
    """Return applied matches. Safe to call when Gmail is briefly down."""
    addr, app_pw = get_gmail_imap(username)
    if not addr or not app_pw:
        return []
    pending = _load_pending(username)
    if not pending:
        return []
    try:
        client = _connect_imap(addr, app_pw)
    except Exception as exc:
        logger.warning("Bill mail check skipped: %s", exc)
        return [{"ok": False, "error": str(exc)}]
    applied: list[dict[str, Any]] = []
    try:
        mails = _collect_mails(client)
    finally:
        _close_imap(client)
    if not mails:
        return []
    for txn in pending:
        tokens = [t for t in _tokens(txn.get("merchant_display") or "", txn.get("description") or "") if len(t) >= 5]
        if not tokens:
            continue
        debit = Decimal(str(txn.get("debit") or 0))
        hit = None
        seeded = None
        for mail in mails:
            text = mail["text"]
            if not any(tok in text for tok in tokens):
                continue
            if not _amount_in(text, debit):
                continue
            seeded = seed_match(f"{txn.get('merchant_key') or ''} {mail['subject']} {text[:400]}")
            if seeded:
                hit = mail
                break
        if not hit or not seeded:
            continue
        category, expense_type = seeded
        if expense_type == "Shared":
            expense_type = "Personal"
        note = f"From email: {hit['subject'][:120]}"
        _apply(username, int(txn["id"]), category, expense_type, note, txn.get("amount_signed"))
        applied.append(
            {
                "ok": True,
                "id": txn["id"],
                "merchant": txn.get("merchant_display"),
                "category": category,
                "amount": float(debit),
            }
        )
        logger.info(
            "Email category %s -> %s (%s)",
            txn.get("merchant_display"),
            category,
            debit,
        )
    return applied
