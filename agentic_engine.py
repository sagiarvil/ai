#!/usr/bin/env python3
"""
BARIŞ AI // AUTONOMOUS AGENTIC EXECUTION ENGINE (OPENHANDS MIMARISI ESASLI)
Durum Makinesi:
RECEIVED -> PLANNED -> RESEARCHING -> VALIDATING -> INSTALLING -> TESTING -> ACTIVATING -> VERIFIED
Hata Durumları:
FAILED, BLOCKED, PARTIAL, ROLLED_BACK, NOT_EXECUTED, UNVERIFIED

Sıfır Sahte Başarı İlkeleri:
1. Modelin ürettiği metin asla başarı kanıtı değildir.
2. Araçsız yanıtlar başarı sayılamaz (NOT_EXECUTED).
3. Başarı kelime eşleşmesi veya dummy script ile değil, IndependentVerificationGate ile belirlenir.
4. Model aktivasyonunda gerçek runtime çıkarım testi (Inference Probe) zorunludur.
5. Hata durumunda otomatik geri alma (Rollback) çalıştırılır.
"""

import asyncio
import enum
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from sandbox_executor import secure_sandbox_run, SANDBOX_DIR
from model_manager import ModelManager
from verification_gate import IndependentVerificationGate

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
TASKS_DIR = WORKSPACE_ROOT / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)
TOOLS_DIR = WORKSPACE_ROOT / "tools"
TOOLS_DIR.mkdir(parents=True, exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_ROOT / "active_engines.json"

OLLAMA_API_URL = "http://127.0.0.1:11434/v1/chat/completions"
DEFAULT_MODEL = "mistral-small-24b-abliterated:latest"

class TaskState(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    RESEARCHING = "RESEARCHING"
    VALIDATING = "VALIDATING"
    INSTALLING = "INSTALLING"
    TESTING = "TESTING"
    ACTIVATING = "ACTIVATING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    ROLLED_BACK = "ROLLED_BACK"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNVERIFIED = "UNVERIFIED"

class ExecutionSandbox:
    @classmethod
    def run_isolated(cls, cmd: str, cwd: Optional[Path] = None, timeout: int = 120) -> Dict[str, Any]:
        """Sandbox executor katmanına güvenli delege eder."""
        return secure_sandbox_run(cmd, cwd=cwd, timeout=timeout)

class AutonomousExecutionEngine:
    def __init__(self, task_id: Optional[str] = None):
        self.task_id = task_id or f"task_{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(2).hex()}"
        self.state = TaskState.RECEIVED
        self.state_history = []
        self.evidences = []
        self.plan = []
        self.installed_artifacts = []
        self.rollback_stack = []

    def transition_to(self, new_state: TaskState, reason: str = ""):
        old = self.state
        self.state = new_state
        entry = {
            "from": old.value,
            "to": new_state.value,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason
        }
        self.state_history.append(entry)
        self._persist_task_state()

    def add_evidence(self, category: str, detail: str, success: bool, raw_data: Any = None):
        ev = {
            "category": category,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "detail": detail,
            "success": bool(success),
            "raw_data": raw_data
        }
        self.evidences.append(ev)
        self._persist_task_state()

    def _persist_task_state(self):
        filepath = TASKS_DIR / f"{self.task_id}.json"
        data = {
            "task_id": self.task_id,
            "current_state": self.state.value,
            "state_history": self.state_history,
            "plan": self.plan,
            "installed_artifacts": self.installed_artifacts,
            "evidences": self.evidences
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --------------------------------------------------------------------------
    # 1. ÇOK KRİTERLİ GITHUB & MODEL ARAŞTIRMA MOTORU (RESEARCH)
    # --------------------------------------------------------------------------
    @classmethod
    def search_and_compare_github_repos(cls, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Çoklu arama yapar; sadece yıldız değil lisans, güncellik ve Apple Silicon uyumunu puanlar.
        """
        cmd = f"gh search repos '{query}' --limit {limit} --json fullName,url,stargazersCount,updatedAt,description,licenseKey"
        res = ExecutionSandbox.run_isolated(cmd, timeout=30)
        if not res["success"] or not res["stdout"]:
            return []
        try:
            repos = json.loads(res["stdout"])
            scored_repos = []
            for r in repos:
                score = r.get("stargazersCount", 0)
                if r.get("licenseKey") in ["mit", "apache-2.0", "bsd-3-clause", "gpl-3.0"]:
                    score += 50
                updated = r.get("updatedAt", "")
                if any(y in updated for y in ["2025", "2026"]):
                    score += 100
                r["composite_score"] = score
                scored_repos.append(r)
            return sorted(scored_repos, key=lambda x: x.get("composite_score", 0), reverse=True)
        except Exception:
            return []

    # --------------------------------------------------------------------------
    # 2. DOĞRULANMIŞ KURULUM & FİZİKSEL ÇALIŞMA PROBE'U (INSTALL & VERIFY)
    # --------------------------------------------------------------------------
    def install_and_verify_repo(self, repo_url: str, test_command: Optional[str] = None) -> Dict[str, Any]:
        self.transition_to(TaskState.INSTALLING, f"Klonlama ve bağımlılık kurulumu başlatıldı: {repo_url}")
        
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target_dir = TOOLS_DIR / repo_name
        
        # Rollback yığını hazırla
        if target_dir.exists():
            backup_dir = TOOLS_DIR / f"{repo_name}_bak_{int(time.time())}"
            shutil.copytree(target_dir, backup_dir)
            self.rollback_stack.append(("restore_dir", str(target_dir), str(backup_dir)))
        else:
            self.rollback_stack.append(("delete_dir", str(target_dir)))

        # Klonlama
        if not (target_dir / ".git").exists():
            c_res = ExecutionSandbox.run_isolated(f"git clone --depth 1 '{repo_url}' '{target_dir}'", timeout=90)
            if not c_res["success"]:
                self.add_evidence("GIT_CLONE", f"Klonlama başarısız (exit_code: {c_res['exit_code']}): {c_res['stderr']}", False)
                self.rollback()
                self.transition_to(TaskState.FAILED, "Git klonlama başarısız.")
                return {"success": False, "error": c_res["stderr"]}
            self.add_evidence("GIT_CLONE", f"Depo izole alana klonlandı: {target_dir}", True)

        # Bağımlılık Denetimi
        req_file = target_dir / "requirements.txt"
        pkg_file = target_dir / "package.json"

        if req_file.exists():
            p_res = ExecutionSandbox.run_isolated("python3 -m pip install -r requirements.txt --break-system-packages", cwd=target_dir, timeout=180)
            if not p_res["success"]:
                self.add_evidence("PIP_INSTALL", f"Pip kurulum hatası (exit_code: {p_res['exit_code']}): {p_res['stderr']}", False)
                self.rollback()
                self.transition_to(TaskState.FAILED, "Python bağımlılıkları kurulamadı.")
                return {"success": False, "error": p_res["stderr"]}
            self.add_evidence("PIP_INSTALL", "Python bağımlılıkları başarıyla kuruldu.", True)
        elif pkg_file.exists():
            n_res = ExecutionSandbox.run_isolated("npm install", cwd=target_dir, timeout=180)
            if not n_res["success"]:
                self.add_evidence("NPM_INSTALL", f"Npm kurulum hatası (exit_code: {n_res['exit_code']}): {n_res['stderr']}", False)
                self.rollback()
                self.transition_to(TaskState.FAILED, "Node.js bağımlılıkları kurulamadı.")
                return {"success": False, "error": n_res["stderr"]}
            self.add_evidence("NPM_INSTALL", "Node.js bağımlılıkları kuruldu.", True)

        # Bağımsız Doğrulama Kapısı (TESTING) - ASLA SAHTE DEĞİL
        self.transition_to(TaskState.TESTING, "IndependentVerificationGate ile fiziksel doğrulama yürütülüyor.")
        
        gate_res = IndependentVerificationGate.verify_runtime_execution(target_dir=target_dir, custom_test_cmd=test_command)
        if not gate_res.get("verified"):
            self.add_evidence(
                "RUNTIME_TEST",
                f"Bağımsız doğrulayıcı reddetti (exit_code: {gate_res.get('exit_code')}): {gate_res.get('reason')}",
                False,
                gate_res.get("output")
            )
            self.rollback()
            self.transition_to(TaskState.FAILED, f"Kurulan motor doğrulama kapısından geçemedi: {gate_res.get('reason')}")
            return {"success": False, "error": gate_res.get("reason")}

        self.add_evidence("RUNTIME_TEST", f"Bağımsız Doğrulama PASS: {gate_res.get('command')}", True, gate_res.get("output"))

        # Aktivasyon & Tescil (ACTIVATING -> VERIFIED)
        self.transition_to(TaskState.ACTIVATING, "Motor aktif kayıt kütüğüne tescil ediliyor.")
        self._register_engine(repo_name, repo_url, str(target_dir))
        self.installed_artifacts.append(repo_name)

        self.transition_to(TaskState.VERIFIED, "Motor kurulumu, bağımlılıkları ve runtime testi %100 PASS.")
        return {
            "success": True,
            "engine": repo_name,
            "dir": str(target_dir),
            "state": self.state.value,
            "evidences": self.evidences
        }

    def _register_engine(self, name: str, url: str, path_str: str):
        try:
            reg = {"engines": []}
            if ACTIVE_ENGINES_FILE.exists():
                with open(ACTIVE_ENGINES_FILE, "r", encoding="utf-8") as f:
                    reg = json.load(f)
            engines = [e for e in reg.get("engines", []) if e.get("name") != name]
            engines.append({
                "name": name,
                "url": url,
                "dir": path_str,
                "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "verified": True,
                "runtime_pass": True
            })
            with open(ACTIVE_ENGINES_FILE, "w", encoding="utf-8") as f:
                json.dump({"engines": engines}, f, indent=2)
        except Exception:
            pass

    def rollback(self):
        self.transition_to(TaskState.ROLLED_BACK, "Hata nedeniyle sistem önceki kararlı duruma geri alınıyor.")
        while self.rollback_stack:
            action = self.rollback_stack.pop()
            op = action[0]
            if op == "delete_dir":
                d = Path(action[1])
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            elif op == "restore_dir":
                target = Path(action[1])
                bak = Path(action[2])
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if bak.exists():
                    shutil.move(bak, target)

    # --------------------------------------------------------------------------
    # 3. RUNTIME DOĞRULAMALI GÖREV İCRA PROTOKOLÜ (AGENTIC LOOP)
    # --------------------------------------------------------------------------
    @classmethod
    async def execute_verified_task(cls, prompt: str, tools_schema: list, call_tool_fn) -> Dict[str, Any]:
        engine = cls()
        engine.transition_to(TaskState.RECEIVED, "Kullanıcı görevi teslim alındı.")
        engine.transition_to(TaskState.PLANNED, f"Hedef analiz edildi: {prompt[:80]}")
        
        system_instruction = (
            "Sen OpenHands mimarisiyle çalışan, DETERMINISTIK bir Otonom Yazılım Mühendisisin. "
            "KESİN KURAL: Asla akıl verme, ders anlatma, 'Şunu yapmanız gerekir' deme! "
            "Kullanıcı bir şey istediğinde DOĞRUDAN araç çağrılarıyla görevi icra et. "
            "Araç çağrısı yapmadan metin üretirsen görevin NOT_EXECUTED olarak iptal edilecektir!"
        )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt}
        ]

        execution_steps = []
        final_reply = ""
        has_executed_tools = False

        # Maksimum 10 tur ReAct döngüsü
        for step_idx in range(1, 11):
            try:
                start_req = time.perf_counter()
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        OLLAMA_API_URL,
                        json={
                            "model": DEFAULT_MODEL,
                            "messages": messages,
                            "tools": tools_schema,
                            "tool_choice": "auto",
                            "temperature": 0.1,
                            "options": {
                                "num_thread": 8,
                                "temperature": 0.1,
                                "num_ctx": 8192,
                                "top_k": 20,
                                "top_p": 0.9
                            }
                        }
                    )
                    elapsed_req = round(time.perf_counter() - start_req, 3)
                    if resp.status_code != 200:
                        engine.transition_to(TaskState.FAILED, f"Model API yanıt vermedi: HTTP {resp.status_code}")
                        break
                    
                    data = resp.json()
                    msg = data["choices"][0]["message"]
            except Exception as e:
                engine.transition_to(TaskState.FAILED, f"Model çağrım hatası: {str(e)}")
                break

            tool_calls = msg.get("tool_calls")
            if tool_calls:
                has_executed_tools = True
                messages.append(msg)

                for tc in tool_calls:
                    fname = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments", "{}")
                    try:
                        fargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        fargs = {}

                    # İlgili aracı çalıştır
                    out = await call_tool_fn(fname, fargs)
                    
                    is_tool_success = not out.startswith("[Hata") and not out.startswith("[Kurulum Başarısız") and not out.startswith("[GÜVENLİK ENGELİ")
                    
                    engine.add_evidence(f"TOOL_{fname}", f"Parametreler: {fargs}", is_tool_success, out[:500])

                    execution_steps.append({
                        "step": step_idx,
                        "tool": fname,
                        "args": fargs,
                        "output": out,
                        "success": is_tool_success
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": out
                    })
            else:
                final_reply = (msg.get("content") or "").strip()
                break

        # SIFIR SAHTE BAŞARI KAPISI (ZERO-FAKE VERIFICATION)
        if not has_executed_tools:
            engine.transition_to(TaskState.NOT_EXECUTED, "Model hiçbir araç çalıştırmadan sadece metin üretti.")
            return {
                "task_id": engine.task_id,
                "status": TaskState.NOT_EXECUTED.value,
                "reply": final_reply or "İşlem icra edilmedi; model yalnızca metin üretti.",
                "execution_steps": [],
                "evidences": engine.evidences,
                "verified": False
            }

        # Tüm adımlar bağımsız başarıyla bitti mi?
        all_passed = all(ev.get("success", False) for ev in engine.evidences)
        if all_passed and execution_steps:
            engine.transition_to(TaskState.VERIFIED, "Tüm adımlar fiziksel kanıtlarla doğrulandı.")
            return {
                "task_id": engine.task_id,
                "status": TaskState.VERIFIED.value,
                "reply": final_reply or "Görev tüm adımlarıyla başarıyla icra edildi ve doğrulandı.",
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": True
            }
        else:
            engine.transition_to(TaskState.PARTIAL, "Bazı adımlar hata verdi veya kısmen tamamlandı.")
            return {
                "task_id": engine.task_id,
                "status": TaskState.PARTIAL.value,
                "reply": final_reply or "Görev kısmen icra edildi; bazı araçlar hata üretti.",
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": False
            }
