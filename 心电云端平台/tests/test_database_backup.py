"""Snapshot and recovery contract; all data is generated inside test scratch."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from server import create_app
from test_pipeline import block, STAMP


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('database_backup'), 'snapshot/restore feature missing')
        import database_backup
        self.backup = database_backup
        scratch = Path(__file__).resolve().parents[1] / '.test_runs'
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / 'source'
        self.app = create_app(self.data, auth_enabled=True, cookie_secure=False)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.user = self.app.state.auth.create_user('owner', 'Owner-test-1234!')
        self.headers = {'X-API-Key': self.app.state.auth.create_device_key('pi2-demo')}
        self.assertEqual(self.client.put('/api/sessions/synthetic', headers=self.headers, json={
            'source': 'demo', 'started_utc': STAMP, 'owner_id': self.user['id']}).status_code, 200)
        self.assertEqual(self.client.put('/api/sessions/synthetic/chunks/0', headers=self.headers, json=block()).status_code, 200)
        self.client.post('/api/auth/login', json={'username': 'owner', 'password': 'Owner-test-1234!'})

    def test_snapshot_does_not_include_chunks_uploaded_after_snapshot(self):
        original = self.backup.snapshot
        def later(data, destination, **kwargs):
            result = original(data, destination, **kwargs)
            self.assertEqual(self.client.put('/api/sessions/synthetic/chunks/1', headers=self.headers, json=block(start=36)).status_code, 200)
            return result
        with patch.object(self.backup, 'snapshot', side_effect=later):
            result = self.backup.create_backup(self.data, 'a' * 32)
        target = Path(self.tmp.name) / 'restored'
        self.backup.restore_backup(self.data / 'backups' / result['filename'], target)
        with closing(sqlite3.connect(target / 'cloud.sqlite')) as db:
            self.assertEqual(db.execute('SELECT sample_count FROM sessions').fetchone()[0], 36)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM browser_sessions').fetchone()[0], 0)
        self.assertEqual((target / 'sessions/synthetic/chunks/00000000.bin').read_bytes(), (self.data / 'sessions/synthetic/chunks/00000000.bin').read_bytes())
        self.assertFalse((target / 'sessions/synthetic/chunks/00000001.bin').exists())
        with self.assertRaises(ValueError): self.backup.restore_backup(self.data / 'backups' / result['filename'], target)

    def test_corrupt_block_reports_problem_and_never_publishes_backup(self):
        (self.data / 'sessions/synthetic/chunks/00000000.bin').write_bytes(b'broken')
        checked = self.backup.check_snapshot(self.data)
        self.assertFalse(checked['ok'])
        self.assertEqual(checked['issue_count'], 1)
        with self.assertRaises(ValueError): self.backup.create_backup(self.data, 'b' * 32)
        self.assertEqual(list((self.data / 'backups').glob('*.zip')), [])

    def test_low_space_missing_and_path_escape_are_rejected(self):
        with patch.object(self.backup.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaises(ValueError): self.backup.create_backup(self.data, 'c' * 32)
        (self.data / 'sessions/synthetic/chunks/00000000.bin').unlink()
        self.assertFalse(self.backup.check_snapshot(self.data)['ok'])
        bad = Path(self.tmp.name) / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as bundle:
            bundle.writestr('../escaped.txt', 'untrusted')
            bundle.writestr('MANIFEST.json', json.dumps({'version': 1, 'files': {}}))
        with self.assertRaises(ValueError): self.backup.restore_backup(bad, Path(self.tmp.name) / 'output')
        self.assertFalse((Path(self.tmp.name) / 'escaped.txt').exists())

    def test_inconsistent_session_total_cannot_be_published(self):
        with closing(sqlite3.connect(self.data / 'cloud.sqlite')) as db, db:
            db.execute('UPDATE sessions SET sample_count=999')
        with self.assertRaises(ValueError): self.backup.create_backup(self.data, 'd' * 32)

    def test_restore_can_be_opened_but_old_cookies_and_device_keys_are_revoked(self):
        with closing(sqlite3.connect(self.data / 'cloud.sqlite')) as db,db:
            for index,status in enumerate(('queued','accepted','recording','uploading','completed')):
                db.execute('INSERT INTO measurement_requests VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (str(index),self.user['id'],'pi2-demo',str(index),60,status,1,99999999999,1,None,''))
        result = self.backup.create_backup(self.data, 'e' * 32)
        destination = Path(self.tmp.name) / 'new-data'
        self.backup.restore_backup(self.data / 'backups' / result['filename'], destination)
        with closing(sqlite3.connect(destination / 'cloud.sqlite')) as db:
            self.assertEqual(dict(db.execute('SELECT id,status FROM measurement_requests')),
                             {'0':'failed','1':'failed','2':'failed','3':'failed','4':'completed'})
        with TestClient(create_app(destination, auth_enabled=True, cookie_secure=False)) as client:
            client.cookies.update(self.client.cookies)
            self.assertEqual(client.get('/api/sessions').status_code, 401)
            self.assertEqual(client.get('/api/device/users', headers=self.headers).status_code, 401)
            login = client.post('/api/auth/login', json={'username': 'owner', 'password': 'Owner-test-1234!'})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get('/api/sessions').json()['total'], 1)
            self.assertEqual(client.get('/api/sessions/synthetic/waveform').status_code, 200)

    def test_restore_rejects_bad_digest_and_non_object_manifest(self):
        backup = self.backup.create_backup(self.data, 'f' * 32)
        archive = self.data / 'backups' / backup['filename']
        for body in ([], {'version': 1, 'files': {'cloud.sqlite': {'bytes': 0, 'sha256': 'bad'}}}):
            invalid = Path(self.tmp.name) / 'invalid.zip'
            with zipfile.ZipFile(invalid, 'w') as bundle:
                bundle.writestr('MANIFEST.json', json.dumps(body))
                bundle.writestr('cloud.sqlite', b'')
            with self.assertRaises(ValueError): self.backup.restore_backup(invalid, Path(self.tmp.name) / 'bad-restore')
            self.assertFalse((Path(self.tmp.name) / 'bad-restore').exists())
        self.assertTrue(archive.is_file())

    def test_interrupted_cleanup_only_removes_owned_known_files(self):
        self.assertTrue(hasattr(self.backup, 'cleanup_interrupted'))
        jid = '1' * 32
        with closing(sqlite3.connect(self.data / 'cloud.sqlite')) as db, db:
            db.execute("INSERT INTO management_jobs(job_id,actor_id,kind,status,created,updated) VALUES(?,?,'backup','running',0,0)", (jid, self.user['id']))
        scratch = self.data / '.maintenance'
        owned = scratch / 'backup-fixture'
        owned.mkdir(parents=True)
        (owned / '.owner.json').write_text(json.dumps({'owner': 'ecg-maintenance-v1', 'job_id': jid}))
        (owned / 'cloud.sqlite').write_bytes(b'partial')
        unknown = scratch / 'keep-user-content'
        unknown.mkdir(); (unknown / 'notes.txt').write_text('keep me')
        malformed = scratch / 'backup-invalid-marker'
        malformed.mkdir()
        (malformed / '.owner.json').write_text(json.dumps({'owner': 'ecg-maintenance-v1', 'job_id': []}))
        self.backup.cleanup_interrupted(self.data)
        self.assertFalse(owned.exists())
        self.assertTrue(malformed.exists())
        self.assertEqual((unknown / 'notes.txt').read_text(), 'keep me')
        self.assertGreater(self.backup.scan_storage(self.data)['bytes']['temporary'], 0)

    def test_backup_directory_sync_failure_does_not_report_success(self):
        self.assertTrue(hasattr(self.backup, 'sync_directory'))
        with patch.object(self.backup, 'sync_directory', side_effect=OSError('synthetic disk error')):
            with self.assertRaises(OSError): self.backup.create_backup(self.data, '2' * 32)


if __name__ == '__main__': unittest.main()
