from expense_tracker import db, web, templates, services
print('All imports OK')
from pathlib import Path
conn = db.connect(Path('data/expenses_anand.db'))
db.init_db(conn)
# Check columns
cols_txn = [row[1] for row in conn.execute('PRAGMA table_info(transactions)').fetchall()]
cols_cls = [row[1] for row in conn.execute('PRAGMA table_info(classifications)').fetchall()]
print('transactions columns:', cols_txn)
print('classifications columns:', cols_cls)
print('uploaded_by present:', 'uploaded_by' in cols_txn)
print('source_txn_id present:', 'source_txn_id' in cols_txn)
print('shared_with present:', 'shared_with' in cols_cls)
conn.close()
print('ALL OK')
