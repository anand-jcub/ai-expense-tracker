"""Remove empty duplicate seeded contacts (keep lowest id per name)."""
from expense_tracker.db import DATA_DIR, connect

SEED_NAMES = {"Highnes", "Ranjima", "Ananthu", "Bipin", "Anupriya"}

with connect(DATA_DIR / "expenses_anand.db") as conn:
    removed = []
    for name in sorted(SEED_NAMES):
        rows = conn.execute(
            """
            SELECT c.id,
                   (SELECT count(*) FROM ledger_entries le WHERE le.contact_id = c.id) AS n
            FROM contacts c
            WHERE c.name = ?
            ORDER BY c.id
            """,
            (name,),
        ).fetchall()
        if len(rows) <= 1:
            continue
        keep = rows[0]["id"]
        for r in rows[1:]:
            if int(r["n"] or 0) > 0:
                print(f"SKIP delete id={r['id']} name={name!r} has {r['n']} ledger rows")
                continue
            conn.execute("DELETE FROM contacts WHERE id = ?", (r["id"],))
            removed.append((name, r["id"], keep))
            print(f"deleted empty duplicate {name!r} id={r['id']} (kept {keep})")
    conn.commit()
    print(f"\nRemoved {len(removed)} empty duplicates")

    print("\nRemaining seed-like / Anand* contacts:")
    rows = conn.execute(
        """
        SELECT id, name,
               (SELECT count(*) FROM ledger_entries le WHERE le.contact_id = contacts.id) AS n
        FROM contacts
        WHERE lower(name) LIKE '%ananth%'
           OR lower(name) LIKE '%anandu%'
           OR name IN ('Highnes','Ranjima','Ananthu','Bipin','Anupriya')
        ORDER BY name, id
        """
    ).fetchall()
    for r in rows:
        print(f"  id={r['id']:4}  ledger={r['n']:3}  {r['name']!r}")
