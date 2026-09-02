"""Comprehensive Empirical Stress Test Harness for Khata Domain Logic (Milestone 2).
"""

import sqlite3
import sys
import time
import traceback
from decimal import Decimal
from typing import Any, List, Dict

# Add repository root to path
sys.path.insert(0, r"c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai")

from expense_tracker.db import init_db
from expense_tracker.contacts import (
    create_contact,
    update_contact,
    get_all_contacts,
    find_contact_by_text,
    add_ledger_entry,
    add_rolling_entry,
    record_opening_balance,
    record_settlement,
    void_ledger_entry,
    get_balance,
    get_ledger,
    get_all_balances,
    detect_passthrough_candidates,
    split_aliases,
)
from expense_tracker.contacts_domain.calculators import (
    _token_in_text,
    _score_contact_match,
    _determine_settlement_params,
    _d,
)


def create_in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


results: List[Dict[str, Any]] = []


def record_result(test_name: str, category: str, status: str, details: str, output: Any = None):
    results.append({
        "test_name": test_name,
        "category": category,
        "status": status,  # PASS, FAIL, BUG_FOUND, UNEXPECTED_BEHAVIOR
        "details": details,
        "output": str(output) if output is not None else ""
    })
    print(f"[{status}] {category} :: {test_name} - {details}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. UNICODE & SPECIAL CHARACTERS IN CONTACT ALIASES & SEARCH
# ─────────────────────────────────────────────────────────────────────────────

def test_unicode_and_special_chars():
    conn = create_in_memory_db()

    # 1.1 Non-Latin scripts (Devanagari, Emoji, CJK, Arabic, Cyrillic)
    try:
        cid1 = create_contact(conn, name="आनंद कुमार", aliases=["anand.k@upi", "आनंद", "😀_emoji_alias"], notes="Hindi name test")
        contact1 = find_contact_by_text(conn, "आनंद")
        if contact1 and contact1["id"] == cid1:
            record_result("Unicode Devanagari Search", "Unicode/Special Chars", "PASS", "Successfully matched Devanagari contact by alias")
        else:
            record_result("Unicode Devanagari Search", "Unicode/Special Chars", "FAIL", f"Failed to match Devanagari contact: got {contact1}")
    except Exception as e:
        record_result("Unicode Devanagari Search", "Unicode/Special Chars", "FAIL", f"Exception raised: {e}")

    # 1.2 Emoji in contact name and search
    try:
        cid_emoji = create_contact(conn, name="Alice 🚀", aliases="rocket_alice, 🚀_alias")
        matched = find_contact_by_text(conn, "Alice 🚀")
        if matched and matched["id"] == cid_emoji:
            record_result("Emoji Contact Name Search", "Unicode/Special Chars", "PASS", "Matched contact with emoji in name")
        else:
            record_result("Emoji Contact Name Search", "Unicode/Special Chars", "FAIL", f"Failed emoji match: {matched}")
    except Exception as e:
        record_result("Emoji Contact Name Search", "Unicode/Special Chars", "FAIL", f"Exception: {e}")

    # 1.3 Regex special characters in alias (e.g. . * + ? ^ $ ( ) [ ] { } | \ )
    regex_aliases = ["bob.*", "bob+test@gmail.com", "bob(hub)", "bob[1]", "^bob$"]
    try:
        cid_regex = create_contact(conn, name="Bob Regex", aliases=regex_aliases)
        m1 = find_contact_by_text(conn, "bob+test@gmail.com")
        m2 = find_contact_by_text(conn, "bob(hub)")
        m3 = find_contact_by_text(conn, "bob.*")
        
        if m1 and m1["id"] == cid_regex and m2 and m2["id"] == cid_regex:
            record_result("Regex Special Chars in Alias Search", "Unicode/Special Chars", "PASS", "Regex symbols in aliases matched correctly without crashing re.search")
        else:
            record_result("Regex Special Chars in Alias Search", "Unicode/Special Chars", "FAIL", f"Mismatch for regex aliases: m1={m1}, m2={m2}, m3={m3}")
    except Exception as e:
        record_result("Regex Special Chars in Alias Search", "Unicode/Special Chars", "BUG_FOUND", f"Regex crash or error when searching regex symbols: {e}\n{traceback.format_exc()}")

    # 1.4 Test direct _token_in_text with regex special chars
    try:
        res_dot = _token_in_text("bob.*", "paying bob.* for dinner")
        res_plus = _token_in_text("bob+test", "send to bob+test now")
        record_result("_token_in_text with Regex Metacharacters", "Unicode/Special Chars", "PASS", f"_token_in_text dot={res_dot}, plus={res_plus}")
    except Exception as e:
        record_result("_token_in_text with Regex Metacharacters", "Unicode/Special Chars", "BUG_FOUND", f"re.search error: {e}")

    # 1.5 Short name parts < 4 letters in contact matching
    try:
        cid_short = create_contact(conn, name="Ali Ram", aliases=[])
        # Search for "Ali" in text "paying Ali for coffee"
        m_short = find_contact_by_text(conn, "paying Ali for coffee")
        if m_short and m_short["id"] == cid_short:
            record_result("Short Name Part (<4 chars) Search", "Unicode/Special Chars", "PASS", "Matched short name part in text")
        else:
            record_result("Short Name Part (<4 chars) Search", "Unicode/Special Chars", "BUG_FOUND", f"Failed to match contact 'Ali Ram' when searching 'paying Ali for coffee' because name parts <4 chars are ignored in partial token split!")
    except Exception as e:
        record_result("Short Name Part (<4 chars) Search", "Unicode/Special Chars", "FAIL", f"Exception: {e}")

    # 1.6 Duplicate contact name handling
    try:
        create_contact(conn, name="Unique Name")
        create_contact(conn, name="Unique Name")
        record_result("Duplicate Contact Name Creation", "Unicode/Special Chars", "BUG_FOUND", "create_contact allowed duplicate name!")
    except sqlite3.IntegrityError as ie:
        record_result("Duplicate Contact Name Creation", "Unicode/Special Chars", "UNEXPECTED_BEHAVIOR", f"create_contact raised raw sqlite3.IntegrityError instead of a clean domain ValueError: {ie}")
    except ValueError as ve:
        record_result("Duplicate Contact Name Creation", "Unicode/Special Chars", "PASS", f"create_contact raised clean domain ValueError: {ve}")

    # 1.7 SQL Injection strings in contact fields
    sqli_name = "Robert'; DROP TABLE contacts; --"
    sqli_alias = "bob' OR '1'='1"
    try:
        cid_sqli = create_contact(conn, name=sqli_name, aliases=sqli_alias, notes="' OR 1=1 --")
        fetched = get_all_contacts(conn)
        found_sqli = any(c["id"] == cid_sqli for c in fetched)
        if found_sqli:
            record_result("SQL Injection Safety", "Unicode/Special Chars", "PASS", "SQL injection strings handled safely as parameterized literals")
        else:
            record_result("SQL Injection Safety", "Unicode/Special Chars", "FAIL", "Contact with SQLi name not found after insert")
    except Exception as e:
        record_result("SQL Injection Safety", "Unicode/Special Chars", "BUG_FOUND", f"SQL error on injection string: {e}")

    # 1.8 Malformed/Corrupted aliases_json in DB directly
    try:
        conn.execute("INSERT INTO contacts (name, aliases_json, created_at) VALUES ('Corrupt Json', 'INVALID_JSON_HERE', '2026-07-01')")
        conn.commit()
        contacts = get_all_contacts(conn)
        corrupt_c = next((c for c in contacts if c["name"] == "Corrupt Json"), None)
        if corrupt_c and corrupt_c["aliases"] == []:
            record_result("Corrupted aliases_json fallback", "Unicode/Special Chars", "PASS", "Fallback to empty list [] when aliases_json is corrupted")
        else:
            record_result("Corrupted aliases_json fallback", "Unicode/Special Chars", "FAIL", f"Unexpected output for corrupt json: {corrupt_c}")
    except Exception as e:
        record_result("Corrupted aliases_json fallback", "Unicode/Special Chars", "FAIL", f"Exception on corrupt json fetch: {e}")

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. ZERO AND NEGATIVE SETTLEMENT AMOUNTS & DIRECT LEDGER ENTRIES
# ─────────────────────────────────────────────────────────────────────────────

def test_settlements_and_zero_negative_amounts():
    conn = create_in_memory_db()

    cid = create_contact(conn, name="Charlie Settlement")
    # Add initial debt: You sent 1000 to Charlie (Charlie owes you 1000, net = +1000)
    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("1000"))

    # 2.1 Zero settlement amount: record_settlement(conn, cid, amount=0)
    try:
        record_settlement(conn, cid, amount=0)
        record_result("Zero Settlement Amount", "Settlement Amounts", "BUG_FOUND", "record_settlement(amount=0) succeeded instead of raising ValueError!")
    except ValueError as ve:
        record_result("Zero Settlement Amount", "Settlement Amounts", "PASS", f"Correctly raised ValueError on zero settlement: {ve}")
    except Exception as e:
        record_result("Zero Settlement Amount", "Settlement Amounts", "UNEXPECTED_BEHAVIOR", f"Raised unexpected exception type: {type(e).__name__}: {e}")

    # 2.2 Negative settlement amount: record_settlement(conn, cid, amount=-500)
    try:
        record_settlement(conn, cid, amount=-500)
        record_result("Negative Settlement Amount", "Settlement Amounts", "BUG_FOUND", "record_settlement(amount=-500) succeeded instead of raising ValueError!")
    except ValueError as ve:
        record_result("Negative Settlement Amount", "Settlement Amounts", "PASS", f"Correctly raised ValueError on negative settlement: {ve}")
    except Exception as e:
        record_result("Negative Settlement Amount", "Settlement Amounts", "UNEXPECTED_BEHAVIOR", f"Raised unexpected exception: {e}")

    # 2.3 Settlement when net balance is ZERO (net == 0) with non-zero amount
    record_settlement(conn, cid) # Full settlement (net becomes 0)
    bal_after = get_balance(conn, cid)
    assert bal_after["net"] == 0.0

    try:
        res_zero_net = record_settlement(conn, cid, amount=100)
        ledger_after = get_ledger(conn, cid)
        settlement_entries = [e for e in ledger_after["entries"] if e.get("purpose") == "settlement"]
        if len(settlement_entries) == 1:
            record_result("Settlement When Net is 0", "Settlement Amounts", "UNEXPECTED_BEHAVIOR", f"record_settlement(amount=100) when net=0 was a silent no-op (returned balance without error or adding entry)")
        else:
            record_result("Settlement When Net is 0", "Settlement Amounts", "PASS", f"Settlement when net=0 created entry or handled correctly: count={len(settlement_entries)}")
    except Exception as e:
        record_result("Settlement When Net is 0", "Settlement Amounts", "PASS", f"Raised exception when net=0: {e}")

    # 2.4 Over-settlement attempt (amount > abs(net))
    cid2 = create_contact(conn, name="Dave OverSettle")
    add_ledger_entry(conn, contact_id=cid2, direction="you_sent", amount=Decimal("300"))
    res_over = record_settlement(conn, cid2, amount=500)
    bal_over = get_balance(conn, cid2)
    if bal_over["net"] == 0.0:
        record_result("Over-Settlement Behavior", "Settlement Amounts", "PASS", f"Settling 500 when debt is 300 capped settlement at 300, net became 0.0")
    else:
        record_result("Over-Settlement Behavior", "Settlement Amounts", "UNEXPECTED_BEHAVIOR", f"Net balance after over-settling 500 on 300 debt: net={bal_over['net']}")

    # 2.5 Direct add_ledger_entry with amount <= 0
    try:
        add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("0"))
        record_result("add_ledger_entry amount=0", "Settlement Amounts", "BUG_FOUND", "add_ledger_entry with amount=0 succeeded!")
    except ValueError as ve:
        record_result("add_ledger_entry amount=0", "Settlement Amounts", "PASS", f"Raised ValueError for amount=0: {ve}")

    try:
        add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=Decimal("-10.50"))
        record_result("add_ledger_entry amount=-10.50", "Settlement Amounts", "BUG_FOUND", "add_ledger_entry with amount=-10.50 succeeded!")
    except ValueError as ve:
        record_result("add_ledger_entry amount=-10.50", "Settlement Amounts", "PASS", f"Raised ValueError for amount=-10.50: {ve}")

    # 2.6 Invalid direction string
    try:
        add_ledger_entry(conn, contact_id=cid, direction="invalid_dir", amount=Decimal("100"))
        record_result("Invalid Direction String", "Settlement Amounts", "BUG_FOUND", "add_ledger_entry allowed invalid direction string!")
    except ValueError as ve:
        record_result("Invalid Direction String", "Settlement Amounts", "PASS", f"Raised ValueError on invalid direction: {ve}")

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. VOIDING PASS-THROUGH AND ROLLING ENTRIES
# ─────────────────────────────────────────────────────────────────────────────

