from expense_tracker import templates
import inspect

src_full = inspect.getsource(templates)

checks = [
    ('loops tab', 'Loops'),
    ('review debits/credits split', 'debit_review'),
    ('business mode', 'render_business_mode'),
    ('period credits list', 'period_credits_list'),
    ('period debits list', 'period_debits_list'),
    ('my expenses card', 'My Expenses'),
    ('exclude business checkbox', 'exclude_business'),
    ('money flow', 'money_flow'),
    ('login/logout', 'logout'),
    ('multi-user auth', 'current_user'),
    ('switch dashboard tab', 'switchDashboardTab'),
]

for label, keyword in checks:
    found = keyword in src_full
    status = 'PRESENT' if found else 'MISSING'
    print(f'  {label}: {status}')

print()
print('Total lines in templates.py:', src_full.count('\n'))
