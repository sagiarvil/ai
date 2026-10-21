"""Crash/restart tests use real locks and processes; model output is scripted."""
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from job_store import JobStore, OwnershipLost
from execution_ownership import WorkerStore, execution_lock
from task_service import TaskService


class OwnershipTests(unittest.TestCase):
    @contextmanager
    def workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            yield root, JobStore(root / '.baris_runtime' / 'jobs.sqlite3')

    def test_terminal_job_rejects_late_checkpoint_and_pending_updates(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'terminal')
            store.claim()
            store.finish(job, 'FAILED', {'reply': 'Bitti'})
            before = store.get(job)
            with self.assertRaises(RuntimeError):
                store.update(job, pending={'name': 'tool_run_shell'}, checkpoint={'late': True})
            after = store.get(job)
            self.assertEqual(after['pending'], before['pending'])
            self.assertEqual(after['checkpoint'], before['checkpoint'])

    def test_unreadable_worker_identity_is_unknown_instead_of_dead(self):
        with self.workspace() as (root, store):
            service = TaskService(root)
            with patch('task_service.alive', return_value=True), \
                 patch('task_service.Path.read_bytes', side_effect=PermissionError('denied')), \
                 patch('task_service.subprocess.check_output', side_effect=PermissionError('denied')):
                self.assertIsNone(service.worker_alive(987654))

    def test_unknown_legacy_worker_is_not_replayed_or_signalled(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'legacy')
            store.claim()
            with store.connection() as db:
                db.execute('UPDATE jobs SET lease=NULL,worker_pid=987654 WHERE id=?', (job,))
            store.recover(lambda pid: None)
            self.assertEqual(store.get(job)['status'], 'RUNNING')
            self.assertIsNone(store.claim())

    def test_legacy_registration_uncertainty_blocks_following_tasks(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'legacy-window')
            store.claim()
            with store.connection() as db:
                db.execute('UPDATE jobs SET lease=NULL,worker_pid=NULL WHERE id=?', (job,))
            store.recover(lambda pid: False)
            self.assertEqual(store.get(job)['status'], 'BLOCKED')
            store.submit({}, 'next')
            self.assertTrue(store.queue_state()['blocked'])
            self.assertIsNone(store.claim())

    def test_previous_claim_cannot_write_events_checkpoint_or_result(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'fence')
            store.claim()
            old = WorkerStore(store, job, store.get(job)['lease'])
            store.recover(lambda pid: False)
            self.assertEqual(store.claim(), job)
            current = store.get(job)
            self.assertNotEqual(current['lease'], old.lease)
            for write in (lambda: old.update(job, pending={'name': 'tool_run_shell'}),
                          lambda: old.event(job, 'LATE', {'message': 'eski çalışan'}),
                          lambda: old.finish(job, 'FAILED', {'reply': 'eski çalışan'})):
                with self.assertRaises(OwnershipLost):
                    write()
            self.assertEqual(store.get(job)['lease'], current['lease'])
            self.assertEqual(store.get(job)['status'], 'RUNNING')
            self.assertIsNone(store.get(job)['pending'])
            self.assertFalse(any(event['kind'] == 'LATE' for event in store.get(job)['events']))

    def test_old_database_migrates_without_losing_records(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE jobs(id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,
                    request_hash TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,
                    created REAL NOT NULL,updated REAL NOT NULL,worker_pid INTEGER,child_pid INTEGER,
                    cancel INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,used REAL DEFAULT 0,
                    checkpoint TEXT,pending TEXT,result TEXT)''')
                db.execute("INSERT INTO jobs(id,request_key,request_hash,payload,status,created,updated) VALUES('old','old','h','{}','FAILED',1,1)")
            store = JobStore(path)
            self.assertEqual(store.get('old')['status'], 'FAILED')
            self.assertIsNone(store.get('old')['lease'])
            self.assertTrue(store.submit({}, 'new'))

    def test_scheduler_cannot_recover_during_spawn_registration_window(self):
        with self.workspace() as (root, store):
            job = store.submit({}, 'launch-window')
            store.claim()
            lock = (root / '.baris_runtime' / 'execution.lock').open('a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            async def restart():
                service = TaskService(root)
                await service.start()
                try:
                    await asyncio.sleep(.3)
                    self.assertEqual(store.get(job)['status'], 'RUNNING')
                    self.assertEqual(store.get(job)['attempts'], 1)
                finally:
                    await service.close()
            try:
                store.recover(lambda pid: False)
                self.assertEqual(store.get(job)['status'], 'RUNNING')
                asyncio.run(restart())
            finally:
                lock.close()

    def test_duplicate_real_worker_cannot_repeat_side_effect(self):
        with self.workspace() as (root, store):
            job = store.submit({'workspace': str(root), 'message': 'Kayıt oluştur.',
                                'budget_seconds': 30}, 'duplicate-worker')
            store.claim()
            # Each child has its own model fixture. Both would execute the same
            # append if ownership depended solely on RUNNING status.
            helper = root / 'worker_fixture.py'
            helper.write_text('''import asyncio,json,sys,time
from pathlib import Path
from unittest.mock import patch
from job_store import JobStore
from task_worker import run_job
root=Path(sys.argv[3]); count=0
async def model(*args,**kwargs):
 global count
 count+=1
 if count==1:
  with (root/'entered').open('a') as f:f.write('x')
  deadline=time.monotonic()+8
  while not (root/'release').exists():
   if time.monotonic()>deadline:raise TimeoutError('Fixture gate')
   await asyncio.sleep(.02)
  action={'name':'tool_plan_steps','arguments':{'steps':['Kayıt oluştur']}}
 elif count==2:
  action={'name':'tool_run_shell','arguments':{'command':"python3 -c \\\"from pathlib import Path;f=Path('effects').open('a');f.write('x');f.close()\\\""}}
 else:action={'name':'__finish__','arguments':{}}
 return {'message':{'content':json.dumps(action)}}
with patch('task_worker.generate',model):run_job(JobStore(sys.argv[1]),sys.argv[2])
''', encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))
            children = []
            try:
                children.append(subprocess.Popen([sys.executable, str(helper), store.path, job, str(root)],
                                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                deadline = time.monotonic() + 5
                while not (root / 'entered').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((root / 'entered').exists())
                children.append(subprocess.Popen([sys.executable, str(helper), store.path, job, str(root)],
                                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                time.sleep(.4)
                (root / 'release').touch()
                for child in children:
                    stdout, stderr = child.communicate(timeout=10)
                    self.assertEqual(child.returncode, 0, stderr.decode())
                self.assertEqual((root / 'entered').read_text(), 'x')
                self.assertEqual((root / 'effects').read_text(), 'x')
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=5)

    def test_inherited_lock_survives_parent_crash_before_worker_registration(self):
        with self.workspace() as (root, store):
            job = store.submit({'workspace': str(root), 'message': 'Dosya yaz.',
                                'budget_seconds': 30, 'expected_files': {'done': 'ok'}}, 'handoff')
            helper = root / 'handoff.py'
            helper.write_text('''import json,os,subprocess,sys,time
from pathlib import Path
from job_store import JobStore
from execution_ownership import execution_lock
store=JobStore(sys.argv[1]);job=sys.argv[2];root=Path(store.path).parent
if sys.argv[3]=='parent':
 with execution_lock(store) as guard:
  assert store.claim()==job
  lease=store.get(job)['lease']
  child=subprocess.Popen([sys.executable,__file__,store.path,job,'child',lease,str(guard.fileno())],
      pass_fds=(guard.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
      start_new_session=True)
  (root/'spawned').write_text(str(child.pid))
  os._exit(77)
else:
 # The parent dies while the inherited descriptor exists but worker_pid is NULL.
 time.sleep(1)
 from task_worker import run_job
 from unittest.mock import patch
 count=0
 async def model(*args,**kwargs):
  global count
  count+=1
  action=({'name':'tool_plan_steps','arguments':{'steps':['Dosyayı yaz']}} if count==1 else
          {'name':'tool_write_file','arguments':{'filepath':'done','content':'ok'}})
  return {'message':{'content':json.dumps(action)}}
 with patch('task_worker.generate',model):run_job(store,job,sys.argv[4],int(sys.argv[5]))
''', encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent))
            parent = subprocess.run([sys.executable, str(helper), store.path, job, 'parent'],
                                    env=env, capture_output=True, timeout=5)
            self.assertEqual(parent.returncode, 77, parent.stderr.decode())
            self.assertIsNone(store.get(job)['worker_pid'])
            with execution_lock(store) as guard:
                self.assertIsNone(guard, 'The parent must not unlock the inherited worker descriptor')
            child_pid = int((Path(store.path).parent / 'spawned').read_text())
            async def restarted():
                service = TaskService(root)
                await service.start()
                try:
                    deadline = time.monotonic() + 5
                    while not store.get(job)['result'] and time.monotonic() < deadline:
                        await asyncio.sleep(.03)
                    result = store.get(job)
                    self.assertEqual(result['status'], 'VERIFIED', result)
                    self.assertEqual(result['attempts'], 1)
                    self.assertEqual((root / 'done').read_bytes(), b'ok')
                finally:
                    await service.close()
            try:
                asyncio.run(restarted())
            finally:
                # We own this fixture child even though it has been orphaned.
                try:
                    if store.get(job)['result'] is None:
                        os.kill(child_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

    def test_cancel_interrupts_silent_model_without_pid_identity_or_signal(self):
        from fastapi.testclient import TestClient
        import durable_api
        from test_durable_runtime import fake_ollama, PLAN
        with self.workspace() as (root, store), fake_ollama([PLAN], initial_delay=6) as (endpoint, requests):
            with patch.object(durable_api, 'WORKSPACE', root), patch.dict(os.environ, {'BARIS_OLLAMA_CHAT_URL': endpoint}), \
                 patch.object(TaskService, 'worker_alive', return_value=None):
                with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                    response = client.post('/api/tasks', json={'message': 'Bekleyen modeli iptal et.'})
                    self.assertEqual(response.status_code, 202)
                    job = response.json()['task_id']
                    deadline = time.monotonic() + 5
                    while not requests and time.monotonic() < deadline:
                        time.sleep(.03)
                    self.assertEqual(len(requests), 1)
                    started = time.monotonic()
                    client.post('/api/tasks/' + job + '/cancel')
                    deadline = time.monotonic() + 4
                    while store.get(job)['result'] is None and time.monotonic() < deadline:
                        time.sleep(.03)
                    row = store.get(job)
                    self.assertEqual(row['status'], 'CANCELLED', row)
                    self.assertLess(time.monotonic() - started, 4)
                    self.assertEqual(row['result']['execution_steps'], [])


if __name__ == '__main__':
    unittest.main()
