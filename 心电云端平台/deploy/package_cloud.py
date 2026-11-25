"""Build a reproducible, source-only Linux cloud bundle from an explicit allowlist."""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'deploy' / 'dist'
MEMBERS = (
    'server.py', 'protocol.py', 'run_server.py', 'uploader.py', 'requirements.txt', 'requirements-model.txt',
    'auth_store.py', 'workspace_store.py', 'analysis_tasks.py', 'manage_accounts.py', 'measurement_store.py',
    'account_applications.py', 'web/applications.js', 'health_routes.py', 'web/health.js', 'web/health_core.js', 'web/health.css',
    'device_store.py', 'device_routes.py', 'web/devices.js',
    'admin_console.py', 'web/admin-common.js', 'web/admin.css',
    'update_routes.py', 'client-releases.json', 'web/update_notice.js', 'web/update_notice.css',
    'web/admin-overview.html', 'web/admin-overview.js', 'web/account-manager.html', 'web/account-manager.js',
    'database_management.py', 'database_routes.py', 'database_backup.py', 'maintenance_tasks.py', 'tools/restore_database.py',
    'workflow_store.py', 'workflow_routes.py', 'web/workflow_core.js', 'web/review.js',
    'annotations.py','backup_schedule.py','web/annotations.js','web/annotations.css','web/backup-schedule.js',
    'web/tasks.html', 'web/operations.html', 'web/workflow-page.js', 'web/workflow.css',
    'web/database-manager.html', 'web/database-manager.js', 'web/database-manager.css',
    'physiology_analysis.py', 'research/streaming_qrs.py', 'research/physiology.py',
    'web/physiology.js', 'web/physiology.css',
    'web/device-manager.html', 'web/device-manager.js', 'web/device-manager.css',
    'web/measurement.js', 'web/measurement.css',
    'web/manifest.webmanifest', 'web/sw.js', 'web/offline.html', 'web/pwa.js', 'web/pwa.css',
    'web/icons/icon-192.png', 'web/icons/icon-512.png', 'web/icons/icon-maskable.png', 'web/icons/apple-touch-icon.png',
    'web/index.html', 'web/app.js', 'web/style.css', 'web/workspace.js', 'web/workspace.css',
    'web/connection.js', 'web/desktop_core.js', 'web/desktop.js', 'web/desktop.css',
    'web/experience_core.js', 'web/experience.js', 'web/experience.css', 'web/mobile.js', 'web/mobile.css',
    'deploy/prepare_public.py', 'deploy/linux/手机公网访问说明.txt',
    'deploy/linux/install.sh', 'deploy/linux/start.sh',
    'deploy/linux/ecg-cloud.service', 'deploy/linux/部署说明.txt',
    'cloud_model/__init__.py', 'cloud_model/engine.py', 'cloud_model/SOURCE.json',
    'cloud_model/vendor/__init__.py', 'cloud_model/vendor/contracts.py',
    'cloud_model/vendor/preprocessing.py', 'cloud_model/vendor/notch_filter.py',
    'cloud_model/vendor/rpeak_detector.py', 'cloud_model/vendor/signal_quality.py',
    'cloud_model/vendor/cardioedge/__init__.py', 'cloud_model/vendor/cardioedge/stream.py',
    'cloud_model/vendor/cardioedge/numpy_candidate.py', 'cloud_model/vendor/cardioedge/portable_weights.npz',
    'cloud_model/vendor/cardioedge/LICENSE.txt', 'cloud_model/vendor/cardioedge/LICENSE-LiteRT.txt',
    'cloud_model/vendor/cardioedge/THIRD_PARTY_NOTICES.txt',
)


def build() -> tuple[Path, str]:
    contents = {}
    for relative in sorted(MEMBERS):
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f'Not a regular project source file: {relative}')
        contents[relative] = path.read_bytes()
        if relative.endswith(('.sh', '.service')) and b'\r' in contents[relative]:
            raise ValueError(f'Linux scripts must use LF line endings: {relative}')
    manifest = ''.join(f'{hashlib.sha256(body).hexdigest()}  {name}\n'
                       for name, body in contents.items()).encode('utf-8')
    contents['MANIFEST.sha256'] = manifest
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / 'ecg-cloud-linux.zip'
    temporary = archive.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, body in sorted(contents.items()):
            info = zipfile.ZipInfo('ecg-cloud/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if name.endswith('.sh') else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, body, compresslevel=9)
    with zipfile.ZipFile(temporary) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == {'ecg-cloud/' + name for name in contents}
        for name, body in contents.items():
            assert bundle.read('ecg-cloud/' + name) == body
    temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (OUTPUT/'MANIFEST.sha256').write_bytes(manifest)
    (OUTPUT/'ecg-cloud-linux.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    return archive, digest


if __name__ == '__main__':
    archive, digest = build()
    print(f'Archive: {archive}')
    print(f'Allowlisted files: {len(MEMBERS)}; includes optional pinned CardioEdge model, no records/credentials/logs')
    print(f'SHA256: {digest}')
