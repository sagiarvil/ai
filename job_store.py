"""Local durable queue. Never infer success from a model's prose."""
import contextlib
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

TERMINAL = {"VERIFIED", "UNVERIFIED", "FAILED", "CANCELLED", "BLOCKED"}


class OwnershipLost(RuntimeError):
    """A stale worker must stop before another action or journal write."""


class JobStore:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    request_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    worker_pid INTEGER, child_pid INTEGER, cancel INTEGER DEFAULT 0,
                    attempts INTEGER DEFAULT 0, used REAL DEFAULT 0,
                    checkpoint TEXT, pending TEXT, result TEXT, lease TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS job_events ON events(job_id,seq);
                CREATE TABLE IF NOT EXISTS model_profiles(
                    model TEXT NOT NULL, context INTEGER NOT NULL, samples INTEGER NOT NULL,
                    first_seconds REAL NOT NULL, chars_per_second REAL NOT NULL,
                    prompt_tokens INTEGER NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(model,context));
            ''')
            # Upgrade existing workspaces without replacing their task history.
            db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'lease' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN lease TEXT')

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit(self, payload, key):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["request_hash"] != digest:
                    raise ValueError("Aynı işlem anahtarı farklı görev için kullanılamaz.")
                return old["id"]
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchone()[0] >= 8:
                raise OverflowError("Görev kuyruğu dolu (8); yeni görev eklenmedi.")
            job_id = "job_" + uuid.uuid4().hex
            db.execute("INSERT INTO jobs(id,request_key,request_hash,payload,status,created,updated) VALUES(?,?,?,?,?,?,?)",
                       (job_id, key, digest, raw, "QUEUED", now, now))
            self._event(db, job_id, "QUEUED", {"message": "Görev kalıcı kuyruğa alındı."})
            return job_id

    def _event(self, db, job_id, kind, data):
        db.execute("INSERT INTO events(job_id,at,kind,data) VALUES(?,?,?,?)",
                   (job_id, time.time(), kind, json.dumps(data, ensure_ascii=False)))
        db.execute("UPDATE jobs SET updated=? WHERE id=?", (time.time(), job_id))

    def _check_owner(self, db, job_id, lease):
        row = db.execute('SELECT status,lease FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if row['status'] in TERMINAL or (lease is not None and
                (row['status'] != 'RUNNING' or row['lease'] != lease)):
            raise OwnershipLost('Görevin yürütme sahipliği sona erdi; geç kayıt veya işlem reddedildi.')

    def event(self, job_id, kind, data, *, lease=None):
        with self.connection() as db:
            if lease is not None:
                db.execute('BEGIN IMMEDIATE')
                self._check_owner(db, job_id, lease)
            self._event(db, job_id, kind, data)

    def get(self, job_id, after=0):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = dict(row)
            for key in ("payload", "checkpoint", "pending", "result"):
                job[key] = json.loads(job[key]) if job[key] else None
            job["events"] = [dict(seq=r["seq"], at=r["at"], kind=r["kind"],
                                  data=json.loads(r["data"])) for r in db.execute(
                "SELECT * FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100",
                (job_id, after))]
            return job

    def public(self, job_id, after=0):
        job = self.get(job_id, after)
        result = {k: job[k] for k in ("id", "status", "created", "updated", "used", "result", "events")}
        result['plan'] = (job.get('checkpoint') or {}).get('plan') or []
        result['budget_seconds'] = job['payload'].get('budget_seconds')
        result['remaining_seconds'] = (max(0, result['budget_seconds'] - job['used'])
                                       if result['budget_seconds'] is not None else None)
        with self.connection() as db:
            latest = db.execute("SELECT * FROM events WHERE job_id=? ORDER BY seq DESC LIMIT 1", (job_id,)).fetchone()
        result['latest_event'] = (dict(seq=latest['seq'], at=latest['at'], kind=latest['kind'],
                                      data=json.loads(latest['data'])) if latest else None)
        result['next_after'] = job['events'][-1]['seq'] if job['events'] else max(0, after)
        result['has_more'] = bool(latest and latest['seq'] > result['next_after'])
        return result

    def queue_state(self):
        with self.connection() as db:
            counts = dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
            blocked = db.execute("SELECT pending,child_pid,result FROM jobs WHERE status='BLOCKED'").fetchall()
        return {'running': counts.get('RUNNING', 0), 'queued': counts.get('QUEUED', 0),
                'blocked': any(self._blocks_queue(r) for r in blocked)}

    @staticmethod
    def _blocks_queue(row):
        return bool(row['child_pid'] or (row['pending'] and
            json.loads(row['pending']).get('name') == 'tool_run_shell') or
            (row['result'] and json.loads(row['result']).get('failure_code') == 'WORKER_OWNERSHIP_UNCERTAIN'))

    def record_model_sample(self, model, context, first_seconds, rate, prompt_tokens):
        import math
        if not model or not all(math.isfinite(x) and x >= 0 for x in (first_seconds,rate)):
            return
        with self.connection() as db:
            db.execute("""INSERT INTO model_profiles VALUES(?,?,1,?,?,?,?)
                ON CONFLICT(model,context) DO UPDATE SET samples=samples+1,
                first_seconds=0.8*first_seconds+0.2*excluded.first_seconds,
                chars_per_second=0.8*chars_per_second+0.2*excluded.chars_per_second,
                prompt_tokens=excluded.prompt_tokens,updated=excluded.updated""",
                (model,context,first_seconds,rate,prompt_tokens,time.time()))

    def model_profile(self, model, context=8192):
        with self.connection() as db:
            row=db.execute("SELECT * FROM model_profiles WHERE model=? AND context=?",(model,context)).fetchone()
            return dict(row) if row else None

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone():
                return None
            blocked = db.execute("SELECT pending,child_pid,result FROM jobs WHERE status='BLOCKED'").fetchall()
            if any(self._blocks_queue(r) for r in blocked):
                return None
            row = db.execute("SELECT id FROM jobs WHERE status='QUEUED' AND cancel=0 ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='RUNNING',attempts=attempts+1,lease=?,worker_pid=NULL WHERE id=?",
                           (uuid.uuid4().hex, row[0]))
                return row[0]

    def update(self, job_id, *, lease=None, **fields):
        allowed = {"worker_pid", "child_pid", "cancel", "used", "checkpoint", "pending"}
        if not fields or set(fields) - allowed:
            raise ValueError("Geçersiz görev güncellemesi.")
        values = [json.dumps(v, ensure_ascii=False) if k in {"checkpoint", "pending"} and v is not None else v
                  for k, v in fields.items()]
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._check_owner(db, job_id, lease)
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + ",updated=? WHERE id=?",
                       (*values, time.time(), job_id))

    def finish(self, job_id, status, result, *, lease=None):
        if status not in TERMINAL:
            raise ValueError("Geçersiz bitiş durumu.")
        result = dict(result, task_id=job_id, status=status,
                      engine_protocol='baris-execution-v2', build='local-ui-v10')
        result.setdefault('execution_steps', [])
        result.setdefault('acceptance', None)
        result.setdefault('execution_completed', False)
        result['verified'] = status == 'VERIFIED'
        if result['verified'] and not (result['acceptance'] and
                                      result['acceptance'].get('success') is True and
                                      result['execution_steps'] and
                                      result['execution_steps'][-1].get('success') is True):
            raise ValueError('Doğrulama kanıtı olmadan VERIFIED kaydedilemez.')
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,cancel FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if lease is not None:
                self._check_owner(db, job_id, lease)
            if row["status"] in TERMINAL:
                return
            if row["cancel"] and status != "BLOCKED":
                status = "CANCELLED"
                result.update(status=status,verified=False,execution_completed=False,
                              reply="İptal istendi; tamamlanan işlemler kayıtta korundu.")
            db.execute("UPDATE jobs SET status=?,result=?,worker_pid=NULL,updated=?,child_pid=CASE WHEN ?='BLOCKED' THEN child_pid ELSE NULL END WHERE id=?",
                       (status, json.dumps(result, ensure_ascii=False), time.time(),status,job_id))
            self._event(db, job_id, status, {"message": result.get("reply", "Görev sonlandı.")})

    def request_cancel(self, job_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in TERMINAL:
                return
            if row["status"] == "QUEUED":
                result = {"task_id":job_id,"status":"CANCELLED","verified":False,
                          "execution_completed":False,"execution_steps":[],"acceptance":None,
                          "reply":"Kuyruktaki görev iptal edildi.",
                          "engine_protocol":"baris-execution-v2","build":"local-ui-v10"}
                db.execute("UPDATE jobs SET status='CANCELLED',cancel=1,result=?,updated=? WHERE id=?",
                           (json.dumps(result,ensure_ascii=False),time.time(),job_id))
                self._event(db,job_id,"CANCELLED",{"message":result["reply"]})
            else:
                db.execute("UPDATE jobs SET cancel=1,updated=? WHERE id=?",(time.time(),job_id))
                self._event(db,job_id,"CANCEL_REQUESTED",{"message":"İptal isteği kaydedildi; çalışan adım durduruluyor."})

    def recover(self, alive):
        from execution_ownership import execution_lock
        with execution_lock(self) as guard:
            if guard is not None:
                self._recover_when_idle(alive)

    def _recover_when_idle(self, alive):
        """Only the scheduler holding execution.lock may call this variant."""
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status='RUNNING'").fetchall()
        for row in rows:
            # Unknown identity is not evidence that a legacy worker is dead.
            # For new claims the caller holds execution.lock, proving no worker
            # owns the workspace. PID lookup is only for pre-lock legacy rows.
            if not row['lease'] and row["worker_pid"] and alive(row["worker_pid"]) is not False:
                continue
            if not row['lease'] and not row['worker_pid']:
                self.finish(row['id'], 'BLOCKED', {
                    'reply': 'Eski görevin çalışan sahipliği belirsiz; otomatik tekrar ve yeni yürütme engellendi.',
                    'failure_code': 'WORKER_OWNERSHIP_UNCERTAIN'})
                continue
            if row["cancel"] and not row["pending"] and not row["child_pid"]:
                self.finish(row["id"],"CANCELLED",{"reply":"Kesilen görev için iptal isteği korundu."})
            elif row["pending"] or row["child_pid"] or row["attempts"] >= 2:
                self.finish(row["id"], "BLOCKED", {
                    "verified": False, "reply": "Kesinti sonrası işlem sonucu belirsiz; otomatik tekrar engellendi."})
            else:
                with self.connection() as db:
                    changed = db.execute("UPDATE jobs SET status='QUEUED',worker_pid=NULL,lease=NULL WHERE id=? AND status='RUNNING' AND cancel=0 AND lease IS ?",
                                         (row["id"], row['lease']))
                    if changed.rowcount:
                        self._event(db, row["id"], "RECOVERED", {"message": "Güvenli kontrol noktasından devam edilecek."})
