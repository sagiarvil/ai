"""Fail-closed, transactional GitHub installer for the OmniCore macOS host.

A checked-out repository is UNTRUSTED. All code execution must pass through
sandbox_executor.secure_sandbox_run; Python/Node packages never install globally.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from sandbox_executor import SANDBOX_DIR, WORKSPACE_ROOT, secure_sandbox_run

STAGING = SANDBOX_DIR / 'installations'
DEPLOYED = WORKSPACE_ROOT / 'installed_engines'
REGISTRY = WORKSPACE_ROOT / 'installed_engines_registry.json'
LOCK = threading.RLock()


def parse_github(url: str) -> tuple[str, str, str]:
    """Only github.com owner/repo URLs; disallow query, fragments, credentials."""
    u = urlparse(url.strip())
    if (u.scheme != 'https' or u.hostname != 'github.com' or u.username or
            u.password or u.query or u.fragment or u.params or u.port is not None):
        raise ValueError('Only plain https://github.com/OWNER/REPO URLs are allowed')
    parts = [p for p in u.path.rstrip('/').split('/') if p]
    if len(parts) != 2:
        raise ValueError('Expected https://github.com/OWNER/REPO')
    owner, repo = parts
    if repo.endswith('.git'):
        repo = repo[:-4]
    valid = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
    if not valid.fullmatch(owner) or not valid.fullmatch(repo) or repo in {'.', '..'}:
        raise ValueError('Invalid GitHub owner/repository')
    return owner, repo, f'https://github.com/{owner}/{repo}.git'


def classify(root: Path) -> str:
    """Do not infer installability from stars or README claims."""
    if (root / 'pyproject.toml').is_file() or (root / 'requirements.txt').is_file() or (root / 'setup.py').is_file():
        return 'python'
    if (root / 'package.json').is_file():
        return 'node'
    if (root / 'Cargo.toml').is_file():
        return 'rust'
    if (root / 'go.mod').is_file():
        return 'go'
    if (root / 'Dockerfile').is_file() or (root / 'compose.yaml').is_file():
        return 'container'
    return 'unsupported'


def run(command: str, directory: Path, timeout: int = 240, *, network: bool = False) -> dict[str, Any]:
    """Never fall back to host subprocess if the OS sandbox is unavailable."""
    result = secure_sandbox_run(command, cwd=directory, timeout=timeout, allow_network=network)
    # 'isolated' flag isn't proof of kernel isolation; macOS checks belong to sandbox tests.
    return result


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _record(registry_key: str, record: dict[str, Any]) -> None:
    with LOCK:
        old = json.loads(REGISTRY.read_text(encoding='utf-8')) if REGISTRY.exists() else {}
        old[registry_key] = record
        atomic_json(REGISTRY, old)


def _fail(stage: str, reason: str, evidence: list[dict[str, Any]], job_id: str) -> dict[str, Any]:
    return {'success': False, 'state': 'FAILED', 'stage': stage, 'error': reason,
            'job_id': job_id, 'evidence': evidence, 'verified': False}


def install_repo(url: str) -> dict[str, Any]:
    """Install *supported* repos; distinguish downloaded, built and verified.

    This function NEVER asserts a repo is functional merely because clone succeeded.
    Activation is intentionally restricted to packages with tests that pass.
    """
    job_id = uuid.uuid4().hex[:16]
    evidence: list[dict[str, Any]] = []
    try:
        owner, name, safe_url = parse_github(url)
    except ValueError as exc:
        return _fail('VALIDATING', str(exc), evidence, job_id)

    STAGING.mkdir(parents=True, exist_ok=True)
    DEPLOYED.mkdir(parents=True, exist_ok=True)
    task_dir = STAGING / job_id
    source = task_dir / 'source'
    task_dir.mkdir(mode=0o700)
    final = DEPLOYED / f'{owner}--{name}'
    previous = DEPLOYED / f'.backup-{owner}--{name}-{job_id}'
    deployed = False
    try:
        clone = run(f"git clone --depth 1 --no-recurse-submodules {safe_url!r} {str(source)!r}", task_dir, 180, network=True)
        evidence.append({'stage': 'CLONE', 'exit_code': clone.get('exit_code'), 'stderr': clone.get('stderr', '')[-600:]})
        if not clone.get('success') or not (source / '.git').is_dir():
            return _fail('CLONE', clone.get('stderr', 'Clone failed'), evidence, job_id)
        kind = classify(source)
        commit = run('git rev-parse HEAD', source, 15)
        if not commit.get('success') or not re.fullmatch(r'[0-9a-f]{40}', commit.get('stdout', '').strip()):
            return _fail('REVISION', 'Cannot verify git commit', evidence, job_id)
        sha = commit['stdout'].strip()
        evidence.append({'stage': 'REVISION', 'commit': sha, 'kind': kind})
        if kind not in {'python', 'node'}:
            return {'success': False, 'verified': False, 'state': 'UNSUPPORTED',
                    'error': f'{kind}: no verified installer adapter; nothing activated',
                    'repo': safe_url, 'commit': sha, 'job_id': job_id, 'evidence': evidence}

        if kind == 'python':
            # Virtualenv stays inside staging. No --break-system-packages, no global pip.
            create = run('python3 -m venv .venv', source, 90)
            if not create.get('success'):
                return _fail('VENV', create.get('stderr', ''), evidence, job_id)
            if (source / 'requirements.txt').is_file():
                # Dependencies execute in the restricted sandbox, with network enabled.
                cmd = '.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt'
            elif (source / 'pyproject.toml').is_file() or (source / 'setup.py').is_file():
                cmd = '.venv/bin/python -m pip install --disable-pip-version-check .'
            else:
                cmd = None
            if cmd:
                deps = run(cmd, source, 600, network=True)
                evidence.append({'stage': 'DEPENDENCIES', 'exit_code': deps.get('exit_code'), 'stderr': deps.get('stderr', '')[-900:]})
                if not deps.get('success'):
                    return _fail('DEPENDENCIES', deps.get('stderr', '')[-900:], evidence, job_id)
            # Explicit test discovery. No `--help`, `ls`, `py_compile` or exit(0) bypass.
            has_tests = (source / 'tests').is_dir() or any(source.glob('test_*.py'))
            if not has_tests:
                return {'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                        'repo': safe_url, 'commit': sha, 'error': 'No test suite discovered; not activated', 'evidence': evidence}
            test = run('.venv/bin/python -m unittest discover -s tests -p "test*.py"' if (source / 'tests').is_dir() else '.venv/bin/python -m unittest discover -p "test_*.py"', source, 180)
        else:
            if not (source / 'package-lock.json').exists():
                return {'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                        'repo': safe_url, 'commit': sha, 'error': 'package-lock.json required; not activated', 'evidence': evidence}
            deps = run('npm ci --ignore-scripts --no-audit --no-fund', source, 600, network=True)
            evidence.append({'stage': 'DEPENDENCIES', 'exit_code': deps.get('exit_code'), 'stderr': deps.get('stderr', '')[-900:]})
            if not deps.get('success'):
                return _fail('DEPENDENCIES', deps.get('stderr', '')[-900:], evidence, job_id)
            pkg = json.loads((source / 'package.json').read_text(encoding='utf-8'))
            if not pkg.get('scripts', {}).get('test'):
                return {'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                        'repo': safe_url, 'commit': sha, 'error': 'No npm test script; not activated', 'evidence': evidence}
            test = run('npm test', source, 180)

        evidence.append({'stage': 'FUNCTIONAL_TEST', 'exit_code': test.get('exit_code'),
                         'stdout': test.get('stdout', '')[-600:], 'stderr': test.get('stderr', '')[-600:]})
        if not test.get('success'):
            return _fail('FUNCTIONAL_TEST', test.get('stderr', '')[-900:], evidence, job_id)
        if final.exists():
            os.replace(final, previous)
        try:
            os.replace(source, final)
            deployed = True
            record = {'repo': safe_url, 'commit': sha, 'type': kind, 'path': str(final),
                      'functional_test_pass': True, 'installed_at': time.time(), 'job_id': job_id,
                      'status': 'FUNCTIONAL_TESTED'}
            _record(f'{owner}/{name}', record)
        except Exception:
            if deployed and final.exists():
                shutil.rmtree(final)
            if previous.exists():
                os.replace(previous, final)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return {'success': True, 'verified': True, 'state': 'FUNCTIONAL_TESTED',
                'note': 'Installed and tests passed. Activation as a running service requires a separate adapter and health probe.',
                'repo': safe_url, 'commit': sha, 'path': str(final), 'job_id': job_id, 'evidence': evidence}
    except Exception as exc:
        return _fail('INTERNAL', f'{type(exc).__name__}: {exc}', evidence, job_id)
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)
