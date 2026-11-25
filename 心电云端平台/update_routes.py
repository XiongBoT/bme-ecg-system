"""Anonymous release metadata and the identity of deployed browser assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

from fastapi.responses import HTMLResponse

MAX_MANIFEST_BYTES = 16 * 1024
VERSION = re.compile(r'(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\Z')
RELEASE_BASE = 'https://github.com/XiongBoT/bme-ecg-system/releases/tag/'


def valid_release(platform: str, item) -> dict | None:
    if not isinstance(item, dict) or platform not in ('windows', 'android'):
        return None
    version = item.get('version')
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        return None
    if any(int(part) > 65535 for part in version.split('.')):
        return None
    prefix = 'desktop-v' if platform == 'windows' else 'android-v'
    expected = re.escape(RELEASE_BASE + prefix + version)
    suffix = r'(?:-preview\.[1-9][0-9]{0,5})?' if platform == 'android' else ''
    url = item.get('url')
    if not isinstance(url, str) or not re.fullmatch(expected + suffix, url):
        return None
    notes = item.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 1000:
        return None
    if any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in notes):
        return None
    result = {'version': version, 'url': url, 'notes': notes}
    if platform == 'android':
        code = item.get('version_code')
        if type(code) is not int or not 1 <= code <= 2147483647:
            return None
        result['version_code'] = code
    return result


def load_releases(path: Path) -> dict:
    unavailable = {'windows': None, 'android': None}
    try:
        if path.is_symlink():
            return unavailable
        with path.open('rb') as source:
            body = source.read(MAX_MANIFEST_BYTES + 1)
        if len(body) > MAX_MANIFEST_BYTES:
            return unavailable
        manifest = json.loads(body.decode('utf-8'))
        if not isinstance(manifest, dict) or type(manifest.get('schema')) is not int or manifest['schema'] != 1:
            return unavailable
        return {name: valid_release(name, manifest.get(name)) for name in unavailable}
    except (OSError, UnicodeError, ValueError, RecursionError):
        return unavailable


def web_build_id(web: Path) -> str:
    """Hash public web contents, never runtime accounts, medical records or mtimes."""
    digest = hashlib.sha256()
    for path in sorted(web.rglob('*')):
        if path.is_symlink():
            raise ValueError('Web assets must be regular project files')
        if not path.is_file():
            continue
        name = path.relative_to(web).as_posix().encode('utf-8')
        body = path.read_bytes()
        digest.update(len(name).to_bytes(8, 'big'))
        digest.update(name)
        digest.update(len(body).to_bytes(8, 'big'))
        digest.update(body)
    return digest.hexdigest()


class UpdateInfo:
    def __init__(self, root: Path):
        self.root = root
        self.build_id = web_build_id(root / 'web')

    def metadata(self) -> dict:
        return {'schema': 1, 'web': {'build_id': self.build_id},
                **load_releases(self.root / 'client-releases.json')}

    def page(self, filename: str) -> HTMLResponse:
        # Names are constants in server routes, never taken from a request.
        html = (self.root / 'web' / filename).read_text(encoding='utf-8')
        extra = (f'<meta name="ecg-web-build" content="{self.build_id}">\n'
                 '<link rel="stylesheet" href="/assets/update_notice.css">\n'
                 '<script src="/assets/update_notice.js" defer></script>')
        return HTMLResponse(html.replace('<head>', '<head>\n' + extra, 1))


def add_routes(app, root: Path) -> UpdateInfo:
    info = UpdateInfo(root)
    app.add_api_route('/api/updates', info.metadata, methods=['GET'])
    return info
