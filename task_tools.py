"""Workspace tools; explicit subprocess groups, bounded output. Not an OS sandbox."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile


def schema(name, description, properties):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(properties), "additionalProperties": False}}}

TEXT = {"type": "string"}
TOOLS = [
    schema("tool_plan_steps", "Görevi 3–12 kısa aşamaya ayır; kod üretme.", {
        "steps": {"type": "array", "items": TEXT, "minItems": 1, "maxItems": 12}}),
    schema("tool_make_directory", "Çalışma alanında dizin oluştur.", {"filepath": TEXT}),
    schema("tool_list_files", "Çalışma alanında dosyaları listele.", {"filepath": TEXT}),
    schema("tool_write_file", "UTF-8 dosya yaz; büyük kodu en fazla 3000 karakterlik parçalara böl.", {
        "filepath": TEXT, "content": {"type": "string", "maxLength": 3000}}),
    schema("tool_append_file", "Son okuma/yazmanın sha256 değeriyle dosyaya parça ekle.", {
        "filepath": TEXT, "content": {"type": "string", "maxLength": 3000}, "expected_sha256": TEXT}),
    schema("tool_read_file", "Dosyayı oku; sonraki değişiklik için sha256 al.", {"filepath": TEXT}),
    schema("tool_run_shell", "Komutu argv olarak çalıştır; shell operatörleri yerine Python dosyası yazıp çalıştır.", {
        "command": TEXT}),
]


class TaskTools:
    def __init__(self, root, store, job_id, tool_seconds=90):
        self.root = Path(root).resolve()
        self.store, self.job_id, self.tool_seconds = store, job_id, tool_seconds
        self.child = None

    def path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Çalışma alanı dışına erişim reddedildi.")
        if path.relative_to(self.root).parts[:1] in [(".git",), (".baris_runtime",)]:
            raise ValueError("Motorun iç kayıtları değiştirilemez.")
        return path

    def stop_child(self):
        if self.child and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait()
            except ProcessLookupError:
                pass

    def execute(self, name, args):
        if name == "tool_plan_steps":
            if not 1 <= len(args["steps"]) <= 12:
                raise ValueError("Plan 1–12 aşama olmalı.")
            return {"success": True, "plan": args["steps"]}
        if name == "tool_run_shell":
            return self.run_command(args["command"])
        path = self.path(args["filepath"])
        if name == "tool_make_directory":
            path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(path)}
        if name == "tool_list_files":
            return {"success": True, "files": sorted(p.name for p in path.iterdir())[:200]}
        if name == "tool_read_file":
            raw = path.read_bytes()
            if len(raw) > 100_000:
                raise ValueError("Dosya 100 KB okuma sınırını aşıyor.")
            return {"success": True, "sha256": hashlib.sha256(raw).hexdigest(),
                    "content": raw.decode()}
        if name not in {"tool_write_file", "tool_append_file"}:
            raise ValueError("Bilinmeyen araç.")
        data = args["content"].encode("utf-8")
        if len(args["content"]) > 3000:
            raise ValueError("Parça 3000 karakteri aşıyor; küçük parçalara böl.")
        if name == "tool_append_file":
            previous = path.read_bytes()
            if hashlib.sha256(previous).hexdigest() != args["expected_sha256"]:
                raise ValueError("Dosya değişmiş; tekrar okuyup doğru hash ile devam et.")
            data = previous + data
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"success": path.read_bytes() == data, "path": str(path),
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
            self.store.update(self.job_id, child_pid=self.child.pid)
            import time
            deadline = time.monotonic() + self.tool_seconds
            overflow = False
            timed_out = False
            try:
                while self.child.poll() is None:
                    if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 4_000_000:
                        overflow = True
                        self.stop_child()
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        self.stop_child()
                        break
                    time.sleep(0.03)
            finally:
                self.stop_child()
                self.store.update(self.job_id, child_pid=None)
            result = {"success": self.child.returncode == 0 and not timed_out and not overflow,
                      "exit_code": 124 if timed_out else self.child.returncode,
                      "argv": argv, "timed_out": timed_out, "output_limit": overflow}
            for label, file in (("stdout", stdout), ("stderr", stderr)):
                size = file.tell()
                file.seek(max(0, size - 16000))
                result[label] = file.read().decode("utf-8", errors="replace")
                result[label + "_truncated"] = size > 16000
            return result
