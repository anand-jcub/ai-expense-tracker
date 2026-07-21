import sys
sys.path.insert(0, '.')
import expense_tracker.templates as T
import expense_tracker.web as W
import expense_tracker.services as S
import inspect

t_src = inspect.getsource(T)
w_src = inspect.getsource(W)
s_src = inspect.getsource(S)

checks = [
    ('templates', 'Loops tab present', 'Loops', t_src, False),
    ('templates', 'debit_review split', 'debit_review', t_src, True),
    ('templates', 'business mode removed', 'render_business_mode', t_src, False),
    ('templates', 'period_credits_list', 'period_credits_list', t_src, True),
    ('templates', 'period_debits_list', 'period_debits_list', t_src, True),
    ('templates', 'My Expenses card', 'My Expenses', t_src, True),
    ('templates', 'exclude_business', 'exclude_business', t_src, True),
    ('templates', 'money_flow section', 'money_flow', t_src, True),
    ('templates', 'logout button', 'logout', t_src, True),
    ('templates', 'current_user', 'current_user', t_src, True),
    ('templates', 'partner_balances', 'partner_balances', t_src, True),
    ('templates', 'shared_with dropdown', 'shared_with', t_src, True),
    ('templates', 'payer_badge avatars', 'payer_badge', t_src, True),
    ('templates', 'switchDashboardTab', 'switchDashboardTab', t_src, True),
    ('web', 'auth/session check', 'get_session_username', w_src, True),
    ('web', 'login handler', 'handle_login', w_src, True),
    ('web', 'sync_shared_transaction', 'sync_shared_transaction', w_src, True),
    ('web', 'DualStackServer', 'DualStackServer', w_src, True),
    ('services', 'compute_partner_balances', 'compute_partner_balances', s_src, True),
    ('services', 'get_household_balances', 'get_household_balances', s_src, True),
    ('services', 'exclude_business in filter', 'exclude_business', s_src, True),
]

for module, label, keyword, src, want_present in checks:
    found = keyword in src
    ok = found == want_present
    verdict = 'OK' if ok else 'MISSING' if want_present else 'EXTRA (should be gone)'
    print(f'[{verdict}] [{module}] {label}')

print()
print('templates.py lines:', t_src.count('\n'))
print('web.py lines:', w_src.count('\n'))
print('services.py lines:', s_src.count('\n'))
