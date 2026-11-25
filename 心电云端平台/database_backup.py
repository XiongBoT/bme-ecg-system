"""Online SQLite snapshot + referenced immutable chunks; server-local backups."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile

from protocol import HEADER, ROWS, decode_chunk

RESERVE = 256 * 1024 * 1024
MAX_FILES = 100000
MAX_RAW = HEADER.size + 36000 * max(row.size for row in ROWS.values())
CHUNK_NAME = re.compile(r'sessions/[A-Za-z0-9][A-Za-z0-9_-]{0,95}/chunks/[0-9]{8,19}\.bin\Z')


def private_dir(data, name):
    target = Path(data) / name
    if target.is_symlink(): raise ValueError('维护目录不能是符号链接')
    target.mkdir(mode=0o700, exist_ok=True)
    if not target.is_dir(): raise ValueError('维护目录不可用')
    return target


def mark_owned(folder, job_id):
    if job_id:
        (Path(folder) / '.owner.json').write_text(json.dumps({'owner': 'ecg-maintenance-v1', 'job_id': job_id}), encoding='utf-8')


def cleanup_interrupted(data):
    """Only under the exclusive worker lock: remove our known partial files."""
    scratch = private_dir(data, '.maintenance')
    allowed = {'.owner.json', 'cloud.sqlite', 'cloud.sqlite-journal', 'cloud.sqlite-wal', 'cloud.sqlite-shm', 'backup.zip'}
    removed = 0
    with closing(readonly(Path(data) / 'cloud.sqlite')) as db:
        for folder in scratch.iterdir():
            if folder.is_symlink() or not folder.is_dir() or not folder.name.startswith(('backup-', 'check-')): continue
            try:
                marker = safe_file(folder, '.owner.json')
                if marker.stat().st_size > 1024: continue
                owner = json.loads(marker.read_text(encoding='utf-8'))
                if not isinstance(owner, dict) or owner.get('owner') != 'ecg-maintenance-v1': continue
                job_id = owner.get('job_id')
                if not isinstance(job_id, str) or not re.fullmatch('[0-9a-f]{32}', job_id): continue
                if not db.execute('SELECT 1 FROM management_jobs WHERE job_id=?', (job_id,)).fetchone(): continue
                children = list(folder.iterdir())
                if any(child.name not in allowed or child.is_symlink() or not child.is_file() for child in children): continue
                if folder.resolve().parent != scratch.resolve(): continue
                for child in children: child.unlink()
                folder.rmdir(); removed += 1
            except (OSError, ValueError):
                # Unknown or unreadable content remains visible in storage usage.
                continue
    return removed


def sync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)


def safe_file(root, relative):
    root = Path(root).resolve()
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in ('.', '..') for part in parts):
        raise ValueError('文件路径无效')
    target = root
    for part in parts:
        target = target / part
        if target.is_symlink(): raise ValueError('数据文件不能经过符号链接')
    if not target.resolve().is_relative_to(root): raise ValueError('数据文件超出允许目录')
    if not target.is_file(): raise ValueError('数据文件缺失')
    return target


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def digest_file(path, progress=lambda *_: None):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b''):
            progress(None, None, None)
            result.update(piece)
    return result.hexdigest()


def snapshot(data, destination, progress=lambda *_: None):
    source = safe_file(data, 'cloud.sqlite')
    deadline = time.monotonic() + 120
    progress(0, 0, '正在生成数据库快照')
    def copied(status, remaining, total):
        if time.monotonic() > deadline: raise ValueError('数据库快照超时，请在写入较少时重试')
        # Cancellation only: writing progress to the source here could repeatedly
        # restart SQLite's online snapshot, or wait on its own read lock.
        progress(None, None, None)
    with closing(readonly(source)) as db, closing(sqlite3.connect(destination)) as target:
        db.backup(target, pages=256, progress=copied, sleep=.05)
    return Path(destination)


def chunk_name(row):
    name = f"sessions/{row['session_id']}/chunks/{row['chunk_id']:08d}.bin"
    if not CHUNK_NAME.fullmatch(name): raise ValueError('数据库记录路径无效')
    return name


def checked_chunk(data, row):
    name = chunk_name(row)
    with safe_file(data, name).open('rb') as handle: raw = handle.read(MAX_RAW + 1)
    rows = decode_chunk(raw, row['sha256'])
    if (len(rows) != row['sample_count'] or rows[0][0] != row['first_id'] or rows[-1][0] != row['last_id']):
        raise ValueError('数据块内容与数据库索引不一致')
    return name, raw


def inspect_snapshot(data, snapshot_path, progress=lambda *_: None):
    issues, issue_count, count = [], 0, 0
    def issue(message):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 50: issues.append(message)
    with closing(readonly(snapshot_path)) as db:
        deadline = time.monotonic() + 60
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        for row in db.execute('PRAGMA quick_check'):
            if row[0] != 'ok': issue('数据库结构：' + str(row[0])[:160])
        for row in db.execute('PRAGMA foreign_key_check'):
            issue('外键引用错误：' + str(row[0])[:100])
        total = db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
        db.set_progress_handler(None, 0)
        for row in db.execute('SELECT * FROM chunks ORDER BY session_id,chunk_id'):
            progress(count, total, '正在核对原始数据块')
            try: checked_chunk(data, row)
            except (OSError, ValueError): issue(f"记录 {row['session_id']} 数据块 {row['chunk_id']} 缺失、损坏或索引不一致")
            count += 1
        for row in db.execute('SELECT s.id,s.sample_count,COALESCE(SUM(c.sample_count),0) AS actual '
                              'FROM sessions s LEFT JOIN chunks c ON c.session_id=s.id GROUP BY s.id'):
            if row['sample_count'] != row['actual']: issue('记录 ' + row['id'] + ' 的总点数与数据块清单不一致')
    progress(count, total, '完整性核对结束')
    return {'ok': not issue_count, 'chunks_checked': count, 'issue_count': issue_count,
            'issues': issues, 'issues_truncated': issue_count > len(issues),
            'scope': '数据库结构、外键、已登记原始块格式/摘要及点数；不扫描未登记孤立文件，不验证医学正确性'}


def check_snapshot(data, progress=lambda *_: None, job_id=None):
    scratch = private_dir(data, '.maintenance')
    with tempfile.TemporaryDirectory(prefix='check-', dir=scratch) as temp:
        mark_owned(temp, job_id)
        copied = snapshot(data, Path(temp) / 'cloud.sqlite', progress=progress)
        return inspect_snapshot(data, copied, progress)


def scan_storage(data, progress=lambda *_: None):
    totals = {'database': 0, 'raw': 0, 'analysis': 0, 'backups': 0, 'temporary': 0, 'other': 0}
    issues, errors, visited = [], 0, 0
    def failed(_):
        nonlocal errors
        errors += 1
        if len(issues) < 20: issues.append('部分路径无法读取，统计不完整')
    for directory, dirs, files in os.walk(data, followlinks=False, onerror=failed):
        kept = []
        for name in dirs:
            if (Path(directory) / name).is_symlink(): failed(None)
            else: kept.append(name)
        dirs[:] = kept
        for name in files:
            target = Path(directory) / name
            if target.is_symlink(): failed(None); continue
            relative = target.relative_to(data)
            category = ('raw' if relative.parts[0] == 'sessions' else 'backups' if relative.parts[0] == 'backups'
                        else 'temporary' if relative.parts[0] == '.maintenance'
                        else 'analysis' if relative.parts[0] in ('analysis', 'physiology')
                        else 'database' if name.startswith('cloud.sqlite') and len(relative.parts) == 1 else 'other')
            try: totals[category] += target.stat().st_size
            except OSError: failed(None)
            visited += 1
            progress(visited, 0, '正在统计存储占用')
    return {'bytes': totals, 'complete': errors == 0, 'issue_count': errors, 'issues': issues,
            'files': visited, 'scope': '文件逻辑大小，含临时维护文件；扫描期间可能继续增长'}


def create_backup(data, job_id, progress=lambda *_: None):
    data = Path(data)
    if not re.fullmatch('[a-f0-9]{32}', job_id): raise ValueError('备份编号无效')
    destination = private_dir(data, 'backups')
    scratch = private_dir(data, '.maintenance')
    if shutil.disk_usage(data).free < RESERVE + safe_file(data, 'cloud.sqlite').stat().st_size * 3:
        raise ValueError('空间不足，备份需保留至少 256 MiB 可用空间')
    filename = 'ecg-backup-' + job_id + '.zip'
    if (destination / filename).exists(): raise ValueError('备份已存在，不覆盖')
    with tempfile.TemporaryDirectory(prefix='backup-', dir=scratch) as temp:
        mark_owned(temp, job_id)
        copied = snapshot(data, Path(temp) / 'cloud.sqlite', progress=progress)
        manifest = {'version': 1, 'created': time.time(), 'scope': 'SQLite and referenced raw chunks; analysis caches excluded', 'files': {}}
        archive = Path(temp) / 'backup.zip'
        with closing(readonly(copied)) as db:
            if [row[0] for row in db.execute('PRAGMA quick_check')] != ['ok'] or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('数据库完整性检查未通过')
            mismatch = db.execute('SELECT s.id FROM sessions s LEFT JOIN chunks c ON c.session_id=s.id '
                'GROUP BY s.id HAVING s.sample_count != COALESCE(SUM(c.sample_count),0) LIMIT 1').fetchone()
            if mismatch: raise ValueError('记录总点数与数据块清单不一致，未生成备份')
            total = db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
            if total + 1 > MAX_FILES: raise ValueError('单份备份最多支持十万个文件')
            sessions = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
            estimated = db.execute('SELECT COALESCE(SUM(sample_count),0) FROM chunks').fetchone()[0] * max(r.size for r in ROWS.values()) + total * HEADER.size
            if shutil.disk_usage(data).free < RESERVE + estimated + copied.stat().st_size * 2:
                raise ValueError('空间不足，无法同时保留数据库快照与备份')
            with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
                manifest['files']['cloud.sqlite'] = {'sha256': digest_file(copied, progress), 'bytes': copied.stat().st_size}
                bundle.write(copied, 'cloud.sqlite')
                for index, row in enumerate(db.execute('SELECT * FROM chunks ORDER BY session_id,chunk_id'), 1):
                    progress(index - 1, total, '正在备份并校验原始数据块')
                    name, raw = checked_chunk(data, row)
                    if shutil.disk_usage(data).free < RESERVE + len(raw): raise ValueError('可用空间下降，备份已停止')
                    bundle.writestr(name, raw)
                    manifest['files'][name] = {'sha256': row['sha256'], 'bytes': len(raw)}
                bundle.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False).encode())
        with archive.open('r+b') as handle: os.fsync(handle.fileno())
        # Read back with cancellation and hashes, before making the name visible.
        with zipfile.ZipFile(archive) as bundle:
            for name, item in manifest['files'].items():
                digest = hashlib.sha256()
                with bundle.open(name) as source:
                    for part in iter(lambda: source.read(1024 * 1024), b''):
                        progress(None, None, None); digest.update(part)
                if digest.hexdigest() != item['sha256']: raise ValueError('备份压缩包校验失败')
            if json.loads(bundle.read('MANIFEST.json')) != manifest: raise ValueError('备份清单校验失败')
        progress(total, total, '备份已校验，正在保存')
        size, digest = archive.stat().st_size, digest_file(archive, progress)
        os.replace(archive, destination / filename)
        sync_directory(destination)
        sync_directory(Path(temp))
        sync_directory(data)
    return {'filename': filename, 'bytes': size, 'sha256': digest, 'chunks': total, 'sessions': sessions,
            'scope': '数据库与其清单引用的原始波形；分析缓存不包含在内', 'server_only': True}


def restore_backup(archive, destination):
    """Offline recovery to a new directory. No overwrite and no live service calls."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink(): raise ValueError('恢复目标必须是尚不存在的新目录')
    parent = destination.parent
    if not parent.is_dir() or parent.resolve() != parent: raise ValueError('恢复父目录必须存在且不能经过符号链接')
    archive = Path(archive)
    if archive.is_symlink(): raise ValueError('备份文件不能是符号链接')
    with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory(prefix='.ecg-restore-', dir=parent) as staging:
        root = Path(staging)
        infos = bundle.infolist()
        names = [info.filename for info in infos]
        if len(names) > MAX_FILES + 1 or len(names) != len(set(names)) or 'MANIFEST.json' not in names:
            raise ValueError('备份文件清单无效')
        if bundle.getinfo('MANIFEST.json').file_size > 32 * 1024 * 1024: raise ValueError('备份清单过大')
        manifest = json.loads(bundle.read('MANIFEST.json'))
        files = manifest.get('files') if isinstance(manifest, dict) else None
        if not isinstance(manifest, dict) or manifest.get('version') != 1 or not isinstance(files, dict) or 'cloud.sqlite' not in files or set(names) != set(files) | {'MANIFEST.json'}:
            raise ValueError('备份版本或文件清单不匹配')
        if shutil.disk_usage(parent).free < sum(info.file_size for info in infos) + RESERVE:
            raise ValueError('恢复空间不足')
        for name, item in files.items():
            if name != 'cloud.sqlite' and not CHUNK_NAME.fullmatch(name): raise ValueError('备份包含未允许的文件路径')
            info = bundle.getinfo(name)
            if not isinstance(item, dict) or type(item.get('bytes')) is not int or item['bytes'] < 0 or item['bytes'] != info.file_size:
                raise ValueError('备份文件长度不匹配')
            if name != 'cloud.sqlite' and info.file_size > MAX_RAW: raise ValueError('原始块超出长度限制')
            if ((info.external_attr >> 16) & 0o170000) == 0o120000: raise ValueError('备份不能包含符号链接')
            output = root / name
            output.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with bundle.open(info) as src, output.open('xb') as dest:
                for part in iter(lambda: src.read(1024 * 1024), b''):
                    digest.update(part); dest.write(part)
            if digest.hexdigest() != item.get('sha256'): raise ValueError('备份文件摘要不匹配')
        checked = inspect_snapshot(root, root / 'cloud.sqlite')
        if not checked['ok']: raise ValueError('恢复前完整性校验未通过')
        with closing(sqlite3.connect(root / 'cloud.sqlite')) as db, db:
            db.row_factory = sqlite3.Row
            expected = {chunk_name(row) for row in db.execute('SELECT * FROM chunks')} | {'cloud.sqlite'}
            if set(files) != expected: raise ValueError('备份原始块与数据库清单不一致')
            db.execute('DELETE FROM browser_sessions')
            db.execute('DELETE FROM device_keys')
            db.execute("UPDATE analysis_jobs SET status='failed',stage='备份恢复，请重新分析',error='派生缓存不在备份范围内'")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'measurement_requests' in tables:
                db.execute("UPDATE measurement_requests SET status='failed',message='从备份恢复，请重新确认并发起测量' "
                           "WHERE status IN ('queued','accepted','recording','uploading')")
            if 'workflow_intents' in tables:
                db.execute("UPDATE workflow_intents SET status='cancelled',message='备份恢复，需由本人重新提交分析'")
            if 'record_reviews' in tables:
                db.execute("UPDATE record_reviews SET context='restored'")
            if 'management_jobs' in tables:
                db.execute("UPDATE management_jobs SET status='interrupted',stage='从备份恢复，需重新执行',error='原运行环境已改变'")
        # The temporary child is renamed, never merged with an existing directory.
        if destination.exists(): raise ValueError('目标目录已出现，停止恢复')
        os.rename(root, destination)
    return {'ok': True, 'chunks': checked['chunks_checked'], 'login_sessions_revoked': True, 'device_keys_revoked': True}
