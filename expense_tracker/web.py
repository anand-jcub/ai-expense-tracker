"""HTTP server: routing, request handling, and static file serving."""

from __future__ import annotations

import json
import logging
import socket
import urllib.parse
from datetime import date
from decimal import Decimal, InvalidOperation
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pypdf.errors import PdfReadError

from .auth import (
    authenticate_user,
    delete_session,
    get_all_usernames,
    init_auth_db,
    register_user,
    verify_session,
)
from .db import (
    APP_ROOT,
    DATA_DIR,
    add_manual_transaction,
    add_transaction_link,
    connect,
    dashboard_data,
    delete_merchant_rule,
    file_sha256,
    import_transactions,
    init_db,
    remove_transaction_link,
    review_transaction,
    write_csv,
    write_json,
)
from .services import (
    CATEGORIES,
    EXPENSE_TYPES,
    compute_partner_balances,
    split_ratio_from_people,
)
from .sbi_pdf import extract_transactions_from_bytes
from .templates import login_page, page, register_page

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = APP_ROOT / "outputs"


class DualStackServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that listens on both IPv4 and IPv6 when possible."""

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


class ExpenseHandler(BaseHTTPRequestHandler):

    # ── helpers ──────────────────────────────────────────────────────────────

    def get_session_username(self) -> str | None:
        """Return the username associated with the current session cookie, or None."""
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session="):
                session_id = part[len("session="):]
                return verify_session(session_id)
        return None

    def get_session_id(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
        return None

    def _db_path_for(self, username: str) -> Path:
        return DATA_DIR / f"expenses_{username.lower()}.db"

    def respond_html(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def redirect(self, message: str | None = None, error: str | None = None, path: str = "/", tab: str | None = None) -> None:
        query = urllib.parse.urlencode({k: v for k, v in {"message": message, "error": error}.items() if v})
        hash_suffix = f"#{tab}" if tab else ""
        target = f"{path}?{query}{hash_suffix}" if query else f"{path}{hash_suffix}"
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()
        self.wfile.flush()

    def respond_json(self, payload: Any, status: int = 200) -> None:
        import json as json_mod
        body = json_mod.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def serve_static(self, filename: str, content_type: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def multipart(self):
        length = int(self.headers.get("Content-Length", "0"))
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        return parse_multipart(body, content_type)

    def log_message(self, format: str, *args) -> None:
        logger.debug("%s %s", self.command, self.path)

    # ── GET routing ──────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            # Static assets — no auth needed
            if parsed.path == "/style.css":
                self.serve_static("style.css", "text/css; charset=utf-8")
                return
            elif parsed.path == "/app.js":
                self.serve_static("app.js", "application/javascript; charset=utf-8")
                return
            elif parsed.path == "/chart.js":
                self.serve_static("chart.js", "application/javascript; charset=utf-8")
                return

            # Auth pages
            if parsed.path == "/login":
                self.respond_html(login_page())
                return
            if parsed.path == "/register":
                self.respond_html(register_page())
                return

            # Session check for all other pages
            username = self.get_session_username()
            if not username:
                self.redirect(path="/login")
                return

            if parsed.path == "/api/contacts/ledger":
                self.handle_api_contact_ledger(username, params)
                return
            if parsed.path == "/api/settlement":
                self.handle_api_settlement(username, params)
                return
            if parsed.path == "/api/settlement/by-name":
                self.handle_api_settlement_by_name(username, params)
                return
            if parsed.path == "/api/settlement/summary":
                self.handle_api_settlement_summary(username)
                return

            if parsed.path == "/":
                db_path = self._db_path_for(username)
                all_users = get_all_usernames()
                with connect(db_path) as conn:
                    data = dashboard_data(conn)
                    from .settlement import settlement_usb_enabled, summary_all_contacts, settlement_to_json

                    if settlement_usb_enabled():
                        usb_list = summary_all_contacts(conn)
                        partner_balances = [
                            {
                                "username": b.contact_name,
                                "contact_id": b.contact_id,
                                "they_owe_you": b.they_owe_you,
                                "you_owe_them": b.you_owe_them,
                                "net": b.net,
                            }
                            for b in usb_list
                            if b.net != 0
                        ]
                    else:
                        partner_balances = compute_partner_balances(conn, username, all_users)
                self.respond_html(
                    page(
                        data,
                        params.get("message", [None])[0],
                        params.get("error", [None])[0],
                        params.get("review_sort", ["newest"])[0],
                        params.get("review_search", [""])[0],
                        params.get("edit_search", [""])[0],
                        params.get("person_search", [""])[0],
                        params.get("start_date", [""])[0],
                        params.get("end_date", [""])[0],
                        "exclude_business" in params,
                        current_user=username,
                        all_users=all_users,
                        partner_balances=partner_balances,
                        tx_filter=params.get("tx_filter", ["needs_review"])[0],
                    )
                )
            elif parsed.path == "/export.csv":
                self.export_file("csv", username)
            elif parsed.path == "/export.json":
                self.export_file("json", username)
            elif parsed.path == "/logout":
                self.handle_logout_get()
            else:
                self.send_error(404)
        except Exception:
            logger.exception("Unexpected error in do_GET")
            self.send_error(500)

    # ── POST routing ─────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        try:
            # Auth POST endpoints — no session needed
            if self.path == "/login":
                self.handle_login()
                return
            if self.path == "/register":
                self.handle_register()
                return
            if self.path == "/logout":
                self.handle_logout()
                return

            # All other POST endpoints require a session
            username = self.get_session_username()
            if not username:
                self.redirect(path="/login")
                return

            if self.path == "/import":
                self.handle_import(username)
            elif self.path == "/manual":
                self.handle_manual(username)
            elif self.path == "/review":
                self.handle_review(username)
            elif self.path == "/edit-classifications":
                self.handle_edit_classifications(username)
            elif self.path == "/connect":
                self.handle_connect(username)
            elif self.path == "/disconnect":
                self.handle_disconnect(username)
            elif self.path == "/delete-rule":
                self.handle_delete_rule(username)
            elif self.path == "/contacts/create":
                self.handle_contact_create(username)
            elif self.path == "/ledger/add":
                self.handle_ledger_add(username)
            elif self.path == "/ledger/passthrough/confirm":
                self.handle_passthrough_confirm(username)
            elif self.path == "/ledger/settle":
                self.handle_ledger_settle(username)
            elif self.path == "/ledger/materialize-shared":
                self.handle_materialize_shared(username)
            elif self.path == "/contacts/merge":
                self.handle_contacts_merge(username)
            else:
                self.send_error(404)
        except Exception:
            logger.exception("Unexpected error in do_POST")
            self.send_error(500)

    # ── Auth handlers ─────────────────────────────────────────────────────────

    def handle_login(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        username = params.get("username", [""])[0].strip().lower()
        password = params.get("password", [""])[0]
        session_id = authenticate_user(username, password)
        if session_id:
            # Ensure the user's DB exists and is migrated (connect() runs init_db)
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                pass
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"session={session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000",
            )
            self.end_headers()
            self.wfile.flush()
        else:
            self.respond_html(login_page(error="Invalid username or password."))

    def handle_register(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        username = params.get("username", [""])[0].strip()
        password = params.get("password", [""])[0]
        confirm = params.get("confirm_password", [""])[0]
        if password != confirm:
            self.respond_html(register_page(error="Passwords do not match."))
            return
        success, message = register_user(username, password)
        if success:
            # Create the user's DB immediately
            db_path = self._db_path_for(username.lower())
            with connect(db_path) as conn:
                pass
            self.respond_html(login_page(message="Account created! Please log in."))
        else:
            self.respond_html(register_page(error=message))

    def handle_logout(self) -> None:
        session_id = self.get_session_id()
        delete_session(session_id)
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", "session=; Path=/; HttpOnly; Max-Age=0")
        self.end_headers()
        self.wfile.flush()

    def handle_logout_get(self) -> None:
        self.handle_logout()

    # ── Data handlers ─────────────────────────────────────────────────────────

    def handle_import(self, username: str) -> None:
        try:
            parts = self.multipart()
            statement = parts.get("statement")
            if statement is None:
                self.redirect(error="No PDF uploaded.")
                return
            password_part = parts.get("password")
            password = password_part.get_content().strip() if password_part else ""
            filename = statement.get_filename() or "statement.pdf"
            content = statement.get_payload(decode=True)
            temp_path, rows = extract_transactions_from_bytes(content, filename, password=password)
            try:
                sha256 = file_sha256(temp_path)
                db_path = self._db_path_for(username)
                with connect(db_path) as conn:
                    _, inserted, parsed = import_transactions(
                        conn,
                        filename,
                        sha256,
                        rows,
                        password_used=bool(password),
                        uploaded_by=username,
                    )
                self.redirect(message=f"Parsed {parsed} transactions and imported {inserted} new transactions.")
            finally:
                temp_path.unlink(missing_ok=True)
        except PdfReadError:
            self.redirect(error="Could not open the PDF. Check the SBI statement password.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during import.")
            self.redirect(error=str(exc))

    def handle_manual(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            txn_date = params.get("txn_date", [""])[0].strip()
            date.fromisoformat(txn_date)
            description = params.get("description", [""])[0].strip()
            if not description:
                raise ValueError("Enter a description.")
            try:
                amount = Decimal(params.get("amount", ["0"])[0])
            except InvalidOperation:
                raise ValueError("Enter a valid amount.") from None
            direction = params.get("direction", ["debit"])[0].strip()
            category = params.get("category", [""])[0].strip()
            expense_type = params.get("expense_type", ["Personal"])[0].strip()
            if not category or expense_type not in EXPENSE_TYPES:
                raise ValueError("Choose a category and expense type.")
            split_ratio = split_ratio_from_people(params.get("split_people", ["1"])[0])
            notes = params.get("notes", [""])[0].strip() or None
            learn = "learn" in params
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                add_manual_transaction(
                    conn,
                    txn_date,
                    description,
                    amount,
                    direction,
                    category,
                    expense_type,
                    split_ratio,
                    notes,
                    learn,
                    uploaded_by=username,
                )
            self.redirect(message="Manual transaction added. Dashboard updated.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error adding manual transaction.")
            self.redirect(error=str(exc))

    def handle_review(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            if "transaction_id" not in params:
                self.handle_review_batch(params, username)
                return

            transaction_id = int(params["transaction_id"][0])
            category = params["category"][0].strip()
            expense_type = params["expense_type"][0].strip()
            if expense_type not in EXPENSE_TYPES:
                raise ValueError("Choose a valid expense type.")
            # Force Shared if shared_with partner selected
            shared_with = params.get("shared_with", [""])[0].strip() or None
            if shared_with:
                expense_type = "Shared"
            if "split_people" in params:
                split_ratio = split_ratio_from_people(params["split_people"][0])
            else:
                split_ratio = Decimal(params.get("split_ratio", ["0.5"])[0] or "0.5")
            notes = params.get("notes", [""])[0].strip() or None
            learn = "learn" in params
            if not category:
                raise ValueError("Choose a category and expense type.")
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                review_transaction(
                    conn, transaction_id, category, expense_type, split_ratio, notes, learn,
                    shared_with=shared_with,
                )
                if shared_with and self._is_registered_username(shared_with):
                    self.sync_shared_transaction(conn, transaction_id, username, shared_with)
            self.redirect(message="Transaction confirmed and merchant knowledge base updated.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during review.")
            self.redirect(error=str(exc))

    def _is_registered_username(self, name: str) -> bool:
        try:
            return name.strip().lower() in {u.lower() for u in get_all_usernames()}
        except Exception:
            return False

    def handle_review_batch(self, params: dict[str, list[str]], username: str) -> None:
        confirmed = 0
        skipped = 0
        db_path = self._db_path_for(username)
        with connect(db_path) as conn:
            for raw_id in params.get("review_ids", []):
                transaction_id = int(raw_id)
                category = params.get(f"category_{transaction_id}", [""])[0].strip()
                if not category:
                    skipped += 1
                    continue
                expense_type = params.get(f"expense_type_{transaction_id}", ["Personal"])[0].strip()
                if expense_type not in EXPENSE_TYPES:
                    raise ValueError("Choose a valid expense type.")
                shared_with = params.get(f"shared_with_{transaction_id}", [""])[0].strip() or None
                if shared_with:
                    expense_type = "Shared"
                split_ratio = split_ratio_from_people(
                    params.get(f"split_people_{transaction_id}", ["1"])[0]
                )
                notes = params.get(f"notes_{transaction_id}", [""])[0].strip() or None
                learn = f"learn_{transaction_id}" in params
                review_transaction(
                    conn, transaction_id, category, expense_type, split_ratio, notes, learn,
                    shared_with=shared_with,
                )
                if shared_with and self._is_registered_username(shared_with):
                    self.sync_shared_transaction(conn, transaction_id, username, shared_with)
                confirmed += 1

        if confirmed:
            self.redirect(message=f"Confirmed {confirmed} review change(s). Dashboard updated.")
        elif skipped:
            self.redirect(error="No changes saved. Choose a category for at least one review row.")
        else:
            self.redirect(message="Nothing waiting for review.")

    def handle_edit_classifications(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            updated = 0
            skipped = 0
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                for raw_id in params.get("edit_ids", []):
                    transaction_id = int(raw_id)
                    category = params.get(f"edit_category_{transaction_id}", [""])[0].strip()
                    if not category:
                        skipped += 1
                        continue
                    expense_type = params.get(f"edit_expense_type_{transaction_id}", ["Personal"])[0].strip()
                    if expense_type not in EXPENSE_TYPES:
                        raise ValueError("Choose a valid expense type.")
                    shared_with = params.get(f"edit_shared_with_{transaction_id}", [""])[0].strip() or None
                    if shared_with:
                        expense_type = "Shared"
                    split_ratio = split_ratio_from_people(
                        params.get(f"edit_split_people_{transaction_id}", ["1"])[0]
                    )
                    notes = params.get(f"edit_notes_{transaction_id}", [""])[0].strip() or None
                    learn = f"edit_learn_{transaction_id}" in params
                    review_transaction(
                        conn, transaction_id, category, expense_type, split_ratio, notes, learn,
                        shared_with=shared_with,
                    )
                    if shared_with and self._is_registered_username(shared_with):
                        self.sync_shared_transaction(conn, transaction_id, username, shared_with)
                    updated += 1

            if updated:
                self.redirect(message=f"Saved {updated} classification edit(s). Dashboard updated.")
            elif skipped:
                self.redirect(error="No edits saved. Choose a category for at least one classified row.")
            else:
                self.redirect(message="No classified rows selected.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error editing classifications.")
            self.redirect(error=str(exc))

    def sync_shared_transaction(self, conn, transaction_id: int, owner: str, shared_with: str) -> None:
        """Replicate a shared transaction to the partner's database."""
        try:
            row = conn.execute(
                "SELECT t.*, c.category, c.expense_type, c.split_ratio, c.my_share, c.notes "
                "FROM transactions t JOIN classifications c ON c.transaction_id = t.id "
                "WHERE t.id = ?",
                (transaction_id,),
            ).fetchone()
            if not row:
                return
            partner_db = self._db_path_for(shared_with)
            with connect(partner_db) as pconn:
                # Check if already replicated
                existing = pconn.execute(
                    "SELECT id FROM transactions WHERE source_txn_id = ? AND uploaded_by = ?",
                    (transaction_id, owner),
                ).fetchone()
                if existing:
                    return
                # Insert the replicated transaction
                pconn.execute(
                    """INSERT OR IGNORE INTO transactions
                       (txn_date, value_date, description, debit, credit, balance,
                        reference, raw_text, merchant_display, amount_signed,
                        uploaded_by, source_txn_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row["txn_date"], row["value_date"], row["description"],
                        row["debit"], row["credit"], row["balance"],
                        row["reference"], row["raw_text"], row["merchant_display"],
                        row["amount_signed"], owner, transaction_id,
                    ),
                )
                new_id = pconn.execute("SELECT last_insert_rowid()").fetchone()[0]
                if new_id:
                    pconn.execute(
                        """INSERT OR IGNORE INTO classifications
                           (transaction_id, category, expense_type, split_ratio, my_share,
                            status, confidence, notes, shared_with)
                           VALUES (?,?,?,?,?,'confirmed',1.0,?,?)""",
                        (
                            new_id, row["category"], row["expense_type"],
                            row["split_ratio"], row["my_share"],
                            row["notes"], owner,
                        ),
                    )
                pconn.commit()
        except Exception:
            logger.exception("Error syncing shared transaction to partner %s", shared_with)

    def export_file(self, kind: str, username: str) -> None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        path = OUTPUT_DIR / f"transactions.{kind}"
        db_path = self._db_path_for(username)
        with connect(db_path) as conn:
            if kind == "csv":
                write_csv(conn, path)
                body = path.read_bytes()
                content_type = "text/csv; charset=utf-8"
            else:
                write_json(conn, path)
                body = path.read_bytes()
                content_type = "application/json; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_connect(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            debit_id = int(params.get("debit_id", ["0"])[0])
            credit_id = int(params.get("credit_id", ["0"])[0])
            try:
                amount = Decimal(params.get("amount", ["0"])[0])
            except InvalidOperation:
                raise ValueError("Enter a valid amount.")
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                add_transaction_link(conn, debit_id, credit_id, amount)
            self.redirect(message="Transactions connected successfully.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error connecting transactions.")
            self.redirect(error=str(exc))

    def handle_disconnect(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            link_id = int(params.get("link_id", ["0"])[0])
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                remove_transaction_link(conn, link_id)
            self.redirect(message="Connection removed successfully.")
        except Exception as exc:
            logger.exception("Unexpected error disconnecting transactions.")
            self.redirect(error=str(exc))

    def handle_delete_rule(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            rule_id = int(params.get("rule_id", ["0"])[0])
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                delete_merchant_rule(conn, rule_id)
            self.redirect(message="Merchant rule deleted successfully.")
        except Exception as exc:
            logger.exception("Unexpected error deleting rule.")
            self.redirect(error=str(exc))

    def handle_api_contact_ledger(self, username: str, params: dict) -> None:
        contact_id_str = params.get("contact_id", [""])[0]
        if not contact_id_str.isdigit():
            self.respond_json({"error": "Invalid contact_id"}, status=400)
            return
        contact_id = int(contact_id_str)
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .contacts import get_contact_ledger
                from .settlement import (
                    compute_unified_settlement,
                    settlement_to_json,
                    settlement_usb_enabled,
                )

                payload = get_contact_ledger(conn, contact_id)
                balance = payload.get("balance")
                virtual_lines = []
                if settlement_usb_enabled():
                    usb = compute_unified_settlement(conn, contact_id)
                    balance = settlement_to_json(usb)
                    virtual_lines = [
                        {
                            k: (float(v) if hasattr(v, "as_tuple") else v)
                            for k, v in line.__dict__.items()
                        }
                        for line in usb.lines
                        if line.kind == "virtual_shared"
                    ]
            self.respond_json(
                {
                    "contact": payload.get("contact"),
                    "balance": balance,
                    "entries": payload.get("entries") or [],
                    "virtual_shared_lines": virtual_lines,
                }
            )
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=404)
        except Exception:
            logger.exception("Failed to load contact ledger for id=%s", contact_id)
            self.respond_json({"error": "Failed to load ledger"}, status=500)

    def handle_api_settlement(self, username: str, params: dict) -> None:
        contact_id_str = params.get("contact_id", [""])[0]
        if not contact_id_str.isdigit():
            self.respond_json({"error": "Invalid contact_id"}, status=400)
            return
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import compute_unified_settlement, settlement_to_json

                bal = compute_unified_settlement(conn, int(contact_id_str))
            self.respond_json(settlement_to_json(bal))
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=404)
        except Exception:
            logger.exception("settlement API failed")
            self.respond_json({"error": "Failed to compute settlement"}, status=500)

    def handle_api_settlement_by_name(self, username: str, params: dict) -> None:
        q = params.get("q", [""])[0].strip()
        if not q:
            self.respond_json({"error": "Missing q"}, status=400)
            return
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import (
                    compute_unified_settlement,
                    format_settlement_answer,
                    resolve_contact,
                    settlement_to_json,
                )

                match = resolve_contact(conn, q)
                if not match:
                    self.respond_json({"error": f"No contact matching '{q}'"}, status=404)
                    return
                bal = compute_unified_settlement(conn, int(match["canonical_id"]))
                payload = settlement_to_json(bal)
                payload["answer"] = format_settlement_answer(bal)
                payload["match_score"] = match.get("score")
            self.respond_json(payload)
        except Exception:
            logger.exception("settlement by-name failed")
            self.respond_json({"error": "Failed to resolve settlement"}, status=500)

    def handle_api_settlement_summary(self, username: str) -> None:
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import settlement_to_json, summary_all_contacts

                items = [
                    settlement_to_json(b)
                    for b in summary_all_contacts(conn)
                    if b.net != 0
                ]
            self.respond_json({"contacts": items})
        except Exception:
            logger.exception("settlement summary failed")
            self.respond_json({"error": "Failed to load summary"}, status=500)

    def handle_contact_create(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        name = params.get("name", [""])[0]
        aliases = params.get("aliases", [""])[0]
        notes = params.get("notes", [None])[0]
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .contacts import create_contact
                create_contact(conn, name, aliases, notes)
            self.redirect(message=f"Contact '{name}' created.", tab="contacts")
        except Exception as exc:
            self.redirect(error=str(exc), tab="contacts")

    def handle_ledger_add(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        contact_id = int(params.get("contact_id", [0])[0])
        direction = params.get("direction", ["you_sent"])[0]
        amount = Decimal(params.get("amount", ["0"])[0])
        purpose = params.get("purpose", ["other"])[0]
        notes = params.get("notes", [None])[0]
        entry_date = params.get("entry_date", [""])[0] or datetime.now().strftime("%Y-%m-%d")
        is_opening_balance = "is_opening_balance" in params
        txn_raw = params.get("transaction_id", [""])[0].strip()
        transaction_id = int(txn_raw) if txn_raw.isdigit() else None
        # Loan suggestions return to review; manual entry returns to contacts
        return_tab = "review" if transaction_id else "contacts"
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .contacts import add_ledger_entry
                add_ledger_entry(
                    conn,
                    contact_id=contact_id,
                    transaction_id=transaction_id,
                    direction=direction,
                    amount=amount,
                    purpose=purpose,
                    notes=notes,
                    entry_date=entry_date,
                    is_opening_balance=is_opening_balance,
                    created_by="user",
                )
            msg = (
                "Loan posted to khata (bank row unchanged)."
                if purpose == "loan" and transaction_id
                else "Ledger entry added successfully."
            )
            self.redirect(message=msg, tab=return_tab)
        except Exception as exc:
            self.redirect(error=str(exc), tab=return_tab)

    def handle_passthrough_confirm(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        action = params.get("action", ["confirm"])[0]
        credit_id = int(params.get("credit_id", [0])[0])
        debit_id = int(params.get("debit_id", [0])[0])
        from_raw = params.get("from_contact_id", ["0"])[0]
        to_raw = params.get("to_contact_id", ["0"])[0]
        from_contact_id = int(from_raw) if str(from_raw).isdigit() and int(from_raw) else 0
        to_contact_id = int(to_raw) if str(to_raw).isdigit() and int(to_raw) else 0
        amount = Decimal(params.get("amount", ["0"])[0])
        entry_date = params.get("entry_date", [""])[0]
        db_path = self._db_path_for(username)
        if action == "confirm":
            with connect(db_path) as conn:
                from .contacts import add_ledger_entry, create_contact
                from .settlement import upgrade_passthrough_siblings

                # Prefer linking existing contacts; only create if still missing
                if not from_contact_id:
                    self.redirect(
                        error="Link sender contact before confirming pass-through.",
                        tab="contacts",
                    )
                    return
                if not to_contact_id:
                    self.redirect(
                        error="Link recipient contact before confirming pass-through.",
                        tab="contacts",
                    )
                    return

                # Upgrade existing non-PT siblings when possible; else insert PT rows
                up_from = upgrade_passthrough_siblings(
                    conn, from_contact_id, credit_id, "they_sent", amount
                )
                up_to = upgrade_passthrough_siblings(
                    conn, to_contact_id, debit_id, "you_sent", amount
                )
                e1 = None
                if up_from == "none":
                    e1 = add_ledger_entry(
                        conn,
                        contact_id=from_contact_id,
                        transaction_id=credit_id,
                        direction="they_sent",
                        amount=amount,
                        purpose="rolling",
                        is_passthrough=True,
                        entry_date=entry_date,
                        created_by="user",
                    )
                if up_to == "none":
                    add_ledger_entry(
                        conn,
                        contact_id=to_contact_id,
                        transaction_id=debit_id,
                        direction="you_sent",
                        amount=amount,
                        purpose="rolling",
                        is_passthrough=True,
                        passthrough_pair_id=e1,
                        entry_date=entry_date,
                        created_by="user",
                    )
                from .settlement import dedupe_ledger_conflicts

                dedupe_ledger_conflicts(conn, from_contact_id, auto_apply=True)
                dedupe_ledger_conflicts(conn, to_contact_id, auto_apply=True)
            self.redirect(message="Pass-through transaction confirmed.", tab="contacts")
        else:
            self.redirect(message="Pass-through suggestion dismissed.", tab="contacts")

    def handle_ledger_settle(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        contact_id = int(params.get("contact_id", [0])[0])
        amount_raw = params.get("amount", [""])[0].strip()
        amount = Decimal(amount_raw) if amount_raw else None
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import record_settlement

                bal = record_settlement(
                    conn,
                    contact_id=contact_id,
                    amount=amount,
                    created_by="user",
                )
            if bal.net == 0 and amount is None:
                self.redirect(message="Balance marked as settled.", tab="contacts")
            else:
                self.redirect(
                    message=f"Settlement recorded. Net now ₹{float(bal.net):,.2f}.",
                    tab="contacts",
                )
        except ValueError as exc:
            self.redirect(error=str(exc), tab="contacts")
        except Exception as exc:
            logger.exception("settle failed")
            self.redirect(error=str(exc), tab="contacts")

    def handle_materialize_shared(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        contact_id = int(params.get("contact_id", [0])[0])
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import materialize_virtual_shares

                n = materialize_virtual_shares(conn, contact_id)
            self.redirect(message=f"Materialized {n} shared share(s).", tab="contacts")
        except Exception as exc:
            self.redirect(error=str(exc), tab="contacts")

    def handle_contacts_merge(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        winner_id = int(params.get("winner_id", [0])[0])
        loser_raw = params.get("loser_ids", [""])[0]
        losers = [int(x) for x in loser_raw.split(",") if x.strip().isdigit()]
        force = "force" in params or params.get("force", ["0"])[0] == "1"
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .settlement import merge_contacts

                result = merge_contacts(
                    conn, winner_id, losers, auto_dedupe=True, force=force
                )
            voided = result.get("dedupe", {}).get("voided_count", 0)
            self.redirect(
                message=(
                    f"Merged {len(losers)} contact(s) into #{winner_id}. "
                    f"Reassigned {result.get('reassigned_ledger_rows', 0)} rows; "
                    f"voided {voided} duplicates."
                ),
                tab="contacts",
            )
        except Exception as exc:
            logger.exception("merge failed")
            self.redirect(error=str(exc), tab="contacts")


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    init_auth_db()
    server = DualStackServer((host, port), ExpenseHandler)
    logger.info("Expense tracker running at http://%s:%d (Dual IPv4/IPv6)", host, port)
    logger.info("Database: %s", DATA_DIR)
    print(f"Expense tracker running at http://{host}:{port}")
    server.serve_forever()
