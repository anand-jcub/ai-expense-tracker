# Changelog

## 2026-07-03

### Added

- Added `state.md` to capture current project state, architecture, behavior, and limitations.
- Added `changelog.md` to track implementation changes.
- Added `Edit classifications` section for reviewed and automatically categorized transactions.
- Added classified-transaction search by merchant, narration, category/type, status, notes, and amount.
- Added batch save for classification corrections.
- Added classification notes to dashboard data and CSV/JSON exports.
- Added manual transaction entry for transactions outside bank statements.
- Added manual debit/credit support with category, type, people split, notes, and optional learning.
- Added dashboard period controls:
  - Start date
  - End date
  - Exclude Business
  - Use my share for split debits
- Added credit/debit pie chart for the selected dashboard period.
- Added expenses-by-category graph based only on debits.
- Added support for showing shared debits by `my_share` when selected.
- Added credit/debit person/text search:
  - Case-insensitive search.
  - Searches merchant, narration, reference, raw text, category/type, and amounts.
  - Shows total credits, total debits, net, graph, and matching rows.

### Changed

- `Learn` is now unchecked by default in the review queue.
- Dashboard top section now focuses on period-specific credit/debit/expense analytics.
- Business exclusion applies to dashboard credit/debit and expense charts.
- Correcting an automatic classification now reuses the review feedback path and marks the row as `reviewed`.
- Credit/debit search, review, classification editing, merchant rules, and shared expenses now open only when their labels are clicked.
- Exports moved to the bottom of the dashboard.
- Removed the recent transactions section from the dashboard.

### Fixed

- Learned merchant matching now handles text variants like `bb now` vs `bbnow`.
- Merchant normalization now ignores variable tokens containing digits.
- Confirming a learned merchant now sweeps matching pending rows out of review.
- Existing learned rules are applied to pending rows when the database initializes.

### Verified

- Split people logic verified through the database review path:
  - 1 person -> 100% my share
  - 2 people -> 50% my share
- Manual debit and credit persistence verified.
- Test suite passing with 19 tests.

## 2026-07-02

### Added

- Created local-first SBI expense tracker app.
- Added password-protected PDF import.
- Added SBI transaction extraction using `pdfplumber`.
- Added SQLite database.
- Added immutable `transactions` table.
- Added separate `classifications` table.
- Added `merchant_rules` knowledge base.
- Added `feedback_events` audit trail.
- Added import duplicate detection by PDF hash.
- Added seeded merchant classification rules:
  - Swiggy -> Food
  - Zomato -> Food
  - BigBasket -> Groceries
  - Netflix -> Subscription
  - Other common transport/utilities/subscription merchants
- Added review queue for unknown transactions.
- Added merchant learning from user confirmation.
- Added shared expense support.
- Added People-based split input.
- Added dashboard with totals, category spend, weekly trend, top merchants, recent transactions, shared expenses, and merchant rules.
- Added CSV and JSON exports.

### Changed

- Review amount display changed from debit-only to signed amount:
  - `+ Rs ...` for credits
  - `- Rs ...` for debits
- Review date sorting added:
  - Newest first
  - Oldest first
- Review split input changed from raw ratio to number of people.
- People default changed from `2` to `1`.
- Review form changed from per-row confirm buttons to one bottom-level batch confirm button.
- Review queue gained search.

### Fixed

- Credit transactions in review no longer display as `Rs 0.00`.
- Shared expense display now shows split as `1/2`, `1/3`, etc. instead of raw decimals.
- Review dashboard updates after batch confirmation.

### Verified

- Test suite grew incrementally from 4 tests to 13 tests as features were added.
