"""Offline adapter validation; not a live Ollama/model benchmark."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from execution_loop import run_loop
from structured_actions import build_request, parse_action

TOOLS = [{"type": "function", "function": {
    "name": "write_file", "description": "UTF-8 dosya yaz.",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string"},
                                  "content": {"type": "string"}},
                   "required": ["path", "content"]}}}]
MESSAGES = [{"role": "user", "content": "Dosya yaz."}]


def response(action):
    return {"message": {"content": json.dumps(action, ensure_ascii=False)}}


class StructuredTests(unittest.TestCase):
    def test_native_schema_request_has_no_tool_parser_dependency(self):
        request = build_request("local", MESSAGES, TOOLS)
        self.assertNotIn("tools", request)
        self.assertNotIn("tool_choice", request)
        self.assertEqual(request["format"]["anyOf"][0]["properties"]["name"]["enum"],
                         ["write_file"])
        self.assertFalse(request["stream"])

    def test_first_action_cannot_finish(self):
        with self.assertRaises(ValueError):
            parse_action(response({"name": "__finish__", "arguments": {}}),
                         MESSAGES, TOOLS)

    def test_valid_action_becomes_executable_call(self):
        reply = parse_action(response({
            "name": "write_file", "arguments": {"path": "x", "content": "Türkçe"}
        }), MESSAGES, TOOLS)
        function = reply["tool_calls"][0]["function"]
        self.assertEqual(function["name"], "write_file")
        self.assertEqual(json.loads(function["arguments"])["content"], "Türkçe")

    def test_text_is_not_executed(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            parse_action({"message": {"content": "Dosyayı oluşturdum."}},
                         MESSAGES, TOOLS)

    def test_wrong_parameter_type_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_action(response({
                "name": "write_file", "arguments": {"path": 42, "content": "x"}
            }), MESSAGES, TOOLS)

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_action(response({"name": "delete_all", "arguments": {}}),
                         MESSAGES, TOOLS)

    def test_finish_allowed_only_after_tool_result(self):
        messages = MESSAGES + [{"role": "tool", "content": "{}"}]
        reply = parse_action(response({"name": "__finish__", "arguments": {}}),
                             messages, TOOLS)
        self.assertNotIn("tool_calls", reply)

    def test_real_file_round_trip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "merhaba.txt"
                async def model(messages, tools):
                    build_request("local", messages, tools)
                    if target.exists():
                        action = {"name": "__finish__", "arguments": {}}
                    else:
                        action = {"name": "write_file", "arguments": {
                            "path": "merhaba.txt", "content": "Merhaba Barış"}}
                    return parse_action(response(action), messages, tools)
                async def tool(name, args):
                    (Path(directory) / args["path"]).write_text(
                        args["content"], encoding="utf-8")
                    return {"success": True}
                async def verify():
                    return {"success": target.read_text(encoding="utf-8") == "Merhaba Barış"}
                result = await run_loop(
                    "Yaz", TOOLS, model, tool, verify_task=verify)
                self.assertEqual(result["status"], "VERIFIED")
                self.assertEqual(target.read_bytes(), "Merhaba Barış".encode())
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
