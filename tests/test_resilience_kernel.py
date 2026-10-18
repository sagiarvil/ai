import asyncio
import unittest
from resilience_kernel import ErrorKind, ResilienceKernel, State, ToolOutcome, ToolSpec

async def allow(_): return True
async def verify(result, _): return result.evidence.get("verified") is True

class ResilienceTests(unittest.TestCase):
    def test_permission_error_has_no_retry(self):
        calls = []
        async def act(_):
            calls.append(1)
            return ToolOutcome(False, code="GIT", stderr="fatal: could not create work tree dir: Operation not permitted")
        spec = ToolSpec("git", act, verify, allow, idempotent=True, max_attempts=4)
        result = asyncio.run(ResilienceKernel().execute(spec, {"repo":"x"}))
        self.assertEqual(result.state, State.BLOCKED)
        self.assertEqual(result.error_kind, ErrorKind.PERMISSION)
        self.assertEqual(len(calls), 1)

    def test_transient_retry_with_proof(self):
        calls = []
        async def act(_):
            calls.append(1)
            if len(calls) == 1:
                return ToolOutcome(False, stderr="connection reset")
            return ToolOutcome(True, evidence={"verified": True})
        spec = ToolSpec("network", act, verify, allow, idempotent=True, max_attempts=2)
        result = asyncio.run(ResilienceKernel().execute(spec, {}))
        self.assertTrue(result.verified)
        self.assertEqual(result.attempts, 2)

    def test_no_fake_success(self):
        async def act(_): return ToolOutcome(True, evidence={})
        spec = ToolSpec("test", act, verify, allow)
        result = asyncio.run(ResilienceKernel().execute(spec, {}))
        self.assertFalse(result.verified)
        self.assertEqual(result.state, State.FAILED)

    def test_preflight_blocks(self):
        calls = []
        async def deny(_): return False
        async def act(_):
            calls.append(1)
            return ToolOutcome(True)
        result = asyncio.run(ResilienceKernel().execute(ToolSpec("blocked",act,verify,deny),{}))
        self.assertEqual(result.state,State.BLOCKED)
        self.assertFalse(calls)

    def test_non_idempotent_never_retried(self):
        calls = []
        async def act(_):
            calls.append(1)
            return ToolOutcome(False,stderr="timed out")
        spec=ToolSpec("payment",act,verify,allow,idempotent=False,max_attempts=4)
        result=asyncio.run(ResilienceKernel().execute(spec,{}))
        self.assertEqual(result.attempts,1)

    # 6. Otomatik Onarma (Remediation) Adaptör Testi
    def test_remediation_adapter_heals_and_retries(self):
        """Düzeltilebilir hatada remediation devreye girmeli, onarıp başarıya ulaştırmalıdır."""
        attempts = []
        remediated = []

        async def act(_):
            attempts.append(1)
            if len(attempts) == 1:
                return ToolOutcome(False, code="DIR_MISSING", stderr="missing config directory")
            return ToolOutcome(True, evidence={"verified": True})

        async def remediate(outcome, _):
            remediated.append(1)
            return True  # Onarıldı

        spec = ToolSpec("remediable", act, verify, allow, idempotent=True, max_attempts=3, remediate=remediate)
        result = asyncio.run(ResilienceKernel().execute(spec, {}))
        self.assertTrue(result.verified)
        self.assertEqual(len(remediated), 1)
        self.assertEqual(len(attempts), 2)

    # 7. Uçtan Uca Dosya Yazma ve Okuma Adaptör Testi
    def test_e2e_file_write_and_read_adapters(self):
        """OmniCoreToolAdapters ile dosya yazma ve okuma uçtan uca doğrulanmalıdır."""
        import tempfile
        from pathlib import Path
        from resilience_kernel import OmniCoreToolAdapters

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            write_spec = OmniCoreToolAdapters.get_file_write_spec(tmp_root)
            read_spec = OmniCoreToolAdapters.get_file_read_spec(tmp_root)

            # 1. Dosya Yaz
            res_write = asyncio.run(ResilienceKernel().execute(write_spec, {
                "filepath": "sub/module.py",
                "content": "def test(): return 42\n"
            }))
            self.assertTrue(res_write.verified)
            self.assertEqual(res_write.state, State.VERIFIED)

            # 2. Dosya Oku
            res_read = asyncio.run(ResilienceKernel().execute(read_spec, {
                "filepath": "sub/module.py"
            }))
            self.assertTrue(res_read.verified)
            self.assertEqual(res_read.state, State.VERIFIED)

            # 3. İhlal Denemesi: .env yazma engellenmeli (Preflight reject)
            res_env = asyncio.run(ResilienceKernel().execute(write_spec, {
                "filepath": ".env",
                "content": "SECRET=123"
            }))
            self.assertEqual(res_env.state, State.BLOCKED)

    # 8. Uçtan Uca Shell Sandbox Adaptör Testi
    def test_e2e_shell_sandbox_adapter(self):
        """Shell adaptörü komutu izole sandbox içinde başarıyla doğrulamalıdır."""
        from resilience_kernel import OmniCoreToolAdapters
        from sandbox_executor import secure_sandbox_run

        shell_spec = OmniCoreToolAdapters.get_shell_spec(secure_sandbox_run)
        res = asyncio.run(ResilienceKernel().execute(shell_spec, {"command": "echo 'RESILIENCE_PASS'"}))
        self.assertTrue(res.verified)
        self.assertEqual(res.state, State.VERIFIED)

    # 9. Uçtan Uca GitHub Kurulum Adaptör Testi
    def test_e2e_github_install_adapter_flow(self):
        """GitHub adaptörü preflight ve test çıktısını bağımsız postcondition ile teyit etmelidir."""
        from resilience_kernel import OmniCoreToolAdapters

        # Mock install_repo ile deterministic akış
        def mock_install_repo(url):
            return {
                "success": True,
                "state": "FUNCTIONAL_TESTED",
                "commit": "a" * 40,
                "path": "/tmp/mock_deployed",
                "job_id": "job_123"
            }

        git_spec = OmniCoreToolAdapters.get_github_install_spec(mock_install_repo)
        res = asyncio.run(ResilienceKernel().execute(git_spec, {"query_or_url": "https://github.com/test/repo"}))
        self.assertTrue(res.verified)
        self.assertEqual(res.state, State.VERIFIED)

        # Geçersiz URL preflight tarafından BLOCKED edilmeli
        res_bad = asyncio.run(ResilienceKernel().execute(git_spec, {"query_or_url": "ftp://bad.url"}))
        self.assertEqual(res_bad.state, State.BLOCKED)


if __name__ == "__main__":
    unittest.main()

