import os
import sys
import ast
import json
import time
import sqlite3
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List
import httpx

PROJECT_ROOT = Path("/Users/macair1/projects/ai")
MEMORY_DB = PROJECT_ROOT / "data" / "omnicore_memory.db"
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


class RepoMapIndexer:
    """
    Claude Code eşleniği Canlı AST Haritalayıcı.
    /Users/macair1/projects/ai içindeki tüm Python modüllerinin sınıf ve fonksiyon
    imzalarını çıkararak modelin kendi altyapısını %100 tanımasını sağlar.
    """
    _cache_map: str = ""
    _cache_ts: float = 0.0

    @classmethod
    def get_repo_map(cls, root: Path = PROJECT_ROOT, ttl: int = 30) -> str:
        now = time.time()
        if cls._cache_map and (now - cls._cache_ts) < ttl:
            return cls._cache_map
        lines = []
        for fpath in sorted(root.glob("*.py"))[:40]:
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"))
                defs = []
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        defs.append(f"class {node.name}({', '.join(methods[:5])})")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        defs.append(f"def {node.name}()")
                if defs:
                    lines.append(f"- {fpath.name}: " + " | ".join(defs[:8]))
            except Exception:
                continue
        cls._cache_map = "\n".join(lines)
        cls._cache_ts = now
        return cls._cache_map


