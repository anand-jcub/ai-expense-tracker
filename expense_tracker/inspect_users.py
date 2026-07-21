import sqlite3

conn = sqlite3.connect("data/users.db")
conn.row_factory = sqlite3.Row

# Get tables
print("TABLES IN users.db:")
tables = conn.execute("select name from sqlite_master where type='table'").fetchall()
for t in tables:
    print(t["name"])
    # print columns
    cols = conn.execute(f"pragma table_info({t['name']})").fetchall()
    for col in cols:
        print(f"  {col['name']}: {col['type']}")

# Get all users
print("\nUSERS:")
users = conn.execute("select * from users").fetchall()
for u in users:
    print(dict(u))

# Get all sessions
print("\nSESSIONS:")
sessions = conn.execute("select * from sessions").fetchall()
for s in sessions:
    print(dict(s))

conn.close()
