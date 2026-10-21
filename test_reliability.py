"""Fault-injection regression tests, independent of model quality."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import durable_api
from job_store import JobStore
from task_tools import TaskTools
from test_durable_runtime import PLAN, fake_ollama


class ReliabilityTests(unittest.TestCase):
    @contextmanager
    def workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=JobStore(root/'jobs.db')
            yield root,store

    def test_slow_profile_reduces_future_action_size(self):
        from task_worker import run_job
        requests=[]
        with self.workspace() as (root,store):
            model='mistral-small-24b-abliterated:latest'
            for _ in range(2):store.record_model_sample(model,8192,15,5,100)
            job=store.submit({'workspace':str(root),'message':'x','budget_seconds':30,
                'expected_files':{'x':'ok'}},'k');store.claim()
            actions=[PLAN,{'name':'tool_write_file','arguments':{'filepath':'x','content':'ok'}}]
            async def generated(request,*args,**kwargs):
                requests.append(request)
                return {'message':{'content':json.dumps(actions.pop(0))}}
            previous=signal.getsignal(signal.SIGTERM)
            try:
                with patch('task_worker.generate',generated):run_job(store,job)
            finally:signal.signal(signal.SIGTERM,previous)
            self.assertEqual(store.get(job)['status'],'VERIFIED')
            variants=requests[-1]['format']['anyOf']
            variant=next(v for v in variants if v['properties']['name']['enum']==['tool_write_file'])
            self.assertEqual(variant['properties']['arguments']['properties']['content']['maxLength'],350)

    def test_model_profile_persists_bounded_observations(self):
        with self.workspace() as (root,store):
            store.record_model_sample('m',8192,10,5,100)
            store.record_model_sample('m',8192,20,10,200)
            profile=JobStore(store.path).model_profile('m')
            self.assertEqual(profile['samples'],2)
            self.assertAlmostEqual(profile['chars_per_second'],6)
            self.assertAlmostEqual(profile['first_seconds'],12)
            store.record_model_sample('m',8192,0,float('nan'),0)
            self.assertEqual(store.model_profile('m')['samples'],2)

    def test_doctor_reports_missing_ollama_without_claiming_success(self):
        from runtime_doctor import inspect_runtime
        with self.workspace() as (root,store):
            def unavailable(*args):raise ConnectionError('offline')
            result=inspect_runtime(root,fetch=unavailable)
            self.assertFalse(result['all_checks_passed'])
            self.assertFalse(result['live_task_completion_verified'])
            self.assertEqual(sum(not x['success'] for x in result['checks']),3)

    def test_doctor_reads_existing_database_without_repair(self):
        from runtime_doctor import inspect_runtime
        with self.workspace() as (root,unused):
            store=JobStore(root/'.baris_runtime'/'jobs.sqlite3');store.submit({},'k')
            def available(url,payload=None):
                return {'version':'test','models':[],'details':{'size':'test'},'capabilities':['completion']}
            result=inspect_runtime(root,fetch=available)
            database=next(c['actual'] for c in result['checks'] if c['name']=='database')
            self.assertEqual(database['integrity'],'ok')
            self.assertEqual(database['counts'],{'QUEUED':1})
            self.assertFalse(result['live_task_completion_verified'])

    def test_cancel_claim_race_never_loses_cancellation(self):
        with self.workspace() as (root,store):
            for i in range(12):
                job=store.submit({'message':'x'},str(i))
                with ThreadPoolExecutor(max_workers=2) as executor:
                    claim=executor.submit(store.claim)
                    cancel=executor.submit(store.request_cancel,job)
                    claim.result();cancel.result()
                row=store.get(job)
                self.assertTrue(row['status']=='CANCELLED' or row['cancel']==1,row)
                if row['status']=='RUNNING':
                    store.finish(job,'FAILED',{'reply':'finish after cancel'})
                self.assertEqual(store.get(job)['status'],'CANCELLED')

    def test_terminal_state_cannot_be_overwritten(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');store.request_cancel(job)
            before=store.get(job)['result']
            store.finish(job,'FAILED',{'reply':'late worker'})
            self.assertEqual(store.get(job)['result'],before)

    def test_cancel_wins_race_with_success(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');store.claim();store.request_cancel(job)
            store.finish(job,'VERIFIED',{'acceptance':{'success':True},'execution_steps':[{'success':True}]})
            row=store.get(job)
            self.assertEqual(row['status'],'CANCELLED')
            self.assertFalse(row['result']['verified'])

    def test_cancelled_job_cannot_start_model(self):
        from task_worker import run_job
        with self.workspace() as (root,store):
            job=store.submit({},'k');store.request_cancel(job)
            with patch('task_worker.generate') as generate:
                run_job(store,job)
                generate.assert_not_called()

    def test_cancel_after_model_response_prevents_tool(self):
        from task_worker import run_job
        with self.workspace() as (root,store):
            job=store.submit({'workspace':str(root),'message':'x','budget_seconds':30},'k');store.claim()
            async def generated(*args,**kwargs):
                store.request_cancel(job)
                return {'message':{'content':json.dumps(PLAN)}}
            previous=signal.getsignal(signal.SIGTERM)
            try:
                with patch('task_worker.generate',generated):
                    run_job(store,job)
            finally:
                signal.signal(signal.SIGTERM,previous)
            row=store.get(job)
            self.assertEqual(row['status'],'CANCELLED')
            self.assertIsNone(row['pending'])
            self.assertEqual(row['result']['execution_steps'],[])

    def test_recovery_keeps_cancel_request(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');store.claim();store.request_cancel(job)
            store.recover(lambda pid:False)
            self.assertEqual(store.get(job)['status'],'CANCELLED')

    def test_uncertain_command_blocks_following_tasks(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');store.claim()
            store.update(job,pending={'name':'tool_run_shell'},child_pid=12345)
            store.recover(lambda pid:False)
            self.assertEqual(store.get(job)['status'],'BLOCKED')
            self.assertEqual(store.get(job)['child_pid'],12345)
            next_job=store.submit({},'next')
            self.assertIsNone(store.claim())
            self.assertEqual(store.get(next_job)['status'],'QUEUED')

    def test_fast_exiting_command_cannot_bypass_output_limit(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');tools=TaskTools(root,store,job)
            def fast_process(*args,**kwargs):
                kwargs['stdout'].write(b'x'*4_000_001)
                return SimpleNamespace(pid=123,returncode=0,poll=lambda:0)
            with patch('task_tools.subprocess.Popen',fast_process):
                result=tools.run_command('python3 -V')
            self.assertFalse(result['success'])
            self.assertTrue(result['output_limit'])
            self.assertEqual(result['exit_code'],0)
            self.assertTrue(result['stdout_truncated'])
            self.assertEqual(len(result['stdout']),16000)

    def test_fsync_failure_leaves_original_and_cleans_temp(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');tools=TaskTools(root,store,job)
            first=tools.execute('tool_write_file',{'filepath':'x','content':'koru'})
            with patch('task_tools.os.fsync',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    tools.execute('tool_append_file',{'filepath':'x','content':'new','expected_sha256':first['sha256']})
            self.assertEqual((root/'x').read_text(),'koru')
            self.assertFalse(any(p.name.startswith('tmp') for p in root.iterdir()))

    def test_external_edit_during_append_is_preserved(self):
        with self.workspace() as (root,store):
            job=store.submit({},'k');tools=TaskTools(root,store,job)
            first=tools.execute('tool_write_file',{'filepath':'x','content':'old'})
            def intervening_edit(fd):
                (root/'x').write_text('external')
            with patch('task_tools.os.fsync',intervening_edit):
                with self.assertRaises(ValueError):
                    tools.execute('tool_append_file',{'filepath':'x','content':'new','expected_sha256':first['sha256']})
            self.assertEqual((root/'x').read_text(),'external')

    def test_api_rejects_disk_full_and_outside_acceptance(self):
        with self.workspace() as (root,store),patch.object(durable_api,'WORKSPACE',root):
            with TestClient(durable_api.app) as client:
                with patch('durable_api.shutil.disk_usage',return_value=SimpleNamespace(free=1)):
                    self.assertEqual(client.post('/api/tasks',json={'message':'x'}).status_code,507)
                for path in ('../outside','.baris_runtime/secrets','.git/config'):
                    response=client.post('/api/tasks',json={'message':'x','expected_files':{path:'x'}})
                    self.assertEqual(response.status_code,422,response.text)

    def test_api_rejects_dead_scheduler_and_storage_failure(self):
        with self.workspace() as (root,store),patch.object(durable_api,'WORKSPACE',root):
            with TestClient(durable_api.app) as client:
                engine=client.app.state.service
                with patch.object(engine,'loop_task',SimpleNamespace(done=lambda:True)):
                    self.assertEqual(client.post('/api/tasks',json={'message':'x'}).status_code,503)
                    self.assertFalse(client.get('/api/engine_info').json()['scheduler_alive'])
                with patch.object(engine.store,'submit',side_effect=sqlite3.OperationalError('disk full')):
                    self.assertEqual(client.post('/api/tasks',json={'message':'x'}).status_code,503)


if __name__=='__main__':
    unittest.main()
