"""One scheduler per machine workspace; worker survives HTTP disconnects."""
import asyncio
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from job_store import JobStore

# Popen handles give stronger identity than PID lookup for our own children.
OWNED_PROCESSES = {}


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class TaskService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = JobStore(self.root / ".baris_runtime" / "jobs.sqlite3")
        self.process = None
        self.loop_task = None
        self.lock = None
        self.worker_log = None

    def worker_alive(self, pid):
        process = OWNED_PROCESSES.get(pid)
        if process is not None:
            if process.poll() is None:
                return True
            OWNED_PROCESSES.pop(pid, None)
            return False
        if not alive(pid):
            return False
        try:
            proc = Path('/proc') / str(pid) / 'cmdline'
            if sys.platform.startswith('linux'):
                command = proc.read_bytes().replace(b'\0', b' ').decode(errors='replace')
            else:
                command = subprocess.check_output(
                    ['ps', '-p', str(pid), '-o', 'command='], text=True,
                    stderr=subprocess.DEVNULL)
            return 'task_worker.py' in command and self.store.path in command
        except (OSError, subprocess.CalledProcessError):
            return False

    async def start(self):
        self.lock = (self.root / ".baris_runtime" / "scheduler.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            self.lock = None
            raise RuntimeError("Bu çalışma alanında başka görev sunucusu çalışıyor.")
        self.store.recover(self.worker_alive)
        self.loop_task = asyncio.create_task(self.dispatch())

    async def dispatch(self):
        while True:
            if self.process is not None and self.process.poll() is not None:
                self.store.recover(self.worker_alive)
                self.process = None
                if self.worker_log:
                    self.worker_log.close()
                    self.worker_log = None
            if self.process is None:
                self.store.recover(self.worker_alive)
                job_id = self.store.claim()
                if job_id:
                    try:
                        self.worker_log = (self.root / ".baris_runtime" / (job_id + ".log")).open("ab")
                        self.process = subprocess.Popen(
                            [sys.executable, str(Path(__file__).with_name("task_worker.py")),
                             self.store.path, job_id], stdin=subprocess.DEVNULL,
                            stdout=self.worker_log, stderr=subprocess.STDOUT,
                            start_new_session=True, env=os.environ.copy())
                        OWNED_PROCESSES[self.process.pid] = self.process
                        self.store.update(job_id, worker_pid=self.process.pid)
                    except OSError as exc:
                        if self.worker_log:
                            self.worker_log.close()
                            self.worker_log = None
                        self.store.finish(job_id, "FAILED", {"reply": "Görev süreci başlatılamadı: " + str(exc)})
            with self.store.connection() as db:
                cancelled = db.execute("SELECT id,worker_pid FROM jobs WHERE status='RUNNING' AND cancel=1").fetchall()
            for row in cancelled:
                if row["worker_pid"] and self.worker_alive(row["worker_pid"]):
                    try:
                        os.kill(row["worker_pid"], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            await asyncio.sleep(0.25)

    async def close(self):
        if self.loop_task:
            self.loop_task.cancel()
            try:
                await self.loop_task
            except asyncio.CancelledError:
                pass
        # Do not kill a worker merely because its web server restarts.
        if self.process:
            import threading
            threading.Thread(target=self.process.wait, daemon=True).start()
        if self.worker_log:
            self.worker_log.close()
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
