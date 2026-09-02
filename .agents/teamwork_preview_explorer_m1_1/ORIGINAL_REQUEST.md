## 2026-07-26T13:57:30Z
<USER_REQUEST>
You are Explorer 1 for Milestone 1 of the Khata / People / Ledger refactoring project.
Working directory: c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_1
Your identity: teamwork_preview_explorer

Your task:
1. Initialize/update BRIEFING.md and progress.md in your working directory.
2. Read AGENTS.md at project root and PROJECT.md at c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\orchestrator\PROJECT.md.
3. Inspect expense_tracker/contacts.py completely. Analyze all functions, SQL queries, data structures, signatures, and module couplings.
4. Categorize functions into 3 explicit domain areas:
   - Contact Management (CRUD, aliases FC-03, renaming)
   - Ledger Calculations (running balances, settlements, itemized lines)
   - Pass-through Tracking (rolling credits/debits, cross-references)
5. Differentiate raw database data-access logic from pure domain calculations.
6. Propose a modular refactoring design that separates data access and domain logic while preserving 100% public API backwards compatibility for web.py and templates.py.
7. Document your complete analysis, map of functions, and proposed structure in c:\Users\User\Documents\Codex\2026-07-02\i-want-to-build-an-ai\.agents\teamwork_preview_explorer_m1_1\handoff.md.
8. Send a completion message back to the orchestrator referencing handoff.md.
</USER_REQUEST>
