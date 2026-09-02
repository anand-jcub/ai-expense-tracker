"""Verification and benchmark script for refactored expense_tracker.contacts module.

Executed by Challenger 2 for Milestone 2.
"""

from __future__ import annotations

import os
import sys
import time
import sqlite3
from decimal import Decimal
from typing import Any, List, Dict

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from expense_tracker.db import init_db
from expense_tracker import contacts
from expense_tracker.contacts_domain import services, dal, calculators


def test_web_py_imported_callers() -> Dict[str, Any]:
    """Tests all functions in contacts.py imported by web.py."""
    print("=== Testing web.py caller functions in contacts.py ===")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    
    results = {}

    # 1. create_contact (used in handle_contact_create)
    cid_alice = contacts.create_contact(conn, name="Alice Smith", aliases="alice, asmith", notes="Friend")
    cid_bob = contacts.create_contact(conn, name="Bob Jones", aliases="bob, bjones", notes="Colleague")
    assert cid_alice > 0 and cid_bob > 0
    results["create_contact"] = "PASS"

    # 2. update_contact (used in handle_contact_edit)
    contacts.update_contact(conn, contact_id=cid_alice, name="Alice S. Smith", aliases=["alice", "asmith", "alice_s"], notes="Updated notes")
    results["update_contact"] = "PASS"

    # 3. get_all_contacts (used in handle_api_settlement, etc.)
    all_contacts = contacts.get_all_contacts(conn)
    assert len(all_contacts) >= 2
    results["get_all_contacts"] = "PASS"

    # 4. find_contact_by_text (used in handle_api_settlement_by_name)
    match = contacts.find_contact_by_text(conn, "alice")
    assert match is not None and match["id"] == cid_alice
    results["find_contact_by_text"] = "PASS"

    # 5. add_ledger_entry (used in handle_ledger_add, handle_passthrough_confirm)
    entry_1 = contacts.add_ledger_entry(
        conn,
        contact_id=cid_alice,
        direction="you_sent",
        amount=Decimal("1500.00"),
        purpose="loan",
        notes="Dinner expense",
        entry_date="2026-07-20",
    )
    assert entry_1 > 0
    results["add_ledger_entry"] = "PASS"

    # 6. get_balance (used in handle_api_settlement, handle_api_settlement_by_name)
    bal_alice = contacts.get_balance(conn, cid_alice)
    assert bal_alice["net"] == 1500.0
    results["get_balance"] = "PASS"

    # 7. get_ledger (used in handle_api_contact_ledger)
    ledger_alice = contacts.get_ledger(conn, cid_alice)
    assert len(ledger_alice["entries"]) == 1
    results["get_ledger"] = "PASS"

    # 8. get_all_balances (used in handle_api_settlement_summary)
    all_bals = contacts.get_all_balances(conn)
    assert len(all_bals) >= 2
    results["get_all_balances"] = "PASS"

    # 9. record_settlement (used in handle_ledger_settle)
    settle_res = contacts.record_settlement(conn, contact_id=cid_alice, amount=Decimal("1000.00"))
    assert settle_res["net"] == 500.0
    results["record_settlement"] = "PASS"

    # 10. add_rolling_entry (used in handle_ledger_rolling)
    rolling_res = contacts.add_rolling_entry(
        conn,
        from_contact_id=cid_alice,
        to_contact_id=cid_bob,
        amount=Decimal("300.00"),
        entry_date="2026-07-21",
        notes="Rolling test",
    )
    assert rolling_res["amount"] == 300.0
    results["add_rolling_entry"] = "PASS"

    # 11. record_opening_balance (used in handle_ledger_opening)
    open_res = contacts.record_opening_balance(
        conn,
        contact_id=cid_bob,
        amount=Decimal("200.00"),
        they_owe_you=True,
        entry_date="2026-07-01",
    )
    assert open_res["amount"] == 200.0
    results["record_opening_balance"] = "PASS"

    # 12. void_ledger_entry (used in handle_ledger_void)
    contacts.void_ledger_entry(conn, entry_id=entry_1)
    bal_after_void = contacts.get_balance(conn, cid_alice)
    assert bal_after_void["net"] == -1000.0  # since 1500 loan was voided, leaving -1000 settlement
    results["void_ledger_entry"] = "PASS"

    # 13. detect_passthrough_candidates (used in db.py / web.py)
    candidates = contacts.detect_passthrough_candidates(conn)
    assert isinstance(candidates, list)
    results["detect_passthrough_candidates"] = "PASS"

    conn.close()
    return results


