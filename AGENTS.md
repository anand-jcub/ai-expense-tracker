# Agent instructions — AI Expense Tracker

## Architecture guardian

Before multi-file feature work (add/remove/change behavior), run the **architecture agent**:

- Constitution: `KEY_PRINCIPLES.md`
- Skill: `.grok/skills/architecture-agent/SKILL.md` (`/architecture-agent`)
- Map: `docs/architecture-map.md`
- Coherence contracts: `docs/feature-coherence.md`
- Script (read-only) — **isolation + completeness**:

```powershell
.\venv\Scripts\python.exe .grok\skills\architecture-agent\scripts\architecture_check.py --intent-zones <ZONES> --feature FC-01
```

**Rules for implementers**

1. Stay inside the **primary zone** named in the architecture review.
2. Do not touch other feature zones to “while we’re here” fix things.
3. Shared files (`web.py`, `templates.py`, `db.py`) may only gain **thin** wiring for the approved intent.
4. **Completeness:** if the feature has a contract (`FC-*`), every **Must cover** surface must be done in the same change (e.g. dashboard date range filters **all** period sections — not only graphs).
5. If the architecture agent returns **FAIL**, stop and re-scope; do not land the change.
6. The architecture agent **never implements features** — only audits.

## Zones (short)

| ID | Area |
|----|------|
| A | Auth |
| B | Import / bank PDF |
| C | Classification / review |
| D | Khata / People / ledger |
| E | Dashboard spend analytics |
| F | React `/app` |
| G | Ops / process |
| H | Tests |
| I | Assistant (Gemini tools + confirm) |
| J | Cloud snapshot (Worker REST / glance) |
| P | Shared edge (`web`, `templates`, `db`) |

## Feature contracts (short)

| ID | Feature |
|----|---------|
| FC-01 | Dashboard period filter consistency |
| FC-02 | Exclude business consistency |
| FC-03 | Contact rename / aliases |
| FC-04 | Rolling / pass-through |
| FC-05 | Shared partner |
| FC-06 | React vs classic shells |
| FC-07 | Mobile / Ask / Graphs share dashboard summary |
| FC-08 | Assistant writes need confirm |
| FC-09 | Live vs snapshot share mobile APIs |

## Data Presentation & Classifier Invariants

1. **No Silent Capping**: When rendering lists filtered by date period or category, never apply hardcoded array slices (e.g. `rows[:40]`, `flow_txns[:50]`) inside template loops. If pagination is needed, implement explicit page controls.
2. **UPI Merchant Naming**: `expense_tracker/classifier.py` is the single source of truth for payee display strings. Preserve initials (e.g. `"Mathew C P"`) and expand brands via `_UPI_BRAND_MAP`. Any parser updates must be backfilled to existing SQLite databases.
3. **Shared Expense Defaults**: Default split count is 2 people unless specified otherwise.
4. **User Review Immutability**: Any transaction with `status = 'reviewed'` or user-confirmed split ratio is strictly immutable to automated re-classification, re-imports, or batch classifier scripts. Reclassification operations must only target unreviewed items (`WHERE status != 'reviewed'`).

## Local run

Prefer silent watchdog:

```powershell
.\start.ps1
```
