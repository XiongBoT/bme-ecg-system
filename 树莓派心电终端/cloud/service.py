"""Independent upload and heartbeat workers; bounded UI snapshots, no Tk calls."""
from copy import deepcopy
import json
import os
import platform
from pathlib import Path
import threading
import time

from recording import SESSION_ID
import session_management
from .uploader import Uploader, UploadError, Cancelled, atomic_json


def submit_analysis(client, sid):
    try:
        job = client.request('POST', f'/api/sessions/{sid}/analysis-jobs')
    except UploadError as exc:
        if exc.status_code != 404: raise
        client.timeout = 120
        return client.request('POST', f'/api/sessions/{sid}/analysis')
    if job.get('status') not in ('queued', 'running'):
        return client.request('GET', f'/api/sessions/{sid}/analysis')
    return dict(session_id=sid, analysis_status=job.get('status', 'queued'), job=job)


class CloudService:
    def __init__(self, data_dir, url=None, client_factory=Uploader, heartbeat_interval=10, controller=None):
        self.root = Path(data_dir)
        self.folder = self.root / 'cloud'
        self.url = url or os.getenv('ECG_CLOUD_URL','').strip() or ('http://127.0.0.1:8768' if os.name == 'nt' else 'http://127.0.0.1:8766')
        self.factory = client_factory
        self.lock = threading.RLock()
        # Serialise durable commands separately. The UI snapshot lock must
        # never cover filesystem I/O (SD-card fsync can take seconds).
        self.command_lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.heartbeat_wake = threading.Event()
        self.heartbeat_interval = heartbeat_interval
        self.device_status = dict(state='standby')
        self.health_assistant_supported = False
        self.controller = controller
        self.remote = None
        self.device_info = dict(model=platform.machine(), platform=platform.system()+' '+platform.release(),
                                app_version='health-assistant-1.1.0',serial_port='',sample_rate_hz=360,protocol='AA55 7-byte / 115200 8N1')
        try:
            model=Path('/proc/device-tree/model').read_text().strip('\x00\n ')
            if model:self.device_info['model']=model[:100]
        except OSError:pass
        self.generation = 0
        self.job = None
        self.state = dict(connection='connecting', message='自动连接云端…', session_id=None,
                          phase='idle', progress=None, result=None, model_status=None,
                          recipients=[], auth_required=None, heartbeat_status='unknown',
                          connection_detail='正在检查服务与设备凭据')
        try:
            cache = json.loads((self.folder/'recipients.json').read_text(encoding='utf-8'))
            if isinstance(cache.get('users'), list): self.state['recipients'] = cache['users'][:500]
            self.state['auth_required'] = cache.get('auth_required')
        except (OSError, ValueError): pass
        try:
            saved = json.loads((self.folder / 'pending.json').read_text(encoding='utf-8'))
            sid = saved.get('session_id')
            if isinstance(sid, str) and SESSION_ID.fullmatch(sid):
                self.job = sid
                self.state.update(session_id=sid, phase='waiting')
        except (OSError, ValueError):
            pass
        self.thread = threading.Thread(target=self._run, name='ecg-cloud', daemon=True)
        self.thread.start()
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, name='ecg-heartbeat', daemon=True)
        self.heartbeat_thread.start()
        if controller is not None:
            from .remote_measurement import RemoteMeasurements
            self.remote=RemoteMeasurements(controller,self)

    def update_device_status(self, snapshot):
        """Copy only bounded scalars; caller may be the 100-ms UI thread."""
        running = snapshot.get('running', False)
        mode = 'saving' if str(snapshot.get('state','')).upper() == 'STOPPING' else 'acquiring' if running else 'error' if snapshot.get('error') else 'standby'
        fields = dict(state=mode, owner_id=snapshot.get('cloud_owner_id') if running else None,
                      session_id=snapshot.get('session_id') if running else None,
                      signal_state=str(snapshot.get('signal_state','unknown'))[:40] if running else 'unknown',
                      signal_text=str(snapshot.get('signal_text',''))[:120] if running else '',
                      received=max(0,int(snapshot.get('received') or 0)) if running else 0,
                      saved=max(0,int(snapshot.get('saved') or 0)) if running else 0)
        port=snapshot.get('remote_port') or ''
        ready=bool(snapshot.get('remote_idle') and port and not running and not snapshot.get('error'))
        if self.remote:self.remote.configure(port,ready)
        fields.update(remote_ready=bool(self.remote and self.remote.ready()),
                      device_info=dict(self.device_info,serial_port=str(port)[:100]),
                      free_bytes=(snapshot.get('storage') or {}).get('free_bytes'))
        with self.lock: self.device_status = fields

    def _heartbeat(self):
        client = None
        while not self.stop.is_set():
            self.heartbeat_wake.clear()
            try:
                if client is None: client = self.factory(self.url, self.folder/'receipts', timeout=4)
                client.cancelled = self.stop.is_set
                health = client.request('GET', '/health')
                if health.get('service') != 'ecg-course-demo' or health.get('deployment') != 'cloud':
                    raise UploadError('设备状态地址不是已配置的云端')
                self.health_assistant_supported=health.get('health_assistant_version',0)>=1
                if health.get('workspace_version',0) >= 1:
                    recipients = client.request('GET', '/api/device/recipients')
                    users = recipients.get('users', [])[:500]
                    cache = dict(users=users, auth_required=bool(recipients.get('auth_required')))
                    with self.lock:
                        changed = self.state['recipients'] != users or self.state['auth_required'] != cache['auth_required']
                        self.state.update(recipients=users, auth_required=cache['auth_required'])
                        payload = dict(self.device_status, upload_phase=self.state['phase'], pending_uploads=int(bool(self.job)))
                    if changed: atomic_json(self.folder/'recipients.json', cache)
                    if not self.health_assistant_supported:
                        payload.pop('device_info',None);payload.pop('remote_ready',None)
                    client.request('PUT','/api/device/heartbeat',payload)
                    self._publish(heartbeat_status='online')
            except Cancelled: pass
            except Exception as exc:
                # Do not overwrite upload outcomes or display stale quality as live.
                self._publish(heartbeat_status='offline')
                if isinstance(exc, UploadError) and exc.status_code in (401,403):
                    self._publish(connection='unauthorized', connection_detail='设备凭据未配置或已失效，请同步设备凭据')
                client = None
            self.heartbeat_wake.wait(self.heartbeat_interval)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.state)

    def _publish(self, generation=None, **fields):
        with self.lock:
            if generation is None or generation == self.generation:
                self.state.update(fields)

    def upload(self, sid):
        if not isinstance(sid, str) or not SESSION_ID.fullmatch(sid):
            raise ValueError('请选择有效的本地记录')
        directory = session_management._directory(session_management._root(self.root), sid)
        if not (directory / 'index.sqlite').is_file():
            raise ValueError('记录尚未建立，请开始采集后再上传')
        with self.command_lock:
            if self.job:
                raise RuntimeError('已有上传任务；请等待完成或取消后再选择记录')
            atomic_json(self.folder / 'pending.json', {'session_id': sid})
            with self.lock:
                self.generation += 1
                self.job = sid
                self.state.update(session_id=sid, phase='waiting', progress=None, result=None,
                                  message='等待连接并上传选定记录')
        self.wake.set()

    def cancel(self):
        with self.command_lock:
            atomic_json(self.folder / 'pending.json', {'session_id': None})
            with self.lock:
                self.generation += 1
                self.job = None
                self.state.update(phase='cancelled', result=None, progress=None,
                                  message='已取消后续传输；本地记录和已上传云端数据保留')
        self.wake.set()

    def reconnect(self):
        self.wake.set()
        self.heartbeat_wake.set()

    def close(self):
        if self.remote:self.remote.close()
        self.stop.set()
        self.wake.set()
        self.heartbeat_wake.set()

    def wait(self, timeout=0):
        deadline = time.monotonic()+timeout
        for thread in (self.thread, self.heartbeat_thread) + ((self.remote.thread,) if self.remote else ()) :
            thread.join(max(0,deadline-time.monotonic()))
        return not self.thread.is_alive() and not self.heartbeat_thread.is_alive() and not (self.remote and self.remote.thread.is_alive())

    def resume(self):
        """Recover after a rejected power-off; durable jobs remain resumable."""
        if self.remote and self.remote.thread.is_alive():return False
        if self.thread.is_alive() or self.heartbeat_thread.is_alive():
            return False
        self.stop.clear()
        self.thread = threading.Thread(target=self._run, name='ecg-cloud', daemon=True)
        self.thread.start()
        self.heartbeat_thread = threading.Thread(target=self._heartbeat, name='ecg-heartbeat', daemon=True)
        self.heartbeat_thread.start()
        self._resume_remote()
        return True

    def _resume_remote(self):
        if self.controller is not None:
            from .remote_measurement import RemoteMeasurements
            self.remote=RemoteMeasurements(self.controller,self)

    def _finish(self, generation, **fields):
        with self.command_lock:
            if generation != self.generation:
                return
            atomic_json(self.folder / 'pending.json', {'session_id': None})
            with self.lock:
                self.job = None
                self.state.update(fields)

    def _run(self):
        client = None
        submitted_generation = None
        while not self.stop.is_set():
            self.wake.clear()
            with self.lock:
                sid, generation = self.job, self.generation
            def cancelled():
                return self.stop.is_set() or generation != self.generation
            # Reuse bounded validation metadata across watch passes. Rebind
            # cancellation and progress to this job, including after retries.
            try:
                if client is None:
                    client = self.factory(self.url, self.folder / 'receipts', timeout=5)
                client.timeout = 5
                client.cancelled = cancelled
                client.progress = lambda done, total: self._publish(generation, progress=(done, total))
                health = client.request('GET', '/health')
                if health.get('ok') is not True or health.get('service') != 'ecg-course-demo' or health.get('deployment') != 'cloud':
                    raise UploadError('连接地址不是已配置的心电云端服务')
                if health.get('workspace_version',0) >= 1 or health.get('auth_required'):
                    client.request('GET', '/api/device/recipients')
                else:
                    client.request('GET', '/api/sessions?limit=1')
                self._publish(connection='online', connection_detail='服务可访问，访问凭据验证通过', model_status=health.get('model_status'))
                if sid:
                    self._publish(generation, phase='uploading', message='上传已保存的数据块…')
                    # The acquisition writer is independent of this history lock.
                    # Prevent moving/deleting a source during a chunk read/upload.
                    with session_management._management_lock(self.root):
                        directory = session_management._directory(session_management._root(self.root), sid)
                        uploaded = client.sync(directory)
                    if cancelled():
                        raise Cancelled()
                    if not uploaded['complete']:
                        self._publish(generation, phase='watching', message='后台补传中；停止采集并保存完成后自动分析')
                    else:
                        self._publish(generation, phase='analyzing', message='数据已上传，等待云端分析…')
                        result = client.request('GET', f'/api/sessions/{sid}/analysis')
                        needs_submit = result.get('analysis_status') in ('not_run', 'stale') or (
                            result.get('analysis_status') == 'failed' and submitted_generation != generation)
                        if needs_submit:
                            result = submit_analysis(client, sid)
                            submitted_generation = generation
                        if result.get('session_id') != sid:
                            raise UploadError('云端结果与当前记录不匹配')
                        status = result.get('analysis_status')
                        if status == 'complete':
                            if not isinstance(result.get('model_result'), dict):
                                raise UploadError('云端结果内容不完整')
                            with self.command_lock:
                                if cancelled():
                                    raise Cancelled()
                                atomic_json(self.folder / 'results' / (sid + '.json'), result)
                            # Explicitly bounded fields; future server arrays
                            # must not accidentally enter every UI deepcopy.
                            model = result['model_result']
                            summary = {k: result.get(k) for k in ('session_id', 'analysis_status', 'model_name', 'model_version')}
                            summary['model_result'] = {
                                'counts': {k: (model.get('counts') or {}).get(k, 0) for k in ('N', 'S', 'V')},
                                'beat_count': model.get('beat_count', 0),
                                'eligible_samples': model.get('eligible_samples', 0)}
                            self._finish(generation, phase='complete', result=summary, message='云端分析完成，完整结果已保存')
                        elif status in ('ineligible', 'not_configured', 'failed'):
                            self._finish(generation, phase=status, result=None,
                                         message=result.get('message') or '当前记录无法完成云端分类')
                        elif status not in ('queued', 'running', 'not_run'):
                            raise UploadError('云端返回未知分析状态')
                elif self.state['phase'] == 'idle':
                    self._publish(message='云端已连接；选择记录上传并分析')
            except Cancelled:
                pass
            except UploadError as exc:
                if exc.status_code in (401,403):
                    client = None  # Reload a replaced credentials file on retry.
                    self._publish(connection='unauthorized', connection_detail='设备凭据未配置或已失效，请同步设备凭据')
                    self._publish(generation, message='设备授权失败；本地记录保留，更新凭据后重试')
                elif exc.retryable:
                    self._publish(generation, connection='offline', connection_detail=str(exc), message=str(exc))
                elif sid:
                    self._finish(generation, phase='failed', result=None, message=str(exc))
                else:
                    self._publish(connection='error', message=str(exc))
            except Exception as exc:
                if sid:
                    self._finish(generation, phase='failed', result=None, message='任务未完成：' + str(exc))
                else:
                    self._publish(connection='error', message='连接检查失败：' + str(exc))
            self.wake.wait(5 if self.job else 10)
