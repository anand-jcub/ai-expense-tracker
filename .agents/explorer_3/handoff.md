# Handoff Report — UI Template Rendering & Web Handling for Date Filtering

**Explorer:** `explorer_3`  
**Target Files:** `expense_tracker/web.py`, `expense_tracker/templates.py`, `expense_tracker/services.py`, `expense_tracker/static/app.js`  
**Feature Contract:** FC-01 (`docs/feature-coherence.md`)

---

## 1. Observation

Direct code observations from the codebase investigation:

### Observation 1.1: Web Handler Route Parameter Capture (`web.py`)
- In `expense_tracker/web.py` (lines 275-276, 345-369):
  ```python
  parsed = urllib.parse.urlparse(self.path)
  params = urllib.parse.parse_qs(parsed.query)
  ...
  period_touched = any(
      k in params
      for k in ("start_date", "end_date", "exclude_business", "use_my_share")
  )
  exclude_business = (
      "exclude_business" in params if period_touched else True
  )
  self.respond_html(
      page(
          data,
          ...
          params.get("start_date", [""])[0],
          params.get("end_date", [""])[0],
          exclude_business,
          ...
      )
  )
  ```
- `web.py` extracts `start_date` and `end_date` from query parameters and forwards them to `page(...)` in `templates.py`.
- No SQL-level date parameters are passed to `dashboard_data(conn)`; all data extracted from SQLite is returned raw (`data["transactions"]`, `data["pending"]`, `data["shared"]`, etc.). Date filtering occurs strictly within Python UI rendering logic.

### Observation 1.2: Default Date Period Computation & `_in_period` Helper (`templates.py`)
- In `expense_tracker/templates.py` (lines 1667-1694):
  ```python
  period_explicit = bool(start_date or end_date)
  if not start_date and not end_date:
      today = date.today()
      month_start = today.replace(day=1).isoformat()
      ...
      month_end = (next_month - timedelta(days=1)).isoformat()
      start_date = month_start
      end_date = month_end
      if min_date and start_date < min_date:
          start_date = min_date
      if max_date and end_date > max_date:
          end_date = max_date
  else:
      start_date = start_date if start_date else min_date
      end_date = end_date if end_date else max_date

  def _in_period(r):
      txn_date = str(row_get(r, "txn_date") or "")
      if start_date and txn_date < start_date:
          return False
      if end_date and txn_date > end_date:
          return False
      return True
  ```

### Observation 1.3: Needs Review Queue & Sidebar Badge Filtering (`templates.py`)
- In `expense_tracker/templates.py` (lines 1661, 1698-1706):
  ```python
  # Full queue sizes for Home attention (not period-filtered — all-time)
  attention_review_count = len(data.get("pending") or [])

  # Filter the pending (needs-review) queue to the selected period always
  filtered_review = filter_review_rows(
      [r for r in (data.get("pending") or []) if _in_period(r)], review_search
  )
  pending_review = sort_review_rows(filtered_review, review_sort)
  ...
  pending_badge_count = len(unified_pending)
  ```
- On initial page load (when no date parameters exist in the URL), `start_date` and `end_date` default to the current calendar month (e.g. `2026-08-01` to `2026-08-31`).
- `data.get("pending")` is filtered by `_in_period(r)` using the default current month. Any pending transaction from a previous month (e.g. `2026-07-15`) is removed from `pending_review` and `pending_badge_count`.
- Home attention strip displays `attention_review_count` (all-time `len(data.get("pending"))`, e.g. "5 to review"), but clicking it jumps to `#review` where `pending_review` renders 0 rows!

### Observation 1.4: Asymmetric `tx_source` & `shared_source` Slicing (`templates.py`)
- In `expense_tracker/templates.py` (lines 1733-1742):
  ```python
  tx_source = (
      [r for r in data["transactions"] if _in_period(r)]
      if period_explicit
      else data["transactions"]
  )
  shared_source = (
      [r for r in (data.get("shared") or []) if _in_period(r)]
      if period_explicit
      else (data.get("shared") or [])
  )
  ```
- When `period_explicit` is `False` (initial load), `tx_source` includes all-time transactions while Home spend charts/metrics use `filter_dashboard_rows` (which filters by current month).
- When `period_explicit` is `True` (user applies period filter on Home), `tx_source` filters transactions by period.

