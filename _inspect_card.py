import sqlite3
c = sqlite3.connect('daemon/helmdeck.db')
c.row_factory = sqlite3.Row
row = c.execute("SELECT * FROM cards WHERE id='20260824-200523-machine'").fetchone()
if row:
    for k in row.keys():
        print(k, '=', repr(row[k])[:400])
else:
    print('not found')
