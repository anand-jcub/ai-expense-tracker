## 2026-07-26T14:27:34Z
<USER_REQUEST>
You are Worker 1 (Gen 2 Replacement) for Milestone 2: Refactor Khata Domain Logic (expense_tracker/contacts.py).
Working directory: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_worker_m2_1_gen2
Your identity: teamwork_preview_worker

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & Rules:
- Primary Zone: D (Khata / People / ledger), Feature Contract: FC-03.
- Refer to AGENTS.md rules and c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\orchestrator\PROJECT.md.
- Review Explorer 1's report at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_1\handoff.md for details.

Task Specification:
1. Refactor expense_tracker/contacts.py to separate:
   - Data Access Layer (SQL queries for contacts, ledger entries, candidate transactions)
   - Pure Domain Calculators (net balance math, running ledger calculation, settlement rules, alias parsing, token matching, contact search scoring)
   - High-level Service Orchestration (contact CRUD, add ledger entry, record settlement, rolling entry, opening balance, void entry, candidate detection)
2. Retain expense_tracker/contacts.py as the top-level public facade preserving 100% backward-compatible function signatures:
   - create_contact, update_contact, get_all_contacts, find_contact_by_text
   - add_ledger_entry, record_opening_balance, record_settlement, void_ledger_entry
   - get_balance, get_ledger, get_all_balances
   - add_rolling_entry, detect_passthrough_candidates
   - calculate_contact_balance, get_contact_ledger (aliases)
3. Optimize detect_passthrough_candidates to eliminate N+1 queries by fetching contacts once.
4. Add clear type hints across all refactored domain logic.
5. Verification:
   - Run python -m py_compile expense_tracker/contacts.py
   - Run python -m pytest tests/test_contacts_ledger.py tests/test_core.py
   - Run python expense_tracker/e2e_test.py
   - Run python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones D --feature FC-03
6. Document changes, test outputs, and architecture check status in c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_worker_m2_1_gen2\handoff.md.
7. Send completion message back to orchestrator.
</USER_REQUEST>
