import asyncio
import unittest
from resilience_kernel import ErrorKind, ExecutionReport, ResilienceKernel, State, ToolOutcome, ToolSpec

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
            if len(calls) == 1: return ToolOutcome(False, stderr="connection reset")
            return ToolOutcome(True, evidence={"verified":True})
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

if __name__ == "__main__": unittest.main()
