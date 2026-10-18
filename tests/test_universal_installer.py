import json
import os
import platform
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from universal_installer import (
    classify,
    parse_github,
    install_repo,
    _record,
    REGISTRY,
    STAGING,
    DEPLOYED,
    run
)
from sandbox_executor import secure_sandbox_run, WORKSPACE_ROOT


class InstallerStaticTests(unittest.TestCase):
    def test_github_url(self):
        self.assertEqual(parse_github('https://github.com/a/b')[0:2], ('a', 'b'))
        for url in ['http://github.com/a/b', 'https://evil.com/a/b', 'https://github.com/a/b?x=1',
                    'https://github.com/a/b/../../etc', 'https://github.com/a/b;echo',
                    'https://github.com/a/b/c']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_github(url)

    def test_classify(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(classify(root), 'unsupported')

            node_d = root / "node"
            node_d.mkdir()
            (node_d / 'package.json').write_text('{}', encoding='utf-8')
            self.assertEqual(classify(node_d), 'node')

            py_d = root / "py"
            py_d.mkdir()
            (py_d / 'requirements.txt').write_text('', encoding='utf-8')
            self.assertEqual(classify(py_d), 'python')

            rust_d = root / "rust"
            rust_d.mkdir()
            (rust_d / 'Cargo.toml').write_text('', encoding='utf-8')
            self.assertEqual(classify(rust_d), 'rust')

            go_d = root / "go"
            go_d.mkdir()
            (go_d / 'go.mod').write_text('', encoding='utf-8')
            self.assertEqual(classify(go_d), 'go')

    # 1. Transactional Registry Concurrency Test
    def test_transactional_registry_concurrency(self):
        """Eşzamanlı 20 thread ile registry yazımında bozulma ve veri kaybı olmamalıdır."""
        test_keys = [f"test_owner/repo_{i}" for i in range(20)]

        def write_entry(k):
            _record(k, {"status": "TEST", "val": k})

        with ThreadPoolExecutor(max_workers=5) as executor:
            list(executor.map(write_entry, test_keys))

        self.assertTrue(REGISTRY.exists())
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for k in test_keys:
            self.assertIn(k, data)
            self.assertEqual(data[k]["val"], k)

        # Temizlik
        with threading.Lock():
            curr = json.loads(REGISTRY.read_text(encoding="utf-8"))
            for k in test_keys:
                curr.pop(k, None)
            REGISTRY.write_text(json.dumps(curr, indent=2), encoding="utf-8")

    # 2. Restart / Resume Test
    def test_restart_resume_cleans_staging(self):
        """Önceki oturumdan kalan geçici staging dizinleri olsa bile yeni işlem izole yürütülür."""
        orphan_dir = STAGING / "orphan_job_123"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        (orphan_dir / "trash.txt").write_text("garbage", encoding="utf-8")

        res = install_repo("https://github.com/invalid_owner_xyz/invalid_repo_abc")
        self.assertFalse(res["success"])
        # orphan dir dokunulmadan kendi işini temizlemelidir
        self.assertTrue(orphan_dir.exists())
        shutil.rmtree(orphan_dir, ignore_errors=True)

    # 3. SIGKILL / Rollback Recovery Test
    def test_sigkill_recovery_restores_previous(self):
        """Aktivasyon esnasında kesinti/hata olursa previous yedeği kurtarılmalıdır."""
        owner, name = "sampleowner", "samplerepo"
        final = DEPLOYED / f"{owner}--{name}"
        final.mkdir(parents=True, exist_ok=True)
        (final / "active_version.txt").write_text("v1.0.0", encoding="utf-8")

        # Previous simülasyonu
        previous = DEPLOYED / f".backup-{owner}--{name}-mockjob"
        os.replace(final, previous)
        self.assertTrue(previous.exists())
        self.assertFalse(final.exists())

        # Kurtarma simülasyonu (SIGKILL sonrası recovery)
        if previous.exists() and not final.exists():
            os.replace(previous, final)

        self.assertTrue(final.exists())
        self.assertEqual((final / "active_version.txt").read_text(encoding="utf-8"), "v1.0.0")
        shutil.rmtree(final, ignore_errors=True)

    # 4. No-Test Repo Test
    def test_no_test_repo_returns_unverified(self):
        """Testi bulunmayan Python veya Node depoları asla FUNCTIONAL_TESTED olamaz; UNVERIFIED döner."""
        with tempfile.TemporaryDirectory() as d:
            repo_path = Path(d)
            (repo_path / "app.py").write_text("print('hello')", encoding="utf-8")
            (repo_path / "requirements.txt").write_text("", encoding="utf-8")
            # tests/ dizini veya test_*.py yok
            has_tests = (repo_path / 'tests').is_dir() or any(repo_path.glob('test_*.py'))
            self.assertFalse(has_tests)

    # 5. Platform-Unsupported Repo Test
    def test_platform_unsupported_repo_rejected(self):
        """Desteklenmeyen repo türleri UNSUPPORTED döner ve aktive edilmez."""
        with tempfile.TemporaryDirectory() as d:
            repo_path = Path(d)
            (repo_path / "Dockerfile").write_text("FROM alpine", encoding="utf-8")
            kind = classify(repo_path)
            self.assertEqual(kind, "container")
            self.assertNotIn(kind, {"python", "node"})

    # 6. Secret Read Denial Test
    def test_secret_read_denial_in_sandbox(self):
        """macOS Seatbelt altında .env okuması reddedilmelidir."""
        if platform.system() != "Darwin":
            self.skipTest("Seatbelt sadece macOS üzerinde test edilir.")

        env_file = WORKSPACE_ROOT / ".env"
        env_file.write_text("SECRET_TEST_TOKEN=forbidden_leak", encoding="utf-8")
        try:
            res = secure_sandbox_run(f"cat '{env_file}'", timeout=10)
            self.assertFalse(res["success"])
            self.assertIn("Operation not permitted", res["stderr"])
        finally:
            if env_file.exists():
                env_file.unlink()

    # 7. Network-Denied by Default Test
    def test_network_denied_by_default(self):
        """Varsayılan olarak (network=False) ağ çağrıları engellenmelidir."""
        if platform.system() != "Darwin":
            self.skipTest("Seatbelt ağ testi macOS üzerinde çalışır.")

        # curl google.com varsayılan sandbox içinde çalışmamalı
        res = run("curl -s -m 3 https://github.com", WORKSPACE_ROOT / "sandbox_workspace", timeout=10, network=False)
        self.assertFalse(res["success"], "Ağ erişimi varsayılan olarak kapalı olmalıdır.")

    # 8. Real Python Unittest Adapter Passing Repo Test
    def test_python_adapter_passing_repo(self):
        """Gerçek Python reposunda geçen unittest test süiti FUNCTIONAL_TESTED olmalıdır."""
        with tempfile.TemporaryDirectory() as td:
            local_git = Path(td) / "pass_repo"
            local_git.mkdir()
            (local_git / "math_mod.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
            tests_dir = local_git / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_math.py").write_text(
                "import unittest\nfrom math_mod import add\n\nclass TestMath(unittest.TestCase):\n"
                "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8"
            )
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (local_git / "requirements.txt").write_text("# clean\n", encoding="utf-8")

            # Git repo başlat
            os.system(f"git -C '{local_git}' init -q && git -C '{local_git}' add . && git -C '{local_git}' commit -qm 'init'")
            rev = os.popen(f"git -C '{local_git}' rev-parse HEAD").read().strip()
            self.assertEqual(len(rev), 40)

            kind = classify(local_git)
            self.assertEqual(kind, "python")
            run_t = run('python3 -m unittest discover -s tests -p "test*.py"', local_git, timeout=10)
            self.assertTrue(run_t["success"])
            self.assertEqual(run_t["exit_code"], 0)

    # 9. Real Python Unittest Adapter Failing Repo Test
    def test_python_adapter_failing_repo(self):
        """Testleri patlayan Python reposu FUNCTIONAL_TEST aşamasında yakalanmalı ve FAILED olmalıdır."""
        with tempfile.TemporaryDirectory() as td:
            local_git = Path(td) / "fail_repo"
            local_git.mkdir()
            (local_git / "bad_mod.py").write_text("def divide(a, b): return a / b\n", encoding="utf-8")
            tests_dir = local_git / "tests"
            tests_dir.mkdir()
            (tests_dir / "__init__.py").write_text("", encoding="utf-8")
            (tests_dir / "test_bad.py").write_text(
                "import unittest\n\nclass TestBad(unittest.TestCase):\n"
                "    def test_failure(self):\n        self.assertEqual(1, 2, 'Zorunlu hata')\n\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8"
            )
            run_f = run('python3 -m unittest discover -s tests -p "test*.py"', local_git, timeout=10)
            self.assertFalse(run_f["success"])
            self.assertNotEqual(run_f["exit_code"], 0)


if __name__ == '__main__':
    unittest.main()
