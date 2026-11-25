"""Administrative metadata, bounded navigation and isolated device grants."""
from contextlib import closing
from datetime import datetime, timezone
import json
import time
import unittest
from unittest.mock import patch

import test_auth


class AdminConsoleTests(unittest.TestCase):
    setUp = test_auth.AccountIsolationTests.setUp
    login = test_auth.AccountIsolationTests.login
    prefix = '/api/admin/console'

    def get(self, path, **params):
        response = self.client.get(self.prefix + path, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_all_metadata_requires_admin_and_keeps_waveforms_private(self):
        paths = ['/overview', '/devices', '/devices/pi2-demo', '/accounts', '/accounts/' + self.alice['id']]
        for path in paths:
            self.assertEqual(self.client.get(self.prefix + path).status_code, 401)
            self.assertEqual(self.client.get(self.prefix + path, headers=self.headers).status_code, 403)
        self.login()
        for path in paths:
            self.assertEqual(self.client.get(self.prefix + path).status_code, 403)
        self.login('admin', 'Admin-test-9182!')
        for path in paths:
            body = json.dumps(self.get(path))
            for forbidden in ('password_hash', 'csrf', 'token_hash', 'signal_text', 'waveform'):
                self.assertNotIn(forbidden, body)
        self.assertEqual(self.client.get('/api/sessions/alice_record/waveform').status_code, 404)

    def test_device_status_separates_enabled_unknown_stale_and_acquiring(self):
        self.login('admin', 'Admin-test-9182!')
        store = self.app.state.devices
        for did in ('online', 'offline', 'unknown', 'disabled'):
            store.create(did, did, [self.alice['id']])
        stamp = time.time()
        with closing(store.connect()) as db, db:
            for did, seen in [('online', stamp - 35), ('offline', stamp - 35.01), ('disabled', stamp)]:
                db.execute('INSERT INTO device_heartbeats VALUES(?,?,?)',
                           (did, seen, json.dumps({'state': 'acquiring', 'signal_text': 'private', 'owner_id': self.bob['id']})))
            db.execute("UPDATE devices SET active=0 WHERE id='disabled'")
        with patch('admin_console.time.time', return_value=stamp):
            items = {d['device_id']: d for d in self.get('/devices')['devices']}
            self.assertEqual(items['online']['connection'], 'online')
            self.assertEqual(items['online']['state'], 'acquiring')
            self.assertEqual(items['offline']['connection'], 'offline')
            self.assertEqual(items['offline']['state'], 'unknown')
            self.assertEqual(items['disabled']['connection'], 'disabled')
            self.assertEqual(items['unknown']['connection'], 'unknown')
            self.assertEqual(self.get('/devices', connection='online')['total'], 1)

    def test_devices_search_page_and_account_context_do_not_change_grants(self):
        self.login('admin', 'Admin-test-9182!')
        for i in range(6):
            self.app.state.devices.create('lab-' + str(i), '实验室 ' + str(i), [self.alice['id']] if i % 2 else [])
        first = self.get('/devices', q='实验室', limit=2, offset=0)
        second = self.get('/devices', q='实验室', limit=2, offset=2)
        self.assertEqual(first['total'], 6)
        self.assertFalse({x['device_id'] for x in first['devices']} & {x['device_id'] for x in second['devices']})
        selected = self.get('/devices', account_id=self.alice['id'], grant='granted')
        self.assertEqual(selected['total'], 4)  # three explicit plus historical shared device
        self.assertEqual(self.get('/devices', q="%' OR 1=1 --")['total'], 0)
        self.assertEqual(self.client.get(self.prefix + '/devices?limit=101').status_code, 422)
        self.assertEqual(self.client.get(self.prefix + '/devices?connection=bad').status_code, 422)

    def test_overview_uses_cloud_registration_day_and_excludes_trash(self):
        self.login('admin', 'Admin-test-9182!')
        stamp = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc).timestamp()
        with closing(self.app.state.auth.connect()) as db, db:
            db.execute("UPDATE sessions SET created_at='2026-11-24T15:59:59Z' WHERE id='alice_record'")
            db.execute("UPDATE sessions SET created_at='2026-11-24T16:00:00Z' WHERE id='bob_record'")
            db.execute("UPDATE sessions SET created_at='2026-11-25T01:00:00Z' WHERE id='legacy_record'")
            db.execute("INSERT INTO session_details(session_id,trashed_at) VALUES('legacy_record','2026-11-25')")
        with patch('admin_console.time.time', return_value=stamp):
            result = self.get('/overview')
        self.assertEqual(result['records']['today_registered'], 1)
        self.assertEqual(result['records']['active'], 2)
        self.assertEqual(result['records']['unassigned'], 0)
        self.assertEqual(result['day']['timezone'], 'Asia/Shanghai')
        self.assertEqual(result['day']['date'], '2026-11-25')
        self.assertIsNone(result['latest_backup'])

    def test_account_detail_counts_records_and_preserves_unknown_history(self):
        self.login('admin', 'Admin-test-9182!')
        self.app.state.devices.create('granted-pi', '采集终端', [self.alice['id']])
        result = self.get('/accounts/' + self.alice['id'])
        self.assertEqual(result['account']['record_count'], 1)
        self.assertEqual(result['account']['device_count'], 2)
        self.assertIsNone(result['account']['last_login_at'])
        self.assertEqual(self.get('/accounts', q='ALICE', role='user')['total'], 1)
        self.assertEqual(self.get('/accounts', role='admin')['total'], 1)
        self.assertEqual(self.client.get(self.prefix + '/accounts/missing').status_code, 404)

    def test_overview_counts_latest_task_per_kind_and_hides_old_failures(self):
        self.login('admin', 'Admin-test-9182!')
        with closing(self.app.state.auth.connect()) as db, db:
            for job, sid, kind, status, stamp in [
                ('old', 'alice_record', 'model', 'failed', 1),
                ('retry', 'alice_record', 'model', 'complete', 2),
                ('rr', 'alice_record', 'physiology', 'failed', 3),
                ('waiting', 'bob_record', 'model', 'queued', 4),
                ('trashed', 'legacy_record', 'model', 'failed', 5),
            ]:
                db.execute('INSERT INTO analysis_jobs(job_id,session_id,kind,status,created,updated,source_digest,stage,total) VALUES(?,?,?,?,?,?,\'digest\',\'stage\',0)',
                           (job, sid, kind, status, stamp, stamp))
            db.execute("INSERT INTO session_details(session_id,trashed_at) VALUES('legacy_record','2026-11-25')")
        result = self.get('/overview')
        self.assertEqual(result['analysis'], {'complete': 1, 'failed': 1, 'queued': 1})
        self.assertEqual([(j['session_id'], j['kind']) for j in result['analysis_problems']], [('alice_record', 'physiology')])

    def test_grant_rechecks_actor_and_never_accepts_an_ordinary_account(self):
        from admin_console import AdminConsole
        from fastapi import HTTPException
        self.app.state.devices.create('lab-pi', '终端', [self.bob['id']])
        store = AdminConsole(self.temp.name)
        with self.assertRaises(HTTPException):
            store.set_grant(self.alice['id'], self.alice['id'], 'lab-pi', True)
        with closing(self.app.state.auth.connect()) as db, db:
            db.execute('UPDATE users SET active=0 WHERE id=?', (self.admin['id'],))
        with self.assertRaises(HTTPException):
            store.set_grant(self.admin['id'], self.alice['id'], 'lab-pi', True)
        users = next(x for x in self.app.state.devices.list(admin=True) if x['device_id'] == 'lab-pi')['user_ids']
        self.assertEqual(users, [self.bob['id']])

    def test_overview_registration_day_link_uses_registration_not_capture_time(self):
        self.login('admin', 'Admin-test-9182!')
        with closing(self.app.state.auth.connect()) as db, db:
            db.execute("UPDATE sessions SET created_at='2026-11-24T15:59:59Z' WHERE id='alice_record'")
            db.execute("UPDATE sessions SET created_at='2026-11-24T16:00:00Z' WHERE id='bob_record'")
            db.execute("UPDATE sessions SET created_at='2026-11-25T16:00:00Z' WHERE id='legacy_record'")
        response = self.client.get('/api/admin/database/records', params={'registered_day': '2026-11-25'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([r['session_id'] for r in response.json()['records']], ['bob_record'])
        self.assertEqual(self.client.get('/api/admin/database/records?registered_day=wrong').status_code, 422)
        self.assertEqual(self.client.get('/api/admin/database/records?registered_day=9999-12-31').status_code, 422)

    def test_single_grant_is_idempotent_preserves_other_users_and_needs_csrf(self):
        self.login('admin', 'Admin-test-9182!')
        self.app.state.devices.create('lab-pi', '终端', [self.bob['id']])
        path = self.prefix + '/accounts/' + self.alice['id'] + '/devices/lab-pi'
        self.assertEqual(self.client.put(path, json={'granted': True}, headers={'X-CSRF-Token': ''}).status_code, 403)
        for _ in range(2):
            self.assertEqual(self.client.put(path, json={'granted': True}).status_code, 200)
        with closing(self.app.state.auth.connect()) as db:
            self.assertEqual({r[0] for r in db.execute("SELECT user_id FROM device_users WHERE device_id='lab-pi'")},
                             {self.alice['id'], self.bob['id']})
        self.assertEqual(self.client.put(path, json={'granted': False}).status_code, 200)
        users = next(x for x in self.app.state.devices.list(admin=True) if x['device_id'] == 'lab-pi')['user_ids']
        self.assertEqual(users, [self.bob['id']])

    def test_full_editor_cannot_replace_a_newer_single_account_grant(self):
        self.login('admin', 'Admin-test-9182!')
        self.app.state.devices.create('lab-pi', '终端', [self.alice['id']])
        self.client.put(self.prefix + '/accounts/' + self.bob['id'] + '/devices/lab-pi', json={'granted': True})
        response = self.client.patch('/api/admin/devices/lab-pi', json={
            'name': '不应保存', 'user_ids': [], 'expected_user_ids': [self.alice['id']], 'expected_legacy_shared': False})
        self.assertEqual(response.status_code, 409, response.text)
        device = self.get('/devices/lab-pi')['device']
        self.assertEqual(device['name'], '终端')
        self.assertEqual(set(device['user_ids']), {self.alice['id'], self.bob['id']})
        renamed = self.client.patch('/api/admin/devices/lab-pi', json={'name': '只改名称'})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(set(renamed.json()['user_ids']), {self.alice['id'], self.bob['id']})

    def test_full_editor_preserves_existing_disabled_grants_but_cannot_add_them(self):
        self.login('admin', 'Admin-test-9182!')
        self.app.state.devices.create('lab-pi', '终端', [self.alice['id']])
        self.client.patch('/api/admin/users/' + self.alice['id'], json={'active': False})
        response = self.client.patch('/api/admin/devices/lab-pi', json={
            'user_ids': [self.alice['id'], self.bob['id']], 'expected_user_ids': [self.alice['id']], 'expected_legacy_shared': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.put(self.prefix + '/accounts/' + self.alice['id'] + '/devices/lab-pi', json={'granted': False})
        self.assertEqual(self.client.patch('/api/admin/devices/lab-pi', json={
            'user_ids': [self.alice['id'], self.bob['id']], 'expected_user_ids': [self.bob['id']], 'expected_legacy_shared': False}).status_code, 422)

    def test_grant_cannot_silently_convert_shared_or_enable_disabled_accounts(self):
        self.login('admin', 'Admin-test-9182!')
        prefix = self.prefix + '/accounts/' + self.alice['id'] + '/devices/'
        self.assertEqual(self.client.put(prefix + 'pi2-demo', json={'granted': False}).status_code, 409)
        self.app.state.devices.create('lab-pi', '终端', [])
        self.client.patch('/api/admin/users/' + self.alice['id'], json={'active': False})
        self.assertEqual(self.client.put(prefix + 'lab-pi', json={'granted': True}).status_code, 409)
        self.assertEqual(self.client.put(prefix + 'missing', json={'granted': True}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
