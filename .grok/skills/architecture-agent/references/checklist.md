# Architecture agent checklist

## Before reviewing

1. Read `docs/architecture-map.md`.
2. Read `docs/feature-coherence.md`.
3. Identify **declared intent** (one sentence).
4. Map intent → **primary zone** + **FC-*** contract id (if feature add/change).
5. Collect files: `git status` / `git diff --name-only`.

---

## A. Isolation (do not pollute other zones)

### Zone inventory

Map every touched file to a zone. Count feature zones (exclude DOC/META/H unless relevant).

- **1 zone** → low isolation risk  
- **2+ feature zones** → **FAIL** unless user approved coupling  

### Isolation questions

For each file outside the primary zone:

1. Why is it required for the declared intent?  
2. Could a thinner adapter work?  
3. Does it change behavior of an unrelated surface?  

### Isolation severity

| Severity | Meaning |
|----------|---------|
| **BLOCK** | Cross-zone behavior without approval |
| **WARN** | Shared file touched for convenience |
| **OK** | Confined to declared zone |

---

## B. Completeness (cover every surface that must change)

**Run this whenever intent is a feature add/change**, not only on large diffs.

### Completeness steps

1. Open the matching **FC-*** in `docs/feature-coherence.md`.  
2. If no FC exists for a multi-surface feature → **WARN** and draft one.  
3. Build a **coverage matrix**:

| Must-cover surface | Shared state used? | Status |
|--------------------|--------------------|--------|
| … | same `start_date`/`end_date`? | COVERED / MISSING / DIVERGENT |

4. Check **May ignore** surfaces are not mislabeled as filtered.  
5. Run the contract’s **Proof** bullets (grep/read).  

### Completeness severity

| Status | Meaning | Verdict impact |
|--------|---------|----------------|
| **MISSING** | Surface should use feature state but does not | **FAIL** |
| **DIVERGENT** | Uses different rules/dates than source of truth | **FAIL** |
| **COVERED** | Same shared state | OK |
| **N/A** | Listed under May ignore | OK if honest UX |

### Classic completeness traps

- Dashboard charts filtered; another Home widget still all-time.  
- Period form updates metrics; Transactions / search still full history without saying so.  
- `exclude_business` on one chart only.  
- Contact renamed in list but not in rolling dropdowns.  
- API updated; React shell still old contract.  

---

## C. Global contract probes

- [ ] Khata balance single-source (`contacts.get_balance`)  
- [ ] Pass-through excluded from net  
- [ ] Anand ≠ Ananthu; Ranji = Ranjima aliases  
- [ ] No spend math in `app.js` / React  
- [ ] Migrations additive  

---

## Output template

```markdown
## Architecture review

**Intent:** …
**Primary zone:** …
**Feature contract:** FC-0N (or none)

### Verdict: PASS | WARN | FAIL

### 1. Isolation
| File | Zone | Expected? | Risk |
|------|------|-----------|------|
| … | … | yes/no | … |

**Blast radius (unrelated surfaces that might break):** …

### 2. Completeness
**Shared state:** e.g. `start_date`, `end_date`, `exclude_business`

| Must-cover surface | Status | Evidence |
|--------------------|--------|----------|
| Period metrics | COVERED | `period_rows` → `dashboard_totals` |
| Category chart | MISSING | still uses unfiltered rows |
| … | … | … |

**May-ignore honesty:** …

**Gaps to close before merge:**
1. …
2. …

### 3. Required before merge
1. Isolation: …
2. Completeness: …

### 4. Approval gate
User must explicitly allow: …
```
