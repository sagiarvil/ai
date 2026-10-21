"""Read-only local diagnosis. Never changes Ollama settings or repairs a database."""
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import urllib.request


def request_json(url, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    request=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=2) as response:
        raw=response.read(1_000_001)
        if len(raw)>1_000_000:
            raise ValueError('Teşhis yanıtı boyut sınırını aşıyor.')
        return json.loads(raw)


def inspect_runtime(root, model='mistral-small-24b-abliterated:latest', fetch=request_json):
    root=Path(root).resolve()
    checks=[]
    def check(name,operation):
        try:
            value=operation()
            checks.append({'name':name,'success':True,'actual':value})
        except Exception as exc:
            checks.append({'name':name,'success':False,'error':type(exc).__name__+': '+str(exc)})
    check('disk_free_bytes',lambda:shutil.disk_usage(root).free)
    check('ollama_version',lambda:fetch('http://127.0.0.1:11434/api/version').get('version'))
    check('loaded_models',lambda:fetch('http://127.0.0.1:11434/api/ps').get('models',[]))
    def show():
        data=fetch('http://127.0.0.1:11434/api/show',{'model':model})
        if not data.get('details'):
            raise ValueError('Model ayrıntıları alınamadı; model hazır sayılmadı.')
        return {'model':model,'details':data.get('details'), 'capabilities':data.get('capabilities')}
    check('selected_model',show)
    db=root/'.baris_runtime'/'jobs.sqlite3'
    if db.is_file():
        def database():
            with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2) as connection:
                integrity=connection.execute('PRAGMA quick_check').fetchone()[0]
                if integrity!='ok':
                    raise ValueError('Veritabanı bütünlük kontrolü: '+integrity)
                counts=dict(connection.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
                profiles=[dict(zip(('model','context','samples','first_seconds','chars_per_second','prompt_tokens','updated'),row))
                    for row in connection.execute('SELECT * FROM model_profiles ORDER BY updated DESC LIMIT 5')]
                blocked=[{'task_id':row[0],'child_pid':row[1],'pending_tool':json.loads(row[2]).get('name') if row[2] else None}
                    for row in connection.execute("SELECT id,child_pid,pending FROM jobs WHERE status='BLOCKED'")]
                return {'integrity':integrity,'counts':counts,'model_profiles':profiles,'blocked':blocked}
        check('database',database)
    return {'python':sys.executable,'python_version':platform.python_version(),
            'platform':platform.platform(),'workspace':str(root),'checks':checks,
            'all_checks_passed':all(item['success'] for item in checks),
            'live_task_completion_verified':False}
