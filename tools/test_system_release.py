"""Exercise unified release boundaries using an isolated real Git checkout."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import stat
import unittest
import zipfile

import package_system_release as system
import prepare_cloud_release as release
import test_cloud_release as cloud_tests
from test_cloud_release import api_fixture, context


class SystemPackageTests(unittest.TestCase):
    git = cloud_tests.PackageTests.git

    def setUp(self):
        cloud_tests.PackageTests.setUp(self)
        for name in (*system.HEARTLIFE_FILES, *system.REQUIRED, 'docs/统一部署.md'):
            self.write(name, b'fixture\n')
        self.write('heartlife/backend/app/routers/example.py', b'pass\n')
        self.write('heartlife/backend/tests/example.py', b'not runtime\n')
        self.commit()
        self.dist = self.root / 'heartlife/frontend/dist'
        self.write('heartlife/frontend/dist/assets/app.js', b'export default {};\n')
        self.write('heartlife/frontend/dist/assets/app.css', b'body { color: black; }\n')
        self.write('heartlife/frontend/dist/index.html',
                   b'<script type="module" src="/heartlife/assets/app.js"></script>'
                   b'<link rel="stylesheet" href="/heartlife/assets/app.css">')
        self.marker()
        self.output = self.root / 'dist'

    def write(self, relative, body):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'user.name=Course test', '-c', 'user.email=course-test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Runtime fixture')
        self.sha = self.git('rev-parse', 'HEAD').strip()

    def marker(self, **changes):
        value = {'schema': 1, 'source_sha': self.sha, 'base_path': '/heartlife/'}
        value.update(changes)
        self.write('heartlife/frontend/dist/release-source.json', json.dumps(value).encode())

    def build(self):
        return system.build(self.root, self.output, self.sha)

    def test_complete_reproducible_bundle_with_hashes_and_no_local_data(self):
        self.write('heartlife/.env', b'private fixture, not a real credential\n')
        self.write('heartlife/data/heartlife.db', b'private fixture\n')
        self.write('heartlife/backend/app/untracked.py', b'not committed\n')
        self.write('心电云端平台/data/records.db', b'private fixture\n')
        result = self.build()
        archive = (self.output / result['archive']).read_bytes()
        self.assertEqual(result, self.build())
        self.assertEqual(archive, (self.output / result['archive']).read_bytes())
        self.assertEqual(result['archive_sha256'], hashlib.sha256(archive).hexdigest())
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = set(bundle.namelist())
            for missing in ('heartlife/.env', 'heartlife/data/heartlife.db',
                            'heartlife/backend/app/untracked.py', 'heartlife/backend/tests/example.py',
                            'ecg-cloud/data/records.db'):
                self.assertNotIn('ecg-system/' + missing, names)
            for required in (*system.REQUIRED, 'heartlife/frontend/dist/index.html',
                             'heartlife/frontend/dist/assets/app.js', 'ecg-cloud/server.py',
                             'DEPLOYMENT.md'):
                self.assertIn('ecg-system/' + required, names)
            manifest = bundle.read('ecg-system/MANIFEST.sha256')
            rows = [line.split('  ', 1) for line in manifest.decode().splitlines()]
            self.assertEqual({'ecg-system/' + name for _, name in rows},
                             names - {'ecg-system/MANIFEST.sha256'})
            for digest, name in rows:
                self.assertEqual(digest, hashlib.sha256(bundle.read('ecg-system/' + name)).hexdigest())
            self.assertEqual(result['manifest_sha256'], hashlib.sha256(manifest).hexdigest())
            metadata = json.loads(bundle.read('ecg-system/RELEASE.json'))
            self.assertEqual(set(metadata['components'].values()), {self.sha})
            self.assertEqual(metadata['status'], 'prepared-not-deployed')
            mode = bundle.getinfo('ecg-system/ecg-cloud/deploy/linux/start.sh').external_attr >> 16
            self.assertTrue(stat.S_ISREG(mode))
            self.assertEqual(mode & 0o777, 0o755)

    def test_wrong_source_dirty_checkout_and_missing_migration_fail_before_output(self):
        with self.assertRaises(system.PackageError):
            system.build(self.root, self.output, '0' * 40)
        self.write('heartlife/backend/app/main.py', b'changed\n')
        with self.assertRaises(system.PackageError):
            self.build()
        self.git('checkout', '--', 'heartlife/backend/app/main.py')
        (self.root / system.REQUIRED[-1]).unlink()
        self.commit()
        self.marker()
        with self.assertRaises(system.PackageError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_frontend_marker_requires_current_commit_and_subpath(self):
        for changes in ({'source_sha': 'b' * 40}, {'base_path': '/'}, {'schema': 2}):
            with self.subTest(changes=changes):
                self.marker(**changes)
                with self.assertRaises(system.PackageError):
                    self.build()
        (self.dist / 'release-source.json').unlink()
        with self.assertRaises(system.PackageError):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_entry_resource_external_or_wrong_base_is_rejected(self):
        for url in ('/assets/app.js', 'https://example.invalid/heartlife/assets/app.js',
                    '/heartlife/assets/missing.js', '/heartlife/%2e%2e/assets/app.js'):
            with self.subTest(url=url):
                self.write('heartlife/frontend/dist/index.html',
                           f'<script src="{url}"></script>'.encode())
                with self.assertRaises(system.PackageError):
                    self.build()
        (self.dist / 'index.html').unlink()
        with self.assertRaises(system.PackageError):
            self.build()

    def test_unexpected_static_files_and_crlf_scripts_are_rejected(self):
        for name in ('.env', 'backup.db', 'assets/app.js.map'):
            path = self.dist / name
            path.write_bytes(b'not a production static file')
            with self.subTest(name=name), self.assertRaises(system.PackageError):
                self.build()
            path.unlink()
        self.write('心电云端平台/deploy/linux/start.sh', b'echo fixture\r\n')
        self.commit()
        self.marker()
        with self.assertRaises(system.PackageError):
            self.build()

    def test_frontend_link_is_rejected_even_if_its_target_is_inside_build(self):
        link = self.dist / 'assets/linked.js'
        try:
            link.symlink_to(self.dist / 'assets/app.js')
        except OSError:
            self.skipTest('This host does not permit symlink creation; Linux CI covers it')
        with self.assertRaises(system.PackageError):
            self.build()

    def test_owner_release_preserves_legacy_bundle_and_adds_unified_evidence(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = release.prepare(self.root, context(self.sha), api_fixture(self.sha),
                                     include_heartlife=True)
        output = self.cloud / 'deploy/dist'
        legacy = json.loads((output / 'release-source.json').read_text(encoding='utf-8'))
        unified = json.loads((output / 'system-release-source.json').read_text(encoding='utf-8'))
        self.assertEqual(result, unified)
        self.assertEqual(legacy['archive'], 'ecg-cloud-linux.zip')
        self.assertEqual(unified['archive'], 'ecg-system-linux.zip')
        for item in (legacy, unified):
            self.assertEqual(item['source_sha'], self.sha)
            self.assertEqual(item['quality_run_id'], 900)
            self.assertEqual(item['status'], 'prepared-not-deployed')
            self.assertEqual(item['archive_sha256'], hashlib.sha256((output / item['archive']).read_bytes()).hexdigest())
            self.assertNotIn('test-only-token', json.dumps(item))
        self.assertEqual(set(unified['components'].values()), {self.sha})

    def test_unified_preparation_cannot_bypass_quality_or_accept_stale_frontend(self):
        self.marker(source_sha='b' * 40)
        with self.assertRaises(release.ReleaseError):
            release.prepare(self.root, context(self.sha), api_fixture(self.sha, runs=[]),
                            include_heartlife=True)
        self.assertFalse((self.cloud / 'deploy/dist').exists())
        with self.assertRaises(system.PackageError):
            release.prepare(self.root, context(self.sha), api_fixture(self.sha), include_heartlife=True)
        self.assertFalse((self.cloud / 'deploy/dist/system-release-source.json').exists())


if __name__ == '__main__':
    unittest.main()