### Observation 1.5: Hardcoded `[:50]` Slice Corrupting Money Flow View (`templates.py`)
- In `expense_tracker/templates.py` (lines 274-307, 339-364, 1997):
  ```python
  # In page():
  {render_money_flows_view(tx_source)}

  # In render_money_flows_view(transactions):
  flow_txns = [
      t for t in transactions
      if dict(t).get("category") in ("Transfer", "Loan") or dict(t).get("expense_type") in ("Transfer", "Loan")
  ]
  ...
  total_inflow = Decimal("0")
  total_outflow = Decimal("0")
  items_html = []
  for f in flow_txns[:50]:
      ...
      if credit > 0:
          total_inflow += credit
      if debit > 0:
          total_outflow += debit
      ...
  net_transfer = total_inflow - total_outflow
  ```
- The loop in `render_money_flows_view` iterates over `flow_txns[:50]` and calculates `total_inflow` and `total_outflow` *inside* the loop.
- If there are more than 50 Transfer/Loan transactions in the period (or all time), any transaction beyond index 50 is excluded from the cards AND excluded from the `Total Inflow`, `Total Outflow`, and `Net Cash Flow` summary stat boxes at the top of the Money Flow tab.

### Observation 1.6: Rules Tab Shared Table Uses All-Time Data (`templates.py`)
- In `expense_tracker/templates.py` (lines 1835-1845 vs line 2073):
  - In `shared_section` (lines 1835-1845): uses `shared_source` (period-filtered when explicit).
  - In `rules_section` (line 2073):
    ```python
    <tbody>{''.join(...) for r in data['shared']) or ...}</tbody>
    ```
  - `#rules` pane renders raw `data['shared']` (all-time), ignoring `shared_source`.

---

## 2. Logic Chain

1. **Premise 1 (Pending Transactions Defect):** `attention_review_count` on the Home attention strip uses all-time pending count `len(data.get("pending"))` (complying with FC-01 for Home attention). However, `pending_review` (rendered in the Needs Review table under `#review` tab) and `pending_badge_count` (rendered on the sidebar nav badge) filter `data["pending"]` by `_in_period(r)`.
   - On default load, `start_date` and `end_date` default to the current calendar month.
   - If pending transactions exist from previous months (e.g. July), `_in_period(r)` returns `False` for those rows.
   - Therefore, the Needs Review table shows 0 rows and the sidebar badge shows 0, even when Home attention strip states "5 to review". When the user clicks "5 to review", no transactions appear in the table. This hides valid pending transactions.

2. **Premise 2 (Money Flow Calculation & Truncation Defect):** `render_money_flows_view(tx_source)` filters `tx_source` for Transfer/Loan transactions (`flow_txns`).
   - The rendering function loops through `flow_txns[:50]` and accumulates `total_inflow` and `total_outflow` within that 50-item loop.
   - Any valid in-period transfer/loan beyond the 50th item is dropped from display AND dropped from the cash flow totals.
   - Additionally, `tx_source` comes only from `data["transactions"]` (classified items), so pending transfers/loans in `data["pending"]` are completely omitted from Money Flow.

3. **Premise 3 (Inconsistent Period Filtering Across Tabs):** FC-01 mandates that period filters consistently control period metrics, charts, and transaction listings when a date range is selected.
   - Currently, `filter_dashboard_rows` (used by Home spend charts and cards) filters by `start_date`, `end_date`, AND `exclude_business`.
   - `tx_source` filters by date ONLY when `period_explicit` is `True`, and never applies `exclude_business`.
   - The Shared expenses table in `#rules` pane uses raw `data['shared']` (all-time), bypassing date filtering entirely.

4. **Conclusion:** Data drops and missing transactions are caused by UI template layer bugs in `templates.py`:
   - Default period filtering on `data["pending"]` hiding prior-month review items.
   - Hardcoded `[:50]` slice in `render_money_flows_view` truncating data and corrupting totals.
   - Omission of `data["pending"]` from Money Flow source data.
   - Direct reference to `data['shared']` in the Rules tab instead of `shared_source`.
   - Asymmetry between `period_explicit` and default period filtering for `tx_source`.

---

## 3. Caveats

- **Scope boundaries:** Investigation focused strictly on UI template rendering (`templates.py`), web route parameter capture (`web.py`), and client-side interactions (`app.js`). Database extraction (`db.py`) and service calculations (`services.py`) were analyzed solely for interface contract points.
- **React Shell (`/app/`):** As noted in FC-06, the React shell under `/app/` is a preview/partial shell. The classic server-rendered templates (`/`) are the primary UI surface investigated.
- **SQL Date Filtering:** Currently, SQL queries in `db.py` do not execute `WHERE txn_date BETWEEN ? AND ?`. All filtering is done in-memory in Python. If data volume grows very large in the future, SQL-level filtering would be more performant, but in-memory Python filtering is what the architecture currently uses.

