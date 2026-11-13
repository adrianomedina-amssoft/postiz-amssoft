import importlib.util,sqlite3,datetime as dt
from pathlib import Path
spec=importlib.util.spec_from_file_location('rotation',str(Path(__file__).with_name('rotation.py')));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
now=dt.datetime(2026,11,13,5,tzinfo=dt.timezone.utc)
def scenario(state='created',postid='post',active=0,minutes=120):
 d=sqlite3.connect(':memory:');d.row_factory=sqlite3.Row;d.executescript('CREATE TABLE assets(hash TEXT,active INTEGER,media TEXT);CREATE TABLE slots(at TEXT,hash TEXT,postid TEXT,state TEXT,error TEXT);');d.execute('INSERT INTO assets VALUES(?,?,?)',('hash',active,'{"id":"media"}'));d.execute('INSERT INTO slots VALUES(?,?,?,?,NULL)',((now+dt.timedelta(minutes=minutes)).isoformat(),'hash',postid,state));d.commit();return d
# Confirmed future cancellation removes reservation and is idempotent.
d=scenario();post={'id':'post','state':'QUEUE','deletedAt':None};calls=[]
def lookup(s):return [post]
def cancel(i):calls.append(i);post['deletedAt']='deleted'
assert not m.retire_missing(d,now,lookup,cancel);assert calls==['post'];assert d.execute('SELECT count(*) FROM slots').fetchone()[0]==0
assert not m.retire_missing(d,now,lookup,cancel) and calls==['post']
# Active assets are untouched.
d=scenario(active=1);assert not m.retire_missing(d,now,lambda s:1/0,lambda i:1/0)
# No API attempt was made for an unsubmitted prepared reservation.
d=scenario('prepared',None);assert not m.retire_missing(d,now,lambda s:1/0,lambda i:1/0);assert not d.execute('SELECT * FROM slots').fetchall()
# Ambiguous creations stay blocked for reconciliation.
d=scenario('creating',None);assert m.retire_missing(d,now,lambda s:[],lambda i:1/0);assert d.execute('SELECT count(*) FROM slots').fetchone()[0]==1
# Imminent or already-published requests are not silently rewritten.
for state,minutes in [('QUEUE',2),('PUBLISHED',120)]:
 d=scenario(minutes=minutes);assert m.retire_missing(d,now,lambda s:[{'id':'post','state':state,'deletedAt':None}],lambda i:1/0)
# Failed confirmation keeps reservation, preventing replacement duplicate.
d=scenario();assert m.retire_missing(d,now,lambda s:[{'id':'post','state':'QUEUE','deletedAt':None}],lambda i:None);assert d.execute('SELECT count(*) FROM slots').fetchone()[0]==1
print('PASS: future cancellation, idempotence, active preservation, prepared cleanup, ambiguous creation, imminent/published safety, deletion confirmation')
