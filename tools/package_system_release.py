"""Package ECG + HeartLife from one clean commit; never connect to a server."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = '/heartlife/'
HEARTLIFE_FILES = (
    'heartlife/backend/requirements.txt', 'heartlife/backend/alembic.ini',
    'heartlife/scripts/migrate.py', 'heartlife/README.md', 'heartlife/.env.example',
    'heartlife/deploy/tencent-cloud/heartlife.service',
    'heartlife/deploy/tencent-cloud/nginx-heartlife-subpath.conf',
    'heartlife/docs/心电集成.md',
)
REQUIRED = ('heartlife/backend/app/main.py', 'heartlife/backend/app/core/config.py',
            'heartlife/backend/migrations/env.py',
            'heartlife/backend/migrations/versions/0001_initial_schema.py')
STATIC_SUFFIXES = {'.html', '.js', '.css', '.json', '.svg', '.png', '.jpg', '.jpeg',
                   '.webp', '.ico', '.woff', '.woff2', '.ttf'}


class PackageError(ValueError):
    pass


def git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise PackageError('Cannot verify the source checkout') from None


def checked_file(root: Path, relative: str) -> bytes:
    path = root / relative
    if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root))):
        raise PackageError(f'Not a regular project file: {relative}')
    if path.stat().st_size > 16 * 1024 * 1024:
        raise PackageError(f'File exceeds package size limit: {relative}')
    body = path.read_bytes()
    if relative.endswith(('.sh', '.service')) and b'\r' in body:
        raise PackageError(f'Linux file must use LF: {relative}')
    return body


class EntryAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script' and values.get('src'):
            self.assets.append(values['src'])
        if tag == 'link' and values.get('rel') in ('stylesheet', 'modulepreload') and values.get('href'):
            self.assets.append(values['href'])


def frontend_files(root: Path, sha: str) -> dict[str, bytes]:
    prefix = 'heartlife/frontend/dist/'
    dist = root / prefix
    if dist.is_symlink() or not dist.is_dir():
        raise PackageError('Build HeartLife frontend before packaging')
    files = {}
    for path in sorted(dist.rglob('*')):
        if path.is_symlink():
            raise PackageError('Frontend build cannot contain links')
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() not in STATIC_SUFFIXES or any(part.startswith('.') for part in path.relative_to(dist).parts):
            raise PackageError(f'Unexpected frontend build file: {relative}')
        files[relative] = checked_file(root, relative)
        if len(files) > 2000:
            raise PackageError('Frontend build has too many files')
    try:
        marker = json.loads(files[prefix + 'release-source.json'])
        if marker != {'schema': 1, 'source_sha': sha, 'base_path': BASE_PATH}:
            raise ValueError('wrong source')
        parser = EntryAssets()
        parser.feed(files[prefix + 'index.html'].decode('utf-8'))
        if not parser.assets:
            raise ValueError('missing assets')
        for value in parser.assets:
            parsed = urlsplit(value)
            path = unquote(parsed.path)
            if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
                    not path.startswith(BASE_PATH) or '\\' in path or '..' in PurePosixPath(path).parts or
                    prefix + path[len(BASE_PATH):] not in files):
                raise ValueError('missing or wrong-base asset')
    except (KeyError, ValueError, UnicodeError, TypeError):
        raise PackageError('Frontend source marker, entry or /heartlife/ assets do not match') from None
    return files


def build(root: Path, output: Path, sha: str) -> dict:
    root, output = root.resolve(), output.absolute()
    if (not re.fullmatch(r'[0-9a-f]{40}', sha) or
            git(root, 'rev-parse', 'HEAD').decode().strip() != sha or
            Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root or
            git(root, 'status', '--porcelain', '--untracked-files=no').strip()):
        raise PackageError('Package requires the exact clean source commit')
    tracked = {}
    for entry in git(root, 'ls-files', '-s', '-z').decode('utf-8').split('\0'):
        if entry:
            info, name = entry.split('\t', 1)
            mode, _oid, stage = info.split()
            if stage != '0':
                raise PackageError('Unresolved source conflict')
            tracked[name] = mode

    def source(name):
        if tracked.get(name) not in ('100644', '100755'):
            raise PackageError(f'Required regular tracked source is missing: {name}')
        return checked_file(root, name)

    cloud_script = '心电云端平台/deploy/package_cloud.py'
    source(cloud_script)
    spec = importlib.util.spec_from_file_location('unified_cloud_packager', root / cloud_script)
    if spec is None or spec.loader is None:
        raise PackageError('Cannot load the checked cloud packager')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contents = {'ecg-cloud/' + name: source('心电云端平台/' + name) for name in module.MEMBERS}
    cloud_manifest = ''.join(f'{hashlib.sha256(body).hexdigest()}  {name.removeprefix("ecg-cloud/")}\n'
                             for name, body in sorted(contents.items())).encode()
    contents['ecg-cloud/MANIFEST.sha256'] = cloud_manifest
    selected = set(HEARTLIFE_FILES)
    selected.update(name for name in tracked if name.startswith(
        ('heartlife/backend/app/', 'heartlife/backend/migrations/')))
    if not set(REQUIRED).issubset(selected):
        raise PackageError('HeartLife backend or migration entry is missing')
    for name in sorted(selected):
        if name not in HEARTLIFE_FILES and Path(name).suffix not in ('.py', '.mako', '.json'):
            raise PackageError(f'Unexpected HeartLife runtime source: {name}')
        contents[name] = source(name)
    contents.update(frontend_files(root, sha))
    contents['DEPLOYMENT.md'] = source('docs/统一部署.md')
    release = {'schema': 1, 'status': 'prepared-not-deployed', 'source_sha': sha,
               'components': {'ecg-cloud': sha, 'heartlife-backend': sha, 'heartlife-frontend': sha},
               'heartlife_base_path': BASE_PATH, 'contains_runtime_data': False}
    contents['RELEASE.json'] = (json.dumps(release, ensure_ascii=False, indent=2) + '\n').encode()
    manifest = ''.join(f'{hashlib.sha256(body).hexdigest()}  {name}\n'
                       for name, body in sorted(contents.items())).encode()
    contents['MANIFEST.sha256'] = manifest
    if sum(map(len, contents.values())) > 128 * 1024 * 1024:
        raise PackageError('Unified package exceeds size limit')
    if output.is_symlink():
        raise PackageError('Package output cannot be a link')
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'ecg-system-linux.zip'
    with tempfile.TemporaryDirectory(prefix='system-package-', dir=output) as temp:
        temporary = Path(temp) / archive.name
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, body in sorted(contents.items()):
                entry = zipfile.ZipInfo('ecg-system/' + name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | (0o755 if name.endswith('.sh') else 0o644)) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(entry, body, compresslevel=9)
        with zipfile.ZipFile(temporary) as bundle:
            if bundle.testzip() is not None or set(bundle.namelist()) != {'ecg-system/' + name for name in contents}:
                raise PackageError('Package verification failed')
            for name, body in contents.items():
                if bundle.read('ecg-system/' + name) != body:
                    raise PackageError('Package member verification failed')
        temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + '.sha256')).write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    return {**release, 'archive': archive.name, 'archive_sha256': digest,
            'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'files': len(contents)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Check a real build in a temporary output directory')
    args = parser.parse_args()
    try:
        sha = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
        if args.check:
            with tempfile.TemporaryDirectory(prefix='ecg-system-check-') as temp:
                result = build(ROOT, Path(temp), sha)
        elif args.output:
            result = build(ROOT, args.output, sha)
        else:
            parser.error('choose --check or --output')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (PackageError, OSError) as exc:
        print(f'Unified package stopped: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
