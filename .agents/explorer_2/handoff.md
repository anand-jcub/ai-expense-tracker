# Handoff Report — Date Filtering Defect Investigation

**Agent:** explorer_2  
**Working Directory:** `C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\explorer_2`  
**Target Areas:** `expense_tracker/db.py`, `expense_tracker/services.py`, `expense_tracker/templates.py`, `expense_tracker/web.py`  
**Feature Contract:** `FC-01` (Dashboard period filter consistency)  

---

## 1. Observation

Direct observations from code inspection and reproduction script execution:

### A. Pre-sliced `data["shared"][:15]` in `db.py`
- **File & Line:** `expense_tracker/db.py:918`
- **Code:**
  ```python
  return {
      "transactions": rows,
      "pending": pending,
      "shared": shared[:15],
      ...
  }
  ```
- **File & Line:** `expense_tracker/templates.py:1738-1742`
- **Code:**
  ```python
  shared_source = (
      [r for r in (data.get("shared") or []) if _in_period(r)]
      if period_explicit
      else (data.get("shared") or [])
  )
  ```
- **Observed Behavior:** `dashboard_data()` pre-slices the global shared expenses list to the 15 most recent all-time rows before returning data to the caller. When `templates.py` filters `shared_source` for a specific date range (`_in_period(r)`), it filters **only** this pre-sliced 15-element array instead of filtering the entire dataset (`data["transactions"]`). If the selected period does not contain those specific 15 all-time transactions, 100% of shared expenses for the selected period are dropped.

### B. Flawed Date Clamping Creating Inverted Date Ranges (`start_date > end_date`)
- **File & Line:** `expense_tracker/templates.py:1669-1686`
- **Code:**
  ```python
  if not start_date and not end_date:
      today = date.today()
      month_start = today.replace(day=1).isoformat()
      if today.month == 12:
          next_month = today.replace(year=today.year + 1, month=1, day=1)
      else:
          next_month = today.replace(month=today.month + 1, day=1)
      month_end = (next_month - timedelta(days=1)).isoformat()
      start_date = month_start
      end_date = month_end
      # Clamp to available data when possible
      if min_date and start_date < min_date:
          start_date = min_date
      if max_date and end_date > max_date:
          end_date = max_date
  ```
- **Observed Behavior:** On default load (no `start_date` or `end_date` in query params), `start_date` is set to the current calendar month start (e.g. `2026-08-01`) and `end_date` to current month end (e.g. `2026-08-31`). When historical data in the database spans e.g. `2024-03-01` (`min_date`) to `2024-03-10` (`max_date`):
  1. `start_date < min_date` (`2026-08-01 < 2024-03-01`) is `False`, so `start_date` remains `2026-08-01`.
  2. `end_date > max_date` (`2026-08-31 > 2024-03-10`) is `True`, so `end_date` is clamped to `2024-03-10`.
  3. The resulting period becomes `start_date = '2026-08-01'` and `end_date = '2024-03-10'` (`start_date > end_date`).
  4. In `filter_dashboard_rows` (`expense_tracker/services.py:191-193`) and `_in_period` (`templates.py:1690-1693`), `txn_date < start_date` evaluates to `True` for all 2024 rows. Consequently, **every single transaction in the database is filtered out** (`period_rows` count = 0), causing all totals, charts, and queues to disappear.

### C. String Boundary Comparison with Timestamps
- **File & Line:** `expense_tracker/services.py:191-193` & `expense_tracker/templates.py:1690-1693`
- **Code:**
  ```python
  if start_date and txn_date < start_date:
      continue
  if end_date and txn_date > end_date:
      continue
  ```
- **Observed Behavior:** Dates are compared as plain strings. When a transaction contains a timestamp component (e.g. `2024-03-15T15:30:00`), and `end_date` is `"2024-03-15"`, string comparison `"2024-03-15T15:30:00" > "2024-03-15"` returns `True` because `'T'` > `''`. Any transaction occurring on the end date with timestamp formatting is erroneously excluded.

