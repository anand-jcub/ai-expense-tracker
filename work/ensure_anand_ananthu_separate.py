"""Ensure Anand (user) is never an alias of contact Ananthu."""
import json
from expense_tracker.db import DATA_DIR, connect

FORBIDDEN = {"anand"}  # app user / different person — not Ananthu

with connect(DATA_DIR / "expenses_anand.db") as conn:
    rows = conn.execute(
        """
        SELECT id, name, aliases_json
        FROM contacts
        WHERE lower(name) LIKE '%ananth%'
           OR lower(name) LIKE '%anandu%'
           OR lower(coalesce(aliases_json, '')) LIKE '%anand%'
        ORDER BY id
        """
    ).fetchall()
    for r in rows:
        try:
            aliases = json.loads(r["aliases_json"] or "[]")
        except Exception:
            aliases = []
        cleaned = [a for a in aliases if a.strip().lower() not in FORBIDDEN]
        if cleaned != aliases:
            conn.execute(
                "UPDATE contacts SET aliases_json = ? WHERE id = ?",
                (json.dumps(cleaned), r["id"]),
            )
            print(f"cleaned id={r['id']} {r['name']!r}: {aliases} -> {cleaned}")
        else:
            print(f"ok id={r['id']} {r['name']!r} aliases={aliases}")
    conn.commit()
