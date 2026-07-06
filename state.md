# Project State

Last updated: 2026-07-03

## Summary

This project is a local-first Phase 1 personal expense tracker for password-protected SBI bank statement PDFs and manual entries. It imports statements, extracts transactions, stores immutable raw transactions in SQLite, supports review and correction workflows for classifications, learns merchant mappings only when explicitly requested, and provides dashboard/search views for spending analysis.

The app runs locally at:

```text
http://127.0.0.1:8765
```

Run command:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
```

## Current Files

- `app.py`: app entry point.
- `expense_tracker/sbi_pdf.py`: SBI PDF extraction logic.
- `expense_tracker/db.py`: SQLite schema, imports, review persistence, exports, learned-rule application.
- `expense_tracker/classifier.py`: merchant normalization, seeded categories, learned-rule matching, shared-expense math.
- `expense_tracker/web.py`: local HTTP app, dashboard, review UI, exports, searches.
- `tests/test_core.py`: regression tests.
- `README.md`: basic run/use documentation.
- `data/expenses.db`: local SQLite database.
- `outputs/transactions.csv` and `outputs/transactions.json`: generated exports.

## Implemented Features

### Import

- Upload weekly SBI statement PDF.
- Enter statement password.
- Extract transaction rows with table-first parsing and text fallback.
- Detect duplicate statement imports by PDF file hash.
- Store original transaction records as immutable rows.

### Manual Transactions

- Add transactions that are not present in bank statements.
- Manual entries support:
  - Date
  - Debit or credit
  - Amount
  - Description
  - Category
  - Type
  - People split
  - Notes
  - Optional learning
- Manual entries are stored in the same immutable `transactions` table as statement imports.
- Manual classifications are stored in `classifications` and marked as `reviewed`.
- Manual debits participate in expenses, shared expenses, dashboard charts, search, and exports.
- Manual credits participate in credit totals and credit/debit search.

### Storage

SQLite tables:

- `imports`: imported statement/manual-entry metadata.
- `transactions`: immutable extracted bank transactions.
- `classifications`: editable category/type/share/review state.
- `merchant_rules`: learned merchant/payee rules.
- `feedback_events`: audit trail of confirmations.

### Classification

- Seed rules for common merchants such as Swiggy, Zomato, BigBasket, Netflix, Uber, Airtel, etc.
- Unknown transactions go to review.
- Learned merchant matching supports exact, compact, and token-based variants.
- Example handled variants: `bb now` vs `bbnow`, `mathew` vs `mathew jose`.
- Variable tokens containing digits are ignored during merchant normalization.

### Review Workflow

- Review queue supports date sorting: newest first / oldest first.
- Review queue supports search.
- One bottom-level `Confirm review changes` button for batch save.
- Rows left as `Choose` remain pending.
- `Learn` is unchecked by default.
- If `Learn` is checked, the merchant rule is saved and matching pending rows are auto-classified.
- Existing learned rules are applied to pending rows on app/database initialization.

Review fields:

- Category
- Type
- People
- Notes
- Learn

### Classification Editing

- Reviewed and automatically categorized transactions can be edited after classification.
- The edit section searches classified rows by merchant, narration, category/type, status, notes, and amount.
- By default, the edit section shows the most recent classified transactions.
- Edits update only `classifications` and `feedback_events`; original `transactions` remain immutable.
- Correcting an auto-classified transaction marks it as `reviewed`.
- `Learn` is still unchecked by default in the edit flow.
- If `Learn` is checked while saving an edit, the merchant knowledge base is updated and matching pending transactions can be swept out of review.

Expense types:

- Personal
- Business
- Shared
- Transfer
- Loan
- Other

### Shared Expenses

- Shared debits use number of people in the UI.
- Internally, split is stored as a ratio.
- Examples:
  - `1` person -> `1.0`
  - `2` people -> `0.5`
  - `4` people -> `0.25`
- By default, People is `1`.

### Dashboard

Top dashboard now includes:

- Period controls: start date and end date.
- `Exclude Business` checkbox.
- `Use my share for split debits` checkbox.
- Period credit total.
- Period debit total.
- Expense basis.
- Awaiting review count.
- Credit/debit pie chart for the selected period.
- Expense-only category graph based on debits.
- Top merchants.

Dashboard behavior:

- `Exclude Business` removes rows where category or type is Business from the dashboard charts.
- `Use my share for split debits` makes shared debit expenses count only `my_share` in expense views.
- Credit/debit pie uses actual bank credits/debits.
- List-heavy sections are collapsed by default and expand when their label is clicked:
  - Credit / debit search
  - Transactions awaiting review
  - Edit classifications
  - Merchant knowledge base
  - Shared expenses
- The recent transactions section has been removed.
- Exports are shown at the bottom of the dashboard.

### Search

Review search:

- Filters pending review cases by merchant, description, date, category/type, debit/credit amount.

Credit/debit search:

- Dedicated section for searching any text/person name across transactions.
- Case-insensitive.
- Searches merchant, statement narration, reference, raw text, category/type, and amounts.
- Shows matching transaction count.
- Shows total credits, total debits, net amount.
- Shows credit/debit graph and matching transaction table.

### Export

- CSV export.
- JSON export.
- Exports are generated under `outputs/`.

## Important Design Decisions

- Original imported transactions remain immutable.
- Review/classification state is stored separately from raw transactions.
- Corrections to reviewed or automatic categories use the same feedback path as review confirmations.
- Learned merchant mappings are stored separately in `merchant_rules`.
- Learning is opt-in, not default.
- Existing pending rows can be swept by learned rules, but only when a rule confidently matches.
- Shared-expense math is based on your share ratio, derived from number of people.

## Known Limitations

- SBI statement layouts vary; real PDFs may require parser tuning in `expense_tracker/sbi_pdf.py`.
- Settlement tracking is not fully implemented yet.
- Credits from friends can be searched and categorized, but they are not yet linked to specific shared expenses.
- There is no editable merchant-rule management UI yet.
- Classification edits are batch-saved from the visible edit rows; there is not yet a full transaction detail page.
- No authentication; this is intended for local use only.
- No advanced natural language query layer yet.

## Verification

Current automated tests:

```text
19 tests passing
```

Run tests:

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```
