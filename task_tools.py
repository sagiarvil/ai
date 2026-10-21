"""Workspace tools; explicit subprocess groups, bounded output. Not an OS sandbox."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import time


def schema(name, description, properties):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(properties), "additionalProperties": False}}}

CHUNK_LIMIT = 700
FILE_BYTES_LIMIT = 100_000

TEXT = {"type": "string"}
TOOLS = [
    schema("tool_plan_steps", "Görevi 3–12 kısa aşamaya ayır; kod üretme.", {
        "steps": {"type": "array", "items": {"type": "string", "maxLength": 160}, "minItems": 1, "maxItems": 12}}),
    schema("tool_make_directory", "Çalışma alanında dizin oluştur.", {"filepath": TEXT}),
    schema("tool_list_files", "Çalışma alanında dosyaları listele.", {"filepath": TEXT}),
    schema("tool_write_file", "Yalnızca YENİ UTF-8 dosya oluştur. Mevcut dosya reddedilir. Devamı için append, düzeltme için patch kullan.", {
        "filepath": TEXT, "content": {"type": "string", "maxLength": 700}}),
    schema("tool_append_file", "Son okuma/yazmanın sha256 değeriyle dosyaya parça ekle.", {
        "filepath": TEXT, "content": {"type": "string", "maxLength": 700}, "expected_sha256": TEXT}),
    schema("tool_read_file", "Dosyayı oku; sonraki değişiklik için sha256 al.", {"filepath": TEXT}),
    schema("tool_run_shell", "Komutu argv olarak çalıştır; shell operatörleri yerine Python dosyası yazıp çalıştır.", {
        "command": TEXT}),
    schema("tool_patch_file", "Mevcut dosyada tek eşleşen metni hash kontrolüyle düzelt; diğer içeriği koru.", {
        "filepath": TEXT, "old_text": {"type": "string", "maxLength": 700},
        "new_text": {"type": "string", "maxLength": 700}, "expected_sha256": TEXT}),
]


class TaskTools:
    def __init__(self, root, store, job_id, tool_seconds=90, chunk_limit=CHUNK_LIMIT, heartbeat=None):
        self.root = Path(root).resolve()
        self.store, self.job_id, self.tool_seconds = store, job_id, tool_seconds
        self.chunk_limit = chunk_limit
        self.child = None
        self.child_group = None
        self.heartbeat = heartbeat

    def path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Çalışma alanı dışına erişim reddedildi.")
        if path.relative_to(self.root).parts[:1] in [(".git",), (".baris_runtime",)]:
            raise ValueError("Motorun iç kayıtları değiştirilemez.")
        return path

    def read(self, path):
        with path.open('rb') as source:
            raw = source.read(FILE_BYTES_LIMIT + 1)
        if len(raw) > FILE_BYTES_LIMIT:
            raise ValueError('Dosya 100 KB işlem sınırını aşıyor.')
        return raw

    def stop_child(self):
        # A parent can exit while descendants remain in its owned process group.
        # Never infer group exit from Popen.poll() alone.
        group = self.child_group
        group_found = False
        if group is not None:
            try:
                os.killpg(group, signal.SIGTERM)
                group_found = True
                deadline = time.monotonic() + 0.25
                while time.monotonic() < deadline:
                    if self.child:
                        self.child.poll()
                    os.killpg(group, 0)
                    time.sleep(0.01)
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                self.child_group = None
        if self.child:
            self.child.wait(timeout=2)
        return group_found

    def execute(self, name, args):
        if name == "tool_plan_steps":
            if not 1 <= len(args["steps"]) <= 12:
                raise ValueError("Plan 1–12 aşama olmalı.")
            plan = []
            for index, step in enumerate(args['steps'], 1):
                if not isinstance(step, str) or len(step) > 160:
                    raise ValueError('Aşama açıklaması en fazla 160 karakter olmalı.')
                if any('\u3400' <= char <= '\u9fff' for char in step):
                    step = f'Aşama {index}: Türkçe açıklama üretilemedi; ilerleme araç kayıtlarından izlenecek.'
                plan.append(step)
            return {"success": True, "plan": plan}
        if name == "tool_run_shell":
            return self.run_command(args["command"])
        path = self.path(args["filepath"])
        if name == "tool_make_directory":
            path.mkdir(parents=True, exist_ok=False)
            return {"success": True, "path": str(path)}
        if name == "tool_list_files":
            return {"success": True, "files": sorted(p.name for p in path.iterdir())[:200]}
        if name == "tool_read_file":
            raw = self.read(path)
            return {"success": True, "sha256": hashlib.sha256(raw).hexdigest(),
                    "content": raw.decode()}
        if name not in {"tool_write_file", "tool_append_file", "tool_patch_file"}:
            raise ValueError("Bilinmeyen araç.")
        if name == "tool_write_file" and path.exists():
            raise ValueError("Dosya zaten var; üzerine yazma engellendi. Devam için tool_append_file, düzeltme için tool_patch_file kullan.")
        if name == "tool_patch_file":
            old, new = args["old_text"], args["new_text"]
            if not old or max(len(old), len(new)) > self.chunk_limit:
                raise ValueError(f"Yama hedefi boş olamaz; hedef ve yeni metin en fazla {self.chunk_limit} karakter olmalı.")
            previous = self.read(path)
            if hashlib.sha256(previous).hexdigest() != args["expected_sha256"]:
                raise ValueError("Dosya değişmiş; tekrar okuyup doğru hash ile devam et.")
            original = previous.decode("utf-8")
            if original.count(old) != 1:
                raise ValueError("Yama hedefi tam bir kez eşleşmeli; dosya değiştirilmedi.")
            data = original.replace(old, new, 1).encode("utf-8")
        else:
            if len(args["content"]) > self.chunk_limit:
                raise ValueError(f"Parça {self.chunk_limit} karakteri aşıyor; küçük parçalara böl.")
            data = args["content"].encode("utf-8")
            if name == "tool_append_file":
                previous = self.read(path)
                if hashlib.sha256(previous).hexdigest() != args["expected_sha256"]:
                    raise ValueError("Dosya değişmiş; tekrar okuyup doğru hash ile devam et.")
                data = previous + data
        if len(data) > FILE_BYTES_LIMIT:
            raise ValueError('Dosya 100 KB işlem sınırını aşıyor; dosya değiştirilmedi.')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if name == "tool_write_file":
                # Atomic create-if-absent; a concurrent creator cannot be overwritten.
                os.link(temporary, path)
            else:
                if self.read(path) != previous:
                    raise ValueError("Dosya işlem sırasında değişti; değişiklik uygulanmadı.")
                os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"success": self.read(path) == data, "path": str(path),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "readback": True}

    def run_command(self, command):
        argv = shlex.split(command)
        if not argv or Path(argv[0]).name not in {
            "python", "python3", "git", "node", "npm", "ls", "pwd", "which", "uname"}:
            raise ValueError("Bu komut doğrudan desteklenmiyor; Python dosyası üzerinden çalıştır.")
        if Path(argv[0]).name in {"python", "python3"}:
            import sys
            argv[0] = sys.executable
        safe_env = {k: v for k, v in os.environ.items()
                    if k in {"PATH", "HOME", "LANG", "TMPDIR", "USER"}}
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            self.child = subprocess.Popen(argv, cwd=self.root, env=safe_env,
                                          stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                          start_new_session=True)
            self.child_group = self.child.pid
            deadline = time.monotonic() + self.tool_seconds
            last_heartbeat = time.monotonic()
            overflow = False
            timed_out = False
            background = False
            try:
                self.store.update(self.job_id, child_pid=self.child.pid)
                while self.child.poll() is None:
                    if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 4_000_000:
                        overflow = True
                        self.stop_child()
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        self.stop_child()
                        break
                    if self.heartbeat and time.monotonic() - last_heartbeat >= 2:
                        self.heartbeat()
                        last_heartbeat = time.monotonic()
                    time.sleep(0.03)
            finally:
                parent_exited = self.child.poll() is not None
                background = self.stop_child() and parent_exited
                self.store.update(self.job_id, child_pid=None)
            overflow = overflow or (os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 4_000_000)
            result = {"success": self.child.returncode == 0 and not timed_out and not overflow and not background,
                      "exit_code": 124 if timed_out else self.child.returncode,
                      "process_exit_code": self.child.returncode,
                      "argv": argv, "timed_out": timed_out, "output_limit": overflow,
                      "background_processes_stopped": background}
            for label, file in (("stdout", stdout), ("stderr", stderr)):
                size = file.tell()
                file.seek(max(0, size - 16000))
                result[label] = file.read().decode("utf-8", errors="replace")
                result[label + "_truncated"] = size > 16000
            return result
