import sqlite3, sys

conn = sqlite3.connect('daemon/helmdeck.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cid = sys.argv[1] if len(sys.argv) > 1 else '20260824-200543-machine-3'
cur.execute('SELECT * FROM cards WHERE id=?', (cid,))
row = cur.fetchone()
if row:
    d = dict(row)
    for k, v in d.items():
        print(k, '=', str(v)[:800])
else:
    print('not found')
