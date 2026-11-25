"""Public install assets must not weaken account isolation or cache private data."""
import json
import ast
import re
import struct
import tempfile
from pathlib import Path
import unittest
from fastapi.testclient import TestClient
from server import create_app
from deploy.package_cloud import MEMBERS

ROOT=Path(__file__).resolve().parents[1]


class PwaTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'work/mobile-app/tmp';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.app=create_app(self.temp.name,auth_enabled=True,cookie_secure=False)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)

    def test_manifest_and_png_icons_are_public_complete_and_packaged(self):
        r=self.client.get('/manifest.webmanifest')
        self.assertEqual(r.status_code,200)
        self.assertIn('application/manifest+json',r.headers['content-type'])
        m=r.json()
        self.assertEqual((m['id'],m['scope'],m['start_url']),('/','/','/'))
        self.assertEqual(m['display'],'standalone')
        self.assertEqual(m['name'],'心电健康助手')
        sizes=set()
        for icon in m['icons']:
            r=self.client.get(icon['src']);self.assertEqual(r.status_code,200)
            self.assertTrue(r.content.startswith(b'\x89PNG\r\n\x1a\n'))
            w,h=struct.unpack('>II',r.content[16:24]);sizes.add(w)
            self.assertEqual(icon['sizes'],f'{w}x{h}')
            self.assertIn('web/'+icon['src'].removeprefix('/assets/'),MEMBERS)
        self.assertTrue({192,512}<=sizes)
        for name in ['web/sw.js','web/manifest.webmanifest','web/offline.html','web/pwa.js','web/pwa.css']:
            self.assertIn(name,MEMBERS)

    def test_worker_has_root_scope_javascript_mime_and_cannot_be_http_cached(self):
        r=self.client.get('/sw.js')
        self.assertEqual(r.status_code,200)
        self.assertIn('javascript',r.headers['content-type'])
        self.assertEqual(r.headers['service-worker-allowed'],'/')
        self.assertIn('no-store',r.headers['cache-control'])
        self.assertEqual(self.client.get('/api/sessions').status_code,401)

    def test_login_and_install_help_available_without_exposing_user_data(self):
        r=self.client.get('/')
        self.assertIn('no-store',r.headers['cache-control'])
        for expected in ['rel="manifest"','apple-touch-icon','id="pwa-install"','id="pwa-help"','/assets/pwa.js']:
            self.assertIn(expected,r.text)
        offline=self.client.get('/assets/offline.html')
        self.assertEqual(offline.status_code,200)
        self.assertIn('暂时无法连接',offline.text)
        self.assertNotIn('password',offline.text)

    def test_deployment_contains_entrypoint_local_imports_and_linked_assets(self):
        tree=ast.parse((ROOT/'server.py').read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            modules=[node.module] if isinstance(node,ast.ImportFrom) and node.module else [a.name for a in node.names] if isinstance(node,ast.Import) else []
            for module in modules:
                name=module.replace('.','/')+'.py'
                if (ROOT/name).is_file():self.assertIn(name,MEMBERS,'服务器包缺少本地依赖')
        for page in ['web/index.html','web/device-manager.html']:
            if not (ROOT/page).exists():continue
            for name in re.findall(r'(?:src|href)="/assets/([^"?#]+)"',(ROOT/page).read_text(encoding='utf-8')):
                self.assertIn('web/'+name,MEMBERS,'网页包缺少静态资源')


if __name__=='__main__':unittest.main()