class EpisodicMemoryBridge:
    """
    data/omnicore_memory.db üzerinde çalışan Epizodik Hafıza Köprüsü.
    Tamamlanan her otonom görevin araç zincirini ve kanıtını kalıcı olarak saklar.
    """
    @staticmethod
    def init_db():
        MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(MEMORY_DB)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS opus_episodic_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    prompt TEXT,
                    tools_used TEXT,
                    verified INTEGER,
                    summary TEXT
                )
            """)
            conn.commit()

    @classmethod
    def recall_recent(cls, limit: int = 5) -> str:
        cls.init_db()
        try:
            with sqlite3.connect(str(MEMORY_DB)) as conn:
                rows = conn.execute(
                    "SELECT prompt, tools_used, summary FROM opus_episodic_log WHERE verified=1 ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            if not rows:
                return "Henüz kayıtlı epizodik görev yok."
            return "\n".join([f"* Görev: {r[0][:80]} -> Araçlar: [{r[1]}] -> Sonuç: {r[2][:120]}" for r in rows])
        except Exception:
            return ""

    @classmethod
    def record_episode(cls, prompt: str, tools_used: List[str], verified: bool, summary: str):
        cls.init_db()
        try:
            with sqlite3.connect(str(MEMORY_DB)) as conn:
                conn.execute(
                    "INSERT INTO opus_episodic_log (ts, prompt, tools_used, verified, summary) VALUES (?, ?, ?, ?, ?)",
                    (time.time(), prompt, ",".join(tools_used), 1 if verified else 0, summary[:1200])
                )
                conn.commit()
        except Exception:
            pass


class PhysicalToolExecutor:
    """
    Tavsiye vermeyi ortadan kaldıran 5 çekirdek fiziksel icra aracı:
    - shell_exec: Zsh/Bash, git, gh, curl, pip, pytest, ollama, lsof çalıştırır.
    - read_file: Satır numaralı kaynak kodu okur.
    - write_file: Dosya yazar + otomatik py_compile sözdizimi testi ve rollback yapar.
    - patch_file: Cerrahî kod bloğu değiştirir + bozulursa otomatik rollback yapar.
    - python_eval: Python/openpyxl/sqlite3 betiklerini canlı çalıştırıp sonucu döner.
    """
    BLOCKED = ["rm -rf /", "mkfs", ":(){:|:&};:"]

    @classmethod
    def run(cls, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.time()
        try:
            if tool == "shell_exec":
                cmd = str(args.get("command", "")).strip()
                if not cmd:
                    return {"ok": False, "error": "Boş komut gönderildi."}
                if any(b in cmd for b in cls.BLOCKED):
                    return {"ok": False, "error": "Güvenlik kilidi: Yasaklı sistem komutu."}
                proc = subprocess.run(
                    cmd, shell=True, cwd=str(PROJECT_ROOT),
                    capture_output=True, text=True, timeout=int(args.get("timeout", 90))
                )
                return {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                    "ms": int((time.time() - t0) * 1000)
                }

            elif tool == "read_file":
                rel = str(args.get("path", "")).strip()
                target = (PROJECT_ROOT / rel).resolve()
                if not target.exists() or not target.is_file():
                    return {"ok": False, "error": f"Dosya bulunamadı: {rel}"}
                lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
                s_line = max(1, int(args.get("start_line", 1)))
                e_line = min(len(lines), int(args.get("end_line", s_line + 200)))
                numbered = [f"{i}: {lines[i-1]}" for i in range(s_line, e_line + 1)]
                return {"ok": True, "path": rel, "total_lines": len(lines), "content": "\n".join(numbered)}

            elif tool == "write_file":
                rel = str(args.get("path", "")).strip()
                content = str(args.get("content", ""))
                target = (PROJECT_ROOT / rel).resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                backup = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else None
                target.write_text(content, encoding="utf-8")
                if target.suffix == ".py":
                    chk = subprocess.run(["python3", "-m", "py_compile", str(target)], capture_output=True, text=True)
                    if chk.returncode != 0:
                        if backup is not None:
                            target.write_text(backup, encoding="utf-8")
                        else:
                            target.unlink(missing_ok=True)
                        return {"ok": False, "error": f"Python sözdizimi hatası (Otomatik Rollback yapıldı):\n{chk.stderr}"}
                return {"ok": True, "path": rel, "bytes": len(content.encode("utf-8")), "verified_syntax": True}

            elif tool == "patch_file":
                rel = str(args.get("path", "")).strip()
                search_str = str(args.get("search", ""))
                replace_str = str(args.get("replace", ""))
                target = (PROJECT_ROOT / rel).resolve()
                if not target.exists():
                    return {"ok": False, "error": f"Dosya yok: {rel}"}
                orig = target.read_text(encoding="utf-8")
                if search_str not in orig:
                    return {"ok": False, "error": "search bloğu dosyada birebir bulunamadı. Önce read_file ile satırları oku."}
                patched = orig.replace(search_str, replace_str, 1)
                target.write_text(patched, encoding="utf-8")
                if target.suffix == ".py":
                    chk = subprocess.run(["python3", "-m", "py_compile", str(target)], capture_output=True, text=True)
                    if chk.returncode != 0:
                        target.write_text(orig, encoding="utf-8")
                        return {"ok": False, "error": f"Patch sözdizimini bozdu (Otomatik Rollback yapıldı):\n{chk.stderr}"}
                return {"ok": True, "path": rel, "patched": True, "verified_syntax": True}

            elif tool == "python_eval":
                code = str(args.get("code", ""))
                proc = subprocess.run(
                    ["python3", "-c", code], cwd=str(PROJECT_ROOT),
                    capture_output=True, text=True, timeout=90
                )
                return {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:]
                }

            else:
                return {"ok": False, "error": f"Tanımsız araç: {tool}. Geçerli araçlar: shell_exec, read_file, write_file, patch_file, python_eval, final_verified_answer"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


class OpusSonnetAutonomousEngine:
    """
    Çok Adımlı Test-Time Compute (TTC) & Zorunlu ReAct İcra Motoru.
    Tavsiye vermeyi reddeder; görevi fiziksel araçlarla icra edip doğrulamadan bitirmez.
    """
    @staticmethod
    def parse_json_action(raw: str) -> Dict[str, Any]:
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            cleaned = cleaned[s:e+1]
        return json.loads(cleaned)

    @classmethod
    async def run_autonomous_loop(
        cls,
        user_prompt: str,
        model: str = "qwen-coder-14b-abliterated:latest",
        max_steps: int = 6
    ) -> Dict[str, Any]:
        repo_map = RepoMapIndexer.get_repo_map()
        recent_mem = EpisodicMemoryBridge.recall_recent()

        system_prompt = f"""Sen Barış AI Otonom Mühendislik ve İcra Çekirdeğisin (Claude Opus / Claude Code Standardı).
ÇALIŞMA DİZİNİ: /Users/macair1/projects/ai (Apple M4 Donanımı)

CANLI REPO AST HARİTASI (Projedeki Mevcut Modül ve Sınıfların):
{repo_map}

EPİZODİK HAFIZA (Son Doğrulanmış Görevler):
{recent_mem}

