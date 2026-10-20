"""Offline regression tests: scripted model, real temporary-file readback."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from execution_loop import run_loop, normalize_result

TOOLS = [{"type": "function", "function": {
    "name": "write", "parameters": {
        "type": "object", "properties": {"content": {"type": "string"}},
        "required": ["content"]}}}]


def call(identifier="one", arguments=None, name="write"):
    return {"tool_calls": [{"id": identifier, "type": "function", "function": {
        "name": name,
        "arguments": json.dumps({"content": "Merhaba Barış"})
        if arguments is None else arguments}}]}


class Script:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.inputs = []

    async def __call__(self, messages, tools):
        self.inputs.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


async def success(name, args):
    return {"success": True}


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_then_actual_file_and_independent_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "deneme.txt"

            async def write(name, args):
                target.write_text(args["content"], encoding="utf-8")
                return {"success": True}

            async def verify():
                return {"success": target.read_text(encoding="utf-8") == "Merhaba Barış"}

            model = Script({"content": "Önce planlayalım."}, call(),
                           {"content": "Tamamlandı."})
            result = await run_loop("Yaz", TOOLS, model, write, verify_task=verify)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertTrue(result["verified"])
            self.assertEqual(len(result["execution_steps"]), 1)
            self.assertEqual(model.inputs[-1][-1]["role"], "tool")

    async def test_text_only_is_not_executed(self):
        result = await run_loop("Yaz", TOOLS, Script(*[{"content": "Plan"}]*3), success)
        self.assertEqual(result["status"], "NOT_EXECUTED")

    async def test_successful_tool_without_acceptance_is_unverified(self):
        result = await run_loop("Yaz", TOOLS, Script(call(), {"content": "Bitti"}), success)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertFalse(result["verified"])

    async def test_nonzero_exit_cannot_be_success(self):
        async def failed(name, args):
            return {"success": True, "exit_code": 1, "stdout": ""}
        result = await run_loop("Yaz", TOOLS, Script(call(), {}), failed)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(result["execution_steps"][0]["success"])

    async def test_api_error_after_tool_remains_failed(self):
        result = await run_loop("Yaz", TOOLS,
                                Script(call(), RuntimeError("API kapalı")), success)
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["verified"])

    async def test_budget_exhaustion_is_not_verified(self):
        result = await run_loop("Yaz", TOOLS, Script(call()), success, max_steps=1)
        self.assertEqual(result["status"], "PARTIAL")

    async def test_bad_arguments_are_returned_to_model(self):
        model = Script(call(arguments="{"), {})
        result = await run_loop("Yaz", TOOLS, model, success)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIn("error", json.loads(model.inputs[-1][-1]["content"]))

    async def test_unknown_tool_never_executes(self):
        async def forbidden(*args):
            self.fail("Bilinmeyen araç yürütüldü")
        result = await run_loop("Yaz", TOOLS, Script(call(name="unknown"), {}), forbidden)
        self.assertEqual(result["status"], "PARTIAL")

    async def test_duplicate_call_id_does_not_repeat_side_effect(self):
        executed = []
        async def counted(name, args):
            executed.append(name)
            return {"success": True}
        await run_loop("Yaz", TOOLS, Script(call(), call(), {}), counted)
        self.assertEqual(executed, ["write"])

    async def test_conflicting_call_id_fails(self):
        result = await run_loop(
            "Yaz", TOOLS, Script(call(), call(arguments='{"content":"other"}')),
            success)
        self.assertEqual(result["status"], "FAILED")

    async def test_independent_verification_failure(self):
        async def verify():
            return {"success": False}
        result = await run_loop("Yaz", TOOLS, Script(call(), {}), success,
                                verify_task=verify)
        self.assertFalse(result["verified"])

    async def test_tool_exception_can_be_repaired(self):
        count = 0
        async def flaky(name, args):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("Geçici araç hatası")
            return {"success": True}
        async def verify():
            return {"success": count == 2}
        result = await run_loop("Yaz", TOOLS,
                                Script(call(), call("two"), {}), flaky,
                                verify_task=verify)
        self.assertEqual(result["status"], "VERIFIED")

    async def test_legacy_error_string_is_never_positive_evidence(self):
        self.assertIsNone(normalize_result("Komut: hata")["success"])

    async def test_chinese_model_reply_is_not_exposed(self):
        result = await run_loop("Yaz", TOOLS,
                                Script(call(), {"content": "这是结果"}), success)
        self.assertNotIn("这是结果", result["reply"])
        self.assertIn("doğrulanmadı", result["reply"])


if __name__ == "__main__":
    unittest.main()
