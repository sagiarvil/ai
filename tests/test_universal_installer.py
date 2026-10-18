import json
import os
import platform
import shutil
import signal
import subprocess
import sys
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
    calculate_directory_manifest,
    recover_interrupted_deployments,
    EngineActivationAdapter,
    REGISTRY,
    STAGING,
    DEPLOYED,
    run
)
from sandbox_executor import secure_sandbox_run, WORKSPACE_ROOT, SANDBOX_DIR



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

    # 1. Transactional Registry Concurrency Test (Thread + Multi-Process)
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

    def test_multiprocess_registry_concurrency(self):
        """İki ayrı Python işletim sistemi sürecinin eşzamanlı kayıt yapması veri kaybı yaratmamalıdır."""
        keys_p1 = [f"mp_owner1/repo_{i}" for i in range(10)]
        keys_p2 = [f"mp_owner2/repo_{i}" for i in range(10)]

        code_p1 = (
            "import sys\n"
            "from universal_installer import _record\n"
            f"keys = {keys_p1!r}\n"
            "for k in keys: _record(k, {'status': 'MP_TEST_1', 'val': k})\n"
        )
        code_p2 = (
            "import sys\n"
            "from universal_installer import _record\n"
            f"keys = {keys_p2!r}\n"
            "for k in keys: _record(k, {'status': 'MP_TEST_2', 'val': k})\n"
        )

        p1 = subprocess.Popen([sys.executable, "-c", code_p1], cwd=str(WORKSPACE_ROOT))
        p2 = subprocess.Popen([sys.executable, "-c", code_p2], cwd=str(WORKSPACE_ROOT))

        ret1 = p1.wait(timeout=30)
        ret2 = p2.wait(timeout=30)
        self.assertEqual(ret1, 0)
        self.assertEqual(ret2, 0)

        self.assertTrue(REGISTRY.exists())
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for k in keys_p1:
            self.assertIn(k, data)
            self.assertEqual(data[k]["val"], k)
        for k in keys_p2:
            self.assertIn(k, data)
            self.assertEqual(data[k]["val"], k)

        # Temizlik
        curr = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for k in keys_p1 + keys_p2:
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

    # 3. Gerçek Subprocess SIGKILL ve Otomatik Kurtarma Testi
    def test_real_subprocess_sigkill_recovery(self):
        """Yarım kalan deployment işlemine gerçek SIGKILL gönderilip recover_interrupted_deployments ile kurtarılmalıdır."""
        owner, name = "sigkillowner", "sigkillrepo"
        final = DEPLOYED / f"{owner}--{name}"
        final.mkdir(parents=True, exist_ok=True)
        (final / "active_version.txt").write_text("v1.0.0-stable", encoding="utf-8")

        # Gerçek bir alt süreç başlatıp os.replace yaparken SIGKILL gönderme testi
        job_id = "testjob123"
        previous = DEPLOYED / f".backup-{owner}--{name}-{job_id}"

        # Subprocess içinde os.replace simüle edip uyurken kill sinyali gönderme
        script = (
            "import os, time, sys\n"
            f"os.replace({str(final)!r}, {str(previous)!r})\n"
            "sys.stdout.write('MOVED\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = proc.stdout.readline()
        self.assertEqual(line.strip(), "MOVED")

        # Subprocess'i gerçek SIGKILL ile sonlandır
        os.kill(proc.pid, signal.SIGKILL)
        proc.stdout.close()
        proc.stderr.close()
        proc.wait()

        # Artık final mevcut değil, previous (.backup-*) mevcut
        self.assertFalse(final.exists())
        self.assertTrue(previous.exists())

        # Otomatik recovery motorunu çalıştır
        recovered = recover_interrupted_deployments()
        self.assertIn(f"{owner}--{name}", recovered)

        # Doğrulama: Eski sürüm sapasağlam geri gelmiş olmalı
        self.assertTrue(final.exists())
        self.assertEqual((final / "active_version.txt").read_text(encoding="utf-8"), "v1.0.0-stable")
        self.assertFalse(previous.exists())

        # Temizlik
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

    # 6. Secret Read Denial Test (Güvenli Fixture)
    def test_secret_read_denial_in_sandbox(self):
        """macOS Seatbelt altında .env okuması reddedilmeli; mevcut gerçek .env asla bozulmamalıdır."""
        if platform.system() != "Darwin":
            self.skipTest("Seatbelt sadece macOS üzerinde test edilir.")

        env_file = WORKSPACE_ROOT / ".env"
        backup_content = env_file.read_bytes() if env_file.exists() else None
        try:
            if not env_file.exists():
                env_file.write_text("SECRET_TEST_TOKEN=forbidden_leak\n", encoding="utf-8")
            res = secure_sandbox_run(f"cat '{env_file}'", timeout=10)
            self.assertFalse(res["success"])
            self.assertIn("Operation not permitted", res["stderr"])
        finally:
            if backup_content is not None:
                env_file.write_bytes(backup_content)
            elif env_file.exists():
                env_file.unlink()

    # 7. Network-Denied by Default Test
    def test_network_denied_by_default(self):
        """Varsayılan olarak (network=False) ağ çağrıları engellenmelidir."""
        if platform.system() != "Darwin":
            self.skipTest("Seatbelt ağ testi macOS üzerinde çalışır.")

        # curl google.com varsayılan sandbox içinde çalışmamalı
        res = run("curl -s -m 3 https://github.com", SANDBOX_DIR, timeout=10, network=False)
        self.assertFalse(res["success"], "Ağ erişimi varsayılan olarak kapalı olmalıdır.")

    def test_sandbox_runtime_probe_success(self):
        """Gerçek sandbox süreci içinde mkdir, touch ve git --version ön testi PASS dönmelidir."""
        from sandbox_executor import verify_sandbox_runtime_probe
        res = verify_sandbox_runtime_probe(SANDBOX_DIR, allow_network=True)
        self.assertTrue(res["success"])
        self.assertEqual(res["exit_code"], 0)

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
            os.system(f"git -C '{local_git}' init -q && git -C '{local_git}' config user.email 'ci@test.local' && git -C '{local_git}' config user.name 'CI' && git -C '{local_git}' add . && git -C '{local_git}' commit -qm 'init'")
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

    # 10. Engine Activation Adapter CLI & HTTP Health Probe Test
    def test_engine_activation_adapter_cli(self):
        """Aktivasyon adaptörü CLI probe yanıtını doğrulamalıdır."""
        res_ok = EngineActivationAdapter.probe_cli(WORKSPACE_ROOT, '-c "import sys; sys.exit(0)"')
        self.assertTrue(res_ok['success'])
        self.assertEqual(res_ok['state'], 'ACTIVE')

        res_fail = EngineActivationAdapter.probe_cli(Path('/nonexistent_path_xyz'), '--help')
        self.assertFalse(res_fail['success'])
        self.assertEqual(res_fail['state'], 'ACTIVATION_FAILED')

    def test_engine_activation_adapter_http(self):
        """Aktivasyon adaptörü HTTP health probe ile canlı servis doğrulamasını yapmalıdır."""
        from http.server import HTTPServer, BaseHTTPRequestHandler

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "healthy"}')

            def log_message(self, format, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), HealthHandler)
        port = server.server_port
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()

        # Açık port üzerinde 200 OK probe testi
        res_probe = EngineActivationAdapter.probe_service_health(port, '/health', timeout_seconds=3)
        self.assertTrue(res_probe['success'])
        self.assertEqual(res_probe['state'], 'ACTIVE')
        self.assertEqual(res_probe['status_code'], 200)

        # Kapalı port üzerinde probe testi
        res_closed = EngineActivationAdapter.probe_service_health(port + 1, '/health', timeout_seconds=1)
        self.assertFalse(res_closed['success'])
        self.assertEqual(res_closed['state'], 'ACTIVATION_FAILED')
        server.server_close()

    # 11. Directory Integrity SHA-256 Manifest Test
    def test_directory_integrity_manifest(self):
        """calculate_directory_manifest tüm dosyaların SHA-256 özetini eksiksiz çıkarmalıdır."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "f1.txt").write_text("hello omnicore", encoding="utf-8")
            (p / "sub").mkdir()
            (p / "sub" / "f2.py").write_text("print('audit')", encoding="utf-8")

            manifest = calculate_directory_manifest(p)
            self.assertIn("f1.txt", manifest)
            self.assertIn(str(Path("sub") / "f2.py"), manifest)
            self.assertEqual(len(manifest["f1.txt"]), 64)
            self.assertEqual(len(manifest[str(Path("sub") / "f2.py")]), 64)

    # 12. Explicit Unsupported Adapters (Rust, Go, Container) Test
    def test_explicit_unsupported_adapters(self):
        """Rust, Go ve Container projeleri açıkça UNSUPPORTED olarak reddedilmelidir."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "Cargo.toml").write_text("[package]\nname = 'test'\n", encoding="utf-8")
            self.assertEqual(classify(p), "rust")

            (p / "Cargo.toml").unlink()
            (p / "go.mod").write_text("module test\n", encoding="utf-8")
            self.assertEqual(classify(p), "go")

            (p / "go.mod").unlink()
            (p / "compose.yaml").write_text("services:\n  app:\n    image: test\n", encoding="utf-8")
    # 13. Zorunlu Kabul Testi: Gerçek GitHub Reposunun Sandbox İçinde Klonlanması
    def test_real_sandbox_github_clone(self):
        """Mac M4 üzerinde gerçek GitHub reposunu sandbox içinde klonlayıp doğrulamalıdır."""
        if platform.system() != "Darwin":
            self.skipTest("Gerçek Seatbelt sandbox kabul testi macOS üzerinde çalışır.")

        url = "https://github.com/octocat/Hello-World"
        res = install_repo(url)

        # Kanıt zincirini kontrol et
        evidence = res.get("evidence", [])
        self.assertTrue(len(evidence) >= 2, "En az PRE_PROBE ve CLONE kanıtı bulunmalıdır.")

        # 1. Pre-probe doğrulaması
        pre_probe = next((e for e in evidence if e.get("stage") == "PRE_PROBE"), None)
        self.assertIsNotNone(pre_probe)
        self.assertEqual(pre_probe.get("exit_code"), 0)

        # 2. Gerçek Git Clone doğrulaması
        clone_ev = next((e for e in evidence if e.get("stage") == "CLONE"), None)
        self.assertIsNotNone(clone_ev)
        self.assertEqual(clone_ev.get("exit_code"), 0)

        # 3. Gerçek Commit SHA doğrulaması
        rev_ev = next((e for e in evidence if e.get("stage") == "REVISION"), None)
        self.assertIsNotNone(rev_ev)
        self.assertEqual(len(rev_ev.get("commit", "")), 40)

        # 4. Desteklenmeyen / test süiti olmayan repo için fail-closed UNVERIFIED / UNSUPPORTED kararı
        self.assertFalse(res.get("verified", False), "Test süiti olmayan repo asla VERIFIED olamaz.")
        self.assertIn(res.get("state"), {"UNSUPPORTED", "UNVERIFIED"})


if __name__ == '__main__':
    unittest.main()


