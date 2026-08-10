from expense_tracker.db import DATA_DIR, connect

with connect(DATA_DIR / "expenses_anand.db") as conn:
    rows = conn.execute(
        """
        SELECT id, name, hex(name) AS name_hex, length(name) AS nlen,
               aliases_json, created_at
        FROM contacts
        WHERE lower(name) LIKE '%ananth%' OR lower(name) LIKE '%anandu%'
        ORDER BY id
        """
    ).fetchall()
    for r in rows:
        print(dict(r))

    dups = conn.execute(
        """
        SELECT name, count(*) AS c
        FROM contacts
        GROUP BY name
        HAVING c > 1
        ORDER BY c DESC
        """
    ).fetchall()
    print("\nDuplicate names:")
    for r in dups:
        print(f"  {r['name']!r} x{r['c']}")

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='contacts'"
    ).fetchone()
    print("\nschema:", schema["sql"] if schema else None)
