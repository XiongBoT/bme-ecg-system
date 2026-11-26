"""Prepare an owner-approved main source bundle; never connect to the server."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPOSITORY = 'XiongBoT/bme-ecg-system'
OWNER = 'XiongBoT'
OWNER_ID = '92081851'
WORKFLOW_PATH = '.github/workflows/quality.yml'


class ReleaseError(Exception):
    """An authorization or verification condition was not satisfied."""


def validate_context(env: dict[str, str]) -> str:
    expected = {
        'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_ACTOR': OWNER,
        'GITHUB_TRIGGERING_ACTOR': OWNER, 'GITHUB_ACTOR_ID': OWNER_ID,
    }
    for key, value in expected.items():
        if env.get(key) != value:
            raise ReleaseError(f'Owner-only main workflow required: {key}')
    sha = env.get('RELEASE_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha) or env.get('GITHUB_SHA') != sha:
        raise ReleaseError('RELEASE_SHA must be the exact full lowercase workflow commit SHA')
    for key in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        if not re.fullmatch(r'[1-9][0-9]*', env.get(key, '')):
            raise ReleaseError(f'Missing or invalid workflow context: {key}')
    if not env.get('GITHUB_TOKEN'):
        raise ReleaseError('A read-only GITHUB_TOKEN is required')
    return sha


class GitHubAPI:
    def __init__(self, token: str):
        self.token = token

    def get(self, path: str) -> dict:
        request = urllib.request.Request(
            f'https://api.github.com/repos/{REPOSITORY}{path}',
            headers={
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'bme-ecg-cloud-release',
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ReleaseError('GitHub verification response exceeds the size limit')
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise ReleaseError(f'GitHub verification failed (HTTP {exc.code})') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ReleaseError('GitHub verification unavailable or response invalid') from None
        if not isinstance(result, dict):
            raise ReleaseError('GitHub verification response must be an object')
        return result


def positive_integer(value) -> bool:
    return type(value) is int and value > 0


def verify_quality(get, sha: str) -> dict:
    """Require the latest main push of this exact workflow and commit to pass."""
    try:
        if get('/branches/main')['commit']['sha'] != sha:
            raise ReleaseError('main has changed; select its current checked commit')
        workflow = get('/actions/workflows/quality.yml')
        workflow_id = workflow['id']
        if (not positive_integer(workflow_id) or workflow['path'] != WORKFLOW_PATH
                or workflow['state'] != 'active'):
            raise ReleaseError('The required quality workflow is missing or inactive')
        response = get(f'/actions/workflows/{workflow_id}/runs'
                       f'?head_sha={sha}&branch=main&event=push&per_page=100')
        rows = response['workflow_runs']
        total = response['total_count']
        if (not isinstance(rows, list) or not rows or type(total) is not int
                or total != len(rows) or total > 100):
            raise ReleaseError('No complete quality-run evidence for this main commit')
        for row in rows:
            if (not isinstance(row, dict) or not positive_integer(row['id'])
                    or not positive_integer(row['run_number'])
                    or not positive_integer(row['run_attempt'])
                    or row['workflow_id'] != workflow_id or row['path'] != WORKFLOW_PATH
                    or row['head_sha'] != sha or row['head_branch'] != 'main'
                    or row['event'] != 'push' or row['repository']['full_name'] != REPOSITORY
                    or row['head_repository']['full_name'] != REPOSITORY
                    or row['html_url'] != f'https://github.com/{REPOSITORY}/actions/runs/{row["id"]}'
                    or 'status' not in row or 'conclusion' not in row):
                raise ReleaseError('Quality-run identity does not match the approved main commit')
        latest = max(rows, key=lambda row: (row['run_number'], row['run_attempt'], row['id']))
        if latest['status'] != 'completed' or latest['conclusion'] != 'success':
            raise ReleaseError('The latest quality run must complete successfully before preparation')
        return latest
    except (KeyError, TypeError, IndexError, ValueError):
        raise ReleaseError('Incomplete or invalid GitHub quality evidence') from None


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ['git', '-C', str(root), *args], check=True, capture_output=True,
            encoding='utf-8', timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ReleaseError('Cannot verify the source checkout') from None


def verify_checkout(root: Path, sha: str) -> None:
    if (Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root.resolve()
            or git(root, 'rev-parse', 'HEAD') != sha):
        raise ReleaseError('Checkout does not match the approved source commit')
    if git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise ReleaseError('Tracked checkout files must be unchanged')
    git(root, 'ls-files', '--error-unmatch', '--', '心电云端平台/deploy/package_cloud.py')


def prepare(root: Path, env: dict[str, str], get=None) -> dict:
    sha = validate_context(env)
    root = root.resolve()
    verify_checkout(root, sha)
    quality = verify_quality(get or GitHubAPI(env['GITHUB_TOKEN']).get, sha)
    source = root / '心电云端平台/deploy/package_cloud.py'
    spec = importlib.util.spec_from_file_location('ecg_cloud_release_packager', source)
    if spec is None or spec.loader is None:
        raise ReleaseError('Cannot load the checked source packager')
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    # An ignored local file must never stand in for source missing from the commit.
    git(root, 'ls-files', '--error-unmatch', '--',
        *('心电云端平台/' + name for name in packager.MEMBERS))
    output = root / '心电云端平台/deploy/dist'
    if output.is_symlink() or not output.resolve().is_relative_to(root):
        raise ReleaseError('Release output must stay in the project output directory')
    archive, digest = packager.build()
    manifest_digest = hashlib.sha256((output / 'MANIFEST.sha256').read_bytes()).hexdigest()
    provenance = {
        'status': 'prepared-not-deployed', 'repository': REPOSITORY,
        'ref': 'refs/heads/main', 'source_sha': sha, 'actor': OWNER,
        'actor_id': OWNER_ID, 'triggering_actor': env['GITHUB_TRIGGERING_ACTOR'],
        'workflow_run_url': f'https://github.com/{REPOSITORY}/actions/runs/{env["GITHUB_RUN_ID"]}',
        'workflow_run_attempt': int(env['GITHUB_RUN_ATTEMPT']),
        'quality_run_id': quality['id'], 'quality_run_url': quality['html_url'],
        'quality_run_attempt': quality['run_attempt'],
        'archive': archive.name, 'archive_sha256': digest,
        'manifest_sha256': manifest_digest,
    }
    (output / 'release-source.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    summary = (
        '## Cloud source bundle prepared\n\n'
        '**Status: prepared-not-deployed. No server was connected or changed.**\n\n'
        f'- Source: `{sha}`\n'
        f'- Quality evidence: {quality["html_url"]}\n'
        f'- Archive SHA-256: `{digest}`\n'
        f'- Manifest SHA-256: `{manifest_digest}`\n\n'
        'XiongBoT must verify the package, backup and maintenance window before deployment.\n'
    )
    if env.get('GITHUB_STEP_SUMMARY'):
        with Path(env['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(summary)
    print(f'Prepared source {sha}; status=prepared-not-deployed; archive SHA-256={digest}')
    return provenance


def main() -> int:
    try:
        prepare(Path(__file__).resolve().parents[1], dict(os.environ))
    except (ReleaseError, OSError, ValueError) as exc:
        print(f'Cloud bundle preparation stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