def test_voiding_passthrough_and_rolling_entries():
    conn = create_in_memory_db()

    c_from = create_contact(conn, name="Person A")
    c_to = create_contact(conn, name="Person B")

    # 3.1 Create rolling entry A -> me -> B for 1500
    roll_res = add_rolling_entry(conn, from_contact_id=c_from, to_contact_id=c_to, amount=1500)
    leg1_id = roll_res["leg_from_id"]
    leg2_id = roll_res["leg_to_id"]

    bal_a_init = get_balance(conn, c_from)
    bal_b_init = get_balance(conn, c_to)

    if bal_a_init["net"] == 0.0 and bal_b_init["net"] == 0.0:
        record_result("Rolling Entry Net Invariance", "Pass-Through & Voiding", "PASS", "Initial rolling entry legs are pass-through; nets are 0.0")
    else:
        record_result("Rolling Entry Net Invariance", "Pass-Through & Voiding", "FAIL", f"Initial rolling entry altered nets: A={bal_a_init['net']}, B={bal_b_init['net']}")

    # 3.2 Void leg 1 of the rolling entry (void_ledger_entry on leg1_id)
    void_ledger_entry(conn, leg1_id, reason="Testing single leg voiding")

    bal_a_after = get_balance(conn, c_from)
    bal_b_after = get_balance(conn, c_to)
    ledger_b = get_ledger(conn, c_to)

    leg2_in_b = next((e for e in ledger_b["entries"] if e["id"] == leg2_id), None)

    if leg2_in_b and not leg2_in_b.get("voided_at"):
        record_result("Voiding Rolling Leg Asymmetry", "Pass-Through & Voiding", "UNEXPECTED_BEHAVIOR", 
                      f"Voiding leg 1 ({leg1_id}) left paired leg 2 ({leg2_id}) active and un-voided in contact B's ledger! (passthrough_pair_id={leg2_in_b.get('passthrough_pair_id')})")
    else:
        record_result("Voiding Rolling Leg Asymmetry", "Pass-Through & Voiding", "PASS", "Leg 2 was also voided or handled")

    # 3.3 Voiding non-existent entry ID
    try:
        void_ledger_entry(conn, 999999, reason="Non-existent entry test")
        record_result("Void Non-Existent Entry ID", "Pass-Through & Voiding", "UNEXPECTED_BEHAVIOR", "void_ledger_entry(999999) executed silently without error or indication of 0 rows updated")
    except Exception as e:
        record_result("Void Non-Existent Entry ID", "Pass-Through & Voiding", "PASS", f"Raised exception for invalid entry ID: {e}")

    # 3.4 Voiding an already voided entry
    try:
        void_ledger_entry(conn, leg1_id, reason="Double void test")
        record_result("Double Void Entry", "Pass-Through & Voiding", "PASS", "Double voiding an entry executes idempotently")
    except Exception as e:
        record_result("Double Void Entry", "Pass-Through & Voiding", "FAIL", f"Exception on double void: {e}")

    # 3.5 Rolling entry with same contact (from_contact == to_contact)
    try:
        add_rolling_entry(conn, from_contact_id=c_from, to_contact_id=c_from, amount=500)
        record_result("Rolling Entry Same Contact", "Pass-Through & Voiding", "BUG_FOUND", "add_rolling_entry allowed from_contact_id == to_contact_id!")
    except ValueError as ve:
        record_result("Rolling Entry Same Contact", "Pass-Through & Voiding", "PASS", f"Correctly raised ValueError when from == to contact: {ve}")

    # 3.6 Rolling entry with non-existent contact
    try:
        add_rolling_entry(conn, from_contact_id=c_from, to_contact_id=88888, amount=500)
        record_result("Rolling Entry Non-Existent Contact", "Pass-Through & Voiding", "BUG_FOUND", "add_rolling_entry allowed non-existent to_contact_id!")
    except ValueError as ve:
        record_result("Rolling Entry Non-Existent Contact", "Pass-Through & Voiding", "PASS", f"Correctly raised ValueError for missing contact: {ve}")

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. RUNNING LEDGER BALANCE CALCULATION EXTREMES & HIGH VOLUME
# ─────────────────────────────────────────────────────────────────────────────

