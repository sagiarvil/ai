"""Qualification-controller tests use a scripted HTTP model, never a real model claim."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import durable_api
from live_qualification import qualify, EXPECTED
from test_durable_runtime import fake_ollama, PLAN


PROGRAM = '''import csv,json,sys,os,tempfile
from decimal import Decimal,InvalidOperation
from pathlib import Path
def main():
 src,out=map(Path,sys.argv[1:])
 if src.resolve()==out.resolve():raise ValueError("Hata: aynı yol")
 total=Decimal(0);refund=Decimal(0);n=c=b=d=0;seen=set()
 with src.open(encoding="utf-8",newline="") as f:
  reader=csv.DictReader(f,delimiter=";")
  if reader.fieldnames!=["islem_id","tutar","durum"]:raise ValueError("Geçersiz başlık")
  for r in reader:
   if r["islem_id"] in seen:d+=1;continue
   seen.add(r["islem_id"])
   try:
    amount=Decimal(r["tutar"])
    if not amount.is_finite():raise InvalidOperation()
   except (InvalidOperation,TypeError):b+=1;continue
   if r["durum"]=="tamamlandi":n+=1;total+=amount
   elif r["durum"]=="iade":refund+=amount
   elif r["durum"]=="iptal":c+=1
 result=dict(tamamlanan_islem_sayisi=n,tamamlanan_tutar=f"{total:.2f}",iade_tutari=f"{refund:.2f}",net_satis=f"{total+refund:.2f}",iptal_sayisi=c,gecersiz_kayit_sayisi=b,yinelenen_kayit_sayisi=d)
 with tempfile.NamedTemporaryFile("w",dir=out.parent,delete=False,encoding="utf-8") as f:
  json.dump(result,f,ensure_ascii=False);temp=f.name
 os.replace(temp,out)
try:main()
except Exception as e:print("Hata:",e,file=sys.stderr);sys.exit(1)
'''


class QualificationTests(unittest.TestCase):
    def exercise(self, program):
        identity = 'a' * 12
        relative = 'baris_canli_kabul_' + identity
        def write(path, content):
            return {'name': 'tool_write_file', 'arguments': {'filepath': relative + '/' + path, 'content': content}}
        actions = [PLAN, write('merhaba.txt', 'Merhaba Barış | ' + identity), PLAN]
        before = ''
        for start in range(0, len(program), 700):
            chunk = program[start:start+700]
            if not before:
                actions.append(write('analiz.py', chunk))
            else:
                actions.append({'name': 'tool_append_file', 'arguments': {'filepath': relative + '/analiz.py',
                    'content': chunk, 'expected_sha256': hashlib.sha256(before.encode()).hexdigest()}})
            before += chunk
        actions.extend([write('deneme.csv', 'islem_id;tutar;durum\n'),
            {'name': 'tool_run_shell', 'arguments': {'command': f'python3 {relative}/analiz.py {relative}/deneme.csv {relative}/deneme.json'}},
            write('hazir.txt', identity)])
        with tempfile.TemporaryDirectory() as directory, fake_ollama(actions) as (url, requests):
            root = Path(directory).resolve()
            with patch.object(durable_api, 'WORKSPACE', root), patch.dict(os.environ, {'BARIS_OLLAMA_CHAT_URL': url}):
                with TestClient(durable_api.app, base_url='http://127.0.0.1') as client:
                    def fetch(path, payload=None, key=None):
                        response = client.get(path) if payload is None else client.post(path, json=payload, headers={'Idempotency-Key': key or 'cancel'})
                        response.raise_for_status()
                        return response.json()
                    with patch('live_qualification.new_identity', return_value=identity):
                        report, path = qualify(root, budget=30, fetch=fetch, log=lambda text: None)
                    self.assertEqual(json.loads(path.read_text()), report)
                    self.assertEqual((root/relative/'analiz.py').read_text(), program)
                    self.assertFalse(report['model_report_used_as_evidence'])
                    return report

    def test_correct_program_is_independently_executed_against_hidden_cases(self):
        report = self.exercise(PROGRAM)
        self.assertTrue(report['passed'], report.get('error'))
        self.assertEqual([c['process_exit_code'] for c in report['commands']], [0,0,0,1,1,1,0])
        self.assertTrue(all(c['passed'] for c in report['checks']))
        self.assertEqual(len(report['jobs']), 2)

    def test_hardcoded_sample_answer_fails_independent_edge_case(self):
        program = 'import pathlib,json,sys\npathlib.Path(sys.argv[2]).write_text(json.dumps(' + repr(EXPECTED) + '))\n'
        report = self.exercise(program)
        self.assertFalse(report['passed'])
        self.assertIn('kenar_sonuc', report['error'])
        self.assertEqual(len(report['commands']), 2)

    def test_unavailable_server_cannot_pass_or_create_model_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            def offline(*args, **kwargs):
                raise ConnectionError('offline')
            report, path = qualify(directory, fetch=offline, log=lambda text: None)
            self.assertFalse(report['passed'])
            self.assertEqual(report['commands'], [])
            self.assertEqual(report['jobs'], [])
            self.assertTrue(path.is_file())
            self.assertFalse(list(Path(directory).glob('baris_canli_kabul_*')))


if __name__ == '__main__':
    unittest.main()
