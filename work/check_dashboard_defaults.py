import re
from datetime import date

from expense_tracker.auth import get_all_usernames
from expense_tracker.db import DATA_DIR, connect, dashboard_data
from expense_tracker.templates import page

with connect(DATA_DIR / "expenses_anand.db") as conn:
    data = dashboard_data(conn)
    html = page(
        data,
        None,
        None,
        exclude_business=True,
        current_user="anand",
        all_users=get_all_usernames(),
    ).decode()

m = re.search(r'name="start_date" value="([^"]+)"', html)
e = re.search(r'name="end_date" value="([^"]+)"', html)
c = re.search(r'name="exclude_business"[^>]*>', html)
print("start", m.group(1) if m else None)
print("end", e.group(1) if e else None)
print("exclude_tag", c.group(0) if c else None)
print("exclude_checked", c and "checked" in c.group(0))
print("expected_month", date.today().strftime("%Y-%m"))
