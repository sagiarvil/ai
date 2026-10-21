"""Real TCP/ASGI/worker/disk round trip, using a scripted model instead of Ollama."""
import json
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from live_qualification import http_client
from test_durable_runtime import PLAN, fake_ollama, write


class HttpSmokeTests(unittest.TestCase):
    @contextmanager
    def server(self, root, endpoint, port):
        source = Path(__file__).resolve().parent
        environment = dict(os.environ, BARIS_WORKSPACE=str(root), BARIS_OLLAMA_CHAT_URL=endpoint)
        with (root / 'restart-server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'durable_api:app', '--host', '127.0.0.1',
                '--port', str(port)], cwd=source, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            request = http_client('http://127.0.0.1:' + str(port))
            try:
                deadline = time.monotonic() + 8
                while True:
                    if process.poll() is not None:
                        self.fail((root / 'restart-server.log').read_text())
                    try:
                        request('/api/engine_info')
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise TimeoutError('HTTP yeniden başlatma testi açılamadı.')
                        time.sleep(.03)
                yield request, process
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def test_separate_web_process_restart_keeps_one_worker_and_one_effect(self):
        from job_store import JobStore
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write()], initial_delay=.7) as (endpoint, requests):
            root = Path(directory).resolve()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            store = None
            job_id = None
            try:
                with self.server(root, endpoint, port) as (request, first):
                    job_id = request('/api/tasks', {'message': 'Dosyayı bir kez oluştur.',
                        'expected_files': {'out.txt': 'Merhaba Barış'}, 'budget_seconds': 30}, 'real-restart')['task_id']
                    store = JobStore(root / '.baris_runtime' / 'jobs.sqlite3')
                    deadline = time.monotonic() + 5
                    while not requests and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertEqual(len(requests), 1)
                    first_pid = first.pid
                    # A hard web-process crash must leave the task worker alive.
                    first.kill()
                    first.wait(timeout=3)
                with self.server(root, endpoint, port) as (request, second):
                    self.assertNotEqual(first_pid, second.pid)
                    deadline = time.monotonic() + 8
                    while True:
                        job = request('/api/tasks/' + job_id)
                        if job['result']:
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError('Bağımsız sunucu yeniden açıldıktan sonra görev bitmedi.')
                        time.sleep(.03)
                    self.assertEqual(job['status'], 'VERIFIED', job)
                    self.assertEqual(store.get(job_id)['attempts'], 1)
                    self.assertEqual(len(requests), 2)
                    self.assertEqual((root / 'out.txt').read_bytes(), 'Merhaba Barış'.encode())
            finally:
                if store is not None and job_id:
                    store.request_cancel(job_id)
                    deadline = time.monotonic() + 4
                    while store.get(job_id)['result'] is None and time.monotonic() < deadline:
                        time.sleep(.03)

    def test_real_http_server_worker_and_independent_disk_read(self):
        source = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write()]) as (endpoint, requests):
            root = Path(directory).resolve()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            base = 'http://127.0.0.1:' + str(port)
            request = http_client(base)
            environment = dict(os.environ, BARIS_WORKSPACE=str(root), BARIS_OLLAMA_CHAT_URL=endpoint)
            task_id = None
            with (root / 'http-server.log').open('wb') as log:
                server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'durable_api:app', '--host', '127.0.0.1',
                    '--port', str(port)], cwd=source, env=environment, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 10
                    while True:
                        if server.poll() is not None:
                            self.fail((root / 'http-server.log').read_text())
                        try:
                            info = request('/api/engine_info')
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError('HTTP sunucusu hazır olmadı.')
                            time.sleep(.05)
                    self.assertEqual(info['workspace'], str(root))
                    self.assertEqual(info['build'], 'local-ui-v10')
                    self.assertFalse(info['os_sandbox'])
                    submitted = request('/api/tasks', {'message': 'out.txt içine Merhaba Barış yaz.',
                        'expected_files': {'out.txt': 'Merhaba Barış'}, 'budget_seconds': 30}, 'tcp-smoke')
                    task_id = submitted['task_id']
                    deadline = time.monotonic() + 15
                    while True:
                        job = request('/api/tasks/' + task_id)
                        if job.get('result'):
                            break
                        if time.monotonic() >= deadline:
                            raise TimeoutError('HTTP görevi sonlanmadı.')
                        time.sleep(.05)
                    self.assertEqual(job['status'], 'VERIFIED', job)
                    self.assertEqual(job['result']['verification_scope'], 'exact_files')
                    self.assertEqual((root / 'out.txt').read_bytes(), 'Merhaba Barış'.encode())
                    self.assertEqual(len(requests), 2)
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    invalid = urllib.request.Request(base + '/api/engine_info', headers={'Host': 'evil.example'})
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(invalid, timeout=2)
                    self.assertEqual(error.exception.code, 400)
                finally:
                    try:
                        if task_id and server.poll() is None:
                            request('/api/tasks/' + task_id + '/cancel', {})
                    except OSError:
                        pass
                    if server.poll() is None:
                        server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(server.pid, signal.SIGKILL)
                        server.wait(timeout=2)


if __name__ == '__main__':
    unittest.main()
