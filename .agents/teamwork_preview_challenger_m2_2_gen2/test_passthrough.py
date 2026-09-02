import sqlite3
import sys
import os
import time
import json
from decimal import Decimal

# Add root directory to sys.path
sys.path.insert(0, r"c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai")

import expense_tracker.db as db
import expense_tracker.contacts as contacts
import expense_tracker.contacts_domain.services as services
import expense_tracker.contacts_domain.dal as dal
import expense_tracker.contacts_domain.calculators as calculators

def setup_inmemory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Initialize schema
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            is_active INTEGER NOT NULL DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            txn_date TEXT NOT NULL,
            credit REAL DEFAULT 0,
            debit REAL DEFAULT 0,
            merchant_display TEXT,
            category TEXT,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS ledger_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            entry_type TEXT NOT NULL,
            amount REAL NOT NULL,
            entry_date TEXT NOT NULL,
            description TEXT,
            transaction_id INTEGER,
            is_passthrough INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (contact_id) REFERENCES contacts(id)
        );
    """)
    return conn

class QueryCounter:
    def __init__(self, conn):
        self.conn = conn
        self.count = 0
        self.queries = []

    def __enter__(self):
        self.conn.set_trace_callback(self.trace_fn)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.set_trace_callback(None)

    def trace_fn(self, statement):
        self.count += 1
        self.queries.append(statement)


def unoptimized_detect_passthrough_candidates(conn: sqlite3.Connection):
    """Legacy/Unoptimized implementation that calls find_contact_by_text per candidate transaction row (N+1 queries)."""
    rows = conn.execute(
        """
        SELECT
            c_tx.id AS credit_tx_id, c_tx.txn_date AS credit_date,
            c_tx.credit AS credit_amount, c_tx.merchant_display AS credit_merchant,
            d_tx.id AS debit_tx_id, d_tx.txn_date AS debit_date,
            d_tx.debit AS debit_amount, d_tx.merchant_display AS debit_merchant
        FROM transactions c_tx
        JOIN transactions d_tx
          ON c_tx.credit = d_tx.debit AND c_tx.credit > 0
        WHERE c_tx.id != d_tx.id
          AND abs(julianday(d_tx.txn_date) - julianday(c_tx.txn_date)) <= 2
          AND c_tx.id NOT IN (
              SELECT transaction_id FROM ledger_entries
              WHERE transaction_id IS NOT NULL AND is_passthrough = 1
          )
          AND d_tx.id NOT IN (
              SELECT transaction_id FROM ledger_entries
              WHERE transaction_id IS NOT NULL AND is_passthrough = 1
          )
        ORDER BY c_tx.txn_date DESC
        LIMIT 10
        """
    ).fetchall()

    candidates = []
    for r in rows:
        # Calls find_contact_by_text twice per row -> causes N+1 queries to DB!
        c_contact = contacts.find_contact_by_text(conn, r["credit_merchant"] or "")
        d_contact = contacts.find_contact_by_text(conn, r["debit_merchant"] or "")
        candidates.append(
            {
                "credit_tx_id": r["credit_tx_id"],
                "credit_date": r["credit_date"],
                "credit_amount": float(r["credit_amount"]),
                "credit_merchant": r["credit_merchant"],
                "credit_contact": (
                    c_contact["name"] if c_contact else (r["credit_merchant"] or "Unknown Sender")
                ),
                "from_contact_id": (c_contact["id"] if c_contact else None),
                "debit_tx_id": r["debit_tx_id"],
                "debit_date": r["debit_date"],
                "debit_amount": float(r["debit_amount"]),
                "debit_merchant": r["debit_merchant"],
                "debit_contact": (
                    d_contact["name"] if d_contact else (r["debit_merchant"] or "Unknown Recipient")
                ),
                "to_contact_id": (d_contact["id"] if d_contact else None),
            }
        )
    return candidates


def test_n_plus_one_query_optimization():
    print("\n--- Test 1: N+1 Query Optimization & Trace Verification ---")
    conn = setup_inmemory_db()

    # Insert 100 active contacts
    for i in range(100):
        conn.execute(
            "INSERT INTO contacts (name, aliases_json) VALUES (?, ?)",
            (f"Contact_{i}", json.dumps([f"Alias_{i}"]))
        )

    # Insert 200 transaction pairs
    for i in range(200):
        conn.execute(
            "INSERT INTO transactions (txn_date, credit, debit, merchant_display) VALUES (?, ?, 0, ?)",
            ("2026-07-01 10:00:00", 100.0 + i, f"Payment from Alias_{i % 100}")
        )
        conn.execute(
            "INSERT INTO transactions (txn_date, credit, debit, merchant_display) VALUES (?, 0, ?, ?)",
            ("2026-07-01 12:00:00", 100.0 + i, f"Transfer to Contact_{(i + 1) % 100}")
        )
    conn.commit()

    # Benchmark Optimized
    with QueryCounter(conn) as qc_opt:
        t0 = time.perf_counter()
        cand_opt = contacts.detect_passthrough_candidates(conn)
        t_opt = time.perf_counter() - t0

    # Benchmark Unoptimized
    with QueryCounter(conn) as qc_unopt:
        t0 = time.perf_counter()
        cand_unopt = unoptimized_detect_passthrough_candidates(conn)
        t_unopt = time.perf_counter() - t0

    print(f"Optimized Query Count:   {qc_opt.count} queries in {t_opt*1000:.3f} ms")
    print(f"Unoptimized Query Count: {qc_unopt.count} queries in {t_unopt*1000:.3f} ms")

    print("\nSQL statements executed by Optimized detect_passthrough_candidates:")
    for q in qc_opt.queries:
        print(f" -> {q.strip()}")

    # Verify query count reduction
    assert qc_opt.count == 3, f"Expected 3 queries for optimized implementation, got {qc_opt.count}"
    assert qc_unopt.count >= 20, f"Expected >20 queries for unoptimized implementation, got {qc_unopt.count}"

    # Verify output equality
    assert cand_opt == cand_unopt, "Optimized and unoptimized outputs MUST match exactly"

    print("Test 1 Result: PASS (N+1 query optimization verified: 3 queries vs 21 queries, output identical)")


def test_matching_correctness():
    print("\n--- Test 2: Matching Correctness Across Multiple Contacts and Scenarios ---")
    conn = setup_inmemory_db()

    # Setup Contacts
    conn.execute("INSERT INTO contacts (name, aliases_json) VALUES (?, ?)", ("Alice Johnson", json.dumps(["Alice", "AJ"])))
    conn.execute("INSERT INTO contacts (name, aliases_json) VALUES (?, ?)", ("Bob Smith", json.dumps(["Bobbie", "Robert"])))
    conn.execute("INSERT INTO contacts (name, aliases_json) VALUES (?, ?)", ("Charlie Brown", json.dumps(["Chuck"])))
    conn.commit()

    # 1. Exact Name match + Alias match
    # Tx 1: Credit from Alice (Merchant: "Alice Johnson") -> Tx 2: Debit to Bob (Merchant: "Payment to Bobbie")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (1, '2026-07-10 10:00:00', 250.00, 0, 'Alice Johnson')")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (2, '2026-07-10 11:00:00', 0, 250.00, 'Payment to Bobbie')")

    # 2. Fallback / Unknown merchant matching
    # Tx 3: Credit from Unknown (Merchant: "Zomato Refund") -> Tx 4: Debit to Unknown (Merchant: "Swiggy Pay")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (3, '2026-07-10 12:00:00', 80.00, 0, 'Zomato Refund')")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (4, '2026-07-10 13:00:00', 0, 80.00, 'Swiggy Pay')")

    # 3. None / Null merchant fallback
    # Tx 5: Credit (Merchant: None) -> Tx 6: Debit (Merchant: None)
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (5, '2026-07-10 14:00:00', 99.00, 0, NULL)")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (6, '2026-07-10 15:00:00', 0, 99.00, NULL)")

    # 4. Date window edge case: 2 days (48 hrs) vs >2 days
    # Tx 7 & 8: Exactly 2 days apart (2026-07-10 00:00:00 and 2026-07-12 00:00:00) -> MATCH
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (7, '2026-07-10 00:00:00', 150.00, 0, 'Chuck')")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (8, '2026-07-12 00:00:00', 0, 150.00, 'AJ')")

    # Tx 9 & 10: 3 days apart (2026-07-10 00:00:00 and 2026-07-13 00:00:00) -> NO MATCH
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (9, '2026-07-10 00:00:00', 300.00, 0, 'Chuck')")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (10, '2026-07-13 00:00:00', 0, 300.00, 'AJ')")

    # 5. Passthrough existing exclusion test
    # Tx 11 & 12: amount 500.00, but Tx 11 is in ledger_entries with is_passthrough = 1
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (11, '2026-07-10 10:00:00', 500.00, 0, 'Alice Johnson')")
    conn.execute("INSERT INTO transactions (id, txn_date, credit, debit, merchant_display) VALUES (12, '2026-07-10 11:00:00', 0, 500.00, 'Bob Smith')")
    conn.execute("INSERT INTO ledger_entries (contact_id, entry_type, amount, entry_date, transaction_id, is_passthrough) VALUES (1, 'passthrough', 500.00, '2026-07-10', 11, 1)")

    conn.commit()

    cands = contacts.detect_passthrough_candidates(conn)

    print(f"\nDetected {len(cands)} passthrough candidates:")
    for idx, c in enumerate(cands):
        print(f" Candidate {idx+1}:")
        print(f"   Credit Tx {c['credit_tx_id']} ({c['credit_date']}): amount={c['credit_amount']}, merchant='{c['credit_merchant']}', contact='{c['credit_contact']}', contact_id={c['from_contact_id']}")
        print(f"   Debit Tx  {c['debit_tx_id']} ({c['debit_date']}): amount={c['debit_amount']}, merchant='{c['debit_merchant']}', contact='{c['debit_contact']}', contact_id={c['to_contact_id']}")

    # Validation 1: Check pair (1, 2)
    cand_1_2 = next((c for c in cands if c['credit_tx_id'] == 1 and c['debit_tx_id'] == 2), None)
    assert cand_1_2 is not None, "Pair (1, 2) should be detected"
    assert cand_1_2['from_contact_id'] == 1, f"Credit contact ID should be 1 (Alice), got {cand_1_2['from_contact_id']}"
    assert cand_1_2['credit_contact'] == "Alice Johnson"
    assert cand_1_2['to_contact_id'] == 2, f"Debit contact ID should be 2 (Bob), got {cand_1_2['to_contact_id']}"
    assert cand_1_2['debit_contact'] == "Bob Smith"

    # Validation 2: Check pair (3, 4) - Fallback unknown merchant
    cand_3_4 = next((c for c in cands if c['credit_tx_id'] == 3 and c['debit_tx_id'] == 4), None)
    assert cand_3_4 is not None, "Pair (3, 4) should be detected"
    assert cand_3_4['from_contact_id'] is None
    assert cand_3_4['credit_contact'] == "Zomato Refund"
    assert cand_3_4['to_contact_id'] is None
    assert cand_3_4['debit_contact'] == "Swiggy Pay"

    # Validation 3: Check pair (5, 6) - NULL merchant fallback
    cand_5_6 = next((c for c in cands if c['credit_tx_id'] == 5 and c['debit_tx_id'] == 6), None)
    assert cand_5_6 is not None, "Pair (5, 6) should be detected"
    assert cand_5_6['from_contact_id'] is None
    assert cand_5_6['credit_contact'] == "Unknown Sender"
    assert cand_5_6['to_contact_id'] is None
    assert cand_5_6['debit_contact'] == "Unknown Recipient"

    # Validation 4: Check pair (7, 8) - 2 day window boundary included
    cand_7_8 = next((c for c in cands if c['credit_tx_id'] == 7 and c['debit_tx_id'] == 8), None)
    assert cand_7_8 is not None, "Pair (7, 8) exactly 2 days apart should be included"
    assert cand_7_8['from_contact_id'] == 3  # Charlie Brown (alias Chuck)
    assert cand_7_8['to_contact_id'] == 1    # Alice Johnson (alias AJ)

    # Validation 5: Check pair (9, 10) - 3 days apart excluded
    cand_9_10 = next((c for c in cands if c['credit_tx_id'] == 9 or c['debit_tx_id'] == 10), None)
    assert cand_9_10 is None, "Pair (9, 10) 3 days apart MUST be excluded"

    # Validation 6: Check pair (11, 12) - Excluded because Tx 11 is in ledger_entries with is_passthrough=1
    cand_11_12 = next((c for c in cands if c['credit_tx_id'] == 11 or c['debit_tx_id'] == 12), None)
    assert cand_11_12 is None, "Pair with existing passthrough ledger entry MUST be excluded"

    print("Test 2 Result: PASS (All matching rules, fallback rules, and exclusion rules verified successfully)")


def run_all_tests():
    print("=== Running Challenger Empirical Tests for detect_passthrough_candidates ===")
    test_n_plus_one_query_optimization()
    test_matching_correctness()
    print("\nALL EMPIRICAL CHALLENGER TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_all_tests()
