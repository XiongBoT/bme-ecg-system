from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import patch
import test_workflow as fixtures


class BackupScheduleTests(unittest.TestCase):
    login=fixtures.WorkflowTests.login
    register=fixtures.WorkflowTests.register

    def setUp(self):
        fixtures.WorkflowTests.setUp(self)
        self.login('manager')
        self.url='/api/admin/database/backup-schedule'
        self.now=datetime(2026,11,25,17,tzinfo=timezone.utc).timestamp() # local next day 01:00

    def configure(self,**changes):
        with patch('backup_schedule.clock',return_value=self.now):
            return self.client.put(self.url,json=dict(enabled=True,hour=2,minute=0,revision=0,**changes))

    def test_defaults_permissions_and_revision(self):
        r=self.client.get(self.url);self.assertEqual(r.status_code,200)
        self.assertFalse(r.json()['enabled']);self.assertEqual(r.json()['revision'],0)
        self.assertEqual(self.configure().status_code,200)
        self.assertEqual(self.configure().status_code,409)
        self.login();self.assertEqual(self.client.get(self.url).status_code,403)
        self.login('manager')
        self.assertEqual(self.client.put(self.url,json={'enabled':'yes','hour':2,'minute':0,'revision':1}).status_code,422)
        self.assertEqual(self.client.put(self.url,headers={'X-CSRF-Token':''},json={'enabled':False,'hour':2,'minute':0,'revision':1}).status_code,403)

    def test_busy_low_space_then_single_catchup_after_restart(self):
        self.assertEqual(self.configure().status_code,200)
        schedule=self.app.state.backup_schedule
        due=self.now+3600
        # Prevent child processes; inspect the durable handoff instead.
        with patch.object(self.app.state.maintenance,'start'),patch('backup_schedule.shutil.disk_usage',return_value=SimpleNamespace(free=8*1024**3)):
            self.assertFalse(schedule.tick(self.now))
            busy=self.app.state.database.enqueue(self.admin['id'],'scan')
            self.assertFalse(schedule.tick(due+10))
            with closing(self.app.state.workflow.connect()) as db,db:db.execute("UPDATE management_jobs SET status='complete'")
            with patch('backup_schedule.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
                self.assertFalse(schedule.tick(due+20))
                self.assertEqual(schedule.read()['state'],'blocked')
            # Several missed days produce one catch-up, not a burst of backups.
            self.assertTrue(schedule.tick(due+3*86400))
            from backup_schedule import BackupSchedule
            restored=BackupSchedule(self.data,self.app.state.maintenance)
            self.assertFalse(restored.tick(due+3*86400+1))
            with closing(schedule.connect()) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM management_jobs WHERE kind='backup'").fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM backup_schedule_runs').fetchone()[0],1)
            self.assertGreater(schedule.read()['next_due'],due+3*86400)

    def test_disable_and_finished_status(self):
        self.configure()
        schedule=self.app.state.backup_schedule
        with patch.object(self.app.state.maintenance,'start'),patch('backup_schedule.shutil.disk_usage',return_value=SimpleNamespace(free=8*1024**3)):
            self.assertTrue(schedule.tick(self.now+3601))
        with closing(schedule.connect()) as db,db:
            db.execute("UPDATE management_jobs SET status='failed',error='空间不足'")
        self.assertEqual(schedule.read()['last_run']['status'],'failed')
        self.assertEqual(self.client.put(self.url,json={'enabled':False,'hour':2,'minute':0,'revision':1}).status_code,200)
        self.assertFalse(schedule.tick(self.now+10*86400));self.assertIsNone(schedule.read()['next_due'])

    def test_recovered_queued_backup_covers_missed_days(self):
        self.configure()
        schedule=self.app.state.backup_schedule
        due=self.now+3600
        resumed=due+3*86400+10
        stop=threading.Event()
        def backup(*args):
            stop.set()
            return {'ok':True}
        with patch.object(self.app.state.maintenance,'start'),patch('backup_schedule.shutil.disk_usage',return_value=SimpleNamespace(free=8*1024**3)):
            self.assertTrue(schedule.tick(due))
            from maintenance_tasks import worker
            with patch('maintenance_tasks.time.time',return_value=resumed),patch('maintenance_tasks.create_backup',side_effect=backup):
                worker(str(self.data),stop)
            self.assertFalse(schedule.tick(resumed+30))
            with closing(schedule.connect()) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM management_jobs WHERE kind='backup'").fetchone()[0],1)
            self.assertGreater(schedule.read()['next_due'],resumed)
            self.assertEqual(schedule.read()['last_run']['status'],'complete')

    def test_restore_disables_schedule_but_keeps_interval_notes(self):
        self.configure()
        self.login()
        fixtures.WorkflowTests.complete(self)
        note={'start_sample':0,'end_sample':35,'kind':'note','note':'合成标注','revision':0,'deleted':False}
        self.assertEqual(self.client.put('/api/sessions/mine/annotations/'+'a'*32,json=note).status_code,200)
        from database_backup import create_backup,restore_backup
        result=create_backup(self.data,'b'*32)
        restored=self.data/'restored-check'
        restore_backup(self.data/'backups'/result['filename'],restored)
        from database_management import connect
        with closing(connect(restored)) as db:
            row=db.execute('SELECT enabled,next_due,revision FROM backup_schedule').fetchone()
            self.assertEqual(tuple(row),(0,None,2))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM annotation_events').fetchone()[0],1)
