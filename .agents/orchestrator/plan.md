# Orchestrator Execution Plan

## Objective
Diagnose and resolve the date filtering defect where transactions disappear from Money Flow and Transactions tabs when a time period filter is selected, ensuring strict architectural compliance with feature contract FC-01.

## Milestones

### Milestone 1: Baseline Architecture Check & Exploration
- **Target**: Run baseline architecture check (`python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones P,E --feature FC-01`).
- **Target**: Investigate `db.py`, `services.py`, `templates.py`, and related modules to trace date range handling (`start_date`, `end_date`), SQL queries, and template data structures (`transactions`, `shared`, `pending`).
- **Deliverables**: Baseline architecture check output, technical root-cause report from Explorers.

### Milestone 2: Defect Remediation & Implementation
- **Target**: Fix root cause in `db.py`, `services.py`, `templates.py` or associated logic.
- **Rules**:
  - Home tab attention strip counts MUST remain all-time.
  - Money Flow and Transactions tab charts/UI MUST correctly display in-period data without dropping valid transactions.
  - Compliance with FC-01 contract and zone constraints (Zones P, E).
- **Deliverables**: Modified code, passing unit tests, implementation report.

### Milestone 3: Comprehensive Verification & Audit
- **Target**:
  1. Python verification script asserting rendered transaction count matches direct SQL `COUNT(*)` for given date ranges.
  2. Full `pytest` test suite execution.
  3. Architecture check pass (`python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones P,E --feature FC-01`).
  4. Forensic audit (`teamwork_preview_auditor`).
- **Deliverables**: Verification script report, test run log, clean audit report.

### Milestone 4: Final Victory Reporting
- **Target**: Notify parent Sentinel (`7ad88d3a-db61-46dc-abea-a93e243eb6f7`) with full victory claim.
