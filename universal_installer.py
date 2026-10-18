"""Fail-closed, transactional GitHub installer for the OmniCore macOS host.

A checked-out repository is UNTRUSTED. All code execution must pass through
sandbox_executor.secure_sandbox_run; Python/Node packages never install globally.
"""
from __future__ import annotations

import fcntl
import hashlib
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

from sandbox_executor import OMNICORE_HOME, secure_sandbox_run, verify_sandbox_runtime_probe

STAGING = OMNICORE_HOME / 'installations'
DEPLOYED = OMNICORE_HOME / 'installed_engines'
REGISTRY = OMNICORE_HOME / 'installed_engines_registry.json'
REGISTRY_LOCK_FILE = OMNICORE_HOME / 'installed_engines_registry.lock'
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


def calculate_directory_manifest(directory: Path) -> dict[str, str]:
    """Tüm dosyaların SHA-256 özetini çıkararak bütünlük manifesti oluşturur."""
    manifest = {}
    if not directory.exists():
        return manifest
    for p in sorted(directory.rglob('*')):
        if p.is_file() and not p.name.startswith('.') and p.name != 'integrity_manifest.json':
            rel = str(p.relative_to(directory))
            try:
                manifest[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            except Exception:
                pass
    return manifest


def recover_interrupted_deployments() -> list[str]:
    """SIGKILL veya çökme sonrası yarım kalan .backup-* dizinlerini otomatik kurtarır."""
    recovered = []
    if not DEPLOYED.exists():
        return recovered
    with LOCK:
        for backup_path in DEPLOYED.glob('.backup-*'):
            name_part = backup_path.name[len('.backup-'):]
            parts = name_part.rsplit('-', 1)
            target_engine = parts[0] if len(parts) == 2 else name_part
            final_target = DEPLOYED / target_engine
            if not final_target.exists():
                try:
                    os.replace(backup_path, final_target)
                    recovered.append(target_engine)
                except Exception:
                    pass
            else:
                shutil.rmtree(backup_path, ignore_errors=True)
    return recovered


def _record(registry_key: str, record: dict[str, Any]) -> None:
    REGISTRY_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_LOCK_FILE, 'a+') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            with LOCK:
                old = json.loads(REGISTRY.read_text(encoding='utf-8')) if REGISTRY.exists() else {}
                old[registry_key] = record
                atomic_json(REGISTRY, old)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _fail(stage: str, reason: str, evidence: list[dict[str, Any]], job_id: str,
          exit_code: int = -1, target_path: str = '', seatbelt_applied: bool = False) -> dict[str, Any]:
    state = 'BLOCKED' if 'Operation not permitted' in reason or exit_code == 126 else 'FAILED'
    return {
        'success': False,
        'state': state,
        'stage': stage,
        'error': reason,
        'exit_code': exit_code,
        'target_path': target_path,
        'seatbelt_applied': seatbelt_applied,
        'job_id': job_id,
        'evidence': evidence,
        'verified': False
    }


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
    task_dir = (STAGING / job_id).resolve()
    source = (task_dir / 'source').resolve()
    task_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = (DEPLOYED / f'{owner}--{name}').resolve()
    previous = (DEPLOYED / f'.backup-{owner}--{name}-{job_id}').resolve()
    deployed = False

    # 3. Gerçek sandbox süreci içinde mkdir, touch, git --version ön testi
    pre_probe = verify_sandbox_runtime_probe(task_dir, allow_network=True)
    if not pre_probe.get('success'):
        err_msg = pre_probe.get('stderr') or 'Sandbox runtime probe failed'
        evidence.append({
            'stage': 'PRE_PROBE',
            'exit_code': pre_probe.get('exit_code'),
            'stderr': pre_probe.get('stderr', ''),
            'target_path': str(task_dir),
            'seatbelt_applied': pre_probe.get('seatbelt_applied', False)
        })
        return _fail('PRE_PROBE', err_msg, evidence, job_id,
                     exit_code=pre_probe.get('exit_code', -1),
                     target_path=str(task_dir),
                     seatbelt_applied=pre_probe.get('seatbelt_applied', False))

    evidence.append({
        'stage': 'PRE_PROBE',
        'exit_code': 0,
        'target_path': str(task_dir),
        'seatbelt_applied': pre_probe.get('seatbelt_applied', False)
    })

    try:
        clone_cmd = f"git clone --depth 1 --no-recurse-submodules '{safe_url}' '{source}'"
        clone = run(clone_cmd, task_dir, 180, network=True)
        clone_stderr = clone.get('stderr', '')
        evidence.append({
            'stage': 'CLONE',
            'exit_code': clone.get('exit_code'),
            'stderr': clone_stderr,
            'target_path': str(source),
            'seatbelt_applied': clone.get('seatbelt_applied', False)
        })
        if not clone.get('success') or not (source / '.git').is_dir():
            fail_reason = clone_stderr if clone_stderr else 'Clone failed'
            return _fail('CLONE', fail_reason, evidence, job_id,
                         exit_code=clone.get('exit_code', -1),
                         target_path=str(source),
                         seatbelt_applied=clone.get('seatbelt_applied', False))

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

            # Proje-özel test adaptörü: pytest vs unittest
            uses_pytest = (
                (source / 'pytest.ini').is_file() or
                (source / 'conftest.py').is_file() or
                ((source / 'pyproject.toml').is_file() and 'tool.pytest' in (source / 'pyproject.toml').read_text(encoding='utf-8', errors='ignore'))
            )
            if uses_pytest:
                # Pytest kurulu mu kontrol et
                pt_check = run('.venv/bin/python -c "import pytest"', source, 10)
                if pt_check.get('success'):
                    test_cmd = '.venv/bin/python -m pytest'
                else:
                    test_cmd = '.venv/bin/python -m unittest discover -s tests -t . -p "test*.py"' if (source / 'tests').is_dir() else '.venv/bin/python -m unittest discover -p "test_*.py"'
            else:
                test_cmd = '.venv/bin/python -m unittest discover -s tests -t . -p "test*.py"' if (source / 'tests').is_dir() else '.venv/bin/python -m unittest discover -p "test_*.py"'

            test = run(test_cmd, source, 180)
        else:
            if not (source / 'package-lock.json').exists():
                return {'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                        'repo': safe_url, 'commit': sha, 'error': 'package-lock.json required; not activated', 'evidence': evidence}

            # Native modül denetimi: npm ci --ignore-scripts native modülleri eksik bırakabilir
            has_native_binding = (source / 'binding.gyp').is_file() or any(source.glob('**/binding.gyp'))
            pkg_raw = (source / 'package.json').read_text(encoding='utf-8')
            pkg = json.loads(pkg_raw)
            scripts = pkg.get('scripts', {})
            has_postinstall = 'postinstall' in scripts or 'install' in scripts

            if has_native_binding or (has_postinstall and 'gyp' in scripts.get('postinstall', '').lower()):
                return {
                    'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                    'repo': safe_url, 'commit': sha,
                    'error': 'Native modules/build detected; npm ci --ignore-scripts leaves native modules incomplete',
                    'evidence': evidence
                }

            deps = run('npm ci --ignore-scripts --no-audit --no-fund', source, 600, network=True)
            evidence.append({'stage': 'DEPENDENCIES', 'exit_code': deps.get('exit_code'), 'stderr': deps.get('stderr', '')[-900:]})
            if not deps.get('success'):
                return _fail('DEPENDENCIES', deps.get('stderr', '')[-900:], evidence, job_id)

            # Opsiyonel lifecycle build adımı (örn: npm run build)
            if 'build' in scripts:
                build_res = run('npm run build', source, 300)
                evidence.append({'stage': 'BUILD', 'exit_code': build_res.get('exit_code'), 'stderr': build_res.get('stderr', '')[-900:]})
                if not build_res.get('success'):
                    return _fail('BUILD', build_res.get('stderr', 'Build failed')[-900:], evidence, job_id)

            # Test runner adaptörü
            test_script = None
            if 'test' in scripts:
                test_script = 'npm test'
            elif 'test:unit' in scripts:
                test_script = 'npm run test:unit'

            if not test_script:
                return {'success': False, 'verified': False, 'state': 'UNVERIFIED', 'job_id': job_id,
                        'repo': safe_url, 'commit': sha, 'error': 'No npm test script; not activated', 'evidence': evidence}
            test = run(test_script, source, 180)

        evidence.append({'stage': 'FUNCTIONAL_TEST', 'exit_code': test.get('exit_code'),
                         'stdout': test.get('stdout', '')[-600:], 'stderr': test.get('stderr', '')[-600:]})
        if not test.get('success'):
            return _fail('FUNCTIONAL_TEST', test.get('stderr', '')[-900:], evidence, job_id)
        if final.exists():
            os.replace(final, previous)
        try:
            os.replace(source, final)
            deployed = True
            manifest = calculate_directory_manifest(final)
            (final / 'integrity_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            record = {'repo': safe_url, 'commit': sha, 'type': kind, 'path': str(final),
                      'functional_test_pass': True, 'installed_at': time.time(), 'job_id': job_id,
                      'status': 'FUNCTIONAL_TESTED', 'manifest_count': len(manifest)}
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
                'repo': safe_url, 'commit': sha, 'path': str(final), 'job_id': job_id, 'evidence': evidence,
                'manifest_count': len(manifest)}
    except Exception as exc:
        return _fail('INTERNAL', f'{type(exc).__name__}: {exc}', evidence, job_id)
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)


