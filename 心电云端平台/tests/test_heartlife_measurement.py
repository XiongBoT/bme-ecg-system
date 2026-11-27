"""Synthetic consent, acquisition and DST aggregation tests for HeartLife."""
from contextlib import closing
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import test_heartlife_bridge as existing
from server import create_app
from heartlife_bridge import HeartLifeBridge


class HeartLifeMeasurementTests(unittest.TestCase):
    setUp = existing.HeartLifeBridgeTests.setUp
    db = existing.HeartLifeBridgeTests.db
    login = existing.HeartLifeBridgeTests.login
    code = existing.HeartLifeBridgeTests.code
    exchange = existing.HeartLifeBridgeTests.exchange
    summary = existing.HeartLifeBridgeTests.summary

    def bind(self, allowed=False, user=None):
        code = (user or self.a).post('/api/heartlife/link-code', json={'measurement_allowed': allowed})
        self.assertEqual(code.status_code, 200, code.text)
        grant = self.exchange(code.json()['code'])
        self.assertEqual(grant.status_code, 200, grant.text)
        self.machine.headers.update({'Authorization': 'Bearer ' + grant.json()['grant_token'],
                                     'X-HeartLife-Subject': existing.SUBJECT})
        return grant.json()

    def device(self, did='pi-heartlife', owner=None, **beat):
        credentials = self.app.state.devices.create(did, did, [owner or self.alice['id']])['credentials']
        client = TestClient(self.app)
        self.addCleanup(client.close)
        client.headers['X-API-Key'] = credentials['token']
        result = client.put('/api/device/heartbeat', json={'state': 'standby', 'remote_ready': True, **beat})
        self.assertEqual(result.status_code, 200, result.text)
        return client

    def measure(self, **extra):
        return self.machine.post('/api/heartlife/measurements', json={
            'device_id': 'pi-heartlife', 'duration_s': 60, 'request_key': 'a' * 32, **extra})

    def weekly(self, **extra):
        return self.machine.get('/api/heartlife/weekly-summary', params={
            'week_start': '2026-11-23', 'timezone': 'Asia/Shanghai', 'observed_days': 7, **extra})

    def record(self, sid, stamp, owner=None, complete=1, source='serial', hr=None, weight=360, samples=21600):
        with closing(self.db()) as db, db:
            db.execute('INSERT INTO sessions(id,metadata,created_at,sample_count,complete,owner_id,ingest_device_id) '
                       'VALUES(?,?,?,?,?,?,?)', (sid, json.dumps({'source': source, 'started_utc': stamp}),
                                                stamp, samples, complete, owner or self.alice['id'], 'pi-heartlife'))
            if hr is not None:
                db.execute('INSERT INTO measurement_summaries VALUES(?,?)',
                           (sid, json.dumps({'analysis_stats': {'hr': {'mean': hr, 'window_samples': weight}}})))

    def test_readonly_default_cannot_escalate_and_consent_survives_exchange(self):
        grant = self.bind()
        self.assertFalse(grant['measurement_allowed'])
        self.assertFalse(self.a.get('/api/heartlife/link').json()['measurement_allowed'])
        self.assertFalse(self.summary().json()['measurement_allowed'])
        for path in ('devices', 'measurements'):
            self.assertEqual(self.machine.get('/api/heartlife/' + path).status_code, 403)
        self.assertEqual(self.measure().status_code, 403)
        self.assertEqual(self.weekly().status_code, 200)
        self.a.delete('/api/heartlife/link')
        code = self.code()
        reply = self.machine.post('/api/heartlife/exchange', json={
            'code': code, 'subject_id': existing.SUBJECT, 'operation_id': existing.OPERATION,
            'measurement_allowed': True})
        self.assertEqual(reply.status_code, 422)
        self.assertFalse(self.exchange(code).json()['measurement_allowed'])

    def test_code_body_strict_bool_extra_fields_and_csrf(self):
        for body in ({'measurement_allowed': 'true'}, {'measurement_allowed': 1}, {'scope': 'measurement'}):
            self.assertEqual(self.a.post('/api/heartlife/link-code', json=body).status_code, 422)
        self.a.headers.pop('X-CSRF-Token')
        self.assertEqual(self.a.post('/api/heartlife/link-code', json={'measurement_allowed': True}).status_code, 403)

    def test_existing_database_upgrade_keeps_grant_and_unexchanged_code_readonly(self):
        grant = self.bind()
        pending_code = self.code(self.b)
        # Reconstruct the previous release's exact columns with its existing rows.
        with closing(self.db()) as db, db:
            for table, columns in (
                ('heartlife_codes', 'code_hash,owner_id,created_at,expires_at'),
                ('heartlife_grants', 'token_hash,owner_id,subject_id,audience,scope,created_at,expires_at,operation_id'),
            ):
                db.execute(f'CREATE TABLE {table}_old AS SELECT {columns} FROM {table}')
                db.execute(f'DROP TABLE {table}')
                db.execute(f'ALTER TABLE {table}_old RENAME TO {table}')
        with patch.dict(os.environ, ECG_HEARTLIFE_URL='https://health.example/heartlife',
                        ECG_HEARTLIFE_CLIENT_SECRET=existing.SECRET):
            HeartLifeBridge(self.db, True)
        self.assertFalse(self.a.get('/api/heartlife/link').json()['measurement_allowed'])
        self.assertEqual(self.measure().status_code, 403)
        exchanged = self.exchange(pending_code, subject='b' * 32)
        self.assertEqual(exchanged.status_code, 200, exchanged.text)
        self.assertFalse(exchanged.json()['measurement_allowed'])

    def test_authorized_devices_only_even_for_admin_and_private_fields_hidden(self):
        self.device()
        self.device('bob-private', owner=self.bob['id'], signal_text='secret')
        with closing(self.db()) as db, db:
            db.execute('UPDATE users SET is_admin=1 WHERE id=?', (self.alice['id'],))
        self.bind(True)
        result = self.machine.get('/api/heartlife/devices')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertTrue(data['measurement_allowed'])
        devices = {row['device_id']: row for row in data['devices']}
        self.assertNotIn('bob-private', devices)
        self.assertTrue(devices['pi-heartlife']['ready'])
        self.assertEqual(set(devices['pi-heartlife']), {'device_id', 'label', 'online', 'ready', 'reason'})
        self.assertNotIn('secret', result.text)
        self.app.state.devices.update('pi-heartlife', user_ids=[])
        self.assertNotIn('pi-heartlife', [d['device_id'] for d in self.machine.get('/api/heartlife/devices').json()['devices']])
        self.assertEqual(self.measure().status_code, 403)

    def test_measurement_reuses_existing_queue_idempotence_and_owner(self):
        device = self.device()
        self.bind(True)
        first = self.measure()
        self.assertEqual(first.status_code, 202, first.text)
        task = first.json()['measurement']
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['report'], {'model': 'not_started', 'physiology': 'not_started'})
        self.assertEqual(self.measure().json()['measurement']['id'], task['id'])
        self.assertEqual(self.measure(duration_s=180).status_code, 409)
        self.assertEqual(self.measure(request_key='b' * 32).status_code, 409)
        self.assertEqual(self.measure(owner_id=self.bob['id']).status_code, 422)
        self.assertEqual(self.measure(duration_s=120).status_code, 422)
        self.assertEqual(self.a.get('/api/measurements').json()['measurements'][0]['id'], task['id'])
        self.assertEqual(self.b.get('/api/measurements').json()['measurements'], [])
        pending = device.get('/api/device/measurements/next').json()['measurement']
        self.assertEqual(pending['owner_id'], self.alice['id'])
        self.assertFalse(next(d for d in self.machine.get('/api/heartlife/devices').json()['devices']
                              if d['device_id'] == 'pi-heartlife')['ready'])
        self.a.delete('/api/heartlife/link')
        self.assertEqual(self.machine.get('/api/heartlife/measurements').status_code, 401)
        # Revocation blocks further bridge access, but does not cancel accepted work.
        self.assertEqual(device.get('/api/device/measurements/next').json()['measurement']['id'], task['id'])

    def test_offline_busy_and_revoked_device_fail_without_request_insert(self):
        device = self.device()
        self.bind(True)
        with closing(self.db()) as db, db:
            db.execute('UPDATE device_heartbeats SET seen=?', (time.time()-36,))
        self.assertEqual(self.measure().status_code, 409)
        self.assertFalse(next(d for d in self.machine.get('/api/heartlife/devices').json()['devices']
                              if d['device_id'] == 'pi-heartlife')['online'])
        device.put('/api/device/heartbeat', json={'state': 'recording', 'remote_ready': True})
        self.assertEqual(self.measure().status_code, 409)
        self.app.state.devices.update('pi-heartlife', active=False)
        self.assertEqual(self.measure().status_code, 403)
        with closing(self.db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM measurement_requests').fetchone()[0], 0)

    def test_upload_complete_does_not_claim_analysis_ready_or_leak_error(self):
        device = self.device()
        self.bind(True)
        task = self.measure().json()['measurement']
        base = '/api/device/measurements/' + task['id']
        device.post(base + '/claim')
        device.post(base + '/status', json={'status': 'recording', 'session_id': 'bridge-record'})
        self.record('bridge-record', '2026-11-25T01:00:00Z')
        result = self.machine.get('/api/heartlife/measurements')
        self.assertEqual(result.status_code, 200, result.text)
        item = result.json()['measurements'][0]
        self.assertEqual(item['status'], 'completed')
        self.assertEqual(item['report'], {'model': 'not_started', 'physiology': 'not_started'})
        with closing(self.db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_jobs').fetchone()[0], 0)
        self.app.state.jobs.enqueue('bridge-record', 'fake-digest', 21600, kind='physiology')
        with closing(self.db()) as db, db:
            db.execute("UPDATE analysis_jobs SET status='failed',error='secret server path'")
            db.execute("UPDATE measurement_requests SET message='secret terminal info'")
        result = self.machine.get('/api/heartlife/measurements')
        self.assertEqual(result.json()['measurements'][0]['report']['physiology'], 'failed')
        self.assertNotIn('secret', result.text)
        with closing(self.db()) as db, db:
            db.execute("UPDATE analysis_jobs SET status='complete'")
        self.assertEqual(self.machine.get('/api/heartlife/measurements').json()['measurements'][0]['report']['physiology'], 'not_started')
        self.app.state.jobs.enqueue('bridge-record', 'model-fake', 21600, kind='model')
        with patch.object(self.app.state.workflow, 'task_status', return_value='ineligible') as status:
            item = self.machine.get('/api/heartlife/measurements').json()['measurements'][0]
            self.assertEqual(item['report']['model'], 'ineligible')
            self.assertGreater(status.call_count, 0)

    def test_weekly_weighted_mean_scope_partial_days_and_missing_values(self):
        self.bind()
        self.record('one', '2026-11-22T16:00:00Z', hr=60, weight=360)
        self.record('two', '2026-11-23T00:00:00Z', hr=90, weight=720)
        self.record('missing', '2026-11-24T01:00:00Z')
        self.record('future', '2026-11-25T01:00:00Z', hr=100)
        self.record('other', '2026-11-23T01:00:00Z', owner=self.bob['id'])
        self.record('partial', '2026-11-23T01:00:00Z', complete=0)
        self.record('synthetic', '2026-11-23T01:00:00Z', source='synthetic')
        self.record('trashed', '2026-11-23T01:00:00Z')
        with closing(self.db()) as db, db:
            db.execute("INSERT INTO session_details VALUES('trashed','','','2026-11-23T01:00:00Z')")
        result = self.weekly(observed_days=2)
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()
        self.assertEqual(data['total_records'], 3)
        self.assertEqual(data['total_duration_s'], 180)
        self.assertEqual(data['hr_mean'], 80)
        self.assertEqual(data['hr_records'], 2)
        self.assertEqual(data['week_end'], '2026-11-29')
        self.assertEqual(len(data['daily_series']), 7)
        self.assertEqual(data['daily_series'][0]['hr_mean'], 80)
        self.assertIsNone(data['daily_series'][1]['hr_mean'])
        self.assertEqual(data['daily_series'][2]['records'], 0)

    def test_weekly_dst_midnights_and_validation(self):
        # US daylight saving ends on Sunday 2026-11-01 (25-hour local day).
        ZoneInfo('America/New_York')
        self.bind()
        self.record('first', '2026-10-26T04:00:00Z')
        self.record('before', '2026-10-26T03:59:59Z')
        self.record('sunday-last', '2026-11-02T04:59:59Z')
        self.record('after', '2026-11-02T05:00:00Z')
        data = self.weekly(week_start='2026-10-26', timezone='America/New_York').json()
        self.assertEqual(data['total_records'], 2)
        self.assertEqual(data['daily_series'][6]['records'], 1)
        for bad in ({'week_start': '2026-11-24'}, {'week_start': '9999-12-27'}, {'timezone': 'Bad/Zone'},
                    {'observed_days': 0}, {'observed_days': 8}):
            self.assertEqual(self.weekly(**bad).status_code, 422)


if __name__ == '__main__':
    unittest.main()
