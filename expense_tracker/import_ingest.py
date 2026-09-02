"""One import path: PDF bytes + saved statement password → SQLite transactions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pypdf.errors import PdfReadError

from .auth import get_statement_password, set_statement_password
from . import db as dbmod
from .db import apply_learned_rules_to_pending, connect, file_sha256, import_transactions
from .sbi_pdf import extract_transactions_from_bytes

logger = logging.getLogger(__name__)


def last_import_path(username: str) -> Path:
    return dbmod.DATA_DIR / f".last_import_{username}.json"


def read_last_import(username: str) -> dict[str, Any] | None:
    path = last_import_path((username or "").strip().lower())
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_last_import(payload: dict[str, Any]) -> None:
    user = str(payload.get("username") or "").strip().lower()
    if not user:
        return
    path = last_import_path(user)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_pdf_password(username: str, typed: str | None = None) -> str:
    typed = (typed or "").strip()
    if typed:
        return typed
    saved = get_statement_password(username)
    if saved:
        return saved
    raise ValueError(
        "No statement password saved yet. Import once from the app and enter the PDF password; "
        "it is stored in the tool and used automatically after that."
    )


def import_statement_bytes(
    username: str,
    content: bytes,
    filename: str,
    typed_password: str | None = None,
) -> dict[str, Any]:
    """Unlock PDF with the tool's saved password (or typed), then import rows.

    Returns dict with parsed, inserted, import reused flags.
    """
    username = (username or "").strip().lower()
    if not username:
        raise ValueError("username required")
    if not content:
        raise ValueError("Empty PDF")
    password = resolve_pdf_password(username, typed_password)
    temp_path: Path | None = None
    try:
        temp_path, rows = extract_transactions_from_bytes(
            content, filename or "statement.pdf", password=password
        )
        sha256 = file_sha256(temp_path)
        db_path = dbmod.DATA_DIR / f"expenses_{username}.db"
        with connect(db_path) as conn:
            import_id, inserted, parsed = import_transactions(
                conn,
                filename or "statement.pdf",
                sha256,
                rows,
                password_used=bool(password),
                uploaded_by=username,
            )
            apply_learned_rules_to_pending(conn)
            conn.commit()
            stats = _import_stats(conn, import_id)
        set_statement_password(username, password)
        already = inserted == 0 and parsed > 0
        payload = {
            "ok": True,
            "username": username,
            "filename": filename,
            "parsed": parsed,
            "inserted": inserted,
            "skipped": max(0, parsed - inserted),
            "import_id": import_id,
            "already_imported": already,
            "start": stats.get("start"),
            "end": stats.get("end"),
            "pending": stats.get("pending"),
            "auto": stats.get("auto"),
        }
        if inserted > 0:
            write_last_import(payload)
            try:
                from .cloud_sync import trigger_cloud_sync_bg

                trigger_cloud_sync_bg(username)
            except Exception:
                pass
        return payload
    except PdfReadError as exc:
        raise ValueError(
            "Could not open the PDF. Check the statement password saved in the tool."
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _import_stats(conn, import_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        select min(t.txn_date) as start, max(t.txn_date) as end,
               sum(case when c.status = 'needs_review' then 1 else 0 end) as pending,
               sum(case when c.status != 'needs_review' then 1 else 0 end) as auto
        from transactions t
        join classifications c on c.transaction_id = t.id
        where t.import_id = ?
        """,
        (import_id,),
    ).fetchone()
    if not row:
        return {}
    return {
        "start": row["start"],
        "end": row["end"],
        "pending": int(row["pending"] or 0),
        "auto": int(row["auto"] or 0),
    }
