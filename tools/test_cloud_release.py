"""Release authorization, CI provenance and source-only package regression tests."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
import zipfile

import prepare_cloud_release as release


REPO = 'XiongBoT/bme-ecg-system'
SHA = 'a' * 40
WORKFLOW_ID = 123
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def context(sha=SHA):
    return {
        'RELEASE_SHA': sha, 'GITHUB_SHA': sha, 'GITHUB_REPOSITORY': REPO,
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
        'GITHUB_ACTOR': 'XiongBoT', 'GITHUB_TRIGGERING_ACTOR': 'XiongBoT',
        'GITHUB_ACTOR_ID': '92081851', 'GITHUB_RUN_ID': '456',
        'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_TOKEN': 'test-only-token',
    }


def quality_run(run_id=900, number=20, conclusion='success', sha=SHA, **changes):
    row = {
        'id': run_id, 'run_number': number, 'run_attempt': 1,
        'workflow_id': WORKFLOW_ID, 'path': '.github/workflows/quality.yml',
        'head_sha': sha, 'head_branch': 'main', 'event': 'push',
        'status': 'completed', 'conclusion': conclusion,
        'html_url': f'https://github.com/{REPO}/actions/runs/{run_id}',
        'repository': {'full_name': REPO}, 'head_repository': {'full_name': REPO},
    }
    row.update(changes)
    return row


def api_fixture(sha=SHA, runs=None, **overrides):
    responses = {
        '/branches/main': {'commit': {'sha': sha}},
        '/actions/workflows/quality.yml': {
            'id': WORKFLOW_ID, 'path': '.github/workflows/quality.yml', 'state': 'active'},
        f'/actions/workflows/{WORKFLOW_ID}/runs?head_sha={sha}&branch=main&event=push&per_page=100': {
            'total_count': len(runs) if runs is not None else 1,
            'workflow_runs': runs if runs is not None else [quality_run(sha=sha)]},
    }
    responses.update(overrides)

    def get(path):
        if path not in responses:
            raise AssertionError(f'Unexpected API request: {path}')
        value = responses[path]
        if isinstance(value, Exception):
            raise value
        return value
    return get


class ContextTests(unittest.TestCase):
    def test_rejects_unauthorized_actor_rerunner_or_non_main_execution(self):
        for key, wrong in (
            ('GITHUB_ACTOR', 'another-member'),
            ('GITHUB_TRIGGERING_ACTOR', 'another-member'),
            ('GITHUB_ACTOR_ID', '1'), ('GITHUB_REPOSITORY', 'another/repo'),
            ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/member-task'),
        ):
            with self.subTest(key=key):
                env = context()
                env[key] = wrong
                with self.assertRaises(release.ReleaseError):
                    release.validate_context(env)

    def test_requires_complete_context_and_exact_lowercase_commit(self):
        for key in context():
            with self.subTest(missing=key):
                env = context()
                del env[key]
                with self.assertRaises(release.ReleaseError):
                    release.validate_context(env)
        for sha in ('main', 'a' * 39, 'A' * 40, ' ' + SHA, SHA + '\n', 'g' * 40):
            with self.subTest(sha=sha):
                with self.assertRaises(release.ReleaseError):
                    release.validate_context(context(sha))
        env = context()
        env['GITHUB_SHA'] = 'b' * 40
        with self.assertRaises(release.ReleaseError):
            release.validate_context(env)
        for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            for value in ('0', '-1', '../file', ''):
                env = context()
                env[key] = value
                with self.assertRaises(release.ReleaseError):
                    release.validate_context(env)
        self.assertEqual(release.validate_context(context()), SHA)


class QualityTests(unittest.TestCase):
    def test_selects_latest_successful_main_push_run_for_exact_workflow(self):
        rows = [quality_run(899, 19, 'failure'), quality_run(900, 20)]
        result = release.verify_quality(api_fixture(runs=rows), SHA)
        self.assertEqual(result['id'], 900)

    def test_newer_failure_or_in_progress_run_cannot_fall_back_to_old_success(self):
        for changes in ({'conclusion': 'failure'}, {'status': 'in_progress', 'conclusion': None},
                        {'conclusion': 'cancelled'}, {'conclusion': 'skipped'}):
            with self.subTest(changes=changes):
                rows = [quality_run(900, 20, **changes), quality_run(899, 19)]
                with self.assertRaises(release.ReleaseError):
                    release.verify_quality(api_fixture(runs=rows), SHA)

    def test_wrong_run_identity_or_missing_schema_is_not_evidence(self):
        for changes in (
            {'workflow_id': 999}, {'path': '.github/workflows/other.yml'},
            {'head_sha': 'b' * 40}, {'head_branch': 'member-task'},
            {'event': 'pull_request'}, {'repository': {'full_name': 'other/repo'}},
            {'head_repository': {'full_name': 'other/repo'}},
            {'html_url': 'https://example.com/success'}, {'run_number': 0},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(release.ReleaseError):
                    release.verify_quality(api_fixture(runs=[quality_run(**changes)]), SHA)
        for key in ('id', 'run_number', 'status', 'conclusion', 'workflow_id', 'path'):
            row = quality_run()
            del row[key]
            with self.subTest(missing=key):
                with self.assertRaises(release.ReleaseError):
                    release.verify_quality(api_fixture(runs=[row]), SHA)

    def test_changed_main_no_runs_truncated_response_or_bad_workflow_is_rejected(self):
        path = f'/actions/workflows/{WORKFLOW_ID}/runs?head_sha={SHA}&branch=main&event=push&per_page=100'
        variants = (
            {'/branches/main': {'commit': {'sha': 'b' * 40}}},
            {'/actions/workflows/quality.yml': {'id': WORKFLOW_ID, 'path': 'wrong', 'state': 'active'}},
            {'/actions/workflows/quality.yml': {'id': WORKFLOW_ID, 'path': '.github/workflows/quality.yml', 'state': 'disabled_manually'}},
            {path: {'total_count': 0, 'workflow_runs': []}},
            {path: {'total_count': 101, 'workflow_runs': [quality_run()]}},
            {path: {'total_count': 1}},
        )
        for overrides in variants:
            with self.subTest(overrides=overrides):
                with self.assertRaises(release.ReleaseError):
                    release.verify_quality(api_fixture(**overrides), SHA)

    def test_api_errors_do_not_echo_token_or_response_body(self):
        token = 'private-token-never-print'
        failure = urllib.error.HTTPError('https://api.github.com', 403, token, {}, None)
        with mock.patch('urllib.request.urlopen', side_effect=failure):
            with self.assertRaises(release.ReleaseError) as error:
                release.GitHubAPI(token).get('/branches/main')
        self.assertNotIn(token, str(error.exception))
        with mock.patch('urllib.request.urlopen', side_effect=TimeoutError(token)):
            with self.assertRaises(release.ReleaseError) as error:
                release.GitHubAPI(token).get('/branches/main')
        self.assertNotIn(token, str(error.exception))


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ecg-release-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cloud = self.root / '心电云端平台'
        packager_source = SOURCE_ROOT / '心电云端平台/deploy/package_cloud.py'
        spec = importlib.util.spec_from_file_location('fixture_packager', packager_source)
        packager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(packager)
        for name in packager.MEMBERS:
            target = self.cloud / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'course fixture\n')
        shutil.copyfile(packager_source, self.cloud / 'deploy/package_cloud.py')
        (self.root / '.gitignore').write_text('**/dist/\n**/__pycache__/\n', encoding='utf-8')
        self.git('init', '--quiet')
        self.git('add', '.')
        self.git('-c', 'user.name=Course test', '-c', 'user.email=course-test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Test fixture')
        self.sha = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True, encoding='utf-8').stdout

    def test_dirty_or_wrong_checkout_is_rejected_before_package_is_created(self):
        (self.cloud / 'server.py').write_text('changed\n', encoding='utf-8')
        with self.assertRaises(release.ReleaseError):
            release.prepare(self.root, context(self.sha), api_fixture(self.sha))
        self.assertFalse((self.cloud / 'deploy/dist').exists())
        self.git('checkout', '--', '心电云端平台/server.py')
        with self.assertRaises(release.ReleaseError):
            release.prepare(self.root, context('b' * 40), api_fixture('b' * 40))

    def test_existing_packager_produces_traceable_source_bundle_without_private_data(self):
        env = context(self.sha)
        summary = self.root / 'summary.txt'
        env['GITHUB_STEP_SUMMARY'] = str(summary)
        with contextlib.redirect_stdout(io.StringIO()):
            result = release.prepare(self.root, env, api_fixture(self.sha))
        output = self.cloud / 'deploy/dist'
        provenance = json.loads((output / 'release-source.json').read_text(encoding='utf-8'))
        self.assertEqual(provenance['status'], 'prepared-not-deployed')
        self.assertEqual(provenance['source_sha'], self.sha)
        self.assertEqual(provenance['repository'], REPO)
        self.assertEqual(provenance['ref'], 'refs/heads/main')
        self.assertEqual(provenance['actor'], 'XiongBoT')
        self.assertEqual(provenance['workflow_run_url'], f'https://github.com/{REPO}/actions/runs/456')
        self.assertEqual(provenance['quality_run_id'], 900)
        archive = output / 'ecg-cloud-linux.zip'
        self.assertEqual(provenance['archive_sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(provenance['manifest_sha256'], hashlib.sha256((output / 'MANIFEST.sha256').read_bytes()).hexdigest())
        self.assertEqual(result, provenance)
        self.assertIn('prepared-not-deployed', summary.read_text(encoding='utf-8'))
        self.assertNotIn(env['GITHUB_TOKEN'], json.dumps(provenance))
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.read('ecg-cloud/server.py'), b'course fixture\n')
            self.assertFalse(any('/data/' in name or '/.git/' in name or name.endswith('.sqlite')
                                 for name in bundle.namelist()))


if __name__ == '__main__':
    unittest.main()
