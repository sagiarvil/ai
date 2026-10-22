"""Real HTTP/SQLite/process/file tests with a scripted Ollama stand-in, not model accuracy."""
import asyncio
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import durable_api
from job_store import JobStore
from task_tools import TaskTools


@contextmanager
def fake_ollama(actions, delay=0.02, reason="stop", initial_delay=0):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            index = len(requests)
            requests.append(request)
            action = actions[min(index, len(actions) - 1)]
            time.sleep(initial_delay)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            try:
                raw = json.dumps(action, ensure_ascii=False)
                midpoint = len(raw) // 2
                self.wfile.write((json.dumps({"message": {"content": raw[:midpoint]}, "done": False}) + "\n").encode())
                self.wfile.flush()
                time.sleep(delay)
                self.wfile.write((json.dumps({"message": {"content": raw[midpoint:]}, "done": True,
                                             "done_reason": reason, "eval_count": 20}) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/api/chat" % server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()


PLAN = {"name": "tool_plan_steps", "arguments": {"steps": ["Veriyi oluştur", "İşlemi doğrula"]}}


def write(content="Merhaba Barış"):
    return {"name": "tool_write_file", "arguments": {"filepath": "out.txt", "content": content}}


def wait_job(client, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get("/api/tasks/" + job_id).json()
        if job["result"]:
            return job
        time.sleep(0.03)
    raise AssertionError("Test görevi sonlanmadı: " + str(job))


class DurableTests(unittest.TestCase):
    @contextmanager
    def client(self, directory, endpoint):
        with patch.object(durable_api, "WORKSPACE", Path(directory)), patch.dict(
            os.environ, {"BARIS_OLLAMA_CHAT_URL": endpoint}
        ):
            with TestClient(durable_api.app, base_url="http://127.0.0.1") as client:
                yield client

    def submit(self, client, message="out.txt içine Merhaba Barış yaz.", key="test"):
        response = client.post("/api/tasks", json={
            "message": message, "expected_files": {"out.txt": "Merhaba Barış"}},
            headers={"Idempotency-Key": key})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["task_id"]

    def test_create_cannot_reset_accumulated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory)/'jobs.db')
            task = store.submit({}, 'create-only')
            tools = TaskTools(directory, store, task)
            first = tools.execute('tool_write_file', {'filepath':'analiz.py','content':'a'*700})
            tools.execute('tool_append_file', {'filepath':'analiz.py','content':'b'*700,'expected_sha256':first['sha256']})
            before = (Path(directory)/'analiz.py').read_bytes()
            with self.assertRaises(ValueError):
                tools.execute('tool_write_file', {'filepath':'analiz.py','content':'reset'})
            self.assertEqual((Path(directory)/'analiz.py').read_bytes(),before)
            self.assertEqual(len(before),1400)

    def test_concurrent_creator_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            store=JobStore(Path(directory)/'jobs.db');task=store.submit({},'race')
            tools=TaskTools(directory,store,task)
            original_link=os.link
            def competing_create(source, target):
                Path(target).write_text('başka yazıcının verisi',encoding='utf-8')
                original_link(source,target)
            with patch('task_tools.os.link',competing_create):
                with self.assertRaises(FileExistsError):
                    tools.execute('tool_write_file',{'filepath':'x','content':'silinmemeli'})
            self.assertEqual((Path(directory)/'x').read_text(),'başka yazıcının verisi')
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir() if p.name.startswith('tmp')),[])

    def test_patch_requires_current_hash_and_unique_target(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory)/'jobs.db')
            task = store.submit({}, 'patch')
            tools = TaskTools(directory, store, task)
            initial = tools.execute('tool_write_file', {'filepath':'x','content':'start|bad|end end'})
            args = {'filepath':'x','old_text':'bad','new_text':'good','expected_sha256':initial['sha256']}
            updated = tools.execute('tool_patch_file',args)
            self.assertEqual((Path(directory)/'x').read_text(),'start|good|end end')
            for old, digest in [('good',initial['sha256']),('end',updated['sha256']),('',updated['sha256'])]:
                with self.assertRaises(ValueError):
                    tools.execute('tool_patch_file',dict(args,old_text=old,expected_sha256=digest))
            self.assertEqual((Path(directory)/'x').read_text(),'start|good|end end')

    def test_existing_directory_is_rejected_without_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory)/'jobs.db');task = store.submit({}, 'directory')
            tools = TaskTools(directory,store,task)
            tools.execute('tool_make_directory',{'filepath':'old'})
            (Path(directory)/'old'/'sentinel').write_text('koru')
            with self.assertRaises(FileExistsError):
                tools.execute('tool_make_directory',{'filepath':'old'})
            self.assertEqual((Path(directory)/'old'/'sentinel').read_text(),'koru')

    def test_model_overwrite_is_rejected_then_append_recovers(self):
        def append(content, before):
            return {'name':'tool_append_file','arguments':{'filepath':'out.txt','content':content,
                'expected_sha256':hashlib.sha256(before.encode()).hexdigest()}}
        actions = [PLAN,write('a'),append('b','a'),write('RESET'),append('c','ab')]
        with tempfile.TemporaryDirectory() as directory, fake_ollama(actions) as (url, requests):
            with self.client(directory,url) as client:
                job_id=client.post('/api/tasks',json={'message':'abc oluştur','expected_files':{'out.txt':'abc'}}).json()['task_id']
                result=wait_job(client,job_id)['result']
                self.assertEqual(result['status'],'VERIFIED',result)
                self.assertEqual((Path(directory)/'out.txt').read_text(),'abc')
                self.assertEqual([x['success'] for x in result['execution_steps']],[True,True,False,True])
                self.assertIn('üzerine yazma engellendi',json.dumps(requests[-1],ensure_ascii=False))

    def test_first_response_can_exceed_stream_idle_while_heartbeat_runs(self):
        from task_worker import _generate_unlocked
        ticks=[]
        with tempfile.TemporaryDirectory() as directory, fake_ollama([write()],initial_delay=0.18,delay=0.01) as (url,_):
            store=JobStore(Path(directory)/'jobs.db');task=store.submit({},'slow-start')
            with patch.dict(os.environ,{'BARIS_OLLAMA_CHAT_URL':url}), patch('task_worker.STREAM_IDLE_SECONDS',0.05), patch('task_worker.HEARTBEAT_SECONDS',0.03):
                result=asyncio.run(_generate_unlocked({'messages':[]},store,task,1,lambda:ticks.append(1)))
            self.assertEqual(json.loads(result['message']['content'])['name'],'tool_write_file')
            self.assertGreaterEqual(len(ticks),2)

    def test_stream_idle_is_still_bounded_after_first_response(self):
        from task_worker import _generate_unlocked,ModelCallError
        with tempfile.TemporaryDirectory() as directory, fake_ollama([write()],delay=0.3) as (url,_):
            store=JobStore(Path(directory)/'jobs.db');task=store.submit({},'idle')
            with patch.dict(os.environ,{'BARIS_OLLAMA_CHAT_URL':url}), patch('task_worker.STREAM_IDLE_SECONDS',0.05):
                with self.assertRaises(ModelCallError) as error:
                    asyncio.run(_generate_unlocked({'messages':[]},store,task,1))
            self.assertEqual(error.exception.detail['error_type'],'ModelIdleTimeout')
            self.assertGreater(error.exception.detail['characters'],0)

    def test_chunk_limit_enforced_before_disk_change(self):
        from structured_actions import parse_action
        from task_tools import TOOLS
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({}, "limits")
            tools = TaskTools(directory, store, task)
            tools.execute("tool_write_file", {"filepath": "x", "content": "ğ" * 700})
            before = (Path(directory) / "x").read_bytes()
            oversized = {"filepath": "x", "content": "ğ" * 701}
            with self.assertRaises(ValueError):
                tools.execute("tool_write_file", oversized)
            with self.assertRaises(ValueError):
                parse_action({"message": {"content": json.dumps({"name": "tool_write_file", "arguments": oversized})}}, [], TOOLS)
            self.assertEqual((Path(directory) / "x").read_bytes(), before)
            tools.chunk_limit = 350
            with self.assertRaises(ValueError):
                tools.execute("tool_write_file", {"filepath": "x", "content": "x" * 351})
            self.assertEqual((Path(directory) / "x").read_bytes(), before)

    def test_stream_deadline_reports_partial_progress_without_execution(self):
        from task_worker import _generate_unlocked, ModelCallError
        with tempfile.TemporaryDirectory() as directory, fake_ollama([write()], delay=1) as (url, _):
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({}, "deadline")
            with patch.dict(os.environ, {"BARIS_OLLAMA_CHAT_URL": url}):
                with self.assertRaises(ModelCallError) as raised:
                    asyncio.run(_generate_unlocked({"messages": []}, store, task, 0.3))
            detail = raised.exception.detail
            self.assertEqual(detail['error_type'], 'TimeoutError')
            self.assertGreater(detail['characters'], 0)
            self.assertGreaterEqual(detail['elapsed_seconds'], 0.25)
            self.assertIn('Kısmi işlem çalıştırılmadı', detail['message'])
            self.assertFalse((Path(directory) / 'out.txt').exists())

    def exercise_retry(self, errors):
        import signal
        from task_worker import run_job, ModelCallError
        from task_tools import TOOLS
        requests = []
        scripted = [PLAN] + [ModelCallError({'message':'Model süre sınırı; kısmi çıktı atıldı.', 'error_type':'TimeoutError'})] * errors + [write()]
        async def generation(request, *args, **kwargs):
            requests.append(request)
            action = scripted.pop(0)
            if isinstance(action, Exception):
                raise action
            return {'message': {'content': json.dumps(action)}}
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.db')
            job_id = store.submit({'workspace': directory, 'message': 'Dosyayı oluştur',
                'budget_seconds': 30, 'expected_files': {'out.txt':'Merhaba Barış'}}, 'retry')
            store.claim()
            previous = signal.getsignal(signal.SIGTERM)
            try:
                with patch('task_worker.generate', generation):
                    run_job(store, job_id)
            finally:
                signal.signal(signal.SIGTERM, previous)
            job = store.get(job_id)
            self.assertEqual(job['status'], 'VERIFIED' if errors == 1 else 'FAILED')
            self.assertEqual(len(requests), 3)
            retry_schema = requests[-1]['format']['anyOf']
            content_limits = [v['properties']['arguments']['properties']['content']['maxLength']
                for v in retry_schema if 'content' in v['properties']['arguments']['properties']]
            self.assertEqual(content_limits, [350, 350])
            self.assertEqual(sum(e['kind']=='MODEL_RETRY' for e in job['events']), 1)
            self.assertEqual((Path(directory)/'out.txt').exists(), errors == 1)
            # A retry must not mutate the shared schema for later jobs.
            self.assertEqual(TOOLS[3]['function']['parameters']['properties']['content']['maxLength'], 700)

    def test_deadline_retries_once_with_smaller_schema_and_recovers(self):
        self.exercise_retry(1)

    def test_second_model_failure_stops_without_side_effect(self):
        self.exercise_retry(2)

    def test_latest_event_is_independent_of_page_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.db')
            task = store.submit({}, 'pagination')
            for index in range(249):
                store.event(task, 'MODEL_PROGRESS', {'message': str(index)})
            store.finish(task, 'FAILED', {'reply': 'Son hata'})
            first = store.public(task)
            self.assertEqual(len(first['events']), 100)
            self.assertEqual(first['latest_event']['kind'], 'FAILED')
            self.assertTrue(first['has_more'])
            second = store.public(task, first['next_after'])
            third = store.public(task, second['next_after'])
            self.assertEqual(third['events'][-1], third['latest_event'])
            self.assertFalse(third['has_more'])

    def test_worker_launch_failure_is_recorded(self):
        from task_service import TaskService
        async def exercise(directory):
            service = TaskService(directory)
            job_id = service.store.submit({"message": "deneme"}, "launch-failure")
            with patch("task_service.subprocess.Popen", side_effect=OSError("test başlatma hatası")):
                await service.start()
                try:
                    for _ in range(50):
                        job = service.store.get(job_id)
                        if job["result"]:
                            break
                        await asyncio.sleep(0.02)
                    self.assertEqual(job["status"], "FAILED")
                    self.assertIn("başlatılamadı", job["result"]["reply"])
                    self.assertFalse(service.loop_task.done())
                finally:
                    await service.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

    def test_real_write_repair_and_independent_acceptance(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write("Merhaba Barış.\n"), {"name":"tool_patch_file", "arguments": {"filepath":"out.txt", "old_text":".\n", "new_text":"", "expected_sha256":hashlib.sha256("Merhaba Barış.\n".encode()).hexdigest()}}]) as (url, requests):
            with self.client(directory, url) as client:
                started = time.monotonic()
                job_id = self.submit(client)
                self.assertLess(time.monotonic() - started, 0.5)
                result = wait_job(client, job_id)["result"]
                self.assertEqual(result["status"], "VERIFIED")
                self.assertEqual((Path(directory) / "out.txt").read_bytes(), "Merhaba Barış".encode())
                self.assertEqual(len(requests), 3)
                self.assertIn("first_difference", json.dumps(requests[-1]))
                self.assertTrue(requests[0]["stream"])

    def test_idempotency_conflict_and_single_submission(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write()]) as (url, _):
            with self.client(directory, url) as client:
                job_id = self.submit(client)
                self.assertEqual(self.submit(client), job_id)
                response = client.post("/api/tasks", json={"message": "different"},
                                       headers={"Idempotency-Key": "test"})
                self.assertEqual(response.status_code, 409)
                wait_job(client, job_id)

    def test_truncated_json_never_executes(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([write()], reason="length") as (url, _):
            with self.client(directory, url) as client:
                result = wait_job(client, self.submit(client))["result"]
                self.assertEqual(result["status"], "FAILED")
                self.assertFalse((Path(directory) / "out.txt").exists())

    def test_cancel_during_model_generation(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN], delay=5) as (url, _):
            with self.client(directory, url) as client:
                job_id = self.submit(client)
                time.sleep(0.4)
                client.post("/api/tasks/" + job_id + "/cancel")
                result = wait_job(client, job_id)["result"]
                self.assertEqual(result["status"], "CANCELLED")
                self.assertFalse((Path(directory) / "out.txt").exists())

    def test_cross_origin_and_oversized_requests_rejected(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN]) as (url, _):
            with self.client(directory, url) as client:
                self.assertEqual(client.post("/api/tasks", json={"message": "x"},
                    headers={"Origin": "https://untrusted.example"}).status_code, 403)
                self.assertEqual(client.post("/api/tasks", json={"message": "x" * 30001}).status_code, 422)

    def test_queue_serializes_workers(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write()], delay=0.1) as (url, _):
            with self.client(directory, url) as client:
                first = self.submit(client, key="one")
                second = self.submit(client, key="two")
                wait_job(client, first)
                wait_job(client, second)
                store = client.app.state.service.store
                with store.connection() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE status='RUNNING'").fetchone()[0], 0)

    def test_recovery_does_not_repeat_uncertain_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({"message": "test"}, "k")
            store.claim()
            store.update(task, pending={"name": "payment", "args": {}})
            store.recover(lambda pid: False)
            self.assertEqual(store.get(task)["status"], "BLOCKED")
            self.assertIsNone(store.claim())

    def test_safe_checkpoint_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({"message": "test"}, "k")
            store.claim()
            store.update(task, checkpoint={"stage": 2}, pending=None)
            store.recover(lambda pid: False)
            self.assertEqual(store.get(task)["status"], "QUEUED")
            self.assertEqual(store.get(task)["checkpoint"], {"stage": 2})

    def test_shell_timeout_kills_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({}, "k")
            tools = TaskTools(directory, store, task, tool_seconds=0.1)
            script = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
                      "\"import time,pathlib;time.sleep(0.5);pathlib.Path('escaped').write_text('bad')\"]);time.sleep(10)")
            result = tools.execute("tool_run_shell", {"command": "python3 -c " + shlex.quote(script)})
            self.assertEqual(result["exit_code"], 124)
            time.sleep(0.7)
            self.assertFalse((Path(directory) / "escaped").exists())

    def test_financial_stress_executes_real_program_and_failure_cases(self):
        data = 'id;tarih;tur;tutar;durum\nT001;2026-10-01;satis;1000.00;onay\nT002;2026-10-02;satis;2500.50;onay\nT003;2026-10-03;iade;-200.25;onay\nT004;2026-10-04;gider;300.00;onay\nT005;2026-10-05;satis;900.00;iptal\nT006;2026-10-06;satis;0.00;onay\nT007;2026-10-07;satis;;onay\nT008;2026-10-08;satis;abc;onay\nT009;2026-10-09;satis;NaN;onay\nT010;2026-10-10;gider;-50.00;onay\nT011;2026-10-11;iade;75.00;onay\nT012;2026-10-12;bilinmeyen;20.00;onay\nT013;2026-02-30;satis;100.00;onay\nT002;2026-10-02;satis;9999.00;onay\nT014;2026-10-14;satis;1.005;onay\nT015;2026-10-15;satis;Infinity;onay\nT016;2026-10-16;satis;125.00;bekliyor\nT017;2026-10-17;gider;0.10;onay\nT018;2026-10-18;satis; 40.00 ;onay\nT019;2026-10-19;satis;10.00;onay\n'
        program = "import csv,json,sys,os,tempfile\nfrom pathlib import Path\nfrom decimal import Decimal,InvalidOperation\nfrom datetime import date\n\ndef main():\n source,target=map(Path,sys.argv[1:3])\n if source.resolve()==target.resolve():raise ValueError('Girdi ve çıktı aynı olamaz')\n totals={k:Decimal('0') for k in ('satis','iade','gider')}\n r=dict(toplam_veri_satiri=0,gecerli_onayli_satir=0,iptal_satir=0,gecersiz_satir=0,yinelenen_satir=0)\n seen=set();errors=[]\n with source.open(encoding='utf-8',newline='') as f:\n  reader=csv.DictReader(f,delimiter=';')\n  if reader.fieldnames!=['id','tarih','tur','tutar','durum']:raise ValueError('CSV başlığı geçersiz')\n  for line,row in enumerate(reader,2):\n   r['toplam_veri_satiri']+=1\n   if row['id'] in seen:\n    r['yinelenen_satir']+=1;errors.append([line,'yinelenen']);continue\n   seen.add(row['id'])\n   try:\n    if date.fromisoformat(row['tarih']).isoformat()!=row['tarih']:raise ValueError()\n    kind=row['tur'];status=row['durum'];amount=Decimal(row['tutar'].strip())\n    if kind not in totals or status not in ('onay','iptal'):raise ValueError()\n    if not amount.is_finite() or amount.as_tuple().exponent < -2:raise ValueError()\n    if (kind=='iade' and amount>=0) or (kind!='iade' and amount<0):raise ValueError()\n   except (ValueError,InvalidOperation):\n    r['gecersiz_satir']+=1;errors.append([line,'geçersiz']);continue\n   if status=='iptal':r['iptal_satir']+=1;continue\n   r['gecerli_onayli_satir']+=1;totals[kind]+=amount\n for k,v in totals.items():r[k+'_toplami']=format(v,'.2f')\n r['net_tutar']=format(totals['satis']+totals['iade']-totals['gider'],'.2f')\n with tempfile.NamedTemporaryFile('w',dir=target.parent,delete=False,encoding='utf-8') as f:\n  json.dump(r,f,ensure_ascii=False,sort_keys=True);tmp=f.name\n os.replace(tmp,target)\n print(json.dumps(errors,ensure_ascii=False))\ntry:main()\nexcept Exception as e:print('İşlem hatası:',e,file=sys.stderr);sys.exit(1)\n"
        harness = "import subprocess,sys,json,hashlib\nfrom decimal import Decimal\nfrom pathlib import Path\nreport=[]\ndef run(src,out,success):\n p=subprocess.run([sys.executable,'analiz.py',src,out],capture_output=True,text=True)\n assert (p.returncode==0)==success,(src,p.stderr)\n report.append(dict(command=p.args,exit_code=p.returncode,stderr=p.stderr))\ndef digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()\nrun('islemler.csv','sonuc.json',True)\nfirst=digest('sonuc.json')\nrun('islemler.csv','sonuc.json',True)\nassert first==digest('sonuc.json')\nrun('yok.csv','sonuc.json',False)\nassert first==digest('sonuc.json')\nPath('bozuk.csv').write_text('yanlis;baslik\\n',encoding='utf-8')\nrun('bozuk.csv','sonuc.json',False)\nassert first==digest('sonuc.json')\nPath('bos.csv').write_text('id;tarih;tur;tutar;durum\\n',encoding='utf-8')\nrun('bos.csv','bos.json',True)\nempty=json.loads(Path('bos.json').read_text())\nassert all(Decimal(str(v))==0 for v in empty.values())\nbefore=digest('islemler.csv')\nrun('islemler.csv','islemler.csv',False)\nassert before==digest('islemler.csv')\nrun('islemler.csv','sonuc.json',True)\nassert first==digest('sonuc.json')\nPath('test_raporu.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')\n"
        expected = {'toplam_veri_satiri': 20, 'gecerli_onayli_satir': 8, 'iptal_satir': 1, 'gecersiz_satir': 10, 'yinelenen_satir': 1, 'satis_toplami': '3550.50', 'iade_toplami': '-200.25', 'gider_toplami': '300.10', 'net_tutar': '3050.15'}
        def file_actions(path, content):
            actions = []
            for start in range(0, len(content), 700):
                arguments = {"filepath": path, "content": content[start:start+700]}
                if start:
                    arguments['expected_sha256'] = hashlib.sha256(content[:start].encode()).hexdigest()
                actions.append({"name": "tool_append_file" if start else "tool_write_file", "arguments": arguments})
            return actions
        actions = [PLAN, *file_actions('islemler.csv',data), *file_actions('analiz.py',program),
                   *file_actions('kontrol.py',harness),
                   {"name":"tool_run_shell","arguments":{"command":"python3 kontrol.py"}}]
        with tempfile.TemporaryDirectory() as directory, fake_ollama(actions) as (url, _):
            with self.client(directory,url) as client:
                response = client.post('/api/tasks',json={
                    'message':'CSV analizi ve altı hata/kurtarma kontrolü yap.',
                    'expected_files':{'sonuc.json':json.dumps(expected,ensure_ascii=False,sort_keys=True)}
                })
                job = wait_job(client,response.json()['task_id'])
                # The worker must run the harness before accepting its independent evidence.
                self.assertEqual(job['status'],'VERIFIED',job)
                self.assertTrue((Path(directory)/'test_raporu.json').exists())
                report=json.loads((Path(directory)/'test_raporu.json').read_text())
                self.assertEqual([r['exit_code'] for r in report],[0,0,1,1,0,1,0])
                self.assertEqual(json.loads((Path(directory)/'sonuc.json').read_text()),expected)

    def test_web_restart_does_not_replay_running_job(self):
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, write()], delay=0.3) as (url, requests):
            with self.client(directory, url) as client:
                job_id = self.submit(client)
                limit = time.monotonic() + 3
                while time.monotonic() < limit:
                    if client.get('/api/tasks/' + job_id).json()['status'] == 'RUNNING':
                        break
                    time.sleep(0.02)
            with self.client(directory, url) as client:
                result = wait_job(client, job_id)['result']
                self.assertEqual(result['status'], 'VERIFIED', result)
                self.assertEqual(len(requests), 2)

    def test_cancel_kills_active_command_process(self):
        command = {'name':'tool_run_shell','arguments':{'command':"python3 -c 'import time;time.sleep(30)'"}}
        with tempfile.TemporaryDirectory() as directory, fake_ollama([PLAN, command]) as (url, _):
            with self.client(directory, url) as client:
                job_id = self.submit(client)
                store = client.app.state.service.store
                deadline = time.monotonic() + 5
                child = None
                while time.monotonic() < deadline:
                    child = store.get(job_id)['child_pid']
                    if child:
                        break
                    time.sleep(0.03)
                self.assertIsNotNone(child)
                client.post('/api/tasks/' + job_id + '/cancel')
                self.assertEqual(wait_job(client, job_id)['status'], 'CANCELLED')
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)

    def test_queue_capacity_and_false_verified_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory)/'jobs.db')
            ids = [store.submit({'message':str(i)},str(i)) for i in range(8)]
            with self.assertRaises(OverflowError):
                store.submit({'message':'overflow'}, 'overflow')
            with self.assertRaises(ValueError):
                store.finish(ids[0], 'VERIFIED', {'reply':'model says done'})
            store.request_cancel(ids[0])
            result = store.get(ids[0])['result']
            self.assertEqual(result['build'],'local-ui-v10')
            self.assertFalse(result['verified'])

    def test_hash_append_rejects_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.db")
            task = store.submit({}, "k")
            tools = TaskTools(directory, store, task)
            first = tools.execute("tool_write_file", {"filepath": "x", "content": "a"})
            args = {"filepath": "x", "content": "b", "expected_sha256": first["sha256"]}
            tools.execute("tool_append_file", args)
            with self.assertRaises(ValueError):
                tools.execute("tool_append_file", args)
            self.assertEqual((Path(directory) / "x").read_text(), "ab")


if __name__ == "__main__":
    unittest.main()