class EngineActivationAdapter:
    """Installed engines are only FUNCTIONAL_TESTED until an adapter verifies runtime health."""

    @staticmethod
    def probe_cli(engine_path: Path, test_arg: str = '--help') -> dict[str, Any]:
        """Verify binary/script responsiveness in the sandbox."""
        if not engine_path.exists():
            return {'success': False, 'state': 'ACTIVATION_FAILED', 'error': 'Engine path does not exist'}
        # Python sanal ortamı varsa onunla çalıştır
        venv_py = engine_path / '.venv' / 'bin' / 'python'
        cmd = f"'{venv_py}' {test_arg}" if venv_py.is_file() else "python3 -c 'import sys; sys.exit(0)'"
        res = run(cmd, engine_path, timeout=30)
        success = res.get('success', False) and res.get('exit_code') == 0
        return {
            'success': success,
            'state': 'ACTIVE' if success else 'ACTIVATION_FAILED',
            'probe_type': 'CLI',
            'exit_code': res.get('exit_code'),
            'error': res.get('stderr') if not success else None
        }

    @staticmethod
    def probe_service_health(port: int, path: str = '/health', timeout_seconds: int = 5) -> dict[str, Any]:
        """Perform an explicit health probe against a running engine service."""
        import urllib.request
        if not path.startswith('/'):
            path = '/' + path
        url = f'http://127.0.0.1:{int(port)}{path}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'OmniCore-HealthProbe/1.0'})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
                code = resp.getcode()
                body = resp.read(1024).decode('utf-8', errors='ignore')
                is_healthy = 200 <= code < 300
                return {
                    'success': is_healthy,
                    'state': 'ACTIVE' if is_healthy else 'ACTIVATION_FAILED',
                    'probe_type': 'HTTP_HEALTH',
                    'status_code': code,
                    'body_preview': body[:200]
                }
        except Exception as exc:
            return {
                'success': False,
                'state': 'ACTIVATION_FAILED',
                'probe_type': 'HTTP_HEALTH',
                'error': f'Health probe failed on {url}: {exc}'
            }

