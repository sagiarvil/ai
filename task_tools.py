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


import ast
import re

def auto_fix_python_source(code):
    """Python kodunda LLM kaynaklı çok satırlı tırnak ve f-string sözdizim hatalarını deterministik olarak onarır."""
    if not isinstance(code, str):
        return code
    try:
        ast.parse(code)
        return code
    except SyntaxError:
        pass

    # file.write('...' \n '...') veya print('...' \n '...') tek tırnaklı çok satırlı dizgileri üçlü tırnak ("""...""") yap
    def replacer(m):
        func = m.group(1)
        prefix = "f" if m.group(2) else ""
        content = m.group(3)
        return f"{func}({prefix}\"\"\"{content}\"\"\")"

    fixed = re.sub(r'(\b\w+\.write|print)\s*\(\s*(f)?\'(.*?)\'\s*\)', replacer, code, flags=re.DOTALL)
    
    # Genel print veya write çağrıları için f-string tek tırnak onarımı
    try:
        ast.parse(fixed)
        return fixed
    except SyntaxError:
        pass

    # f'| {x} | {y['z']} |' -> f"| {x} | {y['z']} |"
    lines = fixed.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(("print(f'\\'", "file.write(f'\\'")) or ("f'\\'" in line and "['\\'" in line):
            lines[i] = re.sub(r"f'\''(.*?)'\''(\s*\)?\s*)$", r'f"""\1"""\2', line)
    candidate = "\n".join(lines)
    try:
        ast.parse(candidate)
        return candidate
    except SyntaxError:
        return fixed


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
        self.created_in_job = set()

    def path(self, value):
        raw = Path(value)
        if raw.is_absolute():
            path = raw.resolve()
        else:
            path = (self.root / value).resolve()

        home = Path.home()
        allowed_roots = [
            self.root,
            Path("/tmp"),
            Path("/private/tmp"),
            home / ".omnicore" / "sandbox_workspace",
            home / "projects"
        ]

        if not any(path == r or path.is_relative_to(r) for r in allowed_roots):
            raise ValueError("Çalışma alanı dışına erişim reddedildi.")
        if path.is_relative_to(self.root) and path.relative_to(self.root).parts[:1] in [(".git",), (".baris_runtime",)]:
            raise ValueError("Motorun iç kayıtları değiştirilemez.")
        if path.name.startswith(".env") or ".ssh" in path.parts:
            raise ValueError("Korumalı dosyalara erişim reddedildi.")
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
            resolved = path.resolve()
            if resolved in (Path("/tmp").resolve(), Path("/private/tmp"), Path.home().resolve(), self.root.resolve()):
                return {"success": True, "path": str(path), "reused": True}
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
            resolved_str = str(path.resolve())
            protected_core = {'server.py', 'durable_api.py', 'task_worker.py', 'task_tools.py', 'baris_local.py', 'omni_chat_panel.py', 'runtime_doctor.py', 'job_store.py', 'acceptance_checks.py', 'structured_actions.py'}
            if resolved_str.startswith(("/tmp/", "/private/tmp/")):
                path.unlink(missing_ok=True)
            elif (path in self.created_in_job or path.suffix in {'.py', '.json', '.txt', '.csv', '.log', '.sh'}) and not path.name.startswith(('test_', 'test.')) and path.name not in protected_core:
                # Kendi görev dosyalarını veya scriptleri kendini iyileştirme (self-healing) kapsamında yeniden yazabilir
                path.unlink(missing_ok=True)
            else:
                raise ValueError("Dosya zaten var; üzerine yazma engellendi. Devam için tool_append_file, düzeltme için tool_patch_file kullan.")
        if name == "tool_patch_file":
            old, new = args["old_text"], args["new_text"]
            if not old or max(len(old), len(new)) > self.chunk_limit:
                raise ValueError(f"Yama hedefi boş olamaz; hedef ve yeni metin en fazla {self.chunk_limit} karakter olmalı.")
            previous = self.read(path)
            if hashlib.sha256(previous).hexdigest() != args["expected_sha256"]:
                raise ValueError("Dosya değişmiş; tekrar okuyup doğru hash ile devam et.")
            original = previous.decode("utf-8")
            if original.count(old) == 1:
                data = original.replace(old, new, 1).encode("utf-8")
            elif old.strip() and original.count(old.strip()) == 1:
                data = original.replace(old.strip(), new.strip(), 1).encode("utf-8")
            else:
                # Fuzzy satır eşleştirme denemesi
                norm_old = "\n".join(line.rstrip() for line in old.strip().splitlines())
                norm_orig = "\n".join(line.rstrip() for line in original.splitlines())
                if norm_orig.count(norm_old) == 1:
                    norm_new = "\n".join(line.rstrip() for line in new.strip().splitlines())
                    data = norm_orig.replace(norm_old, norm_new, 1).encode("utf-8")
                else:
                    raise ValueError(f"Yama hedefi dosyada tam bir kez eşleşmedi. Dosyayı yamamak yerine 'tool_write_file' ile dosyanın tamamını ({path.name}) baştan temiz ve eksiksiz yaz.")
            if data == previous:
                raise ValueError("Yama dosyada hiçbir değişiklik yapmadı; old_text ile new_text birbirinden farklı olmalı.")
        else:
            raw_content = args["content"]
            if path.suffix == ".py":
                raw_content = auto_fix_python_source(raw_content)
            if len(raw_content) > self.chunk_limit:
                raise ValueError(f"Parça {self.chunk_limit} karakteri aşıyor; küçük parçalara böl.")
            data = raw_content.encode("utf-8")
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
                os.replace(temporary, path)
                self.created_in_job.add(path)
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
        if not argv:
            raise ValueError("Komut boş olamaz.")
        cmd_name = Path(argv[0]).name
        is_python = cmd_name.startswith("python")
        allowed_bins = {"git", "node", "npm", "ls", "pwd", "which", "uname", "pytest", "cat", "echo", "head", "tail"}
        if not (is_python or cmd_name in allowed_bins):
            raise ValueError(f"'{cmd_name}' komutu doğrudan desteklenmiyor; Python dosyası üzerinden çalıştır.")
        if "|" in argv or ">" in argv or "<" in argv:
            raise ValueError("Shell operatörleri (| > <) desteklenmez. Dosyayı doğrudan tool_read_file ile okuyun veya görevi bitirmek için __finish__ çağırın.")
        if is_python:
            import sys
            argv[0] = sys.executable
        safe_env = {k: v for k, v in os.environ.items()
                    if k in {"PATH", "HOME", "LANG", "TMPDIR", "USER"}}
        safe_env["PYTHONUNBUFFERED"] = "1"
        safe_env["PYTHONDONTWRITEBYTECODE"] = "1"
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
            if not result["success"] and "SyntaxError" in result.get("stderr", ""):
                result["stderr"] += "\n[ÖNERİ]: Python sözdizim hatası algılandı. Dosyayı yamalamak yerine 'tool_write_file' ile baştan eksiksiz ve temiz şekilde yeniden yazın."
            return result
