"""Synthetic archives and admin permission boundaries; no production files."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from database_backup import create_backup, digest_file
from research.backup_audit import audit
from server import create_app
from test_pipeline import block, STAMP


class BackupOperationsTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'.test_runs';scratch.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data'
        self.app=create_app(self.data,auth_enabled=True,cookie_secure=False)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        for name,admin in [('reader',False),('manager',True)]:
            self.app.state.auth.create_user(name,'test-password',admin)

    def test_schedule_snapshot_is_admin_only_and_reports_disabled_blocked_and_late(self):
        self.assertEqual(self.client.get('/api/admin/operations').status_code,401)
        self.client.post('/api/auth/login',json=dict(username='reader',password='test-password'))
        self.assertEqual(self.client.get('/api/admin/operations').status_code,403)
        self.client.post('/api/auth/login',json=dict(username='manager',password='test-password'))
        result=self.client.get('/api/admin/operations').json()
        self.assertFalse(result['backup_schedule']['enabled'])
        self.assertIn('backup_schedule_disabled',[r['code'] for r in result['issues']])
        with closing(self.app.state.workflow.connect()) as db,db:
            db.execute("UPDATE backup_schedule SET enabled=1,state='blocked',message='private server path',next_due=?",(time.time()-3600,))
        result=self.client.get('/api/admin/operations').json()
        self.assertIn('backup_schedule_blocked',[r['code'] for r in result['issues']])
        self.assertNotIn('private server path',json.dumps(result))
        self.assertNotIn('actor_id',result['backup_schedule'])
        with closing(self.app.state.workflow.connect()) as db,db:
            db.execute("UPDATE backup_schedule SET state='scheduled'")
        result=self.client.get('/api/admin/operations').json()
        self.assertIn('backup_schedule_overdue',[r['code'] for r in result['issues']])

    def test_isolated_restore_integrity_and_preview_never_changes_archives(self):
        owner=self.app.state.auth.create_user('fixture','fixture-password')
        key={'X-API-Key':self.app.state.auth.create_device_key('pi2-demo')}
        self.assertEqual(self.client.put('/api/sessions/fixture',headers=key,json=dict(source='demo',started_utc=STAMP,owner_id=owner['id'])).status_code,200)
        self.assertEqual(self.client.put('/api/sessions/fixture/chunks/0',headers=key,json=block()).status_code,200)
        result=create_backup(self.data,'a'*32)
        source=self.data/'backups'/result['filename']
        second=source.with_name('second.zip');second.write_bytes(source.read_bytes())
        before={p.name:digest_file(p) for p in [source,second]}
        result=audit([source,second],verify=True,scratch=self.root)
        self.assertTrue(result['verified'],result)
        self.assertTrue(all(r['chunks_checked']==1 for r in result['files']))
        self.assertEqual(result['candidate_bytes'],0)
        result=audit([source,second],keep_newest=1,verify=True,scratch=self.root)
        self.assertEqual(sum(r['candidate'] for r in result['files']),1)
        self.assertEqual(result['deleted'],0)
        self.assertEqual(before,{p.name:digest_file(p) for p in [source,second]})
        self.assertEqual(list(self.root.glob('ecg-backup-audit-*')),[])

    def test_corrupt_missing_and_linked_backups_never_become_candidates(self):
        corrupt=self.root/'corrupt.zip';corrupt.write_bytes(b'broken')
        result=audit([corrupt,self.root/'missing.zip'],keep_newest=1,verify=True,scratch=self.root)
        self.assertFalse(result['ok']);self.assertEqual(result['candidate_bytes'],0)
        with patch('research.backup_audit.Path.is_symlink',return_value=True):
            result=audit([corrupt],verify=True)
        self.assertFalse(result['ok']);self.assertFalse(result['verified'])

    def test_size_only_inventory_cannot_claim_verification_or_cleanup_candidates(self):
        path=self.root/'unverified.zip';path.write_bytes(b'not yet checked')
        result=audit([path],keep_newest=1)
        self.assertTrue(result['ok']);self.assertFalse(result['verified']);self.assertEqual(result['candidate_bytes'],0)


if __name__=='__main__':unittest.main()
