#!/usr/bin/env python3
"""Architecture checker: isolation (blast radius) + completeness (feature coverage).

Read-only. Does not modify the project.

Usage (from repo root):
  python .grok/skills/architecture-agent/scripts/architecture_check.py
  python .grok/skills/architecture-agent/scripts/architecture_check.py --base origin/master
  python .grok/skills/architecture-agent/scripts/architecture_check.py --feature FC-01
  python .grok/skills/architecture-agent/scripts/architecture_check.py --intent-zones E,P --feature FC-01
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # repo root

ZONE_RULES: list[tuple[str, str, str]] = [
    (r"^expense_tracker/auth\.py$", "A", "Auth"),
    (r"^data/users\.db$", "A", "Auth"),
    (r"^expense_tracker/sbi_pdf\.py$", "B", "Import/bank"),
    (r"^expense_tracker/classifier\.py$", "C", "Classification"),
    (r"^expense_tracker/learning_engine\.py$", "C", "Classification"),
    (r"^expense_tracker/contacts\.py$", "D", "Khata/People"),
    (r"^expense_tracker/static/(app\.js|style\.css)$", "D", "Khata/People+UI"),
    (r"^expense_tracker/services\.py$", "E", "Dashboard spend"),
    (r"^frontend/", "F", "React shell"),
    (r"^(app\.py|run_forever\.py|start\.ps1|stop\.ps1|restart\.ps1)$", "G", "Ops"),
    (r"^tests/", "H", "Tests"),
    (r"^expense_tracker/db\.py$", "P", "Persistence (shared)"),
    (r"^expense_tracker/web\.py$", "P", "HTTP edge (shared)"),
    (r"^expense_tracker/templates\.py$", "P", "Classic UI (shared)"),
    (r"^docs/", "DOC", "Docs"),
    (r"^README\.md$", "DOC", "Docs"),
    (r"^\.grok/", "META", "Agent meta"),
    (r"^AGENTS\.md$", "META", "Agent meta"),
]

SHARED_ZONES = {"P"}

# Feature completeness probes: id → list of (surface, required patterns in codebase)
# Status is COVERED if all patterns match somewhere in the listed files.
FEATURE_PROBES: dict[str, dict] = {
    "FC-01": {
        "title": "Dashboard period filter",
        "files": [
            ROOT / "expense_tracker" / "templates.py",
            ROOT / "expense_tracker" / "services.py",
            ROOT / "expense_tracker" / "web.py",
        ],
        "surfaces": [
            {
                "name": "period_rows built with start/end + exclude_business",
                "all_of": [
                    r"period_rows\s*=\s*filter_dashboard_rows",
                    r"start_date",
                    r"end_date",
                    r"exclude_business",
                ],
            },
            {
                "name": "metrics use period_totals from period_rows",
                "all_of": [
                    r"period_totals\s*=\s*dashboard_totals\(\s*period_rows",
                    r"period_totals",
                ],
            },
            {
                "name": "category chart uses period_rows / period_categories",
                "all_of": [
                    r"period_categories",
                    r"expenses_by_category\(\s*period_rows",
                ],
            },
            {
                "name": "merchant chart uses period_rows / period_merchants",
                "all_of": [
                    r"period_merchants",
                    r"top_merchants_from_rows\(\s*period_rows|debits_by_merchant\(\s*period_rows",
                ],
            },
            {
                "name": "credit/debit pie uses period_totals",
                "all_of": [
                    r"render_credit_debit_pie\(\s*period_totals",
                ],
            },
        ],
        "warn_if_missing_patterns": [
            (
                r"data\[\"transactions\"\].*period|period.*data\[\"transactions\"\]",
                "Double-check no chart still binds unfiltered data['transactions'] for period UI",
            ),
        ],
    },
    "FC-02": {
        "title": "Exclude business",
        "files": [
            ROOT / "expense_tracker" / "templates.py",
            ROOT / "expense_tracker" / "services.py",
            ROOT / "expense_tracker" / "web.py",
        ],
        "surfaces": [
            {
                "name": "exclude_business threaded into filter_dashboard_rows",
                "all_of": [
                    r"filter_dashboard_rows\([^\)]*exclude_business",
                    r"exclude_business",
                ],
            },
            {
                "name": "default exclude business on first load",
                "all_of": [
                    r"exclude_business\s*=\s*\(",
                    r"period_touched|True",
                ],
            },
        ],
    },
    "FC-03": {
        "title": "Contact rename / aliases",
        "files": [
            ROOT / "expense_tracker" / "contacts.py",
            ROOT / "expense_tracker" / "templates.py",
            ROOT / "expense_tracker" / "web.py",
            ROOT / "expense_tracker" / "static" / "app.js",
        ],
        "surfaces": [
            {
                "name": "update_contact exists and edit route",
                "all_of": [
                    r"def update_contact",
                    r"/contacts/edit|handle_contact_edit",
                ],
            },
            {
                "name": "People UI edit modal",
                "all_of": [
                    r"openEditContactModal|modal-edit-contact",
                ],
            },
        ],
    },
    "FC-04": {
        "title": "Rolling / pass-through",
        "files": [
            ROOT / "expense_tracker" / "contacts.py",
            ROOT / "expense_tracker" / "web.py",
        ],
        "surfaces": [
            {
                "name": "balance excludes passthrough",
                "all_of": [
                    r"is_passthrough",
                    r"get_balance|def get_balance",
                ],
            },
            {
                "name": "rolling posts PT legs",
                "all_of": [
                    r"add_rolling_entry|is_passthrough\s*=\s*True",
                ],
            },
        ],
    },
}


def git_files(base: str | None) -> list[str]:
    cmds = []
    if base:
        cmds.append(["git", "diff", "--name-only", f"{base}...HEAD"])
    cmds.append(["git", "diff", "--name-only"])
    cmds.append(["git", "diff", "--name-only", "--cached"])
    cmds.append(["git", "ls-files", "--others", "--exclude-standard"])
    files: set[str] = set()
    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        for line in out.splitlines():
            line = line.strip().replace("\\", "/")
            if line:
                files.add(line)
    return sorted(files)


def classify(path: str) -> tuple[str, str]:
    for pat, zid, label in ZONE_RULES:
        if re.search(pat, path):
            return zid, label
    return "?", f"Unmapped ({path})"


def read_joined(paths: list[Path]) -> str:
    chunks: list[str] = []
    for p in paths:
        try:
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(chunks)


def check_feature(feature_id: str) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Returns (blocks, warnings, coverage_rows)."""
    blocks: list[str] = []
    warnings: list[str] = []
    rows: list[tuple[str, str]] = []
    fid = feature_id.upper()
    if fid not in FEATURE_PROBES:
        warnings.append(f"Unknown feature id {fid}; see docs/feature-coherence.md")
        return blocks, warnings, rows

    spec = FEATURE_PROBES[fid]
    blob = read_joined(spec["files"])
    print(f"\nCompleteness probe: {fid} — {spec['title']}")
    print("-" * 40)
    for surface in spec["surfaces"]:
        ok = all(re.search(pat, blob, re.I | re.S) for pat in surface["all_of"])
        status = "COVERED" if ok else "MISSING"
        rows.append((surface["name"], status))
        print(f"  [{status}] {surface['name']}")
        if not ok:
            blocks.append(f"{fid}: incomplete surface — {surface['name']}")
    for pat, msg in spec.get("warn_if_missing_patterns", []):
        # these are optional heuristic warnings if pattern FOUND (danger)
        if re.search(pat, blob, re.I | re.S):
            warnings.append(f"{fid}: {msg}")
    return blocks, warnings, rows


