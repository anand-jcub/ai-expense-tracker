"""Quick end-to-end test: render the full dashboard page and check it loads correctly."""
import sys
sys.path.insert(0, '.')

from pathlib import Path
from expense_tracker.db import connect, init_db, dashboard_data
from expense_tracker.templates import page, login_page, register_page
from expense_tracker.services import compute_partner_balances

# Test login page renders
lp = login_page()
assert b'Sign in' in lp, "Login page missing Sign in button"
assert b'auth-card' in lp, "Login page missing auth-card class"
print("login_page: OK")

# Test register page renders
rp = register_page()
assert b'Create account' in rp, "Register page missing Create account"
print("register_page: OK")

# Test error states render
lp_err = login_page(error="Wrong password")
assert b'Wrong password' in lp_err
print("login_page(error): OK")

rp_msg = register_page(message="Account created!")
assert b'Account created!' in rp_msg
print("register_page(message): OK")

# Test dashboard page renders for anand
db_path = Path('data/expenses_anand.db')
if db_path.exists():
    conn = connect(db_path)
    init_db(conn)
    data = dashboard_data(conn)
    balances = compute_partner_balances(conn, 'anand', ['anand', 'sonali'])
    conn.close()
    
    html = page(
        data,
        message="Test message",
        current_user="anand",
        all_users=["anand", "sonali"],
        partner_balances=balances,
    )
    assert b'Expense Tracker' in html
    assert b'anand' in html.lower() or b'Anand' in html
    # Check Loops tab is gone
    assert b'data-tab="loops"' not in html, "Loops tab should be gone!"
    # Check logout is present  
    assert b'logout' in html.lower(), "Logout button missing"
    print(f"dashboard page: OK (size: {len(html):,} bytes)")
    print(f"  transactions: {len(data['transactions'])}")
    print(f"  pending: {len(data['pending'])}")
    print(f"  partner balances: {balances}")
else:
    print("SKIP: No anand DB found")

print("\nALL TESTS PASSED")
