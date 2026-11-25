import json
from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from server import create_app
from health_routes import period_bounds


class HealthAssistantTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'.test_runs';scratch.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.addCleanup(self.temp.cleanup)
        self.app=create_app(self.temp.name,auth_enabled=True,cookie_secure=False)
        self.admin=self.app.state.auth.create_user('admin','admin-password',True)
        self.alice=self.app.state.auth.create_user('alice','abcde')
        self.bob=self.app.state.auth.create_user('bobby','12345')
        self.a=self.login('alice','abcde');self.b=self.login('bobby','12345');self.ad=self.login('admin','admin-password')
        result=self.ad.post('/api/admin/devices',json=dict(device_id='pi-health',name='健康终端',user_ids=[self.alice['id']])).json()
        self.device=TestClient(self.app);self.addCleanup(self.device.close)
        self.device.headers['X-API-Key']=result['credentials']['token']
        self.beat()

    def login(self,name,password):
        c=TestClient(self.app);self.addCleanup(c.close)
        result=c.post('/api/auth/login',json=dict(username=name,password=password))
        self.assertEqual(result.status_code,200,result.text)
        c.headers['X-CSRF-Token']=result.json()['csrf_token'];return c

    def beat(self,**extra):
        result=self.device.put('/api/device/heartbeat',json=dict(state='standby',remote_ready=True,**extra))
        self.assertEqual(result.status_code,200,result.text)

    def payload(self,key='a'*32,**kwargs):
        return dict(device_id='pi-health',duration_s=60,request_key=key,**kwargs)

    def query(self,period='day',anchor='2026-11-25'):
        return self.a.get('/api/records/trends',params=dict(period=period,anchor=anchor,utc_offset_minutes=480))

    def test_five_character_password_create_change_reset_and_four_rejected(self):
        self.assertEqual(self.ad.post('/api/admin/users',json=dict(username='short',password='1234')).status_code,422)
        self.assertEqual(self.ad.post('/api/admin/users',json=dict(username='five5',password='12345')).status_code,200)
        self.assertEqual(self.a.post('/api/auth/password',json=dict(current_password='abcde',new_password='vwxyz')).status_code,200)
        self.login('alice','vwxyz')
        self.assertEqual(self.ad.post('/api/admin/users/'+self.alice['id']+'/password',json=dict(new_password='54321')).status_code,200)
        self.login('alice','54321')

    def test_requests_are_owned_authorized_idempotent_and_exclusive(self):
        denied=self.b.post('/api/measurements',json=self.payload());self.assertEqual(denied.status_code,403)
        first=self.a.post('/api/measurements',json=self.payload());self.assertEqual(first.status_code,202,first.text)
        again=self.a.post('/api/measurements',json=self.payload());self.assertEqual(first.json()['id'],again.json()['id'])
        self.assertEqual(self.a.post('/api/measurements',json=self.payload('b'*32)).status_code,409)
        self.assertEqual(self.b.get('/api/measurements').json()['measurements'],[])
        self.assertEqual(self.device.get('/api/measurements').status_code,403)

    def test_offline_or_legacy_terminal_cannot_start(self):
        self.device.put('/api/device/heartbeat',json=dict(state='standby'))
        self.assertEqual(self.a.post('/api/measurements',json=self.payload()).status_code,409)
        self.beat()
        with closing(sqlite3.connect(Path(self.temp.name)/'cloud.sqlite')) as db, db:db.execute('UPDATE device_heartbeats SET seen=?',(time.time()-60,))
        self.assertEqual(self.a.post('/api/measurements',json=self.payload()).status_code,409)

    def test_claim_is_once_only_and_does_not_repeat_after_restart(self):
        task=self.a.post('/api/measurements',json=self.payload()).json()
        pending=self.device.get('/api/device/measurements/next').json()['measurement'];self.assertEqual(pending['owner_id'],self.alice['id'])
        path='/api/device/measurements/'+task['id']+'/claim'
        self.assertEqual(self.device.post(path,json={}).status_code,200)
        self.assertEqual(self.device.post(path,json={}).status_code,409)
        self.assertIsNone(self.device.get('/api/device/measurements/next').json()['measurement'])
        create_app(self.temp.name,auth_enabled=True,cookie_secure=False)
        self.assertEqual(self.device.post(path,json={}).status_code,409)

    def test_revoked_authorization_and_expiry_prevent_capture(self):
        task=self.a.post('/api/measurements',json=self.payload()).json()
        self.app.state.devices.update('pi-health',user_ids=[])
        self.assertIsNone(self.device.get('/api/device/measurements/next').json()['measurement'])
        self.assertEqual(self.a.get('/api/measurements').json()['measurements'][0]['status'],'failed')
        self.app.state.devices.update('pi-health',user_ids=[self.alice['id']])
        task=self.a.post('/api/measurements',json=self.payload('b'*32)).json()
        with closing(sqlite3.connect(Path(self.temp.name)/'cloud.sqlite')) as db, db:db.execute('UPDATE measurement_requests SET expires_at=? WHERE id=?',(time.time()-1,task['id']))
        self.assertIsNone(self.device.get('/api/device/measurements/next').json()['measurement'])
        self.assertEqual(self.a.get('/api/measurements').json()['measurements'][0]['status'],'expired')

    def test_only_matching_complete_record_creates_report(self):
        task=self.a.post('/api/measurements',json=self.payload()).json();path='/api/device/measurements/'+task['id']
        self.device.post(path+'/claim',json={})
        self.assertEqual(self.device.post(path+'/status',json=dict(status='recording',session_id='health-one')).status_code,200)
        self.device.put('/api/sessions/health-one',json=dict(source='serial',started_utc='2026-11-25T01:00:00Z',owner_id=self.alice['id']))
        self.assertEqual(self.a.get('/api/measurements').json()['measurements'][0]['status'],'recording')
        self.device.post('/api/sessions/health-one/complete',json=dict(chunks=[],sample_count=0,source_status='complete'))
        completed=self.a.get('/api/measurements').json()['measurements'][0]
        self.assertEqual(completed['status'],'completed');self.assertEqual(completed['session_id'],'health-one')
        acknowledgement=self.device.post(path+'/status',json=dict(status='uploading',session_id='health-one'))
        self.assertEqual(acknowledgement.status_code,200,acknowledgement.text)
        self.assertEqual(acknowledgement.json()['status'],'completed')
        self.assertEqual(self.device.post(path+'/status',json=dict(status='uploading',session_id='different')).status_code,409)

    def test_trends_aggregate_all_pages_owner_timezone_trash_and_missing_hr(self):
        with closing(sqlite3.connect(Path(self.temp.name)/'cloud.sqlite')) as db, db:
            for i in range(151):
                metadata=json.dumps(dict(source='serial',started_utc='2026-11-24T16:00:00Z'))
                db.execute('INSERT INTO sessions(id,metadata,created_at,sample_count,complete,owner_id,ingest_device_id) VALUES(?,?,?,?,?,?,?)',
                           ('record'+str(i),metadata,'2026-11-25T00:00:00Z',21600,1,self.alice['id'] if i<150 else self.bob['id'],'pi-health'))
            db.execute("INSERT INTO session_details VALUES('record0','','','2026-11-25T00:00:00Z')")
            db.execute("INSERT INTO measurement_summaries VALUES('record1',?)",(json.dumps(dict(analysis_stats=dict(hr=dict(mean=72.,window_samples=360)))),))
        result=self.query();self.assertEqual(result.status_code,200,result.text);data=result.json()
        self.assertEqual(data['total_records'],149);self.assertEqual(len(data['buckets']),24)
        self.assertEqual(data['buckets'][0]['hr_mean'],72.);self.assertIsNone(data['buckets'][1]['hr_mean'])
        self.assertEqual(self.query(anchor='2026-11-24').json()['total_records'],0)
        self.assertEqual(self.b.get('/api/records/trends',params=dict(period='year',anchor='2026-11-25')).json()['total_records'],1)

    def test_calendar_and_invalid_dates(self):
        self.assertEqual(len(self.query('month','2024-02-01').json()['buckets']),29)
        self.assertEqual(len(self.query('year').json()['buckets']),12)
        self.assertEqual(self.query('day','2026-02-30').status_code,422)
        self.assertEqual(self.query('year','9999-12-31').status_code,422)

    def test_device_information_is_admin_only(self):
        self.beat(device_info=dict(model='Raspberry Pi 2',app_version='1.1.0',serial_port='/dev/ttyUSB0'),free_bytes=1073741824)
        admin=next(d for d in self.ad.get('/api/admin/devices').json()['devices'] if d['device_id']=='pi-health')
        self.assertEqual(admin['device_info']['model'],'Raspberry Pi 2');self.assertEqual(admin['free_bytes'],1073741824)
        self.assertEqual(admin['connection'],'online');self.assertIn('created_at',admin)
        console=self.ad.get('/api/admin/console/devices/pi-health').json()['device']
        self.assertEqual(console['device_info']['model'],'Raspberry Pi 2')
        self.assertEqual(console['free_bytes'],1073741824)
        self.assertTrue(console['remote_ready'])
        with closing(sqlite3.connect(Path(self.temp.name)/'cloud.sqlite')) as db,db:
            db.execute('UPDATE device_heartbeats SET seen=?',(time.time()-60,))
        self.assertFalse(self.ad.get('/api/admin/console/devices/pi-health').json()['device']['remote_ready'])
        self.assertEqual(self.a.get('/api/admin/console/devices/pi-health').status_code,403)
        ordinary=self.a.get('/api/devices').json()['devices']
        self.assertTrue(all('device_info' not in d for d in ordinary))

    def test_body_validation_and_csrf(self):
        self.a.headers.pop('X-CSRF-Token')
        self.assertEqual(self.a.post('/api/measurements',json=self.payload()).status_code,403)
        self.a=self.login('alice','abcde')
        payload=self.payload();payload['duration_s']=120
        self.assertEqual(self.a.post('/api/measurements',json=payload).status_code,422)
        payload=self.payload();payload['owner_id']=self.bob['id']
        self.assertEqual(self.a.post('/api/measurements',json=payload).status_code,422)


if __name__=='__main__':unittest.main()