MUTLAK İCRA YASALARI:
0. ASLA kullanıcının sormadığı 'İndirimli Ürün Sayısı / Toplam İndirim Tutarı / Genel Ciro' gibi uydurma veya ezbere tablolar üretme! Yalnızca kullanıcının son mesajındaki gerçek soruya odaklan.
1. KULLANICIYA "Şu adımları izleyin: 1. GitHub'a gidin, 2. Şunu çalıştırın" ŞEKLİNDE TAVSİYE VERMEK KESİNLİKLE YASAKTIR!
2. Kullanıcının istediği işlemi (GitHub araması, model/repo kurulumu, dosya/kod analizi, bug düzeltme, openpyxl ile Excel dosyası üretimi, sunucu/port kontrolü) FİZİKSEL ARAÇLARI ÇAĞIRARAK BİZZAT SEN YAPACAKSIN.
3. En az 1 fiziksel araç (shell_exec, read_file, write_file, patch_file, python_eval) çalıştırıp gerçek sistem çıktısını doğrulamadan "final_verified_answer" çağırmak YASAKTIR!
4. GitHub'da repo/model aramak için shell_exec ile `curl -s "https://api.github.com/search/repositories?q=..."` veya yerel modelleri görmek için `ollama list` komutunu bizzat çalıştır.

FİZİKSEL ARAÇ ŞEMASI:
- "shell_exec": {{"command": "çalıştırılacak bash/zsh komutu"}}
- "read_file": {{"path": "dosya.py", "start_line": 1, "end_line": 160}}
- "write_file": {{"path": "dosya.py", "content": "tam içerik"}}
- "patch_file": {{"path": "dosya.py", "search": "eski kod", "replace": "yeni kod"}}
- "python_eval": {{"code": "çalıştırılacak python betiği"}}
- "final_verified_answer": {{"summary": "Fiziksel olarak çalıştırılan araçların, değiştirilen dosyaların ve doğrulanan çıktının net mühendislik raporu"}}

