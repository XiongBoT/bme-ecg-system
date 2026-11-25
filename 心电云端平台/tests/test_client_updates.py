"""Public update metadata must not weaken account isolation."""
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from server import create_app

ROOT = Path(__file__).resolve().parents[1]

class ClientUpdateRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def client(self, **kwargs):
        app = create_app(Path(self.temp.name), cookie_secure=False, **kwargs)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_anonymous_read_has_only_public_metadata_and_no_auth_side_effect(self):
        client = self.client(auth_enabled=True)
        response = client.get('/api/updates', headers={'Cookie': 'invalid-session'})
        self.assertEqual(response.status_code, 200)
        info = response.json()
        self.assertEqual(set(info), {'schema', 'web', 'windows', 'android'})
        self.assertEqual(info['schema'], 1)
        self.assertRegex(info['web']['build_id'], r'^[a-f0-9]{64}$')
        self.assertEqual(info['windows']['version'], '1.1.0')
        self.assertEqual(info['android']['version_code'], 1)
        self.assertLess(len(response.content), 16384)
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertNotIn('set-cookie', response.headers)
        self.assertNotIn('x-ecg-user', response.headers)
        self.assertEqual(client.get('/api/sessions').status_code, 401)
        self.assertEqual(client.get('/api/admin/users').status_code, 401)
        self.assertEqual(client.post('/api/updates').status_code, 401)

    def test_token_mode_exempts_only_exact_public_get(self):
        client = self.client(auth_enabled=False, token='test-token-only')
        self.assertEqual(client.get('/api/updates').status_code, 200)
        self.assertEqual(client.get('/api/updates/private').status_code, 401)
        self.assertEqual(client.get('/api/sessions').status_code, 401)
        self.assertEqual(client.get('/api/updates', headers={'Origin':'https://other.example'}).status_code, 403)

    def test_browser_pages_embed_initial_build_and_checker_but_raw_apk_assets_do_not(self):
        client = self.client(auth_enabled=True)
        info = client.get('/api/updates')
        self.assertEqual(info.status_code, 200)
        build = info.json()['web']['build_id']
        for route in ('/', '/devices', '/admin', '/admin/accounts', '/database', '/tasks', '/operations'):
            page = client.get(route)
            self.assertEqual(page.status_code, 200)
            self.assertIn(f'<meta name="ecg-web-build" content="{build}">', page.text)
            self.assertEqual(page.text.count('src="/assets/update_notice.js"'), 1)
            self.assertIn('no-store', page.headers['cache-control'])
        self.assertNotIn('update_notice.js', (ROOT/'web/index.html').read_text(encoding='utf-8'))

class ClientUpdateMetadataTests(unittest.TestCase):
    def policy(self):
        import update_routes
        return update_routes

    def test_release_validation_ignores_extra_fields_and_rejects_untrusted_urls(self):
        policy = self.policy()
        valid = {'version':'1.10.0','url':'https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.10.0','notes':'新版说明','secret':'must not leak'}
        self.assertEqual(policy.valid_release('windows', valid), {k:valid[k] for k in ('version','url','notes')})
        for url in ('http://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.10.0',
                    valid['url']+'?download=evil', valid['url']+'#other',
                    valid['url'].replace('github.com', 'github.com.evil.example'),
                    valid['url'].replace('github.com', 'evil@github.com'),
                    valid['url'].replace('github.com', 'github.com:444'),
                    valid['url'].replace('1.10.0','9.9.9')):
            with self.subTest(url=url):
                self.assertIsNone(policy.valid_release('windows', {**valid,'url':url}))
        for version in ('1.0', 'v1.0.0', '1.0.0-preview.1', '01.0.0', '999999999.0.0', 123):
            self.assertIsNone(policy.valid_release('windows', {**valid,'version':version}))
        android = {'version':'1.0.0','version_code':1,'url':'https://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.0.0-preview.1','notes':'试用版'}
        self.assertIsNotNone(policy.valid_release('android',android))
        for code in (True, 0, -1, '1', 1.5, 2147483648):
            self.assertIsNone(policy.valid_release('android',{**android,'version_code':code}))

    def test_missing_invalid_or_oversized_manifest_is_unavailable_not_latest(self):
        policy = self.policy()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'releases.json'
            for content in (None, '{broken', '[]', '{"schema":2}', 'x'*16385):
                if content is not None: path.write_text(content,encoding='utf-8')
                self.assertEqual(policy.load_releases(path), {'windows':None,'android':None})
            path.write_text(json.dumps({'schema':1,'windows':{'version':'1.1.0','url':'https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v1.1.0','notes':'有效'},'android':{'broken':True}}),encoding='utf-8')
            result=policy.load_releases(path)
            self.assertEqual(result['windows']['version'],'1.1.0')
            self.assertIsNone(result['android'])

    def test_web_digest_changes_with_contents_or_paths_not_mtime_or_records(self):
        policy=self.policy()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);web=root/'web';web.mkdir()
            (web/'index.html').write_text('<head></head>',encoding='utf-8')
            (web/'app.js').write_text('one',encoding='utf-8')
            first=policy.web_build_id(web)
            self.assertRegex(first,r'^[a-f0-9]{64}$')
            (web/'app.js').touch()
            (root/'records.csv').write_text('private fixture',encoding='utf-8')
            self.assertEqual(first,policy.web_build_id(web))
            (web/'app.js').write_text('two',encoding='utf-8')
            second=policy.web_build_id(web)
            self.assertNotEqual(first,second)
            (web/'app.js').rename(web/'other.js')
            self.assertNotEqual(second,policy.web_build_id(web))

if __name__=='__main__': unittest.main()
