"""HTTP server: routing, request handling, and static file serving."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
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
    create_api_token,
    delete_session,
    get_all_usernames,
    get_gemini_api_key,
    get_gmail_imap,
    get_statement_password,
    init_auth_db,
    register_user,
    revoke_api_token,
    set_gemini_api_key,
    set_gmail_imap,
    set_statement_password,
    verify_api_token,
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
    export_rows,
    init_db,
    onboarding_status,
    remove_transaction_link,
    review_transaction,
    write_csv,
    write_json,
)
from .services import (
    CATEGORIES,
    EXPENSE_TYPES,
    compute_partner_balances,
    dashboard_summary_payload,
    split_ratio_from_people,
)
from .import_ingest import import_statement_bytes, read_last_import
from .templates import login_page, page, register_page

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
FRONTEND_DIST = APP_ROOT / "frontend" / "dist"
OUTPUT_DIR = APP_ROOT / "outputs"


class DualStackServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that listens on both IPv4 and IPv6 when possible."""

    allow_reuse_address = True
    daemon_threads = True  # don't block shutdown on hung client threads

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()

    def handle_error(self, request, client_address):
        """Don't dump stack traces for normal client disconnects."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            logger.debug("Client %s disconnected: %s", client_address, exc)
            return
        super().handle_error(request, client_address)


# Client disconnects during write — never fatal to the process
_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError)


def parse_multipart(body: bytes, content_type: str) -> dict[str, Any]:
    """Parse multipart form-data request body into a dictionary of part objects."""
    header_str = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    msg = BytesParser(policy=default).parsebytes(header_str.encode("utf-8") + body)
    parts = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            parts[name] = part
    return parts


class ExpenseHandler(BaseHTTPRequestHandler):

    # ── helpers ──────────────────────────────────────────────────────────────

    def get_session_username(self) -> str | None:
        """Username from session cookie or Authorization: Bearer <api_token>."""
        auth = (self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            user = verify_api_token(token)
            if user:
                return user
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session="):
                session_id = part[len("session="):]
                return verify_session(session_id)
            if part.startswith("session_id="):
                session_id = part[len("session_id="):]
                return verify_session(session_id)
        return None

    def _wants_json(self) -> bool:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return True
        accept = (self.headers.get("Accept") or "").lower()
        return "application/json" in accept

    def _require_user(self) -> str | None:
        """Return username or send 401/redirect and return None."""
        username = self.get_session_username()
        if username:
            return username
        if self._wants_json():
            self.respond_json(
                {"error": "Unauthorized", "hint": "Use session cookie or Authorization: Bearer <token>"},
                status=401,
            )
        else:
            nxt = "/app/" if self._is_mobile() else ""
            login = "/login?next=/app/" if nxt else "/login"
            self.redirect(path=login)
        return None

    def get_session_id(self) -> str | None:
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
            if part.startswith("session_id="):
                return part[len("session_id="):]
        return None

    def check_authentication(self) -> bool:
        """Check authentication, set current_user and db_path in request_context."""
        username = self.get_session_username()
        if username:
            self.current_user = username
            from .db import DATA_DIR, request_context
            request_context.db_path = DATA_DIR / f"expenses_{username.lower()}.db"
            return True
        return False

    def _db_path_for(self, username: str) -> Path:
        return DATA_DIR / f"expenses_{username.lower()}.db"

    def _is_mobile(self) -> bool:
        ua = (self.headers.get("User-Agent") or "").lower()
        return any(token in ua for token in ("iphone", "android", "ipad", "mobile"))

    @staticmethod
    def _safe_next(raw: str) -> str:
        path = (raw or "").strip()
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            return ""
        if path.startswith("/login") or path.startswith("/register"):
            return ""
        return path

    def _session_cookie(self, session_id: str = "", *, clear: bool = False) -> str:
        """Build Set-Cookie; add Secure when COOKIE_SECURE=1 or ENV=production."""
        secure = os.environ.get("COOKIE_SECURE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        } or os.environ.get("ENV", "").strip().lower() in {"prod", "production"}
        if clear:
            parts = ["session=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
        else:
            parts = [
                f"session={session_id}",
                "Path=/",
                "HttpOnly",
                "SameSite=Lax",
                "Max-Age=2592000",
            ]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def _safe_write(self, body: bytes | None = None) -> None:
        try:
            if body is not None:
                self.wfile.write(body)
            self.wfile.flush()
        except _CLIENT_GONE:
            logger.debug("Client gone while writing response")

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """send_error that swallows client disconnects (avoids nested exceptions)."""
        try:
            super().send_error(code, message=message, explain=explain)
        except _CLIENT_GONE:
            logger.debug("Client gone while sending error %s", code)
        except Exception:
            logger.debug("send_error failed for %s", code, exc_info=True)

    def respond_html(self, body: bytes, status: int = 200) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
        except _CLIENT_GONE:
            logger.debug("Client gone during respond_html")

    def redirect(
        self,
        message: str | None = None,
        error: str | None = None,
        path: str = "/",
        tab: str | None = None,
        tx_filter: str | None = None,
    ) -> None:
        q = {k: v for k, v in {"message": message, "error": error, "tx_filter": tx_filter}.items() if v}
        query = urllib.parse.urlencode(q)
        hash_suffix = f"#{tab}" if tab else ""
        target = f"{path}?{query}{hash_suffix}" if query else f"{path}{hash_suffix}"
        try:
            self.send_response(303)
            self.send_header("Location", target)
            self.end_headers()
            self._safe_write()
        except _CLIENT_GONE:
            logger.debug("Client gone during redirect")

    def respond_json(self, payload: Any, status: int = 200) -> None:
        import json as json_mod
        body = json_mod.dumps(payload, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
        except _CLIENT_GONE:
            logger.debug("Client gone during respond_json")

    def serve_static(self, filename: str, content_type: str) -> None:
        path = STATIC_DIR / filename
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self._safe_write(body)
        except _CLIENT_GONE:
            logger.debug("Client gone during serve_static")

    def serve_frontend(self, request_path: str) -> None:
        """Serve Vite build from frontend/dist at /app/ (SPA fallback to index.html)."""
        if not FRONTEND_DIST.is_dir():
            self.respond_html(
                b"<!doctype html><html><body style='font-family:system-ui;padding:2rem'>"
                b"<h1>React app not built</h1>"
                b"<p>Run <code>cd frontend && npm install && npm run build</code>, then restart.</p>"
                b"<p><a href='/'>Back to classic UI</a></p></body></html>"
            )
            return
        rel = request_path[len("/app"):].lstrip("/") or "index.html"
        # Prevent path traversal
        candidate = (FRONTEND_DIST / rel).resolve()
        try:
            candidate.relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            self.send_error(404)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            candidate = FRONTEND_DIST / "index.html"
        if not candidate.is_file():
            self.send_error(404)
            return
        suffix = candidate.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".woff2": "font/woff2",
            ".json": "application/json",
            ".webmanifest": "application/manifest+json",
        }.get(suffix, "application/octet-stream")
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache" if suffix == ".html" else "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def handle_api_onboarding(self, username: str) -> None:
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                payload = onboarding_status(conn)
            self.respond_json(payload)
        except Exception:
            logger.exception("onboarding API failed")
            self.respond_json({"error": "Failed to load onboarding"}, status=500)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def handle_api_meta(self) -> None:
        self.respond_json({"categories": CATEGORIES, "expense_types": EXPENSE_TYPES})

    def handle_api_dashboard_summary(self, username: str, params: dict) -> None:
        start = (params.get("start_date") or params.get("start") or [""])[0]
        end = (params.get("end_date") or params.get("end") or [""])[0]
        raw_ex = (params.get("exclude_business") or ["1"])[0]
        exclude = str(raw_ex).lower() not in {"0", "false", "no", "off"}
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                payload = dashboard_summary_payload(
                    conn,
                    start_date=start or None,
                    end_date=end or None,
                    exclude_business=exclude,
                )
            self.respond_json(payload)
        except Exception:
            logger.exception("dashboard summary API failed")
            self.respond_json({"error": "Failed to load dashboard summary"}, status=500)

    def handle_api_manual(self, username: str) -> None:
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=400)
            return
        try:
            txn_date = str(body.get("txn_date") or "").strip() or date.today().isoformat()
            date.fromisoformat(txn_date)
            description = str(body.get("description") or "").strip()
            if not description:
                raise ValueError("Enter a description.")
            amount = Decimal(str(body.get("amount")))
            direction = str(body.get("direction") or "debit").strip()
            category = str(body.get("category") or "").strip()
            expense_type = str(body.get("expense_type") or "Personal").strip()
            if not category or expense_type not in EXPENSE_TYPES:
                raise ValueError("Choose a category and expense type.")
            split_ratio = split_ratio_from_people(body.get("split_people") or 1)
            notes = str(body.get("notes") or "").strip() or None
            learn = bool(body.get("learn"))
        except (ValueError, InvalidOperation) as exc:
            self.respond_json({"error": str(exc)}, status=400)
            return
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                txn_id = add_manual_transaction(
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            self.respond_json({"ok": True, "transaction_id": txn_id})
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("api manual failed")
            self.respond_json({"error": "Failed to add entry"}, status=500)

    def handle_api_assistant_chat(self, username: str) -> None:
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=400)
            return
        message = str(body.get("message") or body.get("q") or "").strip()
        history = body.get("history") if isinstance(body.get("history"), list) else []
        from .assistant import run_chat

        try:
            payload = run_chat(self._db_path_for(username), username, message, history)
            self.respond_json(payload)
        except Exception:
            logger.exception("assistant chat failed")
            self.respond_json({"error": "Assistant failed", "reply": "Something went wrong."}, status=500)

    def handle_api_assistant_confirm(self, username: str) -> None:
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=400)
            return
        token = str(body.get("confirm_token") or body.get("token") or "").strip()
        from .assistant import confirm_action

        try:
            payload = confirm_action(self._db_path_for(username), username, token)
            status = 200 if payload.get("ok") else 400
            self.respond_json(payload, status=status)
        except Exception:
            logger.exception("assistant confirm failed")
            self.respond_json({"ok": False, "error": "Confirm failed"}, status=500)

    def _filter_export_rows(
        self,
        rows: list[dict],
        start_date: str = "",
        end_date: str = "",
        query: str = "",
        limit: int | None = None,
    ) -> list[dict]:
        """Filter export_rows like dashboard period + text search (for AI / API)."""
        start_date = (start_date or "").strip()
        end_date = (end_date or "").strip()
        q = (query or "").strip().lower()
        out: list[dict] = []
        for row in rows:
            d = str(row.get("txn_date") or "")
            if start_date and d < start_date:
                continue
            if end_date and d > end_date:
                continue
            if q:
                blob = " ".join(
                    str(row.get(k) or "")
                    for k in (
                        "merchant_display",
                        "description",
                        "category",
                        "expense_type",
                        "notes",
                        "reference",
                    )
                ).lower()
                if q not in blob:
                    continue
            # JSON-safe numbers
            item = dict(row)
            for k, v in list(item.items()):
                if isinstance(v, Decimal):
                    item[k] = float(v)
            out.append(item)
            if limit is not None and len(out) >= limit:
                break
        return out

    def handle_api_export(self, username: str, kind: str, params: dict) -> None:
        """GET /api/export.json|csv — same rows as dashboard export; Bearer OK."""
        start = (params.get("start_date") or params.get("start") or [""])[0]
        end = (params.get("end_date") or params.get("end") or [""])[0]
        q = (params.get("q") or params.get("query") or [""])[0]
        limit_raw = (params.get("limit") or [""])[0]
        limit = None
        if str(limit_raw).strip().isdigit():
            limit = max(1, min(int(limit_raw), 5000))
        try:
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                rows = export_rows(conn)
            filtered = self._filter_export_rows(rows, start, end, q, limit)
            if kind == "csv":
                import csv
                import io

                buf = io.StringIO()
                if filtered:
                    writer = csv.DictWriter(buf, fieldnames=list(filtered[0].keys()))
                    writer.writeheader()
                    writer.writerows(filtered)
                body = buf.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header(
                    "Content-Disposition", 'attachment; filename="transactions.csv"'
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.respond_json(
                    {
                        "username": username,
                        "count": len(filtered),
                        "start_date": start or None,
                        "end_date": end or None,
                        "query": q or None,
                        "transactions": filtered,
                    }
                )
        except Exception:
            logger.exception("export API failed")
            self.respond_json({"error": "Failed to export transactions"}, status=500)

    def handle_api_transactions(self, username: str, params: dict) -> None:
        """GET /api/transactions — filtered export rows for agents (default limit 50)."""
        start = (params.get("start_date") or params.get("start") or [""])[0]
        end = (params.get("end_date") or params.get("end") or [""])[0]
        q = (params.get("q") or params.get("query") or [""])[0]
        limit_raw = (params.get("limit") or ["50"])[0]
        try:
            limit = max(1, min(int(limit_raw or 50), 500))
        except ValueError:
            limit = 50
        try:
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                rows = export_rows(conn)
            # newest first for agent browse
            rows = list(reversed(rows))
            filtered = self._filter_export_rows(rows, start, end, q, limit)
            self.respond_json(
                {
                    "username": username,
                    "count": len(filtered),
                    "start_date": start or None,
                    "end_date": end or None,
                    "query": q or None,
                    "transactions": filtered,
                }
            )
        except Exception:
            logger.exception("transactions API failed")
            self.respond_json({"error": "Failed to list transactions"}, status=500)

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

            # React shell (built assets under frontend/dist)
            if parsed.path == "/app" or parsed.path.startswith("/app/"):
                self.serve_frontend(parsed.path)
                return

            # Auth pages / health — no auth
            if parsed.path == "/login":
                nxt = self._safe_next((params.get("next") or [""])[0])
                if not nxt and self._is_mobile():
                    nxt = "/app/"
                self.respond_html(login_page(next_path=nxt))
                return
            if parsed.path == "/register":
                self.respond_html(register_page())
                return
            if parsed.path == "/api/health":
                self.respond_json(
                    {
                        "ok": True,
                        "service": "expense-tracker",
                        "mode": "live",
                        "writes": True,
                        "data_dir": str(DATA_DIR),
                    }
                )
                return

            # Session or Bearer token for everything else
            username = self._require_user()
            if not username:
                return

            if parsed.path == "/" and self._is_mobile():
                self.send_response(302)
                self.send_header("Location", "/app/")
                self.end_headers()
                self._safe_write()
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
            if parsed.path == "/api/onboarding":
                self.handle_api_onboarding(username)
                return
            if parsed.path == "/api/dashboard/summary":
                self.handle_api_dashboard_summary(username, params)
                return
            if parsed.path == "/api/meta":
                self.handle_api_meta()
                return
            if parsed.path in ("/api/export.json", "/api/export/json"):
                self.handle_api_export(username, "json", params)
                return
            if parsed.path in ("/api/export.csv", "/api/export/csv"):
                self.handle_api_export(username, "csv", params)
                return
            if parsed.path == "/api/transactions":
                self.handle_api_transactions(username, params)
                return

            if parsed.path == "/":
                db_path = self._db_path_for(username)
                all_users = get_all_usernames()
                with connect(db_path) as conn:
                    data = dashboard_data(conn)
                    data["onboarding"] = onboarding_status(conn)
                    from .contacts import get_all_balances

                    partner_balances = [
                        {
                            "username": item["contact"]["name"],
                            "contact_id": item["contact"]["id"],
                            "they_owe_you": item["balance"]["they_owe_you"],
                            "you_owe_them": item["balance"]["you_owe_them"],
                            "net": item["balance"]["net"],
                        }
                        for item in get_all_balances(conn)
                        if item["balance"]["net"] != 0
                    ]
                # Period form always sends start_date when applied. First load
                # (no period params) → exclude business by default.
                period_touched = any(
                    k in params
                    for k in ("start_date", "end_date", "exclude_business", "use_my_share")
                )
                exclude_business = (
                    "exclude_business" in params if period_touched else True
                )
                gmail_addr, gmail_pw = get_gmail_imap(username)
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
                        exclude_business,
                        current_user=username,
                        all_users=all_users,
                        partner_balances=partner_balances,
                        tx_filter=params.get("tx_filter", ["needs_review"])[0],
                        exclude_credits="exclude_credits" in params or params.get("exclude_credits", ["0"])[0] in ("1", "true"),
                        last_import=read_last_import(username),
                        gmail_on=bool(gmail_pw),
                        gmail_address=gmail_addr,
                        pdf_password_saved=bool(get_statement_password(username)),
                        gemini_key_saved=bool(get_gemini_api_key(username)),
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
        except _CLIENT_GONE:
            logger.debug("Client disconnected during do_GET")
        except Exception:
            logger.exception("Unexpected error in do_GET")
            try:
                self.send_error(500)
            except _CLIENT_GONE:
                pass

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
            if self.path == "/api/token":
                self.handle_api_token_create()
                return

            # All other POST endpoints require session or Bearer token
            username = self._require_user()
            if not username:
                return

            if self.path == "/api/token/revoke":
                self.handle_api_token_revoke(username)
                return
            post_path = urllib.parse.urlparse(self.path).path
            if post_path == "/api/manual":
                self.handle_api_manual(username)
                return
            if post_path == "/api/assistant/chat":
                self.handle_api_assistant_chat(username)
                return
            if post_path == "/api/assistant/confirm":
                self.handle_api_assistant_confirm(username)
                return
            if self.path == "/import":
                self.handle_import(username)
            elif self.path == "/gmail/connect":
                self.handle_gmail_connect(username)
            elif self.path == "/settings/gemini":
                self.handle_settings_gemini(username)
            elif self.path == "/import/mail-now":
                self.handle_mail_now(username)
            elif self.path == "/api/import/statement":
                self.handle_api_import_statement(username)
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
            elif self.path == "/contacts/edit":
                self.handle_contact_edit(username)
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
            elif self.path == "/ledger/rolling":
                self.handle_ledger_rolling(username)
            elif self.path == "/ledger/opening":
                self.handle_ledger_opening(username)
            elif self.path == "/ledger/void" or self.path.startswith("/ledger/void/"):
                self.handle_ledger_void(username)
            else:
                self.send_error(404)
        except _CLIENT_GONE:
            logger.debug("Client disconnected during do_POST")
        except Exception:
            logger.exception("Unexpected error in do_POST")
            try:
                self.send_error(500)
            except _CLIENT_GONE:
                pass

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
            nxt = self._safe_next(params.get("next", [""])[0])
            if not nxt:
                nxt = "/app/" if self._is_mobile() else "/"
            self.send_response(303)
            self.send_header("Location", nxt)
            self.send_header("Set-Cookie", self._session_cookie(session_id))
            self.end_headers()
            self.wfile.flush()
        else:
            nxt = self._safe_next(params.get("next", [""])[0])
            self.respond_html(login_page(error="Invalid username or password.", next_path=nxt))

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
        self.send_header("Set-Cookie", self._session_cookie(clear=True))
        self.end_headers()
        self.wfile.flush()

    def handle_logout_get(self) -> None:
        self.handle_logout()

    def handle_api_token_create(self) -> None:
        """POST /api/token — exchange username/password for a Bearer API token."""
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").lower()
        username = password = label = ""
        days_valid = 90
        try:
            if "application/json" in ctype:
                payload = json.loads(raw.decode("utf-8") or "{}")
                username = str(payload.get("username") or "")
                password = str(payload.get("password") or "")
                label = str(payload.get("label") or "api")
                days_valid = int(payload.get("days_valid") or 90)
            else:
                params = urllib.parse.parse_qs(raw.decode("utf-8"))
                username = params.get("username", [""])[0]
                password = params.get("password", [""])[0]
                label = params.get("label", ["api"])[0]
                days_raw = params.get("days_valid", ["90"])[0]
                days_valid = int(days_raw) if str(days_raw).isdigit() else 90
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            self.respond_json({"error": "Invalid body"}, status=400)
            return

        token, msg = create_api_token(
            username, password, label=label, days_valid=days_valid
        )
        if not token:
            self.respond_json({"error": msg}, status=401)
            return
        self.respond_json(
            {
                "token": token,
                "token_type": "Bearer",
                "message": msg,
                "usage": "Authorization: Bearer <token>",
            }
        )

    def handle_api_token_revoke(self, username: str) -> None:
        """POST /api/token/revoke — revoke current Bearer token (or body token)."""
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        token = ""
        auth = (self.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token and raw:
            ctype = (self.headers.get("Content-Type") or "").lower()
            try:
                if "application/json" in ctype:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                    token = str(payload.get("token") or "")
                else:
                    params = urllib.parse.parse_qs(raw.decode("utf-8"))
                    token = params.get("token", [""])[0]
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        if not token:
            self.respond_json({"error": "No token provided"}, status=400)
            return
        ok = revoke_api_token(username, token)
        if ok:
            self.respond_json({"ok": True, "message": "Token revoked."})
        else:
            self.respond_json({"error": "Token not found or already revoked"}, status=404)

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
            result = import_statement_bytes(
                username, content, filename, typed_password=password
            )
            if result.get("already_imported"):
                self.redirect(
                    message=f"Already imported ({result['parsed']} transactions in file).",
                    tab="review",
                    tx_filter="last_statement",
                )
            else:
                self.redirect(
                    message=(
                        f"Parsed {result['parsed']} transactions and imported "
                        f"{result['inserted']} new. Review and auto are on Last statement."
                    ),
                    tab="review",
                    tx_filter="last_statement",
                )
        except PdfReadError:
            self.redirect(error="Could not open the PDF. Check the SBI statement password.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during import.")
            self.redirect(error=str(exc))

    def handle_api_import_statement(self, username: str) -> None:
        """POST /api/import/statement — multipart PDF; uses saved statement password."""
        try:
            parts = self.multipart()
            statement = parts.get("statement") or parts.get("file")
            if statement is None:
                self.respond_json({"error": "No PDF (field statement or file)"}, status=400)
                return
            password_part = parts.get("password")
            password = password_part.get_content().strip() if password_part else ""
            filename = statement.get_filename() or "statement.pdf"
            content = statement.get_payload(decode=True)
            result = import_statement_bytes(
                username, content, filename, typed_password=password
            )
            self.respond_json(result)
        except ValueError as exc:
            self.respond_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("API statement import failed")
            self.respond_json({"error": "Import failed"}, status=500)

    def handle_settings_gemini(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        key = (params.get("gemini_api_key", [""])[0] or "").strip()
        if not key:
            self.redirect(error="Paste a Gemini API key.")
            return
        set_gemini_api_key(username, key)
        self.redirect(message="Gemini key saved. Ask on /app/ can use it now.")

    def handle_gmail_connect(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        addr = (params.get("gmail_address", [""])[0] or "").strip()
        app_pw = (params.get("gmail_app_password", [""])[0] or "").strip()
        stmt_pw = (params.get("statement_password", [""])[0] or "").strip()
        if stmt_pw:
            set_statement_password(username, stmt_pw)
        if not addr or not app_pw:
            self.redirect(error="Enter Gmail address and an App Password.")
            return
        if not get_statement_password(username):
            self.redirect(
                error="Also enter the PDF statement password (SBI: last 5 digits of mobile + DOB ddmmyy)."
            )
            return
        set_gmail_imap(username, addr, app_pw)
        # Kick an import now
        try:
            from .mail_import import run_auto_import

            reports = run_auto_import(username)
            inserted = sum(int(r.get("inserted") or 0) for r in reports if r.get("ok"))
            if inserted:
                self.redirect(
                    message=f"Gmail connected. Imported {inserted} new transactions from mail."
                )
            else:
                self.redirect(
                    message="Gmail connected. Auto-import is on — new statement emails will import on this PC."
                )
        except Exception as exc:
            self.redirect(message=f"Gmail saved. First check failed: {exc}")

    def handle_mail_now(self, username: str) -> None:
        try:
            from .mail_import import run_auto_import

            reports = run_auto_import(username)
            inserted = sum(int(r.get("inserted") or 0) for r in reports if r.get("ok"))
            if inserted:
                self.redirect(
                    message=f"Imported {inserted} new transactions from mail.",
                    tab="review",
                    tx_filter="last_statement",
                )
            else:
                self.redirect(message="No new WhatsApp statements in mail.")
        except Exception as exc:
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
            tx_filter = params.get("tx_filter", ["needs_review"])[0]
            self.redirect(
                message="Transaction confirmed.",
                tab="review",
                tx_filter=tx_filter,
            )
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
                raw_people = params.get(f"split_people_{transaction_id}", [""])[0].strip()
                if not raw_people or (expense_type == "Shared" and raw_people in ("1", "0")):
                    raw_people = "2" if expense_type == "Shared" else "1"
                split_ratio = split_ratio_from_people(raw_people)
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            tx_filter = params.get("tx_filter", ["needs_review"])[0]
            self.redirect(
                message=f"Confirmed {confirmed} review change(s).",
                tab="review",
                tx_filter=tx_filter,
            )
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
                    raw_people = params.get(f"edit_split_people_{transaction_id}", [""])[0].strip()
                    if not raw_people or (expense_type == "Shared" and raw_people in ("1", "0")):
                        raw_people = "2" if expense_type == "Shared" else "1"
                    split_ratio = split_ratio_from_people(raw_people)
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
                from .cloud_sync import trigger_cloud_sync_bg

                trigger_cloud_sync_bg(username)
                tx_filter = params.get("tx_filter", ["classified"])[0]
                self.redirect(
                    message=f"Saved {updated} classification edit(s).",
                    tab="review",
                    tx_filter=tx_filter,
                )
            elif skipped:
                self.redirect(error="No edits saved. Choose a category for at least one classified row.")
            else:
                self.redirect(message="No classified rows selected.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error editing classifications.")
            self.redirect(error=str(exc))

    def sync_shared_transaction(self, conn, transaction_id: int, arg3: str | None = None, arg4: str | None = None) -> None:
        """Replicate shared transaction into partner DB, or delete replicated copy if unshared."""
        if arg4 is None:
            shared_with = arg3
            owner = getattr(self, "current_user", "user") or "user"
        else:
            owner = arg3
            shared_with = arg4

        ref = f"shared_src:{owner}:{transaction_id}"
        if not shared_with:
            try:
                from .db import DATA_DIR, request_context
                dir_path = Path(request_context.db_path).parent if hasattr(request_context, "db_path") and request_context.db_path else DATA_DIR
                for db_file in dir_path.glob("expenses_*.db"):
                    pconn = connect(db_file)
                    try:
                        r = pconn.execute("SELECT id FROM transactions WHERE reference = ?", (ref,)).fetchone()
                        if r:
                            tid = int(r["id"])
                            pconn.execute("DELETE FROM classifications WHERE transaction_id = ?", (tid,))
                            pconn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
                            pconn.commit()
                    finally:
                        pconn.close()
            except Exception:
                logger.exception("Error deleting unshared transaction %s", transaction_id)
            return
        try:
            row = conn.execute(
                "SELECT t.*, c.category, c.expense_type, c.split_ratio, c.my_share, c.notes "
                "FROM transactions t JOIN classifications c ON c.transaction_id = t.id "
                "WHERE t.id = ?",
                (transaction_id,),
            ).fetchone()
            if not row:
                return
            from .db import DATA_DIR, get_or_create_shared_import, request_context, utc_now
            if hasattr(request_context, "db_path") and request_context.db_path:
                partner_db = Path(request_context.db_path).parent / f"expenses_{shared_with.lower()}.db"
            else:
                partner_db = self._db_path_for(shared_with)
            partner_db.parent.mkdir(parents=True, exist_ok=True)
            pconn = connect(partner_db)
            try:
                # Check if already replicated
                ref = f"shared_src:{owner}:{transaction_id}"
                existing = pconn.execute(
                    "SELECT id FROM transactions WHERE reference = ? OR (source_txn_id = ? AND uploaded_by = ?)",
                    (ref, transaction_id, owner),
                ).fetchone()
                if existing:
                    return
                # Insert the replicated transaction
                import_id = get_or_create_shared_import(pconn)
                my_share = float(row["my_share"] or 0)
                debit = float(row["debit"] or 0)
                partner_share = max(0.0, debit - my_share)
                cur = pconn.execute(
                    """
                    INSERT INTO transactions (
                        import_id, source_hash, txn_date, value_date, description, reference,
                        debit, credit, amount_signed, balance, raw_text, merchant_key,
                        merchant_display, created_at, uploaded_by, source_txn_id, is_external, external_payer
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, 0.0, ?, 0.0, ?, ?, ?, ?, ?, ?, 1, ?
                    )
                    """,
                    (
                        import_id,
                        f"shared_{owner}_{transaction_id}",
                        row["txn_date"],
                        row["value_date"],
                        f"Shared from {owner}: {row['description']}",
                        ref,
                        debit,
                        -debit,
                        row["raw_text"],
                        row["merchant_key"],
                        row["merchant_display"],
                        utc_now(),
                        owner,
                        transaction_id,
                        owner,
                    ),
                )
                replicated_id = int(cur.lastrowid)
                pconn.execute(
                    """
                    INSERT INTO classifications (
                        transaction_id, status, expense_type, category, split_ratio, my_share, confidence, notes, updated_at
                    ) VALUES (?, 'needs_review', 'Shared', ?, ?, ?, 1.0, ?, ?)
                    """,
                    (
                        replicated_id,
                        row["category"],
                        row["split_ratio"],
                        partner_share,
                        f"Shared by {owner}: {dict(row).get('notes') or ''}".strip(),
                        utc_now(),
                    ),
                )
                pconn.commit()
            finally:
                pconn.close()
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
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
                from .contacts import get_ledger

                payload = get_ledger(conn, contact_id)
            self.respond_json(
                {
                    "contact": payload.get("contact"),
                    "balance": payload.get("balance"),
                    "entries": payload.get("entries") or [],
                    "virtual_shared_lines": [],
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
                from .contacts import get_balance, get_all_contacts

                bal = get_balance(conn, int(contact_id_str))
                for c in get_all_contacts(conn):
                    if c["id"] == int(contact_id_str):
                        bal["contact_name"] = c["name"]
                        break
            self.respond_json(bal)
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
                from .contacts import find_contact_by_text, get_balance

                match = find_contact_by_text(conn, q)
                if not match:
                    self.respond_json({"error": f"No contact matching '{q}'"}, status=404)
                    return
                bal = get_balance(conn, int(match["id"]))
                bal["contact_name"] = match["name"]
                name = match["name"]
                net = bal["net"]
                if net > 0:
                    answer = f"{name} owes you ₹{net:,.2f}."
                elif net < 0:
                    answer = f"You owe {name} ₹{abs(net):,.2f}."
                else:
                    answer = f"{name} is settled (₹0)."
                bal["answer"] = answer
            self.respond_json(bal)
        except Exception:
            logger.exception("settlement by-name failed")
            self.respond_json({"error": "Failed to resolve settlement"}, status=500)

    def handle_api_settlement_summary(self, username: str) -> None:
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .contacts import get_all_balances

                items = [
                    {
                        "contact_id": item["contact"]["id"],
                        "contact_name": item["contact"]["name"],
                        **item["balance"],
                    }
                    for item in get_all_balances(conn)
                    if item["balance"]["net"] != 0
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            self.redirect(message=f"Contact '{name}' created.", tab="contacts")
        except Exception as exc:
            self.redirect(error=str(exc), tab="contacts")

    def handle_contact_edit(self, username: str) -> None:
        """Rename a contact / update aliases so bank fragments get readable names."""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        try:
            contact_id = int(params.get("contact_id", [0])[0])
        except (TypeError, ValueError):
            self.redirect(error="Invalid contact.", tab="contacts")
            return
        name = (params.get("name", [""])[0] or "").strip()
        aliases = params.get("aliases", [""])[0]
        notes = params.get("notes", [None])[0]
        if notes is not None:
            notes = notes.strip() or None
        db_path = self._db_path_for(username)
        try:
            with connect(db_path) as conn:
                from .contacts import update_contact

                update_contact(conn, contact_id, name, aliases, notes)
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            self.redirect(message=f"Updated name to “{name}”.", tab="contacts")
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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
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
            with connect(db_path) as conn:
                from .contacts import add_ledger_entry

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
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
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
                from .contacts import record_settlement

                bal = record_settlement(
                    conn,
                    contact_id=contact_id,
                    amount=amount,
                    created_by="user",
                )
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            if bal["net"] == 0:
                self.redirect(message="Balance marked as settled.", tab="contacts")
            else:
                self.redirect(
                    message=f"Settlement recorded. Net now ₹{float(bal['net']):,.2f}.",
                    tab="contacts",
                )
        except ValueError as exc:
            self.redirect(error=str(exc), tab="contacts")
        except Exception as exc:
            logger.exception("settle failed")
            self.redirect(error=str(exc), tab="contacts")

    def handle_materialize_shared(self, username: str) -> None:
        """Removed with USB simplification - food splits are manual ledger entries."""
        self.redirect(
            message="Shared materialize removed. Add a food-split ledger entry under People.",
            tab="contacts",
        )

    def handle_ledger_rolling(self, username: str) -> None:
        """A -> You -> B rolling chain: two pass-through legs, nets unchanged."""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        try:
            from_id = int(params.get("from_contact_id", [0])[0])
            to_id = int(params.get("to_contact_id", [0])[0])
            amount = Decimal(params.get("amount", ["0"])[0])
            entry_date = params.get("entry_date", [""])[0] or datetime.now().strftime("%Y-%m-%d")
            notes = params.get("notes", [None])[0]
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                from .contacts import add_rolling_entry

                result = add_rolling_entry(
                    conn,
                    from_contact_id=from_id,
                    to_contact_id=to_id,
                    amount=amount,
                    entry_date=entry_date,
                    notes=notes or None,
                    created_by="user",
                )
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            self.redirect(
                message=(
                    f"Rolling ₹{result['amount']:,.2f}: "
                    f"{result['from_contact_name']} → you → {result['to_contact_name']} "
                    f"(pass-through; nets unchanged)."
                ),
                tab="contacts",
            )
        except (ValueError, InvalidOperation) as exc:
            self.redirect(error=str(exc), tab="contacts")
        except Exception as exc:
            logger.exception("rolling chain failed")
            self.redirect(error=str(exc), tab="contacts")

    def handle_ledger_opening(self, username: str) -> None:
        """One-click opening balance: they owe you / you owe them."""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        try:
            contact_id = int(params.get("contact_id", [0])[0])
            amount = Decimal(params.get("amount", ["0"])[0])
            they_owe = params.get("direction", ["they_owe_you"])[0] != "you_owe_them"
            entry_date = params.get("entry_date", [""])[0] or datetime.now().strftime("%Y-%m-%d")
            notes = params.get("notes", [None])[0]
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                from .contacts import record_opening_balance

                result = record_opening_balance(
                    conn,
                    contact_id=contact_id,
                    amount=amount,
                    they_owe_you=they_owe,
                    entry_date=entry_date,
                    notes=notes or None,
                    created_by="user",
                )
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            name = result["contact_name"]
            amt = result["amount"]
            if they_owe:
                msg = f"Opening set: {name} owes you ₹{amt:,.2f}."
            else:
                msg = f"Opening set: you owe {name} ₹{amt:,.2f}."
            self.redirect(message=msg, tab="contacts")
        except (ValueError, InvalidOperation) as exc:
            self.redirect(error=str(exc), tab="contacts")
        except Exception as exc:
            logger.exception("opening balance failed")
            self.redirect(error=str(exc), tab="contacts")

    def handle_ledger_void(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(body)
        try:
            entry_id = int(params.get("entry_id", [0])[0])
            db_path = self._db_path_for(username)
            with connect(db_path) as conn:
                from .contacts import void_ledger_entry

                void_ledger_entry(conn, entry_id, reason="voided by user")
            from .cloud_sync import trigger_cloud_sync_bg

            trigger_cloud_sync_bg(username)
            self.redirect(message="Ledger entry voided.", tab="contacts")
        except Exception as exc:
            self.redirect(error=str(exc), tab="contacts")

    def handle_contacts_merge(self, username: str) -> None:
        """Contact merge removed in simplified khata model."""
        self.redirect(
            error="Contact merge was removed. Use one contact name and aliases instead.",
            tab="contacts",
        )


def run(host: str | None = None, port: int | None = None) -> None:
    """Start the HTTP server.

    Env (hosting):
      HOST          bind address (default 0.0.0.0 for containers; use 127.0.0.1 locally if preferred)
      PORT          listen port (default 8765; Cloud Run sets PORT)
      DATA_DIR      SQLite directory (default ./data; mount a volume in production)
      COOKIE_SECURE 1/true → Secure cookies (use behind HTTPS)
      ENV           production → also enables Secure cookies
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if host is None:
        host = (os.environ.get("HOST") or "0.0.0.0").strip() or "0.0.0.0"
    if port is None:
        port = int((os.environ.get("PORT") or "8765").strip() or "8765")

    # Re-resolve DATA_DIR in case env was set after import (container entrypoints)
    from . import db as db_mod
    from . import auth as auth_mod

    data_dir = Path(os.environ.get("DATA_DIR") or db_mod.DATA_DIR).expanduser().resolve()
    db_mod.DATA_DIR = data_dir
    db_mod.DB_PATH = data_dir / "expenses.db"
    auth_mod.DATA_DIR = data_dir
    auth_mod.USERS_DB_PATH = data_dir / "users.db"
    data_dir.mkdir(parents=True, exist_ok=True)

    init_auth_db()
    try:
        server = DualStackServer((host, port), ExpenseHandler)
    except OSError as exc:
        # Common after a hard kill: port still bound briefly
        logger.error("Could not bind %s:%s — %s", host, port, exc)
        raise
    logger.info("Expense tracker running at http://%s:%d (Dual IPv4/IPv6)", host, port)
    logger.info("Database: %s", data_dir)
    print(f"Expense tracker running at http://{host}:{port}", flush=True)
    from .mail_poller import start_mail_poller

    start_mail_poller()
    print(f"DATA_DIR={data_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        try:
            server.server_close()
        except Exception:
            pass