def auto_detect_features(diff: str, files: list[str]) -> list[str]:
    """Guess which FC contracts are relevant from the change set."""
    found: list[str] = []
    joined = " ".join(files).lower() + "\n" + diff.lower()
    rules = [
        ("FC-01", r"start_date|end_date|period_rows|filter_dashboard|dashboard period"),
        ("FC-02", r"exclude_business"),
        ("FC-03", r"update_contact|contacts/edit|openeditcontact|aliases"),
        ("FC-04", r"passthrough|add_rolling|is_passthrough|rolling"),
        ("FC-05", r"shared_with"),
        ("FC-06", r"frontend/|react"),
    ]
    for fid, pat in rules:
        if re.search(pat, joined, re.I):
            found.append(fid)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Architecture isolation + completeness check"
    )
    parser.add_argument("--base", default=None, help="git base ref (e.g. origin/master)")
    parser.add_argument(
        "--intent-zones",
        default="",
        help="Comma-separated expected zone ids (e.g. D,H)",
    )
    parser.add_argument(
        "--feature",
        action="append",
        default=[],
        help="Feature contract id to completeness-check (repeatable), e.g. FC-01",
    )
    parser.add_argument(
        "--no-auto-feature",
        action="store_true",
        help="Do not auto-detect FC contracts from the diff",
    )
    args = parser.parse_args()
    expected = {z.strip().upper() for z in args.intent_zones.split(",") if z.strip()}

    files = git_files(args.base)
    print("Architecture report (isolation + completeness)")
    print("=" * 48)

    if not files:
        print("No changed files detected — running completeness-only if features requested.")
    else:
        print(f"Changed files: {len(files)}")
        print()

    by_zone: dict[str, list[str]] = defaultdict(list)
    labels: dict[str, str] = {}
    for f in files:
        zid, label = classify(f)
        by_zone[zid].append(f)
        labels[zid] = label

    for zid in sorted(by_zone.keys()):
        print(f"[{zid}] {labels[zid]} ({len(by_zone[zid])} file(s))")
        for f in by_zone[zid]:
            print(f"  - {f}")
        print()

    feature_zones = {z for z in by_zone if z not in {"DOC", "META", "H", "?"}}
    shared_hit = sorted(feature_zones & SHARED_ZONES)
    multi = sorted(feature_zones - SHARED_ZONES)

    blocks: list[str] = []
    warnings: list[str] = []

    # Isolation
    if len(multi) >= 2:
        blocks.append(
            f"ISOLATION: multiple feature zones touched: {', '.join(multi)}. "
            "Split the change or get explicit cross-zone approval."
        )
    if shared_hit and multi:
        warnings.append(
            f"ISOLATION: shared edge/persistence {', '.join(shared_hit)} with feature "
            f"zones {', '.join(multi)}. Keep handlers thin."
        )
    elif shared_hit and not multi:
        warnings.append(
            f"ISOLATION: shared zone(s) only: {', '.join(shared_hit)}. "
            "Confirm no accidental domain logic in web/templates/db."
        )

    if expected:
        unexpected = [
            z
            for z in sorted(feature_zones)
            if z not in expected and z in (feature_zones | SHARED_ZONES)
        ]
        if unexpected:
            blocks.append(
                f"ISOLATION: zones outside declared intent {sorted(expected)}: {unexpected}"
            )

    try:
        diff = subprocess.check_output(
            ["git", "diff", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        diff = ""

    danger_patterns = [
        (r"def get_balance|you_sent.*they_sent", "Balance formula touch — confirm zone D only"),
        (r"settlement\.py|compute_unified_settlement", "Legacy USB settlement reference"),
        (r"\"anand\"", "Possible Anand/Ananthu identity bleed — verify alias lists"),
        (r"ALTER TABLE|DROP COLUMN|DELETE FROM transactions", "Schema/data destructive change"),
    ]
    for pat, msg in danger_patterns:
        if re.search(pat, diff, re.I):
            warnings.append(f"CONTRACT: {msg}")

    # Completeness
    features = [f.upper() for f in args.feature]
    if not args.no_auto_feature:
        for f in auto_detect_features(diff, files):
            if f not in features:
                features.append(f)
    # Always offer FC-01 baseline when dashboard templates/services touched
    if any(
        f.replace("\\", "/").startswith("expense_tracker/templates.py")
        or f.replace("\\", "/").startswith("expense_tracker/services.py")
        for f in files
    ):
        if "FC-01" not in features:
            features.append("FC-01")
        if "FC-02" not in features:
            features.append("FC-02")

    coverage_summary: list[tuple[str, str, str]] = []
    if features:
        print("Completeness (feature coverage)")
        print("=" * 48)
        for fid in features:
            b, w, rows = check_feature(fid)
            blocks.extend(b)
            warnings.extend(w)
            for name, status in rows:
                coverage_summary.append((fid, name, status))
    else:
        print("Completeness: no FC contracts selected (pass --feature FC-01 or touch feature files).")

    print()
    print("Findings")
    print("-" * 40)
    if blocks:
        for b in blocks:
            print(f"BLOCK: {b}")
    if warnings:
        for w in warnings:
            print(f"WARN:  {w}")
    if not blocks and not warnings:
        print("No isolation or completeness issues detected by heuristics.")

    if coverage_summary:
        print()
        print("Coverage matrix")
        print("-" * 40)
        for fid, name, status in coverage_summary:
            print(f"  {fid:6} {status:8} {name}")

    print()
    if blocks:
        print("VERDICT: FAIL")
        print(
            "Fix isolation leaks and/or complete every MUST-COVER surface "
            "(see docs/feature-coherence.md)."
        )
        return 2
    if warnings:
        print("VERDICT: WARN")
        return 1
    print("VERDICT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
