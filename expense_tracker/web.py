"""HTTP server: routing, request handling, and static file serving."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import date
from decimal import Decimal, InvalidOperation
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pypdf.errors import PdfReadError

from .db import (
    APP_ROOT,
    DB_PATH,
    add_manual_transaction,
    connect,
    dashboard_data,
    file_sha256,
    import_transactions,
    init_db,
    review_transaction,
    write_csv,
    write_json,
)
from .services import CATEGORIES, EXPENSE_TYPES, split_ratio_from_people
from .sbi_pdf import extract_transactions_from_bytes
from .templates import page

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_DIR = APP_ROOT / "outputs"


class ExpenseHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            with connect() as conn:
                data = dashboard_data(conn)
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
                    "use_my_share" in params,
                )
            )
        elif parsed.path == "/style.css":
            self.serve_static("style.css", "text/css; charset=utf-8")
        elif parsed.path == "/app.js":
            self.serve_static("app.js", "application/javascript; charset=utf-8")
        elif parsed.path == "/chart.js":
            self.serve_static("chart.js", "application/javascript; charset=utf-8")
        elif parsed.path == "/export.csv":
            self.export_file("csv")
        elif parsed.path == "/export.json":
            self.export_file("json")
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/import":
            self.handle_import()
        elif self.path == "/manual":
            self.handle_manual()
        elif self.path == "/review":
            self.handle_review()
        elif self.path == "/edit-classifications":
            self.handle_edit_classifications()
        else:
            self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        logger.debug("%s %s", self.command, self.path)

    def respond_html(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, message: str | None = None, error: str | None = None) -> None:
        query = urllib.parse.urlencode({k: v for k, v in {"message": message, "error": error}.items() if v})
        target = f"/?{query}" if query else "/"
        self.send_response(303)
        self.send_header("Location", target)
        self.end_headers()

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

    def multipart(self):
        # Uses email.parser to parse HTTP multipart form data by wrapping the
        # body in a synthetic MIME envelope. This avoids external dependencies
        # but differs subtly from RFC 7578. Consider replacing with a dedicated
        # multipart library if edge cases arise with binary payloads.
        length = int(self.headers.get("Content-Length", "0"))
        content_type = self.headers.get("Content-Type", "")
        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        return {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}

    def handle_import(self) -> None:
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
                with connect() as conn:
                    _, inserted, parsed = import_transactions(
                        conn,
                        filename,
                        sha256,
                        rows,
                        password_used=bool(password),
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

    def handle_manual(self) -> None:
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
            with connect() as conn:
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
                )
            self.redirect(message="Manual transaction added. Dashboard updated.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error adding manual transaction.")
            self.redirect(error=str(exc))

    def handle_review(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            if "transaction_id" not in params:
                self.handle_review_batch(params)
                return

            transaction_id = int(params["transaction_id"][0])
            category = params["category"][0].strip()
            expense_type = params["expense_type"][0].strip()
            if "split_people" in params:
                split_ratio = split_ratio_from_people(params["split_people"][0])
            else:
                split_ratio = Decimal(params.get("split_ratio", ["0.5"])[0] or "0.5")
            notes = params.get("notes", [""])[0].strip() or None
            learn = "learn" in params
            if not category or expense_type not in EXPENSE_TYPES:
                raise ValueError("Choose a category and expense type.")
            with connect() as conn:
                review_transaction(conn, transaction_id, category, expense_type, split_ratio, notes, learn)
            self.redirect(message="Transaction confirmed and merchant knowledge base updated.")
        except ValueError as exc:
            self.redirect(error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected error during review.")
            self.redirect(error=str(exc))

    def handle_review_batch(self, params: dict[str, list[str]]) -> None:
        confirmed = 0
        skipped = 0
        with connect() as conn:
            for raw_id in params.get("review_ids", []):
                transaction_id = int(raw_id)
                category = params.get(f"category_{transaction_id}", [""])[0].strip()
                if not category:
                    skipped += 1
                    continue
                expense_type = params.get(f"expense_type_{transaction_id}", ["Personal"])[0].strip()
                if expense_type not in EXPENSE_TYPES:
                    raise ValueError("Choose a valid expense type.")
                split_ratio = split_ratio_from_people(
                    params.get(f"split_people_{transaction_id}", ["1"])[0]
                )
                notes = params.get(f"notes_{transaction_id}", [""])[0].strip() or None
                learn = f"learn_{transaction_id}" in params
                review_transaction(conn, transaction_id, category, expense_type, split_ratio, notes, learn)
                confirmed += 1

        if confirmed:
            self.redirect(message=f"Confirmed {confirmed} review change(s). Dashboard updated.")
        elif skipped:
            self.redirect(error="No changes saved. Choose a category for at least one review row.")
        else:
            self.redirect(message="Nothing waiting for review.")

    def handle_edit_classifications(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            updated = 0
            skipped = 0
            with connect() as conn:
                for raw_id in params.get("edit_ids", []):
                    transaction_id = int(raw_id)
                    category = params.get(f"edit_category_{transaction_id}", [""])[0].strip()
                    if not category:
                        skipped += 1
                        continue
                    expense_type = params.get(f"edit_expense_type_{transaction_id}", ["Personal"])[0].strip()
                    if expense_type not in EXPENSE_TYPES:
                        raise ValueError("Choose a valid expense type.")
                    split_ratio = split_ratio_from_people(
                        params.get(f"edit_split_people_{transaction_id}", ["1"])[0]
                    )
                    notes = params.get(f"edit_notes_{transaction_id}", [""])[0].strip() or None
                    learn = f"edit_learn_{transaction_id}" in params
                    review_transaction(conn, transaction_id, category, expense_type, split_ratio, notes, learn)
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

    def export_file(self, kind: str) -> None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        path = OUTPUT_DIR / f"transactions.{kind}"
        with connect() as conn:
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


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with connect() as conn:
        init_db(conn)
    server = ThreadingHTTPServer((host, port), ExpenseHandler)
    logger.info("Expense tracker running at http://%s:%d", host, port)
    logger.info("Database: %s", DB_PATH)
    print(f"Expense tracker running at http://{host}:{port}")
    print(f"Database: {DB_PATH}")
    server.serve_forever()
