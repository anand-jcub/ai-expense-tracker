"""Import statement PDFs from Gmail or data/inbox using the tool's saved password.

Usage (repo root):
  .\\venv\\Scripts\\python.exe -m expense_tracker.mail_import
  .\\venv\\Scripts\\python.exe -m expense_tracker.mail_import path\\to\\file.pdf

Password: already stored in the tool (first dashboard import). This script
only uploads the PDF — unlock happens automatically.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from expense_tracker.auth import get_gmail_imap, get_statement_password
from expense_tracker.db import DATA_DIR
from expense_tracker.import_ingest import import_statement_bytes


def _user() -> str:
    return (os.environ.get("EXPENSE_MCP_USER") or "anand").strip().lower()


def _inbox_dir() -> Path:
    d = DATA_DIR / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def import_pdf_file(username: str, path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return import_statement_bytes(username, content, path.name)


def collect_inbox_pdfs() -> list[Path]:
    inbox = _inbox_dir()
    return sorted(
        p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"
    )


def _pdf_parts_from_message(msg) -> list[tuple[str, bytes]]:
    import email

    out: list[tuple[str, bytes]] = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        filename = part.get_filename() or ""
        ctype = (part.get_content_type() or "").lower()
        if not filename.lower().endswith(".pdf") and ctype != "application/pdf":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        name = filename or "statement.pdf"
        out.append((name, payload))
    return out


def _is_whatsapp_deposit_statement(msg) -> bool:
    """Only WhatsApp / Deposit Account Statement PDFs — not monthly e-CAS."""
    subj = (msg.get("Subject") or "").lower()
    frm = (msg.get("From") or "").lower()
    if "e-account statement" in subj or "e-statement" in subj:
        return False
    if "cbssbi.cas" in frm or "cas@" in frm:
        return False
    if "whatsappbanking" in frm:
        return True
    if "deposit account statement" in subj:
        return True
    return False


def fetch_gmail_imap(username: str, limit: int = 12) -> list[dict[str, Any]]:
    """Pull statement PDFs from Gmail via IMAP (app password stored in the tool)."""
    import email
    import imaplib

    addr, app_pw = get_gmail_imap(username)
    if not addr or not app_pw:
        return []

    query = os.environ.get(
        "EXPENSE_GMAIL_QUERY",
        "filename:pdf (subject:statement OR subject:e-account OR from:sbi.bank.in)",
    )
    results: list[dict[str, Any]] = []
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    except Exception as exc:
        return [{"ok": False, "filename": None, "error": f"Gmail IMAP connect failed: {exc}"}]
    try:
        try:
            M.login(addr, app_pw)
        except imaplib.IMAP4.error as exc:
            return [{"ok": False, "filename": None, "error": f"Gmail login failed: {exc}"}]
        M.select("INBOX")
        # Standard IMAP only (X-GM-RAW often BAD from imaplib quoting)
        typ, data = M.search(None, "FROM", "whatsappbanking@alerts.sbi.bank.in")
        if typ != "OK" or not data or not data[0]:
            typ, data = M.search(None, "SUBJECT", "Deposit Account Statement")
        if typ != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()[-limit:]
        for mid in reversed(ids):
            typ, fetched = M.fetch(mid, "(RFC822)")
            if typ != "OK" or not fetched:
                continue
            raw = None
            for item in fetched:
                if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], (bytes, bytearray)):
                    raw = item[1]
                    break
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            if not _is_whatsapp_deposit_statement(msg):
                continue
            for filename, content in _pdf_parts_from_message(msg):
                if not filename.lower().startswith("depositaccountstatement"):
                    continue
                try:
                    result = import_statement_bytes(username, content, filename)
                    mid_s = mid.decode() if isinstance(mid, (bytes, bytearray)) else str(mid)
                    result["source"] = f"gmail-imap:{mid_s}"
                    results.append(result)
                except Exception as exc:
                    results.append({"ok": False, "filename": filename, "error": str(exc)})
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return results


def _try_gmail_pdfs(username: str) -> list[dict[str, Any]]:
    """IMAP (preferred) then optional gmail_token.json API."""
    via_imap = fetch_gmail_imap(username)
    if via_imap:
        return via_imap
    token_path = DATA_DIR / "gmail_token.json"
    if not token_path.is_file():
        return []
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return []

    creds = Credentials.from_authorized_user_file(str(token_path))
    service = build("gmail", "v1", credentials=creds)
    query = os.environ.get(
        "EXPENSE_GMAIL_QUERY",
        "filename:pdf (subject:statement OR subject:e-statement OR from:sbi.bank.in)",
    )
    resp = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
    results: list[dict[str, Any]] = []
    for msg in resp.get("messages") or []:
        full = service.users().messages().get(userId="me", id=msg["id"]).execute()
        payload = full.get("payload") or {}
        parts = list(payload.get("parts") or [])
        if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
            parts.append(payload)
        for part in parts:
            filename = (part.get("filename") or "").strip()
            if not filename.lower().endswith(".pdf"):
                continue
            att_id = (part.get("body") or {}).get("attachmentId")
            if not att_id:
                continue
            att = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=msg["id"], id=att_id)
                .execute()
            )
            import base64

            raw = att.get("data") or ""
            content = base64.urlsafe_b64decode(raw)
            try:
                result = import_statement_bytes(username, content, filename)
                result["source"] = f"gmail:{msg['id']}"
                results.append(result)
            except Exception as exc:
                results.append({"ok": False, "filename": filename, "error": str(exc)})
    return results


def run_auto_import(username: str | None = None) -> list[dict[str, Any]]:
    """Used by the background poller: inbox folder + Gmail."""
    username = (username or _user()).strip().lower()
    if not get_statement_password(username):
        return []
    reports: list[dict[str, Any]] = []
    for path in collect_inbox_pdfs():
        try:
            r = import_pdf_file(username, path)
            r["source"] = str(path)
            reports.append(r)
        except Exception as exc:
            reports.append({"ok": False, "filename": path.name, "error": str(exc)})
    reports.extend(_try_gmail_pdfs(username))
    return reports


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    username = _user()
    if not get_statement_password(username):
        print(
            f"No statement password saved for '{username}'.\n"
            "Open the app, import one PDF and enter the password once.\n"
            "It stays in the tool; mail imports then unlock automatically."
        )
        return 2

    jobs: list[Path] = []
    for arg in argv:
        p = Path(arg)
        if p.is_file():
            jobs.append(p)
    if not jobs:
        jobs = collect_inbox_pdfs()

    reports: list[dict[str, Any]] = []
    for path in jobs:
        try:
            r = import_pdf_file(username, path)
            r["source"] = str(path)
            reports.append(r)
            print(
                f"OK {path.name}: parsed={r['parsed']} inserted={r['inserted']}"
                + (" (already imported)" if r.get("already_imported") else "")
            )
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}")
            reports.append({"ok": False, "filename": path.name, "error": str(exc)})

    gmail_reports = _try_gmail_pdfs(username)
    if gmail_reports:
        for r in gmail_reports:
            reports.append(r)
            if r.get("ok"):
                print(
                    f"OK gmail {r.get('filename')}: parsed={r.get('parsed')} inserted={r.get('inserted')}"
                )
            else:
                print(f"FAIL gmail {r.get('filename')}: {r.get('error')}")

    if not reports:
        print(
            "No PDFs found.\n"
            f"  Drop files in {_inbox_dir()}\n"
            "  or pass a path:  import-mail.cmd C:\\path\\statement.pdf\n"
            "  or add data/gmail_token.json for Gmail fetch."
        )
        return 0

    print(json.dumps({"count": len(reports), "results": reports}, indent=2, default=str))
    return 0 if all(r.get("ok") is not False for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
