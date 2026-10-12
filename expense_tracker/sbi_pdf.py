from __future__ import annotations

import re
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber


DATE_PATTERNS = [
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%m-%y",
    "%d/%m/%y",
    "%d %b %Y",
    "%d %b %y",
]

MONEY_RE = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?")
DATE_RE = re.compile(r"^\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})\b")


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value.strip())
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_money(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "Cr", "Dr"}:
        return Decimal("0")
    cleaned = cleaned.replace("Cr", "").replace("Dr", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        match = MONEY_RE.search(cleaned)
        return Decimal(match.group(0).replace(",", "")) if match else Decimal("0")


def clean_cell(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def header_map(headers: list[str]) -> dict[str, int]:
    normalized = [h.lower().replace(".", "").replace("_", " ") for h in headers]
    mapping: dict[str, int] = {}
    for idx, header in enumerate(normalized):
        if "date" in header and "value" not in header and "txn_date" not in mapping:
            mapping["txn_date"] = idx
        elif "value" in header and "date" in header:
            mapping["value_date"] = idx
        elif any(token in header for token in ["description", "particular", "narration", "details"]):
            mapping["description"] = idx
        elif any(token in header for token in ["ref", "cheque", "chq", "instrument"]):
            mapping["reference"] = idx
        elif any(token in header for token in ["debit", "withdrawal", "withdraw"]):
            mapping["debit"] = idx
        elif any(token in header for token in ["credit", "deposit"]):
            mapping["credit"] = idx
        elif "balance" in header:
            mapping["balance"] = idx
    return mapping


def row_value(row: list[str], mapping: dict[str, int], key: str) -> str | None:
    idx = mapping.get(key)
    if idx is None or idx >= len(row):
        return None
    return clean_cell(row[idx])


def is_summary_row(row: list[str]) -> bool:
    text = " ".join(clean_cell(cell).lower() for cell in row if cell)
    summary_keywords = [
        "statement summary",
        "brought forward",
        "dr count",
        "cr count",
        "total debits",
        "total credits",
        "closing balance",
    ]
    return any(kw in text for kw in summary_keywords)


def parse_table_rows(tables: list[list[list[object]]]) -> list[dict]:
    transactions: list[dict] = []
    active_map: dict[str, int] | None = None
    for table in tables:
        # If the table has summary rows and no transaction date rows, skip the whole table
        if any(is_summary_row([clean_cell(c) for c in raw_row]) for raw_row in table):
            has_txns = any(len(r) >= 6 and parse_date(clean_cell(r[0])) for r in table)
            if not has_txns:
                continue

        for raw_row in table:
            row = [clean_cell(cell) for cell in raw_row]
            if not any(row):
                continue
            if is_summary_row(row):
                continue

            maybe_map = header_map(row)
            if {"txn_date", "description"}.issubset(maybe_map):
                active_map = maybe_map
                continue

            # Repeated header rows (e.g. page headers with only 'Balance') without dates
            if maybe_map and not parse_date(row[0]):
                continue

            if not active_map:
                # Auto-detect 7-column or 6-column layout when row begins with valid dates:
                # [txn_date, value_date, description, ref, debit, credit, balance]
                if len(row) >= 7 and parse_date(row[0]) and parse_date(row[1]):
                    active_map = {
                        "txn_date": 0,
                        "value_date": 1,
                        "description": 2,
                        "reference": 3,
                        "debit": 4,
                        "credit": 5,
                        "balance": 6,
                    }
                elif len(row) >= 6 and parse_date(row[0]):
                    active_map = {
                        "txn_date": 0,
                        "value_date": 1,
                        "description": 2,
                        "debit": 3,
                        "credit": 4,
                        "balance": 5,
                    }
                else:
                    continue

            txn_date = parse_date(row_value(row, active_map, "txn_date"))
            if not txn_date:
                # Only treat as continuation if it's not a header-like row
                if transactions and not maybe_map:
                    continuation = " ".join(cell for cell in row if cell)
                    transactions[-1]["description"] = f"{transactions[-1]['description']} {continuation}".strip()
                    transactions[-1]["raw_text"] = f"{transactions[-1]['raw_text']} {continuation}".strip()
                continue

            description = row_value(row, active_map, "description") or row_value(row, active_map, "reference") or ""
            ref_val = row_value(row, active_map, "reference")
            if ref_val == "-":
                ref_val = None
            debit = parse_money(row_value(row, active_map, "debit"))
            credit = parse_money(row_value(row, active_map, "credit"))
            balance_raw = row_value(row, active_map, "balance")
            transactions.append(
                {
                    "txn_date": txn_date,
                    "value_date": parse_date(row_value(row, active_map, "value_date")) or txn_date,
                    "description": description,
                    "reference": ref_val,
                    "debit": debit,
                    "credit": credit,
                    "balance": parse_money(balance_raw) if balance_raw else None,
                    "raw_text": " | ".join(cell for cell in row if cell),
                }
            )
    return [row for row in transactions if (row["debit"] or row["credit"])]


def is_likely_amount_token(val: str) -> bool:
    clean = val.replace("-", "").replace("+", "").strip()
    if not clean:
        return False
    if "." in clean:
        parts = clean.replace(",", "").split(".")
        return len(parts) == 2 and len(parts[1]) in (1, 2) and len(parts[0]) <= 9
    if "," in clean:
        raw_digits = clean.replace(",", "")
        return raw_digits.isdigit() and len(raw_digits) <= 8
    return False


def parse_text_lines(text: str) -> list[dict]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if DATE_RE.match(line):
            if current:
                blocks.append(" ".join(current))
            current = [line.strip()]
        elif current:
            current.append(line.strip())
        if current:
            blocks.append(" ".join(current))

    rows: list[dict] = []
    for block in blocks:
        date_match = DATE_RE.match(block)
        if not date_match:
            continue
        txn_date = parse_date(date_match.group(1))
        if not txn_date:
            continue
        raw_amounts = MONEY_RE.findall(block)
        amounts = [item for item in raw_amounts if is_likely_amount_token(item)]
        if not amounts:
            continue
        parsed_amounts = [parse_money(item) for item in amounts]
        balance = parsed_amounts[-1] if len(parsed_amounts) >= 2 else None
        debit = Decimal("0")
        credit = Decimal("0")
        if len(parsed_amounts) >= 3:
            debit, credit = parsed_amounts[-3], parsed_amounts[-2]
        elif len(parsed_amounts) == 2:
            debit = parsed_amounts[0]

        description = block[date_match.end() :]
        for amount in amounts[-3:]:
            description = description.replace(amount, " ", 1)
        description = re.sub(r"\s+", " ", description).strip(" -|")
        rows.append(
            {
                "txn_date": txn_date,
                "value_date": txn_date,
                "description": description or "",
                "reference": None,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "raw_text": block,
            }
        )
    return [row for row in rows if row["debit"] or row["credit"]]


def extract_transactions(pdf_path: Path, password: str | None = None) -> list[dict]:
    with pdfplumber.open(str(pdf_path), password=password or "") as pdf:
        tables: list[list[list[object]]] = []
        text_parts: list[str] = []
        for page in pdf.pages:
            # 1. First try extracting tables using line strategies (matches SBI bordered tables)
            page_tables = page.extract_tables()
            # If no tables found, try custom strategy
            if not page_tables:
                page_tables = page.extract_tables(
                    {
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "text",
                        "intersection_tolerance": 5,
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                    }
                )
            tables.extend(page_tables or [])
            text_parts.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")

    table_rows = parse_table_rows(tables)
    if table_rows:
        return table_rows
    text_rows = parse_text_lines("\n".join(text_parts))
    if text_rows:
        return text_rows
    raise ValueError("No transactions found. Check that this is an SBI statement PDF and that the password is correct.")


def extract_transactions_from_bytes(
    content: bytes,
    filename: str,
    password: str | None = None,
) -> tuple[Path, list[dict]]:
    suffix = Path(filename).suffix or ".pdf"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        handle.write(content)
        handle.close()
        path = Path(handle.name)
        return path, extract_transactions(path, password=password)
    except Exception:
        Path(handle.name).unlink(missing_ok=True)
        raise

