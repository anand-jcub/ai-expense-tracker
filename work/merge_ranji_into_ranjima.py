"""Soft-merge Ranji bank fragments into Ranjima (same person)."""
import json
from expense_tracker.db import DATA_DIR, connect
from expense_tracker.contacts import get_balance, get_all_contacts

WINNER = 26  # Ranjima
LOSERS = [2, 3, 16]  # Ranjima Sbin, Ranji Idib Payme, Cr Ms Ranji Idib

with connect(DATA_DIR / "expenses_anand.db") as conn:
    winner = conn.execute(
        "SELECT id, name, aliases_json FROM contacts WHERE id = ?", (WINNER,)
    ).fetchone()
    if not winner:
        raise SystemExit("Ranjima not found")

    try:
        aliases = json.loads(winner["aliases_json"] or "[]")
    except Exception:
        aliases = []

    for lid in LOSERS:
        row = conn.execute(
            "SELECT id, name, aliases_json, merged_into_id FROM contacts WHERE id = ?",
            (lid,),
        ).fetchone()
        if not row:
            print(f"skip missing id={lid}")
            continue
        # collect aliases from loser name
        for a in [row["name"].lower().strip()]:
            if a and a not in aliases:
                aliases.append(a)
        try:
            for a in json.loads(row["aliases_json"] or "[]"):
                if a and a not in aliases:
                    aliases.append(a)
        except Exception:
            pass

        n = conn.execute(
            "UPDATE ledger_entries SET contact_id = ? WHERE contact_id = ?",
            (WINNER, lid),
        ).rowcount
        conn.execute(
            "UPDATE contacts SET merged_into_id = ? WHERE id = ?",
            (WINNER, lid),
        )
        print(f"merged id={lid} {row['name']!r} -> Ranjima; moved {n} ledger rows")

    for a in ["ranji", "ms ranji", "ranjima", "9497760612", "ranjima sbin"]:
        if a not in aliases:
            aliases.append(a)

    conn.execute(
        "UPDATE contacts SET aliases_json = ? WHERE id = ?",
        (json.dumps(aliases), WINNER),
    )
    conn.commit()
    print("Ranjima aliases:", aliases)
    print("Ranjima balance:", get_balance(conn, WINNER))
    print("visible contacts with ranji:")
    for c in get_all_contacts(conn):
        blob = (c["name"] + " " + " ".join(c.get("aliases") or [])).lower()
        if "ranji" in blob:
            print(f"  id={c['id']} {c['name']!r}")