def test_running_ledger_extremes():
    conn = create_in_memory_db()

    cid = create_contact(conn, name="Extreme Ledger Person")

    # 4.1 Extreme financial numbers: Decimal precision vs Float conversion
    large_amt = Decimal("999999999999999.99") # ~1 Quadrillion - 1 cent
    micro_amt = Decimal("0.00000001") # Sub-cent / Satoshi scale

    add_ledger_entry(conn, contact_id=cid, direction="you_sent", amount=large_amt)
    add_ledger_entry(conn, contact_id=cid, direction="they_sent", amount=large_amt)

    bal_large = get_balance(conn, cid)
    if bal_large["net"] == 0.0:
        record_result("Large Amount Precision Net", "Ledger Balance Extremes", "PASS", "Net balance correctly equals 0.0 after symmetric 10^15 entry subtraction")
    else:
        record_result("Large Amount Precision Net", "Ledger Balance Extremes", "BUG_FOUND", f"Float precision drift on 10^15 amounts: net={bal_large['net']}")

    # Sub-cent precision test
    cid_micro = create_contact(conn, name="Micro Person")
    add_ledger_entry(conn, contact_id=cid_micro, direction="you_sent", amount=micro_amt)
    bal_micro = get_balance(conn, cid_micro)
    if bal_micro["total_you_sent"] == float(micro_amt):
        record_result("Micro Sub-cent Amount", "Ledger Balance Extremes", "PASS", f"Sub-cent amount float conversion: {bal_micro['total_you_sent']}")
    else:
        record_result("Micro Sub-cent Amount", "Ledger Balance Extremes", "UNEXPECTED_BEHAVIOR", f"Sub-cent float mismatch: expected {float(micro_amt)}, got {bal_micro['total_you_sent']}")

    # 4.2 Out-of-order date entries vs ID order running ledger assembly
    cid_ooo = create_contact(conn, name="Out Of Order Person")
    add_ledger_entry(conn, contact_id=cid_ooo, direction="you_sent", amount=Decimal("100"), entry_date="2026-07-15")
    add_ledger_entry(conn, contact_id=cid_ooo, direction="they_sent", amount=Decimal("30"), entry_date="2026-07-01")
    add_ledger_entry(conn, contact_id=cid_ooo, direction="you_sent", amount=Decimal("50"), entry_date="2026-07-10")

    ledger_ooo = get_ledger(conn, cid_ooo)
    entries = ledger_ooo["entries"]

    dates = [e["entry_date"] for e in entries]
    running_balances = [e["running_balance"] for e in entries]

    if dates == ["2026-07-01", "2026-07-10", "2026-07-15"] and running_balances == [-30.0, 20.0, 120.0]:
        record_result("Out-Of-Order Entry Date Running Ledger", "Ledger Balance Extremes", "PASS", f"Running balance calculated in entry_date ASC order: dates={dates}, running={running_balances}")
    else:
        record_result("Out-Of-Order Entry Date Running Ledger", "Ledger Balance Extremes", "BUG_FOUND", f"Out of order running balance incorrect! dates={dates}, running={running_balances}")

    # 4.3 High volume performance & running balance accuracy (1,000 entries)
    cid_hv = create_contact(conn, name="High Volume Person")
    t0 = time.time()
    for i in range(1, 501):
        add_ledger_entry(conn, contact_id=cid_hv, direction="you_sent", amount=Decimal("10.50"), entry_date=f"2026-01-01")
        add_ledger_entry(conn, contact_id=cid_hv, direction="they_sent", amount=Decimal("5.25"), entry_date=f"2026-01-02")
    t_insert = time.time() - t0

    t1 = time.time()
    bal_hv = get_balance(conn, cid_hv)
    t_bal = time.time() - t1

    t2 = time.time()
    ledger_hv = get_ledger(conn, cid_hv)
    t_ledger = time.time() - t2

    expected_net = (10.50 - 5.25) * 500
    last_running = ledger_hv["entries"][-1]["running_balance"]

    if abs(bal_hv["net"] - expected_net) < 0.001 and abs(last_running - expected_net) < 0.001:
        record_result("High Volume Ledger 1000 Rows", "Ledger Balance Extremes", "PASS", f"1,000 entries processed: insert={t_insert:.3f}s, get_balance={t_bal:.4f}s, get_ledger={t_ledger:.4f}s. Net={bal_hv['net']}, Last Running={last_running}")
    else:
        record_result("High Volume Ledger 1000 Rows", "Ledger Balance Extremes", "BUG_FOUND", f"High volume net calculation mismatch: expected {expected_net}, got net={bal_hv['net']}, running={last_running}")

    # 4.4 Non-existent contact ID in get_ledger vs get_balance
    try:
        get_ledger(conn, contact_id=999999)
        record_result("get_ledger Non-Existent Contact", "Ledger Balance Extremes", "BUG_FOUND", "get_ledger(999999) did not raise ValueError!")
    except ValueError as ve:
        record_result("get_ledger Non-Existent Contact", "Ledger Balance Extremes", "PASS", f"get_ledger correctly raised ValueError: {ve}")

    try:
        bal_missing = get_balance(conn, contact_id=999999)
        record_result("get_balance Non-Existent Contact", "Ledger Balance Extremes", "UNEXPECTED_BEHAVIOR", f"get_balance(999999) returned empty balance dict {bal_missing} without checking if contact exists!")
    except Exception as e:
        record_result("get_balance Non-Existent Contact", "Ledger Balance Extremes", "PASS", f"get_balance raised exception for missing contact: {e}")

    conn.close()


if __name__ == "__main__":
    print("=== STARTING KHATA DOMAIN STRESS TESTS ===")
    test_unicode_and_special_chars()
    test_settlements_and_zero_negative_amounts()
    test_voiding_passthrough_and_rolling_entries()
    test_running_ledger_extremes()
    print("=== STRESS TESTS COMPLETE ===")
