import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from cloud.remote_measurement import RemoteMeasurements
from cloud.uploader import UploadError


class RemoteMeasurementTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).resolve().parents[1]/'work'/'remote-tests';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup)
        self.started=[];self.uploaded=[];self.snapshot=dict(running=False,session_id=None,error=None)
        def start(**kwargs):self.started.append(kwargs);self.snapshot.update(running=True,session_id='measurement1');return 'measurement1'
        self.controller=SimpleNamespace(snapshot=lambda:dict(self.snapshot),start=start)
        self.cloud_state=dict(phase='idle',session_id=None)
        self.cloud=SimpleNamespace(snapshot=lambda:dict(self.cloud_state),upload=lambda sid:self.uploaded.append(sid))
        self.remote=object.__new__(RemoteMeasurements)
        self.remote.controller=self.controller;self.remote.cloud=self.cloud;self.remote.path=Path(self.temp.name)/'receipt.json'
        self.remote.lock=threading.Lock();self.remote.port='/dev/ttyUSB0';self.remote.enabled=True;self.remote.pending=None
        self.calls=[];self.fail_claim=False;self.complete=False
        def request(method,path,payload=None):
            self.calls.append((method,path,payload))
            if path.endswith('/next'):return {'measurement':dict(id='a'*32,duration_s=60,owner_id='b'*32,owner_name='alice')}
            if path.endswith('/claim'):
                if self.fail_claim:raise OSError('lost response')
                return {'accepted':True}
            return {'status':'completed' if self.complete else payload['status']}
        self.client=SimpleNamespace(request=request)

    def test_capture_uses_real_serial_explicit_owner_and_requested_duration(self):
        self.remote.step(self.client)
        self.assertEqual(len(self.started),1);self.assertEqual(self.started[0]['source'],'serial')
        self.assertEqual(self.started[0]['duration'],60);self.assertEqual(self.started[0]['cloud_owner_id'],'b'*32)
        self.remote.step(self.client);self.assertEqual(len(self.started),1)
        self.snapshot['running']=False;self.remote.step(self.client);self.assertEqual(self.uploaded,['measurement1'])
        self.cloud_state.update(phase='complete',session_id='measurement1');self.complete=True;self.remote.step(self.client)
        self.assertIsNone(self.remote.pending)

    def test_ambiguous_claim_is_not_retried_as_physical_capture(self):
        self.fail_claim=True
        with self.assertRaises(OSError):self.remote.step(self.client)
        self.fail_claim=False;self.remote.step(self.client)
        self.assertEqual(self.started,[]);self.assertEqual(sum(path.endswith('/claim') for _,path,_ in self.calls),1)

    def test_busy_or_disabled_terminal_does_not_poll_for_start(self):
        self.remote.configure('/dev/ttyUSB0',False);self.remote.step(self.client);self.assertEqual(self.calls,[])
        self.remote.configure('/dev/ttyUSB0',True);self.snapshot['running']=True;self.remote.step(self.client);self.assertEqual(self.calls,[])

    def test_failed_capture_does_not_produce_success_or_upload(self):
        self.remote.step(self.client);self.snapshot.update(running=False,error='串口断开')
        self.remote.step(self.client);self.assertEqual(self.remote.pending['stage'],'failed')
        self.remote.step(self.client);self.assertEqual(self.uploaded,[])
        self.assertEqual(self.calls[-1][2]['status'],'failed')

    def test_expired_server_task_does_not_trap_capture_or_block_local_upload(self):
        self.remote.step(self.client)
        def expired(*args):raise UploadError('任务已经结束',409)
        self.client.request=expired
        self.remote.step(self.client)
        self.assertEqual(self.remote.pending['stage'],'recording')
        self.snapshot['running']=False
        self.remote.step(self.client)
        self.assertEqual(self.uploaded,['measurement1'])
        self.assertIsNone(self.remote.pending)


if __name__=='__main__':unittest.main()
