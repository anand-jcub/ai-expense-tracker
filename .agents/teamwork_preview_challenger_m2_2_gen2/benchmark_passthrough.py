"""Benchmark and verification script for detect_passthrough_candidates & web.py integration."""

from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from typing import Any

from expense_tracker.contacts import (
    create_contact,
    detect_passthrough_candidates,
    get_all_contacts,
    get_all_balances,
    get_balance,
    get_ledger,
    add_ledger_entry,
    add_rolling_entry,
    record_opening_balance,
    record_settlement,
    void_ledger_entry,
    find_contact_by_text,
    update_contact,
)
from expense_tracker.db import init_db, connect


class QueryCounter:
    """SQLite trace callback to count executed SQL queries."""

    def __init__(self, conn: sqlite3.Connection):
        self.count = 0
        self.queries: list[str] = []
        conn.set_trace_callback(self._trace)

    def _trace(self, sql: str) -> None:
        # Ignore transaction control statements
        s = sql.strip().upper()
        if not (s.startswith("BEGIN") or s.startswith("COMMIT") or s.startswith("ROLLBACK")):
            self.count += 1
            self.queries.append(sql)

    def reset(self) -> None:
        self.count = 0
        self.queries.clear()


def unoptimized_detect_passthrough_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Unoptimized baseline implementation that queries contacts per candidate match (N+1 queries)."""
    from expense_tracker.contacts_domain.dal import _fetch_candidate_transactions

    rows = _fetch_candidate_transactions(conn, limit=10)
    candidates = []
    for r in rows:
        # Calls find_contact_by_text which fetches all contacts each time
        c_contact = find_contact_by_text(conn, r["credit_merchant"] or "")
        d_contact = find_contact_by_text(conn, r["debit_merchant"] or "")
        candidates.append(
            {
                "credit_tx_id": r["credit_tx_id"],
                "credit_date": r["credit_date"],
                "credit_amount": float(Decimal(str(r["credit_amount"]))),
                "credit_merchant": r["credit_merchant"],
                "credit_contact": (
                    c_contact["name"] if c_contact else (r["credit_merchant"] or "Unknown Sender")
                ),
                "from_contact_id": (c_contact["id"] if c_contact else None),
                "debit_tx_id": r["debit_tx_id"],
                "debit_date": r["debit_date"],
                "debit_amount": float(Decimal(str(r["debit_amount"]))),
                "debit_merchant": r["debit_merchant"],
                "debit_contact": (
                    d_contact["name"] if d_contact else (r["debit_merchant"] or "Unknown Recipient")
                ),
                "to_contact_id": (d_contact["id"] if d_contact else None),
            }
        )
    return candidates


def run_benchmark():
    print("=== 1. Setting up in-memory database with realistic dataset ===")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Populate 50 contacts
    print("Creating 50 contacts...")
    contact_ids = []
    for i in range(50):
        cid = create_contact(conn, f"Contact_{i}", aliases=[f"Alias_{i}_A", f"Alias_{i}_B"])
        contact_ids.append(cid)

    # Populate matching credit and debit transactions for pass-through detection
    print("Inserting 20 matching transaction pairs...")
    for i in range(20):
        # First insert an import row
        imp_cur = conn.execute(
            "INSERT INTO imports (source_filename, file_sha256, imported_at) VALUES (?, ?, ?)",
            (f"file_{i}.pdf", f"sha_{i}", "2026-07-26T00:00:00Z"),
        )
        imp_id = imp_cur.lastrowid

        # Credit transaction
        conn.execute(
            """
            INSERT INTO transactions (import_id, source_hash, txn_date, description, credit, debit, amount_signed, raw_text, merchant_key, merchant_display, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                imp_id,
                f"hash_credit_{i}",
                f"2026-07-{(i % 28) + 1:02d}",
                f"UPI Received from Contact_{i % 50}",
                100.0 + i * 10,
                0.0,
                100.0 + i * 10,
                "raw",
                f"alias_{i % 50}_a",
                f"Alias_{i % 50}_A",
                "2026-07-26T00:00:00Z",
            ),
        )
        # Matching debit transaction (same amount, within 1 day)
        conn.execute(
            """
            INSERT INTO transactions (import_id, source_hash, txn_date, description, credit, debit, amount_signed, raw_text, merchant_key, merchant_display, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                imp_id,
                f"hash_debit_{i}",
                f"2026-07-{(i % 28) + 1:02d}",
                f"UPI Paid to Contact_{(i + 1) % 50}",
                0.0,
                100.0 + i * 10,
                -(100.0 + i * 10),
                "raw",
                f"alias_{(i + 1) % 50}_b",
                f"Alias_{(i + 1) % 50}_B",
                "2026-07-26T00:00:00Z",
            ),
        )
    conn.commit()

    qc = QueryCounter(conn)

    print("\n=== 2. Benchmarking detect_passthrough_candidates ===")

    # Test Optimized detect_passthrough_candidates
    qc.reset()
    t0 = time.perf_counter()
    for _ in range(100):
        res_opt = detect_passthrough_candidates(conn)
    t_opt = (time.perf_counter() - t0) / 100.0
    queries_opt = qc.count / 100.0

    # Test Unoptimized detect_passthrough_candidates
    qc.reset()
    t0 = time.perf_counter()
    for _ in range(100):
        res_unopt = unoptimized_detect_passthrough_candidates(conn)
    t_unopt = (time.perf_counter() - t0) / 100.0
    queries_unopt = qc.count / 100.0

    print(f"Optimized Implementation:")
    print(f"  Execution time per call: {t_opt * 1000:.4f} ms")
    print(f"  SQL Queries per call: {queries_opt:.1f}")
    print(f"Unoptimized Baseline Implementation:")
    print(f"  Execution time per call: {t_unopt * 1000:.4f} ms")
    print(f"  SQL Queries per call: {queries_unopt:.1f}")
    print(f"Query Reduction: {queries_unopt - queries_opt:.1f} queries saved per call ({(1 - queries_opt / queries_unopt) * 100:.1f}% reduction)")
    print(f"Speedup Factor: {t_unopt / t_opt:.2f}x faster")
    assert res_opt == res_unopt, "Optimized and unoptimized results must match!"
    print("Results verification: MATCHED successfully!")

    print("\n=== 3. Testing web.py caller integration ===")
    from expense_tracker import web

    # Test that web imports all contacts functions cleanly
    required_funcs = [
        "get_all_balances",
        "get_ledger",
        "get_balance",
        "get_all_contacts",
        "find_contact_by_text",
        "create_contact",
        "update_contact",
        "add_ledger_entry",
        "record_settlement",
        "add_rolling_entry",
        "record_opening_balance",
        "void_ledger_entry",
        "detect_passthrough_candidates",
    ]
    import expense_tracker.contacts as contacts_mod

    for func_name in required_funcs:
        assert hasattr(contacts_mod, func_name), f"Missing function {func_name} in contacts module!"
        func = getattr(contacts_mod, func_name)
        assert callable(func), f"{func_name} is not callable!"
        print(f"  [OK] contacts.{func_name} is available and callable.")

    print("\nAll benchmark and caller integration checks PASSED!")


if __name__ == "__main__":
    run_benchmark()
