import sqlite3, time
from pathlib import Path

class Store:
    def __init__(self,path='data/manager.sqlite3'):
        self.path=str(path); Path(self.path).parent.mkdir(parents=True,exist_ok=True); self.init()
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row; return db
    def init(self):
        with self.connect() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, ts REAL, pid INTEGER, name TEXT, cpu REAL, memory REAL, status TEXT, user_idle_seconds REAL, foreground INTEGER, activity_supported INTEGER);
            CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, ts REAL, pid INTEGER, anomaly TEXT, severity TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, ts REAL, pid INTEGER, incident_id INTEGER, action TEXT, reason TEXT);
            CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, ts REAL, pid INTEGER, incident_id INTEGER, action TEXT, result TEXT, detail TEXT, outcome TEXT, outcome_detail TEXT);''')
            cols={r['name'] for r in d.execute('PRAGMA table_info(actions)')}
            sample_cols={r['name'] for r in d.execute('PRAGMA table_info(samples)')}
            if 'user_idle_seconds' not in sample_cols: d.execute('ALTER TABLE samples ADD COLUMN user_idle_seconds REAL')
            if 'foreground' not in sample_cols: d.execute('ALTER TABLE samples ADD COLUMN foreground INTEGER')
            if 'activity_supported' not in sample_cols: d.execute('ALTER TABLE samples ADD COLUMN activity_supported INTEGER')
            if 'outcome' not in cols: d.execute('ALTER TABLE actions ADD COLUMN outcome TEXT')
            if 'outcome_detail' not in cols: d.execute('ALTER TABLE actions ADD COLUMN outcome_detail TEXT')
    def add_sample(self,pid,name,cpu,memory,status,user_idle_seconds=None,foreground=None,activity_supported=False):
        with self.connect() as d:d.execute('INSERT INTO samples(ts,pid,name,cpu,memory,status,user_idle_seconds,foreground,activity_supported) VALUES(?,?,?,?,?,?,?,?,?)',(time.time(),pid,name,cpu,memory,status,user_idle_seconds,None if foreground is None else int(foreground),int(activity_supported)))
    def incident(self,pid,anomaly,severity,detail):
        with self.connect() as d:return d.execute('INSERT INTO incidents VALUES(NULL,?,?,?,?,?)',(time.time(),pid,anomaly,severity,detail)).lastrowid
    def decision(self,pid,iid,action,reason):
        with self.connect() as d:d.execute('INSERT INTO decisions VALUES(NULL,?,?,?,?,?)',(time.time(),pid,iid,action,reason))
    def action(self,pid,iid,action,result,detail='',outcome=None):
        with self.connect() as d:return d.execute('INSERT INTO actions(ts,pid,incident_id,action,result,detail,outcome) VALUES(?,?,?,?,?,?,?)',(time.time(),pid,iid,action,result,detail,outcome)).lastrowid
    def action_outcome(self,action_id,outcome,detail=''):
        with self.connect() as d:d.execute('UPDATE actions SET outcome=?,outcome_detail=? WHERE id=?',(outcome,detail,action_id))
    def rows(self,table,limit=100):
        if table not in {'samples','incidents','decisions','actions'}: raise ValueError(table)
        with self.connect() as d:return [dict(r) for r in d.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT ?', (limit,))]