### D. Mismatch between `tx_source` and `period_rows`
- **File & Line:** `expense_tracker/templates.py:1733-1737` & `lines 1763-1764`
- **Code:**
  ```python
  tx_source = (
      [r for r in data["transactions"] if _in_period(r)]
      if period_explicit
      else data["transactions"]
  )
  period_rows = filter_dashboard_rows(data["transactions"], start_date, end_date, exclude_business)
  ```
- **Observed Behavior:** When `period_explicit` is `False`, `period_rows` filters `data["transactions"]` by the default month, but `tx_source` passes the full all-time `data["transactions"]`. Conversely, when `period_explicit` is `True`, `tx_source` applies `_in_period` but ignores the `exclude_business` flag, creating mismatched transaction sets between the Home dashboard charts/metrics and the Transactions tab.

### E. Execution Results of Reproduction Script
Running `.agents/explorer_2/test_date_filter_defect.py`:
```text
=== Testing Defect 1: Shared Expenses Pre-slicing (:15) ===
Total transactions in DB: 20
Total shared rows returned by dashboard_data (sliced to :15): 15
March Shared DB Count: 10
March Shared Count via data['shared'][:15] (Templates logic): 5
March Shared Count via data['transactions'] (Correct logic): 10
-> DEFECT CONFIRMED: Shared transactions missing because data['shared'] was pre-sliced to 15!

=== Testing Defect 2: Inverted Date Range Clamping ===
Data min_date: 2024-03-01, max_date: 2024-03-10
Computed start_date: '2026-08-01', end_date: '2024-03-10'
Total transactions in DB: 10
Filtered period_rows count: 0
-> DEFECT CONFIRMED: Inverted date range (start_date > end_date) causes ALL transactions to disappear!

=== Testing Defect 3: Timestamp Boundary Comparison ===
Selected period: 2024-03-01 to 2024-03-15
Row txn_date in DB: '2024-03-15T15:30:00'
period_rows count: 0
-> DEFECT CONFIRMED: Transaction on end_date with timestamp was excluded due to string comparison!
```

---

## 2. Logic Chain

1. **Parameter Flow:**
   - User submits query string parameters (or loads `/`) -> `web.py:345-369` extracts `start_date` and `end_date` -> passes parameters to `templates.py:page()`.
   - `db.py:dashboard_data()` loads all transactions via SQL `SELECT t.*, c.* FROM transactions t JOIN classifications c ON c.transaction_id = t.id ORDER BY t.txn_date DESC`. SQL construction performs **no date filtering**.

2. **Pre-slicing Bottleneck (Defect 1):**
   - `db.py:888-918` pre-filters `shared = [r for r in rows if r["expense_type"] == "Shared"]` and truncates `data["shared"] = shared[:15]`.
   - In `templates.py:1738-1742`, `shared_source` filters `data["shared"]` against `_in_period(r)`.
   - Since `data["shared"]` only holds 15 items globally, any shared transactions in the selected date range outside of those top 15 global rows are unreachable and disappear from the UI.

3. **Inverted Date Clamping (Defect 2):**
   - On default load (`not start_date and not end_date`), `month_start` and `month_end` are generated using current system date (`date.today()`).
   - `templates.py:1680-1683` attempts to clamp dates to dataset boundaries `min_date` and `max_date`.
   - If `month_start > max_date` (dataset is historical relative to system clock), `start_date < min_date` evaluates to `False` (leaving `start_date = month_start`), while `end_date > max_date` evaluates to `True` (clamping `end_date = max_date`).
   - This produces `start_date > end_date` (e.g. `2026-08-01 > 2024-03-10`).
   - In `filter_dashboard_rows()` (`services.py:191-193`), `txn_date < start_date` evaluates to `True` for every historical transaction, setting `period_rows = []`.

4. **Timestamp Boundary Exclusion (Defect 3):**
   - `services.py:190-194` and `templates.py:1689-1694` perform string comparisons: `txn_date > end_date`.
   - Standard HTML date pickers provide `end_date` as `YYYY-MM-DD` (10 chars).
   - If `txn_date` contains time (e.g. `YYYY-MM-DDTHH:MM:SS`), string comparison treats any timestamp on `end_date` as greater than `end_date`, discarding end-of-day entries.

