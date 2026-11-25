"""Presentation metadata and a bounded heartbeat, separate from immutable ECG input."""
from contextlib import closing
import json
import time


class WorkspaceStore:
    def __init__(self, connect):
        self.connect = connect
        with closing(connect()) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS session_details(session_id TEXT PRIMARY KEY REFERENCES sessions(id),
                name TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', trashed_at TEXT);
            CREATE TABLE IF NOT EXISTS device_heartbeat(id INTEGER PRIMARY KEY CHECK(id=1), seen REAL NOT NULL, payload TEXT NOT NULL);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
            for column in ('owner_id', 'ingest_device_id'):
                if column not in columns: db.execute('ALTER TABLE sessions ADD COLUMN ' + column + ' TEXT')
            db.execute('CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner_id,created_at)')
            # The pre-account database is already pinned to one device by settings.
            # Restore its upload identity without assigning any personal owner.
            db.execute("UPDATE sessions SET ingest_device_id=(SELECT value FROM settings WHERE name='device_id') WHERE ingest_device_id IS NULL")
            db.commit()

    def heartbeat(self, payload, device_id, db=None):
        if db is None:
            with closing(self.connect()) as connection, connection:
                return self.heartbeat(payload,device_id,connection)
        db.execute('INSERT OR REPLACE INTO device_heartbeats VALUES(?,?,?)', (device_id,time.time(),json.dumps(payload)))
        return {'accepted': True}

    def device(self, principal=None, device_id=None):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM device_heartbeats WHERE device_id=?', (device_id,)).fetchone()
        if not row:
            return dict(connection='unknown', state='unknown', signal_state='unknown', session_id=None, last_seen=None)
        age = max(0, time.time()-row['seen'])
        result = {**json.loads(row['payload']), 'connection': 'online' if age <= 35 else 'offline',
                  'last_seen': row['seen'], 'age_seconds': round(age, 1)}
        if not principal or not principal.get('is_admin'):result.pop('device_info',None)
        if age > 35:
            result['remote_ready']=False
            result.update(state='unknown', signal_state='unknown', signal_text='', session_id=None)
        if principal and principal.get('kind') == 'user' and result.get('owner_id') != principal['id']:
            result.update(state=('standby' if result['state']=='standby' else 'other_user') if age <= 35 else 'unknown', signal_state='unknown',
                          signal_text='', session_id=None, owner_id=None, received=0, saved=0,
                          upload_phase='unknown', pending_uploads=0)
        return result
