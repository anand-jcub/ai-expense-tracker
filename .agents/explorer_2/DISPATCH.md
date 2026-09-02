## 2026-08-10T06:26:50Z
Investigate the backend data retrieval and date filtering logic in `expense_tracker/db.py` and `expense_tracker/services.py`:
1. Trace how `start_date` and `end_date` are received, processed, and passed into SQL queries or Python filter functions.
2. Examine SQL query construction in `db.py` (e.g. date comparisons `date >= ? AND date <= ?`, timestamp format, string vs date comparison, end of day boundary like `23:59:59` vs `00:00:00`).
3. Examine filtering functions in `services.py` for `transactions`, `shared`, and `pending` queues.
4. Identify exactly why transactions go missing when a date range filter is applied.
5. Formulate a detailed, root-cause diagnosis and recommended fix strategy.