def unoptimized_detect_passthrough_candidates(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Simulates the N+1 unoptimized detect_passthrough_candidates (calling find_contact_by_text per row)."""
    rows = dal._fetch_candidate_transactions(conn, limit=10)
    candidates = []
    for r in rows:
        # Before optimization: query database for contacts twice per row
        c_contact = contacts.find_contact_by_text(conn, r["credit_merchant"] or "")
        d_contact = contacts.find_contact_by_text(conn, r["debit_merchant"] or "")
        candidates.append(
            {
                "credit_tx_id": r["credit_tx_id"],
                "credit_date": r["credit_date"],
                "credit_amount": float(calculators._d(r["credit_amount"])),
                "credit_merchant": r["credit_merchant"],
                "credit_contact": (
                    c_contact["name"] if c_contact else (r["credit_merchant"] or "Unknown Sender")
                ),
                "from_contact_id": (c_contact["id"] if c_contact else None),
                "debit_tx_id": r["debit_tx_id"],
                "debit_date": r["debit_date"],
                "debit_amount": float(calculators._d(r["debit_amount"])),
                "debit_merchant": r["debit_merchant"],
                "debit_contact": (
                    d_contact["name"] if d_contact else (r["debit_merchant"] or "Unknown Recipient")
                ),
                "to_contact_id": (d_contact["id"] if d_contact else None),
            }
        )
    return candidates


def benchmark_detect_passthrough() -> Dict[str, Any]:
    """Benchmarks detect_passthrough_candidates query count and execution time: before vs after pre-fetching."""
    print("\n=== Benchmarking detect_passthrough_candidates (Before vs After Pre-fetching) ===")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Populate 50 contacts
    for i in range(50):
        contacts.create_contact(conn, f"Contact_{i}", aliases=f"alias_{i}, c_{i}")

    # Create an import record first for foreign key compliance if needed
    cur = conn.execute("INSERT INTO imports (source_filename, file_sha256, imported_at) VALUES ('test.pdf', 'hash123', '2026-07-25T00:00:00')")
    imp_id = cur.lastrowid

    # Create transactions table entries to trigger candidates
    # Add pairs of credit (income) and debit (expense) transactions with same amount & date
    now_date = "2026-07-25"
    for i in range(10):
        conn.execute(
            """
            INSERT INTO transactions (
                import_id, source_hash, txn_date, description, debit, credit, amount_signed,
                raw_text, merchant_key, merchant_display, created_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                imp_id, f"hash_c_{i}", now_date, f"Credit from Contact_{i}", 1000.0 + i, 1000.0 + i,
                f"raw credit {i}", f"contact_{i}", f"Contact_{i}", "2026-07-25T00:00:00"
            )
        )
        conn.execute(
            """
            INSERT INTO transactions (
                import_id, source_hash, txn_date, description, debit, credit, amount_signed,
                raw_text, merchant_key, merchant_display, created_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                imp_id, f"hash_d_{i}", now_date, f"Debit to Contact_{(i+1)%50}", 1000.0 + i, -(1000.0 + i),
                f"raw debit {i}", f"contact_{(i+1)%50}", f"Contact_{(i+1)%50}", "2026-07-25T00:00:00"
            )
        )
    conn.commit()

    # Trace queries for unoptimized (Before)
    query_log_before: list[str] = []
    conn.set_trace_callback(lambda q: query_log_before.append(q))
    start_time = time.perf_counter()
    iterations = 200
    for _ in range(iterations):
        res_before = unoptimized_detect_passthrough_candidates(conn)
    elapsed_before = time.perf_counter() - start_time
    conn.set_trace_callback(None)

    queries_per_call_before = len(query_log_before) // iterations

    # Trace queries for optimized (After)
    query_log_after: list[str] = []
    conn.set_trace_callback(lambda q: query_log_after.append(q))
    start_time = time.perf_counter()
    for _ in range(iterations):
        res_after = contacts.detect_passthrough_candidates(conn)
    elapsed_after = time.perf_counter() - start_time
    conn.set_trace_callback(None)

    queries_per_call_after = len(query_log_after) // iterations

    query_reduction_pct = ((queries_per_call_before - queries_per_call_after) / queries_per_call_before) * 100
    speedup = elapsed_before / elapsed_after if elapsed_after > 0 else float("inf")

    benchmark_stats = {
        "candidate_rows_returned": len(res_after),
        "before_prefetch_queries_per_call": queries_per_call_before,
        "after_prefetch_queries_per_call": queries_per_call_after,
        "query_reduction_pct": round(query_reduction_pct, 2),
        "before_prefetch_time_ms": round(elapsed_before * 1000 / iterations, 4),
        "after_prefetch_time_ms": round(elapsed_after * 1000 / iterations, 4),
        "speedup_factor": round(speedup, 2),
    }

    conn.close()
    return benchmark_stats


if __name__ == "__main__":
    caller_results = test_web_py_imported_callers()
    for fn, status in caller_results.items():
        print(f"  {fn}: {status}")

    bench_results = benchmark_detect_passthrough()
    print("\nBenchmark Results:")
    for k, v in bench_results.items():
        print(f"  {k}: {v}")
