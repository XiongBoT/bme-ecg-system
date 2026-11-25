"""Synthetic workflow tests: account boundaries, durable intent and review context."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import create_app
from test_pipeline import block, STAMP


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.test_runs'
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.app = create_app(self.data, auth_enabled=True, cookie_secure=False)
        self.client = TestClient(self.app)
        self.user = self.app.state.auth.create_user('owner', 'Owner-workflow-812!')
        self.other = self.app.state.auth.create_user('other', 'Other-workflow-812!')
        self.admin = self.app.state.auth.create_user('manager', 'Manager-workflow-812!', True)
        self.device = {'X-API-Key': self.app.state.auth.create_device_key('pi2-demo')}
        self.payload = block()
        self.register('mine', self.user['id'])
        self.register('theirs', self.other['id'])
        self.login()

    def login(self, name='owner'):
        response = self.client.post('/api/auth/login', json={'username': name, 'password': name.title()+'-workflow-812!'})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers['X-CSRF-Token'] = response.json()['csrf_token']

    def register(self, sid, owner):
        self.assertEqual(self.client.put('/api/sessions/'+sid, headers=self.device, json={'source':'demo', 'started_utc':STAMP, 'owner_id':owner}).status_code, 200)
        self.assertEqual(self.client.put('/api/sessions/'+sid+'/chunks/0', headers=self.device, json=self.payload).status_code, 200)

    def complete(self, sid='mine'):
        response = self.client.post('/api/sessions/'+sid+'/complete', headers=self.device, json={
            'chunks':[{'chunk_id':0,'sha256':self.payload['sha256'],'sample_count':36}], 'sample_count':36,'source_status':'complete'})
        self.assertEqual(response.status_code, 200, response.text)

    def pref(self, model=False, physiology=False):
        result = self.client.put('/api/workflow/preferences', json={'auto_model':model,'auto_physiology':physiology})
        self.assertEqual(result.status_code, 200, result.text)

    def rows(self, sql, params=()):
        with closing(self.app.state.workflow.connect()) as db:
            return [dict(row) for row in db.execute(sql, params)]

    def test_defaults_owner_filter_and_csrf(self):
        result = self.client.get('/api/workflow/preferences')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'auto_model':False,'auto_physiology':False})
        response = self.client.get('/api/workflow/tasks').json()
        self.assertEqual([r['session_id'] for r in response['records']], ['mine'])
        self.assertEqual(response['records'][0]['stage'], 'uploading')
        self.assertEqual(self.client.get('/api/workflow/tasks', headers=self.device).status_code, 403)
        self.assertEqual(self.client.put('/api/workflow/preferences', headers={'X-CSRF-Token':''}, json={'auto_model':True,'auto_physiology':False}).status_code, 403)
        self.login('manager')
        self.assertEqual(self.client.get('/api/workflow/tasks').json()['records'], [])

    def test_completion_outbox_idempotent_and_not_retroactive(self):
        self.pref(physiology=True)
        self.complete(); self.complete()
        intents = self.rows('SELECT * FROM workflow_intents')
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0]['kind'], 'physiology')
        self.complete('theirs')
        self.assertEqual(len(self.rows('SELECT * FROM workflow_intents')), 1)
        self.login('other'); self.pref(physiology=True); self.complete('theirs')
        self.assertEqual(len(self.rows('SELECT * FROM workflow_intents')), 1)

    def test_dispatch_and_crash_retry_reuse_same_job(self):
        self.pref(physiology=True); self.complete()
        store = self.app.state.workflow
        with patch.object(self.app.state.jobs, 'start'):
            store.dispatch_once()
            job = self.rows('SELECT * FROM analysis_jobs')[0]
            with closing(store.connect()) as db, db:
                db.execute("UPDATE workflow_intents SET status='pending',job_id=NULL")
                db.execute("UPDATE analysis_jobs SET status='failed'")
            store.dispatch_once()
        self.assertEqual(len(self.rows('SELECT * FROM analysis_jobs')), 1)
        self.assertEqual(self.rows('SELECT * FROM workflow_intents')[0]['job_id'], job['job_id'])

    def test_disable_preference_cancels_unsubmitted_intent(self):
        self.pref(physiology=True); self.complete(); self.pref()
        self.app.state.workflow.dispatch_once()
        self.assertEqual(self.rows('SELECT * FROM analysis_jobs'), [])
        self.assertEqual(self.rows('SELECT * FROM workflow_intents')[0]['status'], 'cancelled')

    def test_reusing_manual_job_binds_intent_in_the_same_transaction(self):
        self.pref(physiology=True); self.complete()
        with patch.object(self.app.state.jobs, 'start'):
            response = self.client.post('/api/sessions/mine/physiology-jobs')
            self.assertEqual(response.status_code, 202, response.text)
            intent = self.rows('SELECT * FROM workflow_intents')[0]
            self.assertEqual(intent['job_id'], response.json()['job_id'])
            self.app.state.workflow.dispatch_once()
        self.assertEqual(len(self.rows('SELECT * FROM analysis_jobs')), 1)

    def test_binding_failure_rolls_back_job_and_intent(self):
        self.pref(physiology=True); self.complete()
        queue = self.app.state.jobs
        def broken(db, job):
            db.execute("UPDATE workflow_intents SET status='queued',job_id=?", (job['job_id'],))
            raise RuntimeError('simulated interruption')
        with self.assertRaises(RuntimeError):
            queue.enqueue('mine', 'test-digest', 36, kind='physiology', on_enqueued=broken)
        self.assertEqual(self.rows('SELECT * FROM analysis_jobs'), [])
        self.assertEqual(self.rows('SELECT * FROM workflow_intents')[0]['status'], 'pending')

    def test_restart_preserves_pending_intent_and_revoked_owner_cancels_it(self):
        self.pref(physiology=True); self.complete()
        from workflow_store import WorkflowStore
        original = self.app.state.workflow
        replacement = WorkflowStore(self.data, self.app.state.jobs, original.services['model'], original.services['physiology'])
        with closing(replacement.connect()) as db, db:
            db.execute('UPDATE users SET active=0 WHERE id=?', (self.user['id'],))
        replacement.dispatch_once()
        self.assertEqual(self.rows('SELECT * FROM analysis_jobs'), [])
        self.assertEqual(self.rows('SELECT * FROM workflow_intents')[0]['status'], 'cancelled')

    def test_backup_restore_invalidates_review_and_cancels_pending_work(self):
        from database_backup import create_backup, restore_backup
        self.pref(physiology=True); self.complete()
        current = self.client.get('/api/sessions/mine/review').json()
        self.assertEqual(self.client.put('/api/sessions/mine/review', json={
            'status':'viewed','note':'test','revision':0,'context':current['context']}).status_code, 200)
        backup = create_backup(self.data, 'a'*32)
        destination = self.data / 'restored'
        restore_backup(self.data / 'backups' / backup['filename'], destination)
        import sqlite3
        with closing(sqlite3.connect(destination / 'cloud.sqlite')) as db:
            self.assertEqual(db.execute('SELECT status FROM workflow_intents').fetchone()[0], 'cancelled')
            self.assertEqual(db.execute('SELECT context FROM record_reviews').fetchone()[0], 'restored')

    def test_model_not_ready_is_explicit_without_blocking_upload(self):
        self.pref(model=True); self.complete(); self.app.state.workflow.dispatch_once()
        record = self.client.get('/api/workflow/tasks').json()['records'][0]
        self.assertEqual(record['stage'], 'attention')
        self.assertEqual(record['automatic'][0]['status'], 'blocked')
        self.assertEqual(record['complete'], True)

    def test_queue_full_retries_later(self):
        from analysis_tasks import QueueFull
        self.pref(physiology=True); self.complete()
        with patch.object(self.app.state.jobs, 'enqueue', side_effect=QueueFull('full')):
            self.app.state.workflow.dispatch_once()
        intent = self.rows('SELECT * FROM workflow_intents')[0]
        self.assertEqual(intent['status'], 'pending')
        self.assertGreater(intent['next_try'], intent['created'])

    def test_review_owner_revision_and_changed_analysis(self):
        self.complete()
        path = '/api/sessions/mine/review'
        old = self.client.get(path).json()
        self.assertEqual(old['status'], 'pending')
        self.assertEqual(self.client.get('/api/sessions/mine/analysis').json()['source_digest'], old['basis']['analyses']['model']['digest'])
        body = {'status':'viewed','note':'已查看测试记录','revision':old['revision'],'context':old['context']}
        saved = self.client.put(path, json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['revision'], 1)
        self.assertEqual(self.client.put(path, json=body).status_code, 409)
        with patch.object(self.app.state.jobs, 'start'):
            self.assertEqual(self.client.post('/api/sessions/mine/physiology-jobs').status_code, 202)
        current = self.client.get(path).json()
        self.assertTrue(current['stale'])
        body.update(revision=1)
        self.assertEqual(self.client.put(path, json=body).status_code, 409)
        self.assertEqual(self.client.get('/api/sessions/theirs/review').status_code, 404)
        self.login('manager')
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_operations_admin_only_and_no_waveform_or_notes(self):
        self.assertEqual(self.client.get('/api/admin/operations').status_code, 403)
        self.login('manager')
        result = self.client.get('/api/admin/operations')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['uploads']['pending'], 2)
        self.assertIn('issues', result.json())
        for value in ('raw_adc','Owner-workflow','owner_id','source_digest','waveform','theirs'):
            self.assertNotIn(value, result.text)

    def test_task_center_marks_missing_or_old_result_for_reanalysis(self):
        self.complete()
        with patch.object(self.app.state.jobs, 'start'):
            job = self.client.post('/api/sessions/mine/physiology-jobs').json()
        with closing(self.app.state.workflow.connect()) as db, db:
            db.execute("UPDATE analysis_jobs SET status='complete' WHERE job_id=?", (job['job_id'],))
        result = self.client.get('/api/workflow/tasks').json()
        self.assertEqual(result['records'][0]['stage'], 'attention')
        self.assertEqual(result['records'][0]['jobs']['physiology']['status'], 'stale')
        self.assertEqual(result['counts']['attention'], 1)

    def test_trash_restore_cancels_automatic_intents_for_both_entrypoints(self):
        for admin in (False, True):
            with self.subTest(admin=admin):
                sid = 'trash-admin' if admin else 'trash-owner'
                self.login(); self.pref(physiology=True); self.register(sid, self.user['id']); self.complete(sid)
                if admin: self.login('manager')
                prefix = '/api/admin/database/records/' if admin else '/api/sessions/'
                self.assertEqual(self.client.post(prefix+sid+'/trash').status_code, 200)
                self.assertEqual(self.client.post(prefix+sid+'/restore').status_code, 200)
                with patch.object(self.app.state.jobs, 'start'): self.app.state.workflow.dispatch_once()
                self.assertEqual(self.rows('SELECT status FROM workflow_intents WHERE session_id=?', (sid,))[0]['status'], 'cancelled')
                self.assertEqual(self.rows('SELECT * FROM analysis_jobs WHERE session_id=?', (sid,)), [])


if __name__ == '__main__': unittest.main()