---

## 4. Conclusion & Fix Recommendations

### Summary Diagnosis
The issue where transactions go missing or are dropped from the Money Flow and Transactions tabs when date filtering is applied (or on default page load) is driven by **5 primary defects in `templates.py`**:

1. **Defect 1 (Needs Review Hiding):** `templates.py:1698` filters `data["pending"]` using `_in_period(r)`. On initial load, `_in_period` defaults to the current month, hiding all pending items from prior months while Home attention strip shows their all-time count.
2. **Defect 2 (Money Flow Truncation & Total Corruption):** `templates.py:294` slices `flow_txns[:50]` inside the aggregation loop for `total_inflow` and `total_outflow`, dropping transactions beyond index 50 and corrupting summary box amounts.
3. **Defect 3 (Money Flow Pending Omission):** `render_money_flows_view` is passed `tx_source` (which contains only classified `data["transactions"]`), omitting pending transfers/loans from `data["pending"]`.
4. **Defect 4 (Rules Shared Table Bypass):** `templates.py:2073` renders `data['shared']` (all-time) instead of `shared_source` (period-filtered).
5. **Defect 5 (Explicit vs Default Period Filtering Asymmetry):** `tx_source` and `shared_source` check `period_explicit`, creating inconsistent behavior between default current-month view and explicit date range selection.

### Detailed Recommendations for UI Fix

1. **Needs Review Queue & Sidebar Badge Alignment (`templates.py`):**
   - Unify `pending_review` to show all pending transactions requiring review (all-time) UNLESS the user explicitly applies a date filter range.
   - Alternatively, if `pending_review` is period-filtered, ensure sidebar badge count (`pending_badge_count`) and Home attention strip count (`attention_review_count`) reflect the exact same count, with a clear toggle/link to "Show all pending items" if items exist outside the selected period.

2. **Fix Money Flow View (`templates.py:render_money_flows_view`):**
   - Compute `total_inflow`, `total_outflow`, and `net_transfer` over the ENTIRE `flow_txns` list (all in-period transfers/loans).
   - Do NOT truncate `flow_txns` before calculating totals. If DOM card rendering needs pagination, slice `items_html` AFTER accumulating totals over all matching rows.
   - Include pending transfers/loans (from `data["pending"]`) in `transactions` parameter passed to `render_money_flows_view`.

3. **Fix Shared Table under Rules Tab (`templates.py:line 2073`):**
   - Change line 2073 to iterate over `shared_source` instead of `data['shared']`.

4. **Unify Period Filtering Helper (`templates.py`):**
   - Ensure `_in_period(r)` normalizes date strings by taking `str(txn_date)[:10]` before string comparison to handle ISO timestamps correctly.
   - Ensure `tx_source`, `shared_source`, and `period_rows` share consistent period filtering logic when a user selects a date range on Home.

---

## 5. Verification Method

To verify these findings independently:

1. **Needs Review Hiding Verification:**
   - Inspect `expense_tracker/templates.py` line 1698:
     `filtered_review = filter_review_rows([r for r in (data.get("pending") or []) if _in_period(r)], review_search)`
   - Create a database with a pending transaction dated in the previous month (e.g. `2026-07-15`) and load GET `/` without query parameters.
   - Observe that `len(data["pending"])` is 1 (shown on Home attention strip), but `pending_review` in the `#review` tab is empty `[]`.

2. **Money Flow Truncation Verification:**
   - Inspect `expense_tracker/templates.py` line 294 & 304-307:
     `for f in flow_txns[:50]:`
   - Pass 60 transfer transactions (e.g. 60 x ₹100 credit) to `render_money_flows_view`.
   - Assert `total_inflow`: expected `6000`, actual returned by current template `5000`.

3. **Rules Shared Table Verification:**
   - Inspect `expense_tracker/templates.py` line 2073:
     Observe `for r in data['shared']` instead of `for r in shared_source`.

4. **Pytest & Architecture Audit:**
   - Run `pytest` to verify test suite status:
     `.\venv\Scripts\pytest`
   - Run architecture check:
     `.\venv\Scripts\python.exe .grok\skills\architecture-agent\scripts\architecture_check.py --intent-zones P,E --feature FC-01`
