# AI-Powered Personal Expense Tracker - Phase 1

This is a local-first Phase 1 system for importing weekly password-protected SBI statement PDFs, extracting transactions, learning merchant categorization rules, asking for confirmation on unknown transactions, and showing a spending dashboard.

## Run (recommended — stays up)

From the project folder, use the watchdog launcher so the app **auto-restarts**
if it crashes, and survives after the terminal closes:

```powershell
cd C:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai
.\start.ps1
```

Then open:

```text
http://127.0.0.1:8765
```

| Script | Purpose |
|--------|---------|
| `.\start.ps1` | Start (or no-op if already up) |
| `.\stop.ps1` | Stop server + watchdog |
| `.\restart.ps1` | Bounce cleanly |

One-shot (no auto-restart): `.\venv\Scripts\python.exe app.py`

## What Phase 1 Supports

- Password-protected SBI PDF import through `pdfplumber`.
- Immutable raw transaction rows in SQLite.
- Separate `classifications` table for category/type/split/review state.
- Separate `merchant_rules` table for learned merchant mappings.
- Automatic categorization for known merchants and seeded examples like Swiggy, Zomato, BigBasket, Netflix.
- Review queue for unknown merchants.
- Feedback learning: confirmed merchant mappings are reused in future imports.
- Shared expense support with configurable number of people, defaulting to 1 person.
- Dashboard for total spend, category spend, weekly trend, top merchants, review queue, shared expenses, and effective personal share.
- List-heavy dashboard sections expand when clicked.
- CSV and JSON exports from the bottom of the dashboard.

## Data Model

The app writes to:

```text
data/expenses.db
```

Important tables:

- `imports`: one row per imported PDF file.
- `transactions`: immutable extracted bank transactions.
- `classifications`: editable categorization/review metadata. Shared splits are stored internally as ratios, so 1 person is stored as `1.0` and 2 people is stored as `0.5`.
- `merchant_rules`: learned merchant knowledge base.
- `feedback_events`: audit trail of user confirmations.

## Notes on SBI PDFs

SBI statement layouts can vary across account types and statement generators. The extractor first tries table extraction and then falls back to line-based parsing. If the first real PDF exposes a layout variant, improve only `expense_tracker/sbi_pdf.py`; the rest of the app is isolated from parser changes.

## Tests

```powershell
& 'C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```
