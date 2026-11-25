"""Administrator account overview and targeted login revocation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import time
import unittest

from fastapi.testclient import TestClient
from auth_store import AuthStore, digest
import test_auth


class AccountManagementTests(unittest.TestCase):
    setUp = test_auth.AccountIsolationTests.setUp
    login = test_auth.AccountIsolationTests.login

    def overview(self, uid):
        response = self.client.get('/api/admin/users')
        self.assertEqual(response.status_code, 200, response.text)
        return next(user for user in response.json()['users'] if user['id'] == uid)

    def other_client(self, username='alice', password='Alice-test-9182!'):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        response = client.post('/api/auth/login', json={'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.text)
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        return client

    def test_overview_tracks_successful_login_and_excludes_expired_sessions(self):
        self.login('admin', 'Admin-test-9182!')
        before = self.overview(self.alice['id'])
        self.assertIsInstance(before.get('created_at'), (int, float))
        self.assertIsNone(before['last_login_at'])
        self.assertEqual(before['active_sessions'], 0)
        alice = self.other_client()
        self.other_client()
        after = self.overview(self.alice['id'])
        self.assertGreaterEqual(after['last_login_at'], before['created_at'])
        self.assertEqual(after['active_sessions'], 2)
        alice.post('/api/auth/login', json={'username': 'alice', 'password': 'wrong'})
        self.assertEqual(self.overview(self.alice['id'])['last_login_at'], after['last_login_at'])
        with closing(self.app.state.auth.connect()) as db, db:
            db.execute('UPDATE browser_sessions SET expires=? WHERE token_hash=?',
                       (time.time() - 1, digest(alice.cookies.get('ecg_session'))))
        self.assertEqual(self.overview(self.alice['id'])['active_sessions'], 1)
        self.assertEqual(set(after), {'id', 'username', 'is_admin', 'active',
                                     'created_at', 'last_login_at', 'active_sessions'})

    def test_activity_upgrade_preserves_old_accounts_and_unknown_dates(self):
        self.login('admin', 'Admin-test-9182!')
        auth = self.app.state.auth
        with closing(auth.connect()) as db, db:
            db.execute('DROP TABLE IF EXISTS user_activity')
        AuthStore(auth.connect)
        AuthStore(auth.connect)  # repeat startup is safe
        row = self.overview(self.alice['id'])
        self.assertIn('created_at', row)
        self.assertIsNone(row['created_at'])
        self.assertIsNone(row['last_login_at'])
        alice = self.other_client()
        row = self.overview(self.alice['id'])
        self.assertIsNone(row['created_at'])
        self.assertIsInstance(row['last_login_at'], (float, int))
        self.assertEqual(alice.get('/api/sessions').json()['total'], 1)
        # The old five-column insert remains valid for old clients/rollback.
        with closing(auth.connect()) as db, db:
            db.execute("INSERT INTO users VALUES('legacy','old-user','unused',0,1)")
        self.assertIsNone(self.overview('legacy')['created_at'])

    def test_admin_can_revoke_only_target_existing_logins_and_preserve_password(self):
        alice = self.other_client()
        alice2 = self.other_client()
        bob = self.other_client('bob', 'Bobby-test-9182!')
        self.login('admin', 'Admin-test-9182!')
        auth = self.app.state.auth
        with closing(auth.connect()) as db, db:
            db.execute("INSERT INTO browser_sessions VALUES('expired',?,'expired-csrf',?)",
                       (self.alice['id'], time.time() - 1))
        path = '/api/admin/users/' + self.alice['id'] + '/revoke-sessions'
        response = self.client.post(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['revoked_sessions'], 2)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.overview(self.alice['id'])['active_sessions'], 0)
        for client in (alice, alice2):
            self.assertEqual(client.get('/api/auth/me').status_code, 401)
        self.assertEqual(bob.get('/api/sessions').json()['total'], 1)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 200)
        self.assertEqual(self.client.get('/api/sessions/alice_record').status_code, 404)
        self.assertEqual(self.client.get('/api/device/recipients', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.post(path).json()['revoked_sessions'], 0)
        self.assertEqual(self.other_client().get('/api/sessions').json()['total'], 1)

    def test_revocation_requires_admin_csrf_and_cannot_target_administrators(self):
        path = '/api/admin/users/' + self.alice['id'] + '/revoke-sessions'
        self.assertEqual(self.client.post(path).status_code, 401)
        self.assertEqual(self.client.post(path, headers=self.headers).status_code, 403)
        self.login()
        self.assertEqual(self.client.post(path).status_code, 403)
        self.login('admin', 'Admin-test-9182!')
        self.assertEqual(self.client.post(path, headers={'X-CSRF-Token': ''}).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/users/' + self.admin['id'] + '/revoke-sessions').status_code, 409)
        self.assertEqual(self.client.post('/api/admin/users/missing/revoke-sessions').status_code, 404)

    def test_overview_is_admin_only_and_personal_payload_stays_minimal(self):
        self.assertEqual(self.client.get('/api/admin/users', headers=self.headers).status_code, 403)
        reply = self.login()
        expected = {'id', 'username', 'is_admin', 'active'}
        self.assertEqual(set(reply.json()['user']), expected)
        self.assertEqual(set(self.client.get('/api/auth/me').json()['user']), expected)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 403)
        recipients = self.client.get('/api/device/recipients', headers=self.headers).json()['users']
        self.assertTrue(all('last_login_at' not in user and 'active_sessions' not in user for user in recipients))

    def test_creation_normalizes_name_and_rejects_invalid_or_duplicate_accounts(self):
        self.login('admin', 'Admin-test-9182!')
        payload = {'username': '  New-User_2 ', 'password': 'Initial-test-9182!'}
        result = self.client.post('/api/admin/users', json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['username'], 'new-user_2')
        self.assertIsInstance(self.overview(result.json()['id']).get('created_at'), (float, int))
        self.assertEqual(self.client.post('/api/admin/users', json=payload).status_code, 422)
        for username, password in [('ab', payload['password']), ('bad name', payload['password']),
                                   ('_test', payload['password']), ('valid-user', 'shrt')]:
            response = self.client.post('/api/admin/users', json={'username': username, 'password': password})
            self.assertEqual(response.status_code, 422)

    def test_simultaneous_creation_reports_duplicate_instead_of_server_error(self):
        def create(_):
            try:
                return self.app.state.auth.create_user('same-name', 'Initial-test-9182!')
            except ValueError as exc:
                return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn('账号已存在', results)


if __name__ == '__main__':
    unittest.main()
