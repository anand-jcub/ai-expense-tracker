from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

from .classifier import (
    DEFAULT_SPLIT_RATIO,
    classify_transaction,
    display_merchant,
    effective_share,
    normalize_merchant,
)


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"
DB_PATH = DATA_DIR / "expenses.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a DB connection and ensure schema/migrations are applied."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    init_db(conn)
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def migrate_ledger_schema(conn: sqlite3.Connection) -> None:
    """Bring contacts/ledger tables up to the current dual-column schema.

    Legacy DBs used ``entry_type`` (and sometimes ``passthrough_contact_id``)
    without ``direction`` / ``passthrough_pair_id``. Newer code dual-writes
    both direction and entry_type.
    """
    if not _table_exists(conn, "ledger_entries"):
        return

    _safe_add_column(conn, "ledger_entries", "direction", "TEXT")
    _safe_add_column(conn, "ledger_entries", "entry_type", "TEXT")
    _safe_add_column(conn, "ledger_entries", "purpose", "TEXT")
    _safe_add_column(conn, "ledger_entries", "is_passthrough", "INTEGER DEFAULT 0")
    _safe_add_column(conn, "ledger_entries", "passthrough_pair_id", "INTEGER")
    _safe_add_column(conn, "ledger_entries", "is_opening_balance", "INTEGER DEFAULT 0")
    _safe_add_column(conn, "ledger_entries", "entry_date", "TEXT")
    _safe_add_column(conn, "ledger_entries", "created_by", "TEXT DEFAULT 'user'")
    _safe_add_column(conn, "ledger_entries", "notes", "TEXT")

    cols = _table_columns(conn, "ledger_entries")

    # Backfill direction <-> entry_type so readers can use either column.
    try:
        if "direction" in cols and "entry_type" in cols:
            conn.execute(
                """
                UPDATE ledger_entries
                SET entry_type = direction
                WHERE (entry_type IS NULL OR entry_type = '')
                  AND direction IS NOT NULL AND direction != ''
                """
            )
            conn.execute(
                """
                UPDATE ledger_entries
                SET direction = entry_type
                WHERE (direction IS NULL OR direction = '')
                  AND entry_type IS NOT NULL AND entry_type != ''
                """
            )
        elif "direction" in cols and "entry_type" not in cols:
            pass  # only direction present
        elif "entry_type" in cols and "direction" not in cols:
            # direction column should already have been added above
            conn.execute(
                """
                UPDATE ledger_entries
                SET direction = entry_type
                WHERE (direction IS NULL OR direction = '')
                  AND entry_type IS NOT NULL AND entry_type != ''
                """
            )
    except Exception as exc:
        logger.warning("Ledger direction/entry_type backfill skipped: %s", exc)

    # Normalize purpose defaults
    try:
        conn.execute(
            """
            UPDATE ledger_entries
            SET purpose = 'other'
            WHERE purpose IS NULL OR purpose = ''
            """
        )
    except Exception as exc:
        logger.debug("Ledger purpose backfill skipped: %s", exc)

    # Ensure entry_date is populated for older rows
    try:
        conn.execute(
            """
            UPDATE ledger_entries
            SET entry_date = substr(created_at, 1, 10)
            WHERE (entry_date IS NULL OR entry_date = '')
              AND created_at IS NOT NULL
            """
        )
    except Exception as exc:
        logger.debug("Ledger entry_date backfill skipped: %s", exc)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_contact ON ledger_entries(contact_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON ledger_entries(transaction_id)"
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists imports (
            id integer primary key autoincrement,
            source_filename text not null,
            file_sha256 text not null unique,
            imported_at text not null,
            password_used integer not null default 0,
            transaction_count integer not null default 0
        );

        create table if not exists transactions (
            id integer primary key autoincrement,
            import_id integer not null references imports(id),
            source_hash text not null unique,
            txn_date text not null,
            value_date text,
            description text not null,
            reference text,
            debit numeric not null default 0,
            credit numeric not null default 0,
            amount_signed numeric not null,
            balance numeric,
            raw_text text not null,
            merchant_key text not null,
            merchant_display text not null,
            created_at text not null
        );

        create table if not exists classifications (
            transaction_id integer primary key references transactions(id),
            category text,
            expense_type text not null,
            split_ratio numeric not null default 1.0,
            my_share numeric not null default 0,
            status text not null,
            confidence numeric not null default 0,
            rule_id integer references merchant_rules(id),
            notes text,
            updated_at text not null
        );

        create table if not exists merchant_rules (
            id integer primary key autoincrement,
            merchant_key text not null unique,
            merchant_display text not null,
            category text not null,
            expense_type text not null,
            split_ratio numeric not null default 1.0,
            confidence numeric not null default 1.0,
            match_count integer not null default 0,
            user_confirmed integer not null default 1,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists feedback_events (
            id integer primary key autoincrement,
            transaction_id integer not null references transactions(id),
            merchant_key text not null,
            category text not null,
            expense_type text not null,
            split_ratio numeric not null,
            notes text,
            created_at text not null
        );

        create index if not exists idx_classifications_status on classifications(status);
        create index if not exists idx_transactions_txn_date on transactions(txn_date);

        create table if not exists transaction_links (
            id integer primary key autoincrement,
            debit_id integer not null references transactions(id) on delete cascade,
            credit_id integer not null references transactions(id) on delete cascade,
            amount numeric not null,
            created_at text not null,
            unique(debit_id, credit_id)
        );

        create table if not exists contacts (
            id integer primary key autoincrement,
            name text not null unique,
            aliases_json text not null default '[]',
            notes text,
            created_at text not null
        );

        create table if not exists ledger_entries (
            id integer primary key autoincrement,
            contact_id integer not null references contacts(id) on delete cascade,
            transaction_id integer references transactions(id) on delete set null,
            direction text,
            entry_type text,
            amount numeric not null,
            purpose text not null default 'other',
            is_passthrough integer default 0,
            passthrough_pair_id integer references ledger_entries(id),
            is_opening_balance integer default 0,
            notes text,
            entry_date text not null,
            created_by text not null default 'user',
            created_at text not null
        );

        create index if not exists idx_ledger_contact on ledger_entries(contact_id);
        create index if not exists idx_ledger_transaction on ledger_entries(transaction_id);
        """
    )
    conn.commit()

    # Column migrations for multi-user & ledger support
    _safe_add_column(conn, "transactions", "uploaded_by", "TEXT")
    _safe_add_column(conn, "transactions", "source_txn_id", "INTEGER")
    _safe_add_column(conn, "classifications", "shared_with", "TEXT")
    _safe_add_column(conn, "contacts", "aliases_json", "TEXT DEFAULT '[]'")
    _safe_add_column(conn, "contacts", "notes", "TEXT")

    migrate_ledger_schema(conn)
    migrate_settlement_schema(conn)
    conn.commit()

    seed_default_contacts(conn)

    swept = apply_learned_rules_to_pending(conn)
    if swept:
        conn.commit()
        logger.info("Applied learned rules to %d pending row(s) on startup.", swept)


def migrate_settlement_schema(conn: sqlite3.Connection) -> None:
    """Additive columns for unified settlement (USB) model."""
    if not _table_exists(conn, "contacts"):
        return

    _safe_add_column(conn, "contacts", "merged_into_id", "INTEGER")
    _safe_add_column(conn, "contacts", "merge_batch_id", "TEXT")
    _safe_add_column(conn, "contacts", "linked_username", "TEXT")

    if _table_exists(conn, "ledger_entries"):
        _safe_add_column(conn, "ledger_entries", "source", "TEXT")
        _safe_add_column(conn, "ledger_entries", "voided_at", "TEXT")
        _safe_add_column(conn, "ledger_entries", "void_reason", "TEXT")
        # Backfill source from created_by
        try:
            conn.execute(
                """
                UPDATE ledger_entries
                SET source = CASE
                    WHEN created_by = 'auto' THEN 'auto_migrate'
                    WHEN purpose = 'settlement' THEN 'settlement'
                    WHEN coalesce(is_passthrough, 0) = 1 THEN 'auto_passthrough'
                    ELSE 'user'
                END
                WHERE source IS NULL OR source = ''
                """
            )
        except Exception as exc:
            logger.debug("source backfill skipped: %s", exc)

    if _table_exists(conn, "classifications"):
        _safe_add_column(conn, "classifications", "shared_with", "TEXT")
        _safe_add_column(conn, "classifications", "shared_with_contact_id", "INTEGER")
        # Backfill shared_with_contact_id where text resolvable
        try:
            from .settlement import resolve_contact

            rows = conn.execute(
                """
                SELECT transaction_id, shared_with FROM classifications
                WHERE shared_with IS NOT NULL AND shared_with != ''
                  AND (shared_with_contact_id IS NULL)
                """
            ).fetchall()
            for r in rows:
                match = resolve_contact(conn, r["shared_with"])
                if match:
                    conn.execute(
                        "UPDATE classifications SET shared_with_contact_id = ? WHERE transaction_id = ?",
                        (match["canonical_id"], r["transaction_id"]),
                    )
        except Exception as exc:
            logger.debug("shared_with_contact_id backfill skipped: %s", exc)

    # Indexes (non-unique lookup + partial unique for auto_shared when possible)
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ledger_contact_txn "
            "ON ledger_entries(contact_id, transaction_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contacts_merged "
            "ON contacts(merged_into_id)"
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_auto_shared
            ON ledger_entries(contact_id, transaction_id)
            WHERE source = 'auto_shared' AND (voided_at IS NULL OR voided_at = '')
            """
        )
    except Exception as exc:
        logger.debug("Settlement index creation skipped: %s", exc)


def _safe_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    if not _table_exists(conn, table):
        return
    try:
        existing = _table_columns(conn, table)
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            logger.info("Added column %s.%s", table, column)
    except Exception as exc:
        logger.warning("Column migration skipped for %s.%s: %s", table, column, exc)


def seed_default_contacts(conn: sqlite3.Connection) -> None:
    from .contacts import create_contact, find_contact_by_text
    defaults = [
        ("Highnes", ["highnes", "highnes.7@sibl", "8078866770", "highnesj sibl", "dr highnes sibl"]),
        ("Ranjima", ["ranjima", "9497760612"]),
        ("Ananthu", ["ananthu", "anand"]),
        ("Bipin", ["bipin"]),
        ("Anupriya", ["anupriya"]),
    ]
    for name, aliases in defaults:
        try:
            if not find_contact_by_text(conn, name):
                create_contact(conn, name, aliases)
        except Exception:
            pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transaction_hash(row: dict) -> str:
    """Produce a dedup key for a transaction.

    Normalizes the description (lowercase, alphanumeric characters only) and
    money amounts to prevent duplicates due to slight spacing, wrapping, or
    decimal representation differences across different PDF statement layouts.
    """
    desc_clean = re.sub(r"[^a-z0-9]+", "", str(row.get("description") or "").lower())
    try:
        debit_dec = Decimal(str(row.get("debit") or "0"))
        debit_str = f"{debit_dec:.2f}"
    except Exception:
        debit_str = "0.00"
    try:
        credit_dec = Decimal(str(row.get("credit") or "0"))
        credit_str = f"{credit_dec:.2f}"
    except Exception:
        credit_str = "0.00"

    payload = "|".join([
        str(row.get("txn_date", "") or ""),
        desc_clean,
        debit_str,
        credit_str,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_transactions(
    conn: sqlite3.Connection,
    source_filename: str,
    sha256: str,
    rows: list[dict],
    password_used: bool,
    uploaded_by: str | None = None,
) -> tuple[int, int, int]:
    existing = conn.execute("select id from imports where file_sha256 = ?", (sha256,)).fetchone()
    if existing:
        return existing["id"], 0, len(rows)

    now = utc_now()
    cur = conn.execute(
        """
        insert into imports (source_filename, file_sha256, imported_at, password_used)
        values (?, ?, ?, ?)
        """,
        (source_filename, sha256, now, int(password_used)),
    )
    import_id = int(cur.lastrowid)
    inserted = 0
    skipped = 0

    for row in rows:
        merchant_key = normalize_merchant(row["description"])
        merchant_display = display_merchant(row["description"])
        source_hash = transaction_hash(row)
        amount_signed = Decimal(str(row.get("credit") or "0")) - Decimal(str(row.get("debit") or "0"))
        try:
            txn_cur = conn.execute(
                """
                insert into transactions (
                    import_id, source_hash, txn_date, value_date, description, reference,
                    debit, credit, amount_signed, balance, raw_text, merchant_key,
                    merchant_display, created_at, uploaded_by
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    source_hash,
                    row["txn_date"],
                    row.get("value_date"),
                    row["description"],
                    row.get("reference"),
                    str(row.get("debit") or "0"),
                    str(row.get("credit") or "0"),
                    str(amount_signed),
                    str(row.get("balance")) if row.get("balance") is not None else None,
                    row.get("raw_text") or row["description"],
                    merchant_key,
                    merchant_display,
                    now,
                    uploaded_by,
                ),
            )
        except sqlite3.IntegrityError:
            skipped += 1
            continue

        classification = classify_transaction(conn, merchant_key)
        my_share = effective_share(
            amount_signed,
            classification.expense_type,
            classification.split_ratio,
        )
        conn.execute(
            """
            insert into classifications (
                transaction_id, category, expense_type, split_ratio, my_share,
                status, confidence, rule_id, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(txn_cur.lastrowid),
                classification.category,
                classification.expense_type,
                str(classification.split_ratio),
                str(my_share),
                classification.status,
                str(classification.confidence),
                classification.rule_id,
                now,
            ),
        )
        inserted += 1

    conn.execute(
        "update imports set transaction_count = ? where id = ?",
        (inserted, import_id),
    )
    conn.commit()
    logger.info(
        "Imported %s: %d inserted, %d skipped, %d parsed.",
        source_filename, inserted, skipped, len(rows),
    )
    return import_id, inserted, len(rows)


def add_manual_transaction(
    conn: sqlite3.Connection,
    txn_date: str,
    description: str,
    amount: Decimal,
    direction: str,
    category: str,
    expense_type: str,
    split_ratio: Decimal = DEFAULT_SPLIT_RATIO,
    notes: str | None = None,
    learn: bool = False,
    uploaded_by: str | None = None,
) -> int:
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    if direction not in {"debit", "credit"}:
        raise ValueError("Choose debit or credit.")

    now = utc_now()
    manual_id = uuid.uuid4().hex
    debit = amount if direction == "debit" else Decimal("0")
    credit = amount if direction == "credit" else Decimal("0")
    amount_signed = credit - debit
    merchant_key = normalize_merchant(description)
    merchant_display = display_merchant(description, fallback="Manual")

    cur = conn.execute(
        """
        insert into imports (source_filename, file_sha256, imported_at, password_used, transaction_count)
        values (?, ?, ?, 0, 1)
        """,
        ("manual-entry", f"manual:{manual_id}", now),
    )
    import_id = int(cur.lastrowid)
    txn_cur = conn.execute(
        """
        insert into transactions (
            import_id, source_hash, txn_date, value_date, description, reference,
            debit, credit, amount_signed, balance, raw_text, merchant_key,
            merchant_display, created_at, uploaded_by
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            import_id,
            f"manual:{manual_id}",
            txn_date,
            txn_date,
            description,
            f"manual-{manual_id[:12]}",
            str(debit),
            str(credit),
            str(amount_signed),
            None,
            f"Manual transaction: {description}",
            merchant_key,
            merchant_display,
            now,
            uploaded_by,
        ),
    )
    transaction_id = int(txn_cur.lastrowid)

    # Insert classification directly in final state instead of
    # creating a placeholder then immediately overwriting it.
    my_share = effective_share(amount_signed, expense_type, split_ratio)
    rule_id = None
    if learn:
        rule_id = _save_merchant_rule(conn, merchant_key, merchant_display, category, expense_type, split_ratio, now)
    conn.execute(
        """
        insert into classifications (
            transaction_id, category, expense_type, split_ratio, my_share,
            status, confidence, rule_id, notes, updated_at
        )
        values (?, ?, ?, ?, ?, 'reviewed', 1.0, ?, ?, ?)
        """,
        (transaction_id, category, expense_type, str(split_ratio), str(my_share), rule_id, notes, now),
    )
    conn.execute(
        """
        insert into feedback_events (
            transaction_id, merchant_key, category, expense_type,
            split_ratio, notes, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (transaction_id, merchant_key, category, expense_type, str(split_ratio), notes, now),
    )
    if rule_id is not None:
        apply_learned_rule_to_pending(conn, rule_id, now)
    conn.commit()
    logger.info("Manual transaction added: %s %s %s.", direction, amount, description)
    return transaction_id


def _save_merchant_rule(
    conn: sqlite3.Connection,
    merchant_key: str,
    merchant_display: str,
    category: str,
    expense_type: str,
    split_ratio: Decimal,
    now: str,
) -> int:
    """Create or update a merchant rule. Returns the rule ID."""
    existing = conn.execute(
        "select id, match_count from merchant_rules where merchant_key = ?",
        (merchant_key,),
    ).fetchone()
    if existing:
        rule_id = existing["id"]
        conn.execute(
            """
            update merchant_rules
            set merchant_display = ?, category = ?, expense_type = ?, split_ratio = ?,
                confidence = 1.0, match_count = match_count + 1,
                user_confirmed = 1, updated_at = ?
            where id = ?
            """,
            (merchant_display, category, expense_type, str(split_ratio), now, rule_id),
        )
    else:
        cur = conn.execute(
            """
            insert into merchant_rules (
                merchant_key, merchant_display, category, expense_type,
                split_ratio, confidence, match_count, user_confirmed,
                created_at, updated_at
            )
            values (?, ?, ?, ?, ?, 1.0, 1, 1, ?, ?)
            """,
            (merchant_key, merchant_display, category, expense_type, str(split_ratio), now, now),
        )
        rule_id = int(cur.lastrowid)
    logger.info("Merchant rule saved: %s -> %s/%s (rule_id=%d).", merchant_key, category, expense_type, rule_id)
    return rule_id


def review_transaction(
    conn: sqlite3.Connection,
    transaction_id: int,
    category: str,
    expense_type: str,
    split_ratio: Decimal = DEFAULT_SPLIT_RATIO,
    notes: str | None = None,
    learn: bool = False,
    shared_with: str | None = None,
    shared_with_contact_id: int | None = None,
) -> None:
    tx = conn.execute(
        "select merchant_key, merchant_display, amount_signed from transactions where id = ?",
        (transaction_id,),
    ).fetchone()
    if not tx:
        raise ValueError(f"Unknown transaction id: {transaction_id}")

    now = utc_now()
    rule_id = None
    if learn:
        rule_id = _save_merchant_rule(
            conn, tx["merchant_key"], tx["merchant_display"],
            category, expense_type, split_ratio, now,
        )

    # Resolve partner contact when text provided
    sw_text = (shared_with or "").strip() or None
    sw_cid = shared_with_contact_id
    if sw_text and sw_cid is None:
        try:
            from .settlement import resolve_contact

            match = resolve_contact(conn, sw_text)
            if match:
                sw_cid = int(match["canonical_id"])
        except Exception:
            pass
    if sw_text or sw_cid:
        expense_type = "Shared"

    amount = Decimal(str(tx["amount_signed"]))
    my_share = effective_share(amount, expense_type, split_ratio)

    cols = _table_columns(conn, "classifications")
    set_parts = [
        "category = ?",
        "expense_type = ?",
        "split_ratio = ?",
        "my_share = ?",
        "status = 'reviewed'",
        "confidence = 1.0",
        "rule_id = ?",
        "notes = ?",
        "updated_at = ?",
    ]
    values: list = [
        category,
        expense_type,
        str(split_ratio),
        str(my_share),
        rule_id,
        notes,
        now,
    ]
    if "shared_with" in cols:
        set_parts.append("shared_with = ?")
        values.append(sw_text)
    if "shared_with_contact_id" in cols:
        set_parts.append("shared_with_contact_id = ?")
        values.append(sw_cid)
    values.append(transaction_id)
    conn.execute(
        f"UPDATE classifications SET {', '.join(set_parts)} WHERE transaction_id = ?",
        tuple(values),
    )
    conn.execute(
        """
        insert into feedback_events (
            transaction_id, merchant_key, category, expense_type,
            split_ratio, notes, created_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transaction_id,
            tx["merchant_key"],
            category,
            expense_type,
            str(split_ratio),
            notes,
            now,
        ),
    )
    if rule_id is not None:
        apply_learned_rule_to_pending(conn, rule_id, now)
    conn.commit()


def apply_learned_rule_to_pending(conn: sqlite3.Connection, rule_id: int, now: str | None = None) -> int:
    return apply_learned_rules_to_pending(conn, rule_id=rule_id, now=now)


def apply_learned_rules_to_pending(
    conn: sqlite3.Connection,
    rule_id: int | None = None,
    now: str | None = None,
) -> int:
    now = now or utc_now()
    pending = conn.execute(
        """
        select t.id, t.merchant_key, t.amount_signed
        from transactions t
        join classifications c on c.transaction_id = t.id
        where c.status = 'needs_review'
        """
    ).fetchall()
    updated = 0
    for row in pending:
        classification = classify_transaction(conn, row["merchant_key"])
        if classification.rule_id is None:
            continue
        if rule_id is not None and classification.rule_id != rule_id:
            continue
        amount = Decimal(str(row["amount_signed"]))
        my_share = effective_share(amount, classification.expense_type, classification.split_ratio)
        conn.execute(
            """
            update classifications
            set category = ?, expense_type = ?, split_ratio = ?, my_share = ?,
                status = 'auto', confidence = ?, rule_id = ?, updated_at = ?
            where transaction_id = ?
            """,
            (
                classification.category,
                classification.expense_type,
                str(classification.split_ratio),
                str(my_share),
                str(classification.confidence),
                classification.rule_id,
                now,
                row["id"],
            ),
        )
        updated += 1
    return updated


def dashboard_data(conn: sqlite3.Connection) -> dict:
    """Fetch all joined transaction data for the dashboard.

    Aggregation and period filtering is handled by the caller (services/templates)
    to avoid computing values that are immediately discarded and recomputed.
    """
    rows = conn.execute(
        """
        select t.*, c.category, c.expense_type, c.split_ratio, c.my_share,
               c.status, c.confidence, c.notes, c.rule_id, c.shared_with,
               c.shared_with_contact_id,
               coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0) as debit_offset,
               coalesce((select sum(amount) from transaction_links where credit_id = t.id), 0) as credit_offset
        from transactions t
        join classifications c on c.transaction_id = t.id
        order by t.txn_date desc, t.id desc
        """
    ).fetchall()

    pending = [r for r in rows if r["status"] == "needs_review"]

    by_merchant: dict[str, Decimal] = {}
    shared: list[sqlite3.Row] = []
    for row in rows:
        debit = Decimal(str(row["debit"] or 0))
        if debit <= 0:
            continue
        by_merchant[row["merchant_display"]] = by_merchant.get(row["merchant_display"], Decimal("0")) + debit
        if row["expense_type"] == "Shared":
            shared.append(row)

    rules = conn.execute(
        "select * from merchant_rules order by updated_at desc, merchant_display"
    ).fetchall()
    from .connections import get_connection_suggestions
    from .contacts import get_all_contacts, calculate_contact_balance, detect_passthrough_candidates
    from .settlement import suggest_merge_groups
    contacts = get_all_contacts(conn)
    contacts_with_balances = []
    for c in contacts:
        if c.get("merged_into_id"):
            continue
        bal = calculate_contact_balance(conn, c["id"])
        contacts_with_balances.append({
            "contact": c,
            "balance": bal,
        })
    passthrough_candidates = detect_passthrough_candidates(conn)
    try:
        merge_suggestions = suggest_merge_groups(conn)
    except Exception:
        logger.exception("merge suggestions failed")
        merge_suggestions = []
    try:
        from .settlement import suggest_loan_posts
        loan_suggestions = suggest_loan_posts(conn)
    except Exception:
        logger.exception("loan suggestions failed")
        loan_suggestions = []

    return {
        "transactions": rows,
        "pending": pending,
        "shared": shared[:15],
        "top_merchants": sorted(by_merchant.items(), key=lambda item: item[1], reverse=True)[:10],
        "rules": rules,
        "suggestions": get_connection_suggestions(conn),
        "links": get_transaction_links(conn),
        "linkable": get_linkable_transactions(conn),
        "contacts": contacts_with_balances,
        "passthrough_candidates": passthrough_candidates,
        "merge_suggestions": merge_suggestions,
        "loan_suggestions": loan_suggestions,
    }


def onboarding_status(conn: sqlite3.Connection) -> dict:
    """Checklist for first-run guidance (P3)."""
    try:
        import_count = conn.execute("SELECT count(*) FROM imports").fetchone()[0]
    except Exception:
        import_count = 0
    try:
        txn_count = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
    except Exception:
        txn_count = 0
    try:
        reviewed = conn.execute(
            "SELECT count(*) FROM classifications WHERE status = 'reviewed'"
        ).fetchone()[0]
    except Exception:
        reviewed = 0
    try:
        contact_count = conn.execute("SELECT count(*) FROM contacts").fetchone()[0]
    except Exception:
        contact_count = 0
    try:
        ledger_count = conn.execute("SELECT count(*) FROM ledger_entries").fetchone()[0]
    except Exception:
        ledger_count = 0
    try:
        shared_tagged = conn.execute(
            """
            SELECT count(*) FROM classifications
            WHERE expense_type = 'Shared'
              AND shared_with IS NOT NULL AND shared_with != ''
            """
        ).fetchone()[0]
    except Exception:
        shared_tagged = 0

    steps = [
        {
            "id": "import",
            "label": "Import an SBI statement",
            "hint": "Import tab · PDF + password",
            "done": import_count > 0 or txn_count > 0,
        },
        {
            "id": "review",
            "label": "Classify at least one transaction",
            "hint": "Transactions tab · set category & type",
            "done": reviewed > 0,
        },
        {
            "id": "people",
            "label": "Have contacts for khata",
            "hint": "People tab · add or merge contacts",
            "done": contact_count > 0,
        },
        {
            "id": "ledger",
            "label": "Record a person balance (loan / entry)",
            "hint": "People · + Entry or Suggested loans",
            "done": ledger_count > 0,
        },
        {
            "id": "shared",
            "label": "Tag a shared expense partner (optional)",
            "hint": "Transactions · Type Shared · Shared with",
            "done": shared_tagged > 0,
        },
    ]
    complete = all(s["done"] for s in steps if s["id"] != "shared")
    return {
        "complete": complete,
        "steps": steps,
        "counts": {
            "imports": import_count,
            "transactions": txn_count,
            "reviewed": reviewed,
            "contacts": contact_count,
            "ledger_entries": ledger_count,
            "shared_tagged": shared_tagged,
        },
    }


def export_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        select t.id, t.txn_date, t.value_date, t.description, t.reference,
               t.debit, t.credit, t.amount_signed, t.balance,
               t.merchant_display, c.category, c.expense_type,
               c.split_ratio, c.my_share, c.status, c.confidence, c.notes,
               coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0) as debit_offset,
               coalesce((select sum(amount) from transaction_links where credit_id = t.id), 0) as credit_offset
        from transactions t
        join classifications c on c.transaction_id = t.id
        order by t.txn_date, t.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def write_csv(conn: sqlite3.Connection, path: Path) -> None:
    rows = export_rows(conn)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(conn: sqlite3.Connection, path: Path) -> None:
    path.write_text(json.dumps(export_rows(conn), indent=2), encoding="utf-8")


def add_transaction_link(conn: sqlite3.Connection, debit_id: int, credit_id: int, amount: Decimal) -> int:
    if amount <= 0:
        raise ValueError("Link amount must be greater than zero.")
    # Fetch debit info
    debit_row = conn.execute("select debit from transactions where id = ?", (debit_id,)).fetchone()
    if not debit_row or Decimal(str(debit_row["debit"])) <= 0:
        raise ValueError("Invalid debit transaction.")
    # Fetch credit info
    credit_row = conn.execute("select credit from transactions where id = ?", (credit_id,)).fetchone()
    if not credit_row or Decimal(str(credit_row["credit"])) <= 0:
        raise ValueError("Invalid credit transaction.")
    
    # Calculate remaining debit
    linked_debit = conn.execute(
        "select sum(amount) as s from transaction_links where debit_id = ?", (debit_id,)
    ).fetchone()["s"]
    linked_debit_val = Decimal(str(linked_debit)) if linked_debit is not None else Decimal("0")
    remaining_debit = Decimal(str(debit_row["debit"])) - linked_debit_val
    
    # Calculate remaining credit
    linked_credit = conn.execute(
        "select sum(amount) as s from transaction_links where credit_id = ?", (credit_id,)
    ).fetchone()["s"]
    linked_credit_val = Decimal(str(linked_credit)) if linked_credit is not None else Decimal("0")
    remaining_credit = Decimal(str(credit_row["credit"])) - linked_credit_val
    
    if amount > remaining_debit:
        raise ValueError(f"Amount exceeds remaining debit balance of ₹{remaining_debit:.2f}")
    if amount > remaining_credit:
        raise ValueError(f"Amount exceeds remaining credit balance of ₹{remaining_credit:.2f}")
    
    now = utc_now()
    cur = conn.execute(
        """
        insert into transaction_links (debit_id, credit_id, amount, created_at)
        values (?, ?, ?, ?)
        """,
        (debit_id, credit_id, str(amount), now)
    )
    conn.commit()
    return int(cur.lastrowid)


def remove_transaction_link(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("delete from transaction_links where id = ?", (link_id,))
    conn.commit()


def get_transaction_links(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        select l.id as link_id, l.amount as link_amount, l.created_at as linked_at,
               td.id as debit_id, td.txn_date as debit_date, td.merchant_display as debit_merchant,
               td.description as debit_desc, td.debit as debit_total,
               tc.id as credit_id, tc.txn_date as credit_date, tc.merchant_display as credit_merchant,
               tc.description as credit_desc, tc.credit as credit_total
        from transaction_links l
        join transactions td on l.debit_id = td.id
        join transactions tc on l.credit_id = tc.id
        order by l.created_at desc
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_linkable_transactions(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    # Linkable debits
    debits = conn.execute(
        """
        select t.*,
               (t.debit - coalesce((select sum(amount) from transaction_links where debit_id = t.id), 0)) as remaining
        from transactions t
        where t.debit > 0 and remaining > 0
        order by t.txn_date desc, t.id desc
        """
    ).fetchall()
    # Linkable credits
    credits = conn.execute(
        """
        select t.*,
               (t.credit - coalesce((select sum(amount) from transaction_links where credit_id = t.id), 0)) as remaining
        from transactions t
        where t.credit > 0 and remaining > 0
        order by t.txn_date desc, t.id desc
        """
    ).fetchall()
    return {
        "debits": [dict(d) for d in debits],
        "credits": [dict(c) for c in credits],
    }


def delete_merchant_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    conn.execute("delete from merchant_rules where id = ?", (rule_id,))
    conn.commit()
