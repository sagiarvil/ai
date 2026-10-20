"""Local durable queue. Never infer success from a model's prose."""
import contextlib
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

TERMINAL = {"VERIFIED", "UNVERIFIED", "FAILED", "CANCELLED", "BLOCKED"}


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
                    checkpoint TEXT, pending TEXT, result TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS job_events ON events(job_id,seq);
            ''')

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

    def event(self, job_id, kind, data):
        with self.connection() as db:
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
        return result

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone():
                return None
            row = db.execute("SELECT id FROM jobs WHERE status='QUEUED' ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='RUNNING', attempts=attempts+1 WHERE id=?", (row[0],))
                return row[0]

    def update(self, job_id, **fields):
        allowed = {"worker_pid", "child_pid", "cancel", "used", "checkpoint", "pending"}
        if not fields or set(fields) - allowed:
            raise ValueError("Geçersiz görev güncellemesi.")
        values = [json.dumps(v, ensure_ascii=False) if k in {"checkpoint", "pending"} and v is not None else v
                  for k, v in fields.items()]
        with self.connection() as db:
            db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + ",updated=? WHERE id=?",
                       (*values, time.time(), job_id))

    def finish(self, job_id, status, result):
        if status not in TERMINAL:
            raise ValueError("Geçersiz bitiş durumu.")
        result = dict(result, task_id=job_id, status=status,
                      engine_protocol='baris-execution-v2', build='local-ui-v5')
        result.setdefault('execution_steps', [])
        result.setdefault('acceptance', None)
        result.setdefault('execution_completed', False)
        result['verified'] = status == 'VERIFIED'
        if result['verified'] and not (result['acceptance'] and
                                      result['acceptance'].get('success') is True and
                                      result['execution_steps']):
            raise ValueError('Doğrulama kanıtı olmadan VERIFIED kaydedilemez.')
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?,result=?,worker_pid=NULL,child_pid=NULL,updated=? WHERE id=?",
                       (status, json.dumps(result, ensure_ascii=False), time.time(), job_id))
            self._event(db, job_id, status, {"message": result.get("reply", "Görev sonlandı.")})

    def request_cancel(self, job_id):
        job = self.get(job_id)
        if job["status"] == "QUEUED":
            self.finish(job_id, "CANCELLED", {"verified": False, "reply": "Kuyruktaki görev iptal edildi."})
        elif job["status"] == "RUNNING":
            self.update(job_id, cancel=1)

    def recover(self, alive):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status='RUNNING'").fetchall()
        for row in rows:
            if row["worker_pid"] and alive(row["worker_pid"]):
                continue
            if row["pending"] or row["attempts"] >= 2:
                self.finish(row["id"], "BLOCKED", {
                    "verified": False, "reply": "Kesinti sonrası işlem sonucu belirsiz; otomatik tekrar engellendi."})
            else:
                with self.connection() as db:
                    db.execute("UPDATE jobs SET status='QUEUED',worker_pid=NULL WHERE id=?", (row["id"],))
                    self._event(db, row["id"], "RECOVERED", {"message": "Güvenli kontrol noktasından devam edilecek."})
