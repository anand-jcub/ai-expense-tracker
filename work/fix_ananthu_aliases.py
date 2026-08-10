import json
from expense_tracker.db import DATA_DIR, connect

with connect(DATA_DIR / "expenses_anand.db") as conn:
    row = conn.execute(
        "SELECT id, aliases_json FROM contacts WHERE name = 'Ananthu' ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        raise SystemExit("no Ananthu")
    try:
        aliases = json.loads(row["aliases_json"] or "[]")
    except Exception:
        aliases = []
    for a in ["ananthu", "anandu", "anandhu", "anandusnai"]:
        if a not in aliases:
            aliases.append(a)
    # drop overly broad "anand" alias (matches your username / many strings)
    aliases = [a for a in aliases if a != "anand"]
    conn.execute(
        "UPDATE contacts SET aliases_json = ? WHERE id = ?",
        (json.dumps(aliases), row["id"]),
    )
    conn.commit()
    print("Ananthu", row["id"], aliases)
