"""Execute explicitly requested serial captures once, with a durable recovery receipt."""
import json
import threading
import time

from .uploader import atomic_json, UploadError


class RemoteMeasurements:
    def __init__(self, controller, cloud):
        self.controller, self.cloud = controller, cloud
        self.path = cloud.folder/'remote-measurement.json'
        self.lock = threading.Lock()
        self.port = None
        self.enabled = False
        self.pending = None
        self.stop = threading.Event()
        try:
            prior=json.loads(self.path.read_text(encoding='utf-8'))
            if prior.get('id') and prior.get('stage')!='finished':
                # Never automatically restart a physical capture after a process crash.
                self.pending=dict(prior,stage='failed',message='终端已重启；请检查本地记录，未自动重新采集')
        except (OSError,ValueError):pass
        self.thread=threading.Thread(target=self._run,name='ecg-remote-measurement',daemon=True)
        self.thread.start()

    def configure(self, port, enabled):
        with self.lock:self.port,self.enabled=port,bool(enabled)

    def ready(self):
        with self.lock:return bool(self.enabled and self.port and self.pending is None)

    def close(self):
        self.stop.set()

    def _save(self, **updates):
        self.pending.update(updates)
        atomic_json(self.path,self.pending)

    def _status(self, client, status, message):
        payload=dict(status=status,message=message)
        if self.pending.get('session_id'):payload['session_id']=self.pending['session_id']
        try:
            return client.request('POST','/api/device/measurements/'+self.pending['id']+'/status',payload)
        except UploadError as exc:
            if exc.status_code in (404,409):
                # A server-expired task must not trap the local capture/upload worker forever.
                return {'status':'failed'}
            raise

    def step(self, client):
        if self.pending:
            stage=self.pending['stage']
            if stage in ('prepared','failed'):
                try:self._status(client,'failed',self.pending.get('message') or '终端准备中断，请重新发起测量')
                except UploadError as exc:
                    if exc.status_code not in (404,409):raise
                self._save(stage='finished');self.pending=None
                return
            snapshot=self.controller.snapshot()
            if stage=='recording':
                signal=str(snapshot.get('signal_text') or '等待采集信号')[:100]
                self._status(client,'recording','正在采集，请保持静止。'+signal)
                if snapshot.get('session_id')!=self.pending.get('session_id'):
                    self._save(stage='failed',message='终端记录已切换，请检查本地记录');return
                if snapshot.get('running'):return
                if snapshot.get('error'):
                    self._save(stage='failed',message='采集未完成：'+str(snapshot['error'])[:100]);return
                # Record the upload intent before dispatch. Repeating upload is idempotent.
                self._save(stage='uploading')
            if self.pending['stage']=='uploading':
                sid=self.pending['session_id']
                state=self.cloud.snapshot()
                if state.get('session_id')!=sid or state.get('phase')=='idle':self.cloud.upload(sid)
                response=self._status(client,'uploading','采集已结束，正在上传并生成报告')
                if response.get('status') in ('completed','failed','expired'):
                    self._save(stage='finished');self.pending=None
                elif state.get('phase')=='failed':
                    self._save(stage='failed',message='上传失败，本地记录保留，请在终端重新上传')
            return
        with self.lock:port,enabled=self.port,self.enabled
        if not enabled or not port or self.controller.snapshot().get('running'):return
        if self.cloud.snapshot().get('phase') in ('waiting','watching','uploading','analyzing'):return
        command=client.request('GET','/api/device/measurements/next').get('measurement')
        if not command:return
        if command.get('duration_s') not in (60,180,300):return
        # Persist BEFORE claiming; lost claim responses must never start a second capture.
        self.pending=dict(id=command['id'],stage='prepared',session_id=None)
        self._save()
        client.request('POST','/api/device/measurements/'+command['id']+'/claim',{})
        with self.lock:
            if not self.enabled or self.port!=port:
                self._save(stage='failed',message='终端连接或页面状态已改变，请重新确认');return
        try:
            sid=self.controller.start(source='serial',port=port,duration=command['duration_s'],
                                      cloud_owner_id=command['owner_id'],cloud_owner_name=command['owner_name'])
            self._save(stage='recording',session_id=sid)
        except Exception as exc:self._save(stage='failed',message='无法开始采集：'+str(exc)[:100])

    def _run(self):
        client=None
        while not self.stop.is_set():
            try:
                if getattr(self.cloud,'health_assistant_supported',False):
                    if client is None:client=self.cloud.factory(self.cloud.url,self.cloud.folder/'receipts',timeout=4)
                    client.cancelled=self.stop.is_set
                    self.step(client)
            except Exception:
                client=None  # Keep the durable receipt and retry only acknowledgements/upload.
            self.stop.wait(2)
