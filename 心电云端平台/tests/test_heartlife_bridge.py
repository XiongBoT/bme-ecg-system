"""Synthetic integration tests for the opt-in, summary-only HeartLife grant."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from server import create_app
from heartlife_bridge import safe_heartlife_url


SECRET = 'integration-test-client-secret-32-chars'
SUBJECT = 'a' * 32
OPERATION = 'c' * 32


class HeartLifeBridgeTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.test_runs'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, ECG_HEARTLIFE_URL='https://health.example/heartlife',
                        ECG_HEARTLIFE_CLIENT_SECRET=SECRET):
            self.app = create_app(self.temp.name, auth_enabled=True, cookie_secure=False)
        self.alice = self.app.state.auth.create_user('alice', 'abcde')
        self.bob = self.app.state.auth.create_user('bobby', 'abcde')
        self.a = self.login('alice')
        self.b = self.login('bobby')
        self.machine = TestClient(self.app)
        self.addCleanup(self.machine.close)
        self.machine.headers['X-HeartLife-Key'] = SECRET

    def db(self):
        db = sqlite3.connect(Path(self.temp.name) / 'cloud.sqlite')
        db.row_factory = sqlite3.Row
        return db

    def login(self, name, password='abcde'):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        response = client.post('/api/auth/login', json={'username': name, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        return client

    def code(self, client=None):
        response = (client or self.a).post('/api/heartlife/link-code')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['code']

    def exchange(self, code, subject=SUBJECT, operation=OPERATION):
        return self.machine.post('/api/heartlife/exchange', json={
            'code': code, 'subject_id': subject, 'operation_id': operation})

    def link(self, client=None, subject=SUBJECT):
        response = self.exchange(self.code(client), subject)
        self.assertEqual(response.status_code, 200, response.text)
        grant = response.json()
        self.machine.headers.update({'Authorization': 'Bearer ' + grant['grant_token'],
                                     'X-HeartLife-Subject': subject, 'X-HeartLife-Operation': OPERATION})
        return grant

    def summary(self, **extra):
        return self.machine.get('/api/heartlife/summary', params={
            'period': 'day', 'anchor': '2026-11-25', 'utc_offset_minutes': 480, **extra})

    def test_default_disabled_and_safe_url(self):
        with tempfile.TemporaryDirectory(dir=Path(self.temp.name).parent) as path:
            with patch.dict(os.environ, ECG_HEARTLIFE_URL='', ECG_HEARTLIFE_CLIENT_SECRET=''):
                app = create_app(path, auth_enabled=True, cookie_secure=False)
            with TestClient(app) as client:
                self.assertIsNone(client.get('/api/auth/config').json()['heartlife_url'])
                self.assertEqual(client.post('/api/heartlife/exchange', json={
                    'code': 'x' * 32, 'subject_id': SUBJECT}).status_code, 503)
        self.assertEqual(self.a.get('/api/auth/config').json()['heartlife_url'], 'https://health.example/heartlife')
        for url in ('http://health.example', 'https://user@health.example', 'https://health.example/heartlife?',
                    'https://health.example/#', 'https://health.example/evil', 'https://health.example:8000',
                    'https://health.example\\@evil.example', 'https://health.example/%68eartlife'):
            self.assertIsNone(safe_heartlife_url(url), url)
        for url in ('https://health.example', 'https://health.example/', 'https://health.example/heartlife/'):
            self.assertIsNotNone(safe_heartlife_url(url), url)
        with tempfile.TemporaryDirectory(dir=Path(self.temp.name).parent) as path:
            with patch.dict(os.environ, ECG_HEARTLIFE_URL='https://health.example', ECG_HEARTLIFE_CLIENT_SECRET=SECRET):
                app = create_app(path, auth_enabled=False)
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/heartlife/exchange', headers={'X-HeartLife-Key': SECRET}, json={
                    'code': 'x' * 32, 'subject_id': SUBJECT}).status_code, 503)

    def test_code_requires_user_and_csrf(self):
        self.assertEqual(self.machine.post('/api/heartlife/link-code').status_code, 401)
        self.a.headers.pop('X-CSRF-Token')
        self.assertEqual(self.a.post('/api/heartlife/link-code').status_code, 403)
        self.a = self.login('alice')
        self.code()
        device_key = self.app.state.auth.create_device_key('pi2-demo')
        self.machine.headers['X-API-Key'] = device_key
        self.assertEqual(self.machine.post('/api/heartlife/link-code').status_code, 403)
        self.assertEqual(self.machine.get('/api/heartlife/link').status_code, 403)

    def test_code_rotation_expiry_replay_and_no_raw_secrets(self):
        first, second = self.code(), self.code()
        self.assertGreaterEqual(len(second), 32)
        self.assertEqual(self.exchange(first).status_code, 401)
        grant = self.exchange(second)
        self.assertEqual(grant.status_code, 200, grant.text)
        self.assertEqual(self.exchange(second).status_code, 401)
        with closing(self.db()) as db:
            dumped = '\n'.join(db.iterdump())
        self.assertNotIn(second, dumped)
        self.assertNotIn(grant.json()['grant_token'], dumped)
        self.a.delete('/api/heartlife/link')
        code = self.code()
        with closing(self.db()) as db, db:
            db.execute('UPDATE heartlife_codes SET expires_at=?', (time.time()-1,))
        self.assertEqual(self.exchange(code).status_code, 401)

    def test_one_to_one_and_failed_conflict_does_not_consume_code(self):
        self.link()
        self.assertEqual(self.a.post('/api/heartlife/link-code').status_code, 409)
        code = self.code(self.b)
        self.assertEqual(self.exchange(code).status_code, 409)
        self.assertEqual(self.exchange(code, 'b' * 32).status_code, 200)
        self.assertTrue(self.a.get('/api/heartlife/link').json()['linked'])
        self.assertEqual(self.a.delete('/api/heartlife/link').status_code, 200)
        self.assertFalse(self.a.get('/api/heartlife/link').json()['linked'])

    def test_grant_has_no_general_api_access_and_all_credentials_required(self):
        self.link()
        self.assertEqual(self.machine.get('/api/sessions').status_code, 401)
        self.assertEqual(self.machine.post('/api/measurements', json={}).status_code, 401)
        self.assertEqual(self.summary().status_code, 200)
        original = dict(self.machine.headers)
        for header in ('X-HeartLife-Key', 'Authorization', 'X-HeartLife-Subject'):
            self.machine.headers.pop(header)
            self.assertEqual(self.summary().status_code, 401, header)
            self.machine.headers.clear()
            self.machine.headers.update(original)
        self.machine.headers['X-HeartLife-Subject'] = 'b' * 32
        self.assertEqual(self.summary().status_code, 401)
        self.machine.headers['X-HeartLife-Subject'] = SUBJECT
        self.machine.headers['X-HeartLife-Key'] = 'wrong-secret'
        self.assertEqual(self.summary().status_code, 401)
        self.machine.headers['X-HeartLife-Key'] = SECRET
        for field, bad in (('scope', 'waveform:read'), ('audience', 'other-app')):
            with closing(self.db()) as db, db:
                db.execute(f'UPDATE heartlife_grants SET {field}=?', (bad,))
            self.assertEqual(self.summary().status_code, 401)
            with closing(self.db()) as db, db:
                db.execute('UPDATE heartlife_grants SET scope=?,audience=?', ('summary:read', 'heartlife'))

    def test_summary_matches_trends_and_excludes_other_owners_and_private_fields(self):
        self.link()
        with closing(self.db()) as db, db:
            for i in range(9):
                db.execute('INSERT INTO sessions(id,metadata,created_at,sample_count,complete,owner_id,ingest_device_id) '
                           'VALUES(?,?,?,?,?,?,?)', ('record' + str(i), json.dumps({
                               'source': 'synthetic' if i == 6 else 'serial',
                               'started_utc': '2026-11-24T16:00:00Z'}),
                               '2026-11-25T00:00:00Z', 21600, 0 if i == 7 else 1,
                               self.bob['id'] if i == 8 else self.alice['id'], 'pi2-demo'))
            db.execute("INSERT INTO session_details VALUES('record0','secret title','secret note','2026-11-25T00:00:00Z')")
            db.execute("INSERT INTO measurement_summaries VALUES('record1',?)", (json.dumps({
                'analysis_stats': {'hr': {'mean': 72., 'window_samples': 360}}, 'secret': 'hidden'}),))
        response = self.summary()
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        baseline = self.a.get('/api/records/trends', params={
            'period': 'day', 'anchor': '2026-11-25', 'utc_offset_minutes': 480}).json()
        self.assertEqual(data['trends'], baseline)
        self.assertEqual(baseline['total_records'], 5)
        self.assertEqual(len(data['recent_records']), 5)
        self.assertEqual(set(r['session_id'] for r in data['recent_records']), {'record' + str(i) for i in range(1, 6)})
        self.assertIsNone(next(r for r in data['recent_records'] if r['session_id'] == 'record2')['hr_mean'])
        self.assertNotIn('secret', response.text)
        self.assertNotIn('analysis_stats', response.text)
        self.assertEqual(data['ecg_user'], {'id': self.alice['id'], 'username': 'alice'})
        for period, anchor in [('month', '2024-02-01'), ('year', '2026-11-25')]:
            self.assertEqual(self.summary(period=period, anchor=anchor).status_code, 200)
        self.assertEqual(self.summary(anchor='2026-02-30').status_code, 422)
        self.assertEqual(self.summary(period='year', anchor='9999-12-31').status_code, 422)

    def test_expired_grant_revoke_and_disable_reenable_are_permanent(self):
        self.link()
        with closing(self.db()) as db, db:
            db.execute('UPDATE heartlife_grants SET expires_at=?', (time.time()-1,))
        self.assertEqual(self.summary().status_code, 401)
        self.assertEqual(self.machine.delete('/api/heartlife/grant').status_code, 200)
        self.assertEqual(self.machine.delete('/api/heartlife/grant').status_code, 200)
        self.link()
        self.app.state.auth.manage_user(self.alice['id'], active=False)
        self.assertEqual(self.summary().status_code, 401)
        self.app.state.auth.manage_user(self.alice['id'], active=True)
        self.assertEqual(self.summary().status_code, 401)

    def test_password_and_session_revocation_destroy_pending_and_issued_grants(self):
        for action in ('password', 'reset', 'sessions'):
            self.a = self.login('alice')
            code = self.code()
            if action == 'password':
                self.app.state.auth.change_password(self.alice['id'], 'abcde', 'abcde')
            elif action == 'reset':
                self.app.state.auth.manage_user(self.alice['id'], new_password='abcde')
            else:
                self.app.state.auth.revoke_user_sessions(self.alice['id'])
            self.assertEqual(self.exchange(code).status_code, 401)
            self.a = self.login('alice')
            self.link()
            if action == 'password':
                self.app.state.auth.change_password(self.alice['id'], 'abcde', 'abcde')
            elif action == 'reset':
                self.app.state.auth.manage_user(self.alice['id'], new_password='abcde')
            else:
                self.app.state.auth.revoke_user_sessions(self.alice['id'])
            self.assertEqual(self.summary().status_code, 401)

    def test_exchange_rate_limit_and_cross_origin(self):
        for _ in range(20):
            self.assertEqual(self.exchange('x' * 32).status_code, 401)
        self.assertEqual(self.exchange('x' * 32).status_code, 429)
        self.assertEqual(self.machine.get('/api/heartlife/summary', headers={
            'Origin': 'https://untrusted.example'}).status_code, 403)

    def test_lost_exchange_recovery_only_revokes_exact_subject(self):
        self.link()
        self.link(self.b, 'b' * 32)
        self.machine.headers['X-HeartLife-Subject'] = SUBJECT
        self.assertEqual(self.machine.delete('/api/heartlife/subject-grant').status_code, 200)
        self.assertFalse(self.a.get('/api/heartlife/link').json()['linked'])
        self.assertTrue(self.b.get('/api/heartlife/link').json()['linked'])
        self.assertEqual(self.exchange(self.code(), operation='d' * 32).status_code, 200)
        # A delayed old cleanup cannot delete the later association.
        self.assertEqual(self.machine.delete('/api/heartlife/subject-grant').status_code, 200)
        self.assertTrue(self.a.get('/api/heartlife/link').json()['linked'])
        self.machine.headers.pop('X-HeartLife-Operation')
        self.assertEqual(self.machine.delete('/api/heartlife/subject-grant').status_code, 401)
        self.machine.headers['X-HeartLife-Operation'] = OPERATION
        self.machine.headers.pop('X-HeartLife-Key')
        self.assertEqual(self.machine.delete('/api/heartlife/subject-grant').status_code, 401)

    def test_simultaneous_exchange_consumes_once(self):
        code = self.code()
        def redeem():
            client = TestClient(self.app)
            try:
                return client.post('/api/heartlife/exchange', headers={'X-HeartLife-Key': SECRET},
                                   json={'code': code, 'subject_id': SUBJECT, 'operation_id': OPERATION}).status_code
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: redeem(), range(2)))
        self.assertEqual(sorted(statuses), [200, 401])
        with closing(self.db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM heartlife_grants').fetchone()[0], 1)

    def test_account_revoke_during_request_cannot_issue_new_code(self):
        original = self.app.state.auth.authenticate
        def authenticate_then_revoke(request):
            result = original(request)
            if request.url.path == '/api/heartlife/link-code':
                self.app.state.auth.revoke_user_sessions(self.alice['id'])
            return result
        with patch.object(self.app.state.auth, 'authenticate', authenticate_then_revoke):
            self.assertEqual(self.a.post('/api/heartlife/link-code').status_code, 401)
        with closing(self.db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM heartlife_codes').fetchone()[0], 0)

    def test_exchange_database_failure_rolls_back_grant_and_code_consumption(self):
        code = self.code()
        with closing(self.db()) as db, db:
            db.execute("""CREATE TRIGGER fail_consume BEFORE DELETE ON heartlife_codes
                BEGIN SELECT RAISE(ABORT, 'test injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.exchange(code)
        with closing(self.db()) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM heartlife_grants').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM heartlife_codes').fetchone()[0], 1)
            db.execute('DROP TRIGGER fail_consume')
        self.assertEqual(self.exchange(code).status_code, 200)


if __name__ == '__main__':
    unittest.main()
