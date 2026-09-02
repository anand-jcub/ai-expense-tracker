# Empirical Verification & Adversarial Challenge Report — Milestone 2

**Target Module**: `expense_tracker/contacts.py` and `expense_tracker/contacts_domain/`  
**Challenger**: Challenger 1 (Empirical Challenger)  
**Date**: 2026-07-26  
**Verdict**: **PASS (VERIFIED)**  

---

## 1. Observation

### Command 1: Adversarial Domain Calculator Test Harness
Executed custom adversarial test harness `.agents/teamwork_preview_challenger_m2_1/test_harness_m2.py`:
- Command: `python .agents/teamwork_preview_challenger_m2_1/test_harness_m2.py`
- Result:
```text
.....................
----------------------------------------------------------------------
Ran 21 tests in 0.003s

OK
```
Specific Domain Functions Tested:
1. `split_aliases`:
   - Empty input (`""`, `"   "`, `",, , "`, `[]`) -> returns `[]`.
   - Whitespace and case variations (`"  Alice , BOB , alice ,  bob  "`) -> returns `['alice', 'bob']`.
   - Unicode strings (`" Ánand ,  Müller , 🤖 , áñänd "`) -> returns `['ánand', 'müller', '🤖', 'áñänd']`.
   - List inputs (`["  Alice ", "BOB", "alice"]`) -> returns `['alice', 'bob']`.
   - Non-string in list (`[123, "alice"]`) -> raises `AttributeError` (expected for non-string types in input list).
2. `_calculate_net_balance`:
   - Zero entries (`[]`) -> returns `net: 0.0`, `status: "settled"`, `you_sent: 0.0`, `they_sent: 0.0`, `entry_count: 0`.
   - Mixed positive amounts (`you_sent` $120.50, `they_sent` $40.25) -> returns `net: 80.25`, `status: "owes_you"`, `they_owe_you: 80.25`, `you_owe_them: 0.0`.
   - Reverse direction (`you_sent` $50, `they_sent` $150) -> returns `net: -100.0`, `status: "you_owe"`, `they_owe_you: 0.0`, `you_owe_them: 100.0`.
   - Filtering contract observation: `_calculate_net_balance` relies on `dal._fetch_ledger_entries` for filtering `is_passthrough` and `voided_at` rows before calculating net balances.
3. `_determine_settlement_params`:
   - Amount `None` with `net = Decimal('100.00')` -> returns `(Decimal('100.00'), 'they_sent')`.
   - Amount `None` with `net = Decimal('-100.00')` -> returns `(Decimal('100.00'), 'you_sent')`.
   - Requested amount $150 exceeding `net` $100 -> correctly caps `settle_amt` to $100 (`Decimal('100.00')`).
   - Zero amount (`Decimal('0')`) -> raises `ValueError("Settlement amount must be greater than zero.")`.
   - Negative amount (`Decimal('-20.00')`) -> raises `ValueError("Settlement amount must be greater than zero.")`.
   - Partial settlement ($40 on net -$100) -> returns `(Decimal('40.00'), 'you_sent')`.

### Command 2: Pytest Suite Execution
Executed unit and integration test suites:
- Command: `.\venv\Scripts\python.exe -m pytest tests/test_contacts_ledger.py tests/test_core.py`
- Result:
```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
collected 25 items

tests\test_contacts_ledger.py .....                                      [ 20%]
tests\test_core.py ....................                                  [100%]

============================= 25 passed in 0.46s ==============================
```

### Command 3: End-to-End Suite Execution
Executed E2E integration test:
- Command: `python expense_tracker/e2e_test.py`
- Result:
```text
login_page: OK
register_page: OK
login_page(error): OK
register_page(message): OK
dashboard page: OK (size: 339,562 bytes)
  transactions: 154
  pending: 16
  partner balances: []

ALL TESTS PASSED
```

---

## 2. Logic Chain

1. **Observation 1** demonstrates that pure domain calculators in `expense_tracker/contacts_domain/calculators.py` correctly handle edge cases in alias parsing, unicode strings, decimal net balance calculations, status determination, and settlement parameter constraints without failing or producing unexpected outputs.
2. **Observation 1** also shows proper separation of concerns: `_calculate_net_balance` performs pure financial math on provided rows, while SQL filtering for pass-through entries (`is_passthrough = 0`) and voided entries (`voided_at IS NULL`) is properly isolated in `expense_tracker/contacts_domain/dal.py`.
3. **Observation 2** confirms that existing unit tests in `tests/test_contacts_ledger.py` and `tests/test_core.py` pass without any regressions following the refactoring of `contacts.py` into submodules (`calculators.py`, `dal.py`, `services.py`).
4. **Observation 3** confirms that high-level web service flows and end-to-end user workflows function properly with the re-exported facade in `expense_tracker/contacts.py`.

---

## 3. Caveats

- `split_aliases`: When passed a `list[str]`, `split_aliases` cleans, lowercases, and deduplicates each item in the list, but does not split individual string elements by comma. Pass raw string input if comma-splitting of list elements is desired.
- `_calculate_net_balance`: If raw row dicts containing `is_passthrough=1` or `voided_at` timestamps are passed directly to `_calculate_net_balance` bypassing `dal._fetch_ledger_entries`, they will be included in the calculation. Service level calls always route through `dal._fetch_ledger_entries(..., include_transactions=False, exclude_voided=True)`.

---

## 4. Conclusion

The refactored `expense_tracker/contacts.py` and `expense_tracker/contacts_domain/` architecture is **EMPIRICALLY VERIFIED**.
- Pure financial domain functions are completely decoupled from SQLite dependencies.
- All edge cases for alias parsing, net balance arithmetic, and settlement parameter calculations pass without errors.
- 100% pass rate across unit test harness (21 tests), pytest suite (25 tests), and E2E system suite.

---

## 5. Verification Method

To independently verify these results:

1. Run the empirical adversarial test harness:
   ```powershell
   python .agents/teamwork_preview_challenger_m2_1/test_harness_m2.py
   ```
   *Expected output*: `Ran 21 tests in ... OK`

2. Run the pytest regression suite:
   ```powershell
   .\venv\Scripts\python.exe -m pytest tests/test_contacts_ledger.py tests/test_core.py
   ```
   *Expected output*: `25 passed in 0.46s`

3. Run the end-to-end system test:
   ```powershell
   python expense_tracker/e2e_test.py
   ```
   *Expected output*: `ALL TESTS PASSED`