5. **Inconsistent Tab Sources (Defect 4):**
   - `tx_source` uses `data["transactions"]` (all-time) when `period_explicit` is `False`, but switches to `_in_period` rows when `period_explicit` is `True`.
   - `tx_source` does not apply `exclude_business` filtering, violating FC-01 coherence requirements where period filters must feed consistent datasets.

---

## 3. Caveats

- **API Endpoints:** Read-only analysis focused on classic HTML UI rendering paths (`web.py`, `templates.py`, `services.py`, `db.py`). React `/app` routes using `/api/contacts/ledger` or `/api/settlement` calculate ledger balances directly via `contacts.py` / `dal.py` without consuming `filter_dashboard_rows`.
- **Database Schema:** `transactions.txn_date` is a `TEXT` column. Standard parsers store `YYYY-MM-DD` strings, but manual entries or future PDF formats might insert full ISO timestamps. Fixes must handle both 10-char dates and full ISO timestamps seamlessly.

---

## 4. Conclusion & Recommended Fix Strategy

### Root Cause Assessment
Transactions go missing due to:
1. Hardcoded `:15` array truncation on `data["shared"]` in `db.py` before period filtering is applied.
2. Flawed default date clamping in `templates.py` producing inverted date ranges (`start_date > end_date`) when historical data precedes the current calendar month.
3. String-based date comparison in `services.py` / `templates.py` without truncating ISO timestamps to 10 characters (`YYYY-MM-DD`).
4. Disconnected transaction source logic (`tx_source` vs `period_rows`) causing inconsistency between dashboard metrics and transaction sub-tabs.

### Recommended Fix Strategy (for Implementer Agent)

1. **Fix Shared Expenses Slicing (`db.py` & `templates.py`)**:
   - In `templates.py`, derive `shared_source` directly from `period_rows` (or `data["transactions"]` filtered by `_in_period`):
     ```python
     shared_source = [r for r in period_rows if r["expense_type"] == "Shared"]
     ```
   - In `db.py:dashboard_data()`, return all shared rows or ensure `data["shared"]` contains complete shared records before tab rendering.

2. **Fix Default Date Range Clamping (`templates.py:1669-1686`)**:
   - Update period resolution logic so that if the current calendar month does not overlap with `[min_date, max_date]`, default `start_date` and `end_date` to `min_date` and `max_date` (or the date range of the latest available month in the dataset).
   - Ensure `start_date <= end_date` is enforced as an invariant (e.g. `if start_date > end_date: start_date = min_date`).

3. **Normalize Date Comparisons (`services.py:187-202` & `templates.py:1688-1694`)**:
   - Truncate date strings to 10 characters before comparison:
     ```python
     txn_date_str = str(row["txn_date"])[:10]
     start_str = start_date[:10] if start_date else ""
     end_str = end_date[:10] if end_date else ""
     if start_str and txn_date_str < start_str:
         continue
     if end_str and txn_date_str > end_str:
         continue
     ```

4. **Align Period Filtering across UI Tabs (`templates.py`)**:
   - Ensure `period_rows` is used consistently across metrics, charts, and transaction lists when period filtering is active, maintaining strict compliance with `FC-01`.

---

## 5. Verification Method

To independently verify the diagnosis and future fix:

1. **Run the Reproduction Test Script:**
   ```powershell
   .\venv\Scripts\python.exe .agents\explorer_2\test_date_filter_defect.py
   ```
   *Expected Result before fix:* All 3 defect assertions trigger `DEFECT CONFIRMED`.  
   *Expected Result after fix:* Script outputs 0 defect warnings and all filtered counts match direct SQL counts.

2. **Run Pytest Suite:**
   ```powershell
   .\venv\Scripts\pytest
   ```
   *Expected Result:* All 49 existing test cases pass cleanly.

3. **Run Architecture Agent Check:**
   ```powershell
   .\venv\Scripts\python.exe .grok\skills\architecture-agent\scripts\architecture_check.py --intent-zones P,E --feature FC-01
   ```
