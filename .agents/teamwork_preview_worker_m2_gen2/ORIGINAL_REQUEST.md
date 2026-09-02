## 2026-07-26T19:57:24Z

You are Worker 1 (Gen 2 replacement) for Milestone 2 (Khata Domain Logic Refactoring).
Your working directory is: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_worker_m2_gen2\

Context:
Your predecessor experienced a network timeout. You are resuming execution from step 1.
Read the Explorer 1 handoff report at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_1\handoff.md, PROJECT.md at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\orchestrator\PROJECT.md, and AGENTS.md at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\AGENTS.md.

Task:
Refactor expense_tracker/contacts.py into clean, single-responsibility domain functions, decoupled data access layers, and explicit boundaries between contact management, ledger calculation, and pass-through tracking.

Requirements:
1. Re-organize/modularize expense_tracker/contacts.py into 3 distinct logical sections (or sub-modules):
   - Data Access Layer: Isolated SQL database functions (`_fetch_all_contacts`, `_fetch_ledger_entries`, `_insert_contact_record`, `_update_contact_record`, `_insert_ledger_entry`, `_soft_void_ledger_entry`, `_fetch_candidate_transactions`).
   - Pure Domain & Financial Calculation Layer: Pure functions free of SQLite connection dependencies (`split_aliases`, `_token_in_text`, `_score_contact_match`, `_calculate_net_balance`, `_build_running_ledger`, `_determine_settlement_params`).
   - Service Orchestration Layer: Public API facade functions (`create_contact`, `update_contact`, `get_all_contacts`, `find_contact_by_text`, `add_ledger_entry`, `get_balance`, `get_ledger`, `get_all_balances`, `record_opening_balance`, `record_settlement`, `void_ledger_entry`, `add_rolling_entry`, `detect_passthrough_candidates`).
2. Add explicit Python type hints across all functions.
3. Optimize `detect_passthrough_candidates` to prevent N+1 queries by pre-fetching `get_all_contacts(conn)` once before iterating over transaction candidates.
4. Maintain 100% backward compatibility for all existing function signatures, return dictionary keys, and legacy aliases (`calculate_contact_balance`, `get_contact_ledger`).
5. Run build/test verification after implementation:
   - `python -m py_compile expense_tracker/contacts.py`
   - `python -m pytest tests/test_contacts_ledger.py tests/test_core.py`
   - `python expense_tracker/e2e_test.py`
   - `python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03`

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Deliverables:
- Initialize progress.md in your working directory.
- Document all implementation details, commands run, and test results in handoff.md.
- Send a completion message to orchestrator (ID: 0a0f5ba9-c2f1-4654-9a4e-33c9078ba339) with the path to handoff.md.
