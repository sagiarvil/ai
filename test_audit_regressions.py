"""Reproductions from the repository audit; scripted models are not live qualification."""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import signal
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient
import durable_api
from job_store import JobStore
from structured_actions import build_request, parse_action
from task_tools import TaskTools, TOOLS
from task_worker import ModelCallError, run_job
from test_durable_runtime import PLAN


class AuditTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile('/proc/' + str(os.getpid()) + '/cmdline'), 'Bu ortamın PID alanı /proc ile eşleşmiyor; native Linux CI sınar')
    def test_linux_launcher_identity_does_not_depend_on_ps_binary(self):
        from baris_local import process_command
        with patch('baris_local.subprocess.check_output', side_effect=AssertionError('ps should not be invoked on Linux')):
            command = process_command(os.getpid())
        if 'python' not in command.lower():
            self.skipTest('Host /proc farklı PID alanını gösteriyor; native Linux CI bu kontrolü sınar')
        self.assertIn('python', command.lower())

    def test_unverified_legacy_pid_never_receives_a_signal(self):
        from baris_local import shutdown_server
        with patch('baris_local.process_command', return_value='unrelated application'), patch('baris_local.os.kill') as kill:
            with self.assertRaises(ValueError):
                shutdown_server(5053, {'pid': 12345}, {})
            kill.assert_not_called()

    def test_managed_shutdown_requires_private_token_and_never_exposes_it(self):
        with self.workspace() as (root, store), patch.object(durable_api, 'WORKSPACE', root):
            with patch.dict(os.environ, {'BARIS_MANAGER_TOKEN': 'private-fixture-token'}):
                with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                    info = client.get('/api/engine_info')
                    self.assertTrue(info.json()['managed_shutdown'])
                    self.assertNotIn('private-fixture-token', info.text)
                    with patch('durable_api.os.kill') as kill:
                        for headers in ({}, {'X-Baris-Manager': 'wrong'}, {b'X-Baris-Manager': b'\xff'}):
                            self.assertEqual(client.post('/api/local_shutdown', headers=headers).status_code, 403)
                        kill.assert_not_called()
                        response = client.post('/api/local_shutdown', headers={'X-Baris-Manager': 'private-fixture-token'})
                        self.assertEqual(response.status_code, 202)
                        deadline = time.monotonic() + 1
                        while not kill.called and time.monotonic() < deadline:
                            time.sleep(.01)
                        kill.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_supported_web_entry_points_use_one_application(self):
        import omni_chat_panel
        import server
        self.assertIs(omni_chat_panel.app, durable_api.app)
        self.assertIs(server.app, durable_api.app)

    def test_legacy_web_runtime_cannot_be_imported_without_explicit_opt_in(self):
        import subprocess, sys
        environment = {k: v for k, v in os.environ.items() if k not in
                       {'BARIS_ENABLE_LEGACY_TOOLS', 'BARIS_RUN_LEGACY_INTEGRATION'}}
        result = subprocess.run([sys.executable, '-c', 'import legacy_omni_chat_panel'],
                                capture_output=True, text=True, env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Eski araç katmanı kapalı', result.stderr)

    def test_legacy_system_script_is_inert_without_explicit_option(self):
        import subprocess
        result = subprocess.run(['bash', 'deploy_armored_node.sh'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('çalıştırılmadı', result.stdout)

    def test_http_200_without_tokens_is_not_a_successful_model_probe(self):
        import httpx
        from model_manager import ModelManager
        client = MagicMock()
        client.__aenter__.return_value.post = AsyncMock(side_effect=[
            httpx.Response(200, json={'details': {}}),
            httpx.Response(200, json={'response': '', 'eval_count': 0})])
        with patch('model_manager.httpx.AsyncClient', return_value=client):
            result = asyncio.run(ModelManager.verify_model_runtime('local'))
        self.assertFalse(result['success'])
        self.assertFalse(result['inference_pass'])

    @contextmanager
    def workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            yield root, JobStore(root / '.baris_runtime' / 'jobs.sqlite3')

    def run_script(self, root, store, actions, expected=None, used=0):
        job = store.submit({'workspace': str(root), 'message': 'Kapsamdaki işi tamamla.',
                            'budget_seconds': 30, 'expected_files': expected}, 'script')
        store.claim()
        store.update(job, used=used)
        requests = []
        async def generate(request, *args, **kwargs):
            requests.append(request)
            action = actions.pop(0)
            if callable(action):
                return await action()
            return {'message': {'content': json.dumps(action)}}
        previous = signal.getsignal(signal.SIGTERM)
        try:
            with patch('task_worker.generate', generate):
                run_job(store, job)
        finally:
            signal.signal(signal.SIGTERM, previous)
        return store.get(job), requests

    def test_native_messages_preserve_task_and_stable_prefix(self):
        task = 'Yalnızca Türkçe.\nprint("Merhaba\\nBarış")'
        action = {'name': 'tool_write_file', 'arguments': {'filepath': 'x', 'content': 'a\nb'}}
        assistant = parse_action({'message': {'content': json.dumps(action)}}, [], TOOLS)
        history = [{'role': 'system', 'content': 'Kullanıcı kapsamı yetki sınırıdır.'},
                   {'role': 'user', 'content': task}, assistant,
                   {'role': 'tool', 'content': '{"success":true}'}]
        first = build_request('local', history, TOOLS)
        second = build_request('local', history + [assistant, history[-1]], TOOLS)
        self.assertEqual(first['messages'][1], {'role': 'user', 'content': task})
        self.assertEqual(second['messages'][:len(first['messages'])], first['messages'])
        self.assertEqual(json.loads(first['messages'][2]['content']), action)
        self.assertIn('Kullanıcı kapsamı', first['messages'][0]['content'])
        self.assertNotIn('tools', first)
        self.assertTrue(all('tool_calls' not in m for m in first['messages']))

    def test_duplicate_action_keys_are_not_executable(self):
        raw = '{"name":"tool_write_file","name":"tool_make_directory","arguments":{"filepath":"x"}}'
        with self.assertRaises(ValueError):
            parse_action({'message': {'content': raw}}, [], TOOLS)

    def test_chinese_plan_explanation_is_not_exposed_to_user(self):
        with self.workspace() as (root, store):
            tools = TaskTools(root, store, store.submit({}, 'language'))
            result = tools.execute('tool_plan_steps', {'steps': ['编写代码', 'Sonucu doğrula']})
            self.assertIn('Türkçe açıklama üretilemedi', result['plan'][0])
            self.assertEqual(result['plan'][1], 'Sonucu doğrula')
            self.assertFalse(any('\u3400' <= char <= '\u9fff' for char in json.dumps(result, ensure_ascii=False)))

    def test_background_descendant_is_stopped_after_parent_exits(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'child')
            child = "import time,pathlib;time.sleep(.5);pathlib.Path('escaped').write_text('late')"
            parent = 'import subprocess,sys;subprocess.Popen([sys.executable,"-c",' + repr(child) + '])'
            (root / 'parent.py').write_text(parent)
            result = TaskTools(root, store, job).run_command('python3 parent.py')
            time.sleep(.6)
            self.assertFalse((root / 'escaped').exists(), 'An orphan changed disk after TOOL_DONE')
            self.assertFalse(result['success'])
            self.assertTrue(result['background_processes_stopped'])

    def test_database_registration_failure_still_stops_spawned_command(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'register')
            (root / 'child.py').write_text("import time,pathlib;time.sleep(.3);pathlib.Path('escaped').write_text('late')")
            update = store.update
            def fail_registration(job_id, **fields):
                if fields.get('child_pid'):
                    raise OSError('injected database failure')
                return update(job_id, **fields)
            with patch.object(store, 'update', fail_registration):
                with self.assertRaises(OSError):
                    TaskTools(root, store, job).run_command('python3 child.py')
            time.sleep(.4)
            self.assertFalse((root / 'escaped').exists())

    def test_failed_command_cannot_certify_preexisting_expected_file(self):
        with self.workspace() as (root, store):
            (root / 'out.txt').write_text('ok')
            command = {'name': 'tool_run_shell', 'arguments': {'command': "python3 -c 'raise SystemExit(2)'"}}
            job, _ = self.run_script(root, store, [PLAN, command, {'name': '__finish__', 'arguments': {}}], {'out.txt': 'ok'})
            self.assertNotEqual(job['status'], 'VERIFIED', job)
            self.assertFalse(job['result']['execution_completed'])

    def test_total_budget_exhaustion_is_distinct_and_never_retried(self):
        with self.workspace() as (root, store):
            async def expired():
                await asyncio.sleep(.06)
                raise ModelCallError({'message': 'Model deadline', 'error_type': 'TimeoutError'})
            job, requests = self.run_script(root, store, [expired], used=29.98)
            self.assertEqual(len(requests), 1)
            self.assertEqual(job['result'].get('failure_code'), 'TASK_BUDGET_EXHAUSTED')
            self.assertFalse(any(e['kind'] == 'MODEL_RETRY' for e in job['events']))
            self.assertEqual(job['result']['budget_seconds'], 30)

    def test_uncertain_command_cleanup_blocks_queue_and_keeps_pid(self):
        with self.workspace() as (root, store):
            original = TaskTools.execute
            def uncertain(tools, name, arguments):
                if name == 'tool_run_shell':
                    store.update(tools.job_id, child_pid=12345)
                    raise PermissionError('Injected cleanup failure; no actual process was spawned')
                return original(tools, name, arguments)
            with patch.object(TaskTools, 'execute', uncertain):
                job, requests = self.run_script(root, store, [PLAN, {'name': 'tool_run_shell', 'arguments': {'command': 'python3 -V'}}])
            self.assertEqual(job['status'], 'BLOCKED')
            self.assertEqual(job['child_pid'], 12345)
            self.assertEqual(len(requests), 2)
            self.assertEqual(job['result']['failure_code'], 'COMMAND_CLEANUP_UNCERTAIN')
            self.assertTrue(store.queue_state()['blocked'])

    def test_slow_generation_with_fast_start_does_not_double_round_trips(self):
        with self.workspace() as (root, store):
            model = 'mistral-small-24b-abliterated:latest'
            for _ in range(2):
                store.record_model_sample(model, 8192, 10, 5, 100)
            job, requests = self.run_script(root, store, [PLAN, {'name': 'tool_write_file',
                'arguments': {'filepath': 'x', 'content': 'ok'}}], {'x': 'ok'})
            self.assertEqual(job['status'], 'VERIFIED')
            variant = next(v for v in requests[-1]['format']['anyOf'] if v['properties']['name']['enum'] == ['tool_write_file'])
            self.assertEqual(variant['properties']['arguments']['properties']['content']['maxLength'], 700)

    def test_large_file_append_is_rejected_without_mutation(self):
        with self.workspace() as (root, store):
            target = root / 'large'
            original = b'a' * 100_000
            target.write_bytes(original)
            tools = TaskTools(root, store, store.submit({}, 'large'))
            import hashlib
            with self.assertRaises(ValueError):
                tools.execute('tool_append_file', {'filepath': 'large', 'content': 'x',
                    'expected_sha256': hashlib.sha256(original).hexdigest()})
            self.assertEqual(target.read_bytes(), original)

    def test_nonlocal_host_cannot_bypass_origin_guard(self):
        with self.workspace() as (root, store), patch.object(durable_api, 'WORKSPACE', root):
            with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                response = client.post('/api/tasks', headers={'Host': 'evil.example', 'Origin': 'http://evil.example'}, json={'message': 'x'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(client.get('/api/engine_info').status_code, 200)

    def test_request_bytes_are_bounded_before_json_validation(self):
        with self.workspace() as (root, store), patch.object(durable_api, 'WORKSPACE', root):
            with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                raw = b'{"message":"' + b'x' * 300_000 + b'"}'
                response = client.post('/api/tasks', content=raw, headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 413)
                response = client.post('/api/tasks', content=iter([raw[:100_000], raw[100_000:]]), headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 413)

    def test_invalid_acceptance_path_is_validation_error(self):
        with self.workspace() as (root, store), patch.object(durable_api, 'WORKSPACE', root):
            with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                response = client.post('/api/tasks', json={'message': 'x', 'expected_files': {'bad\x00path': 'x'}})
                self.assertEqual(response.status_code, 422)

    def test_blocked_queue_rejects_new_tasks_instead_of_hiding_wait(self):
        with self.workspace() as (root, store), patch.object(durable_api, 'WORKSPACE', root):
            with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                job = store.submit({}, 'uncertain')
                store.claim()
                store.update(job, pending={'name': 'tool_run_shell', 'args': {}})
                store.recover(lambda pid: False)
                response = client.post('/api/tasks', json={'message': 'new'})
                self.assertEqual(response.status_code, 503, response.text)


if __name__ == '__main__':
    unittest.main()