HER ADIMDA YALNIZCA AŞAĞIDAKİ JSON OBJESİNİ DÖNDÜR:
{{
  "thought": "Kısa teknik karar ve çalıştırılacak fiziksel aracın amacı",
  "tool": "shell_exec | read_file | write_file | patch_file | python_eval | final_verified_answer",
  "args": {{ ... }}
}}
"""
        history: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"KULLANICI EMRİ: {user_prompt}"}
        ]

        executed_tools: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=180.0) as client:
            for step in range(1, max_steps + 1):
                resp = await client.post("http://127.0.0.1:11434/api/chat", json={
                    "model": model,
                    "messages": history,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_ctx": 12288,
                        "num_predict": 2500
                    }
                })
                raw_content = resp.json().get("message", {}).get("content", "{}")
                try:
                    action = cls.parse_json_action(raw_content)
                except Exception as e:
                    history.append({"role": "assistant", "content": raw_content})
                    history.append({"role": "user", "content": f" SÖZDİZİMİ HATASI: Geçersiz JSON ({e}). Sadece geçerli bir JSON objesi döndür."})
                    continue

                tool_name = str(action.get("tool", "")).strip()
                tool_args = action.get("args", {})
                if not isinstance(tool_args, dict):
                    tool_args = {}
                thought = str(action.get("thought", "")).strip()

                # ANTI-ADVICE GUARDRAIL: Hiçbir fiziksel araç çalıştırmadan yanıt dönmeyi reddet!
                if tool_name == "final_verified_answer":
                    if len(executed_tools) == 0 and step <= 3:
                        history.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                        history.append({
                            "role": "user",
                            "content": "YASAK İHLALİ: Henüz hiçbir fiziksel araç (shell_exec, read_file, write_file, python_eval) çalıştırmadın! Kullanıcıya tavsiye veremezsin. Hemen uygun fiziksel aracı çağırarak görevi bizzat icra et!"
                        })
                        continue

                    summary_text = str(tool_args.get("summary") or action.get("summary") or thought)
                    evidence_file = EVIDENCE_DIR / f"evidence_opus_{int(time.time())}.json"
                    evidence_payload = {
                        "timestamp": time.time(),
                        "prompt": user_prompt,
                        "model": model,
                        "steps_taken": step,
                        "executed_tools": executed_tools,
                        "final_summary": summary_text
                    }
                    evidence_file.write_text(json.dumps(evidence_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    EpisodicMemoryBridge.record_episode(
                        user_prompt,
                        [t["tool"] for t in executed_tools],
                        True,
                        summary_text
                    )

                    # İcra kanıt logunu özetin altına ekle
                    trace_lines = [
                        f"⚡ **[Otonom İcra Kanıtı — {len(executed_tools)} Fiziksel Araç Çalıştırıldı | Kanıt: `{evidence_file.name}`]**"
                    ]
                    for t in executed_tools:
                        ok_badge = "✅ PASS" if t["observation"].get("ok") else "⚠️ RETRY"
                        cmd_preview = t["args"].get("command") or t["args"].get("path") or "python_eval"
                        trace_lines.append(f"- Adım {t['step']}: `{t['tool']}({cmd_preview})` ➔ {ok_badge}")

                    full_report = summary_text + "\n\n---\n" + "\n".join(trace_lines)
                    return {
                        "status": "VERIFIED_COMPLETE",
                        "steps": step,
                        "executed_tools": executed_tools,
                        "evidence_path": str(evidence_file.relative_to(PROJECT_ROOT)),
                        "reply": full_report
                    }

                # Fiziksel aracı çalıştır ve çıktıyı gözlemle
                obs = PhysicalToolExecutor.run(tool_name, tool_args)
                executed_tools.append({
                    "step": step,
                    "thought": thought,
                    "tool": tool_name,
                    "args": tool_args,
                    "observation": obs
                })

                history.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
                history.append({
                    "role": "user",
                    "content": (
                        f"FİZİKSEL ARAÇ ÇIKTISI (Adım {step} - {tool_name}):\n"
                        f"{json.dumps(obs, ensure_ascii=False)}\n\n"
                        f"Eğer işlem başarılıysa ve tüm gereksinimler fiziksel olarak doğrulandıysa 'final_verified_answer' aracını çağır. "
                        f"Hata varsa (ok=false) veya ek işlem gerekiyorsa bir sonraki fiziksel aracı çağır."
                    )
                })

        # Maksimum adım dolduğunda yapılan tüm fiziksel işlemleri derle
        trace_summary = "\n".join([
            f"- Adım {t['step']} `{t['tool']}`: ok={t['observation'].get('ok')} | çıktı={str(t['observation'].get('stdout') or t['observation'].get('error'))[:250]}"
            for t in executed_tools
        ])
        return {
            "status": "MAX_STEPS_COMPLETED",
            "steps": max_steps,
            "executed_tools": executed_tools,
            "reply": f"Otonom icra {max_steps} adımda tamamlandı:\n{trace_summary}"
        }


def mount_opus_sonnet_gateway(app):
    """
    FastAPI app.router.routes içerisindeki eski pasif sohbet rotalarını temizleyip
    tüm ana uç noktaları (/api/opus_execute, /api/chat, /chat) doğrudan
    OpusSonnetAutonomousEngine'e bağlar.
    """
    override_paths = {"/api/opus_execute", "/api/chat", "/chat", "/api/omni_chat"}
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", None) not in override_paths
    ]

    @app.post("/api/opus_execute")
    @app.post("/api/chat")
    @app.post("/chat")
    @app.post("/api/omni_chat")
    async def unified_opus_sonnet_gateway(request: dict):
        prompt = (
            request.get("prompt")
            or request.get("message")
            or request.get("query")
            or request.get("text")
            or ""
        )
        if not prompt and "messages" in request and isinstance(request["messages"], list):
            for m in reversed(request["messages"]):
                if isinstance(m, dict) and m.get("role") == "user":
                    prompt = m.get("content", "")
                    break

        model = request.get("model", "qwen-coder-14b-abliterated:latest")
        if model not in ["qwen-coder-14b-abliterated:latest", "deepseek-r1:latest", "mistral-small:24b", "deepseek-r1-14b-abliterated:latest"]:
            model = "qwen-coder-14b-abliterated:latest"

        res = await OpusSonnetAutonomousEngine.run_autonomous_loop(
            user_prompt=prompt,
            model=model,
            max_steps=int(request.get("max_steps", 6))
        )
        return {
            "status": res["status"],
            "ok": True,
            "reply": res["reply"],
            "response": res["reply"],
            "content": res["reply"],
            "message": res["reply"],
            "steps": res["steps"],
            "executed_tools": res["executed_tools"],
            "evidence_path": res.get("evidence_path", ""),
            "choices": [{"message": {"role": "assistant", "content": res["reply"]}}]
        }
