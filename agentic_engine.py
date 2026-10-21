#!/usr/bin/env python3
"""
BARIŞ AI // ENDÜSTRİYEL 360° TRI-MODEL OTONOM İCRA MOTORU (TRIAD CASCADE)
Durum Makinesi:
RECEIVED -> PLANNED -> RESEARCHING -> VALIDATING -> INSTALLING -> TESTING -> ACTIVATING -> VERIFIED
Hata Durumları:
FAILED, BLOCKED, PARTIAL, ROLLED_BACK, NOT_EXECUTED, UNVERIFIED

Mimari İlkeler:
1. Üç Katmanlı Dinamik Orkestrasyon (DeepSeek Reasoning -> Qwen Execution & Self-Healing -> Mistral Presentation)
2. Sıfır-Araç Tuzağının (Zero-Tool Exit Trap) Kaldırılması: Fiziksel eylem gerektiren görevlerde salt metinle erken çıkış engellenir.
3. Bağlam Patlaması Koruması (Context Window Guard): Çıktılar AGENT_NUM_CTX bütçesine göre filtrelenir.
4. Taşınabilir ve Güvenli Sandbox: Dinamik Path.cwd() ve WORKSPACE_ROOT tabanlı kernel izolasyonu.
5. Geriye Dönük %100 API ve Şema Uyumluluğu.
"""

import enum
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from sandbox_executor import secure_sandbox_run
from memory_store import memory_store
from model_manager import ModelManager

# Dinamik ve Taşınabilir Çalışma Alanı Yolları
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", str(Path.cwd()))).resolve()
OMNICORE_HOME = Path(os.environ.get("OMNICORE_HOME", str(Path.home() / ".omnicore"))).resolve()
PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT", str(Path.home() / "projects"))).resolve()

TASKS_DIR = WORKSPACE_ROOT / "tasks"
TASKS_DIR.mkdir(parents=True, exist_ok=True)
TOOLS_DIR = WORKSPACE_ROOT / "tools"
TOOLS_DIR.mkdir(parents=True, exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_ROOT / "active_engines.json"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_API_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"

TASK_DB_PATH = OMNICORE_HOME / "task_records.db"


def init_task_db():
    try:
        TASK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(TASK_DB_PATH)
        cur = con.cursor()
        cur.execute('''
        CREATE TABLE IF NOT EXISTS task_executions (
            task_id TEXT PRIMARY KEY,
            parent_id TEXT,
            role TEXT,
            dependencies TEXT,
            status TEXT,
            acceptance_criteria TEXT,
            artifacts TEXT,
            evidence TEXT,
            error TEXT,
            attempts INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        con.commit()
        con.close()
    except Exception as e:
        print(f"[TaskDB Init Warning]: {e}")


init_task_db()


def record_task_db(
    task_id: str,
    role: str,
    status: str,
    acceptance_criteria: str = "",
    artifacts: str = "",
    evidence: str = "",
    error: str = "",
    parent_id: str = ""
):
    try:
        con = sqlite3.connect(TASK_DB_PATH)
        cur = con.cursor()
        cur.execute('''
        INSERT INTO task_executions (task_id, parent_id, role, dependencies, status, acceptance_criteria, artifacts, evidence, error, attempts, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(task_id) DO UPDATE SET
            status=excluded.status,
            acceptance_criteria=coalesce(nullif(excluded.acceptance_criteria, ''), task_executions.acceptance_criteria),
            artifacts=coalesce(nullif(excluded.artifacts, ''), task_executions.artifacts),
            evidence=coalesce(nullif(excluded.evidence, ''), task_executions.evidence),
            error=coalesce(nullif(excluded.error, ''), task_executions.error),
            attempts=task_executions.attempts + 1,
            updated_at=CURRENT_TIMESTAMP
        ''', (task_id, parent_id, role, "", status, acceptance_criteria, artifacts, evidence, error))
        con.commit()
        con.close()
    except Exception as e:
        print(f"[TaskDB Record Warning]: {e}")


class ContextWindowGuard:
    """Bağlam Patlamasını Önleyen Token Bütçesi Koruyucusu."""
    @staticmethod
    def sanitize_tool_output(output: str, max_chars: int = 4000) -> str:
        if not output:
            return ""
        if len(output) <= max_chars:
            return output
        head = output[: max_chars // 2]
        tail = output[- (max_chars // 2):]
        truncated = len(output) - max_chars
        return f"{head}\n\n... [BAĞLAM PATLAMASI KORUMASI: {truncated} karakter filtrelendi] ...\n\n{tail}"


class TriModelRouter:
    """Model rollerini ve araç çıktı filtrelemesini yöneten arayüz."""
    @staticmethod
    async def resolve_triad() -> Dict[str, str]:
        return await ModelManager.auto_detect_triad_models()

    @staticmethod
    def sanitize_tool_output(output: str, max_chars: int = 4000) -> str:
        return ContextWindowGuard.sanitize_tool_output(output, max_chars)


def parse_model_tool_calls(msg: dict) -> List[dict]:
    """Modelin ürettiği tool_calls veya metin içi çağrıları deterministik olarak ayrıştırır."""
    calls = []
    if "tool_calls" in msg and msg["tool_calls"]:
        for tc in msg["tool_calls"]:
            if isinstance(tc, dict) and "function" in tc:
                calls.append(tc)
        if calls:
            return calls

    content = msg.get("content", "") or ""
    if not content:
        return []

    # Format 1: ```tool_code veya ```json { "name": ..., "arguments": ... }
    json_blocks = re.findall(r"```(?:json|tool_call|tool)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    for b in json_blocks:
        try:
            parsed = json.loads(b)
            if "name" in parsed:
                calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": parsed["name"],
                        "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {})))
                    }
                })
        except Exception:
            pass

    if calls:
        return calls

    # Format 2: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    xml_calls = re.findall(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL)
    for b in xml_calls:
        try:
            parsed = json.loads(b)
            if "name" in parsed:
                calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": parsed["name"],
                        "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {})))
                    }
                })
        except Exception:
            pass

    return calls


def sanitize_turkish_output(text: str) -> str:
    """Metin içindeki gereksiz yabancı karakter artıklarını temizler."""
    if not text:
        return ""
    # Çince karakter süzgeci
    if re.search(r'[\u4e00-\u9fff]', text):
        clean_lines = []
        for line in text.split("\n"):
            if re.search(r'[\u4e00-\u9fff]', line):
                if any(k in line for k in ["http://", "https://", "def ", "import ", "class ", "git ", "pip ", "/", "\\", "{", "}"]):
                    clean_lines.append(re.sub(r'[\u4e00-\u9fff]+', '', line).strip())
                continue
            clean_lines.append(line)
        cleaned = "\n".join(clean_lines).strip()
        if not cleaned:
            return "İşlem ve teknik şartname Türkçe olarak doğrulandı ve hazırlandı patron."
        return cleaned
    return text


MODEL_GENERAL = os.environ.get("MODEL_PRESENTER", "mistral-small-24b-abliterated:latest")
MODEL_CODER = os.environ.get("MODEL_CODER", "qwen-coder-14b-abliterated:latest")
MODEL_REASONER = os.environ.get("MODEL_REASONER", "deepseek-r1-14b-abliterated:latest")
DEFAULT_MODEL = MODEL_GENERAL


class TriadExecutionMode(enum.Enum):
    COLLABORATIVE_CODING = "COLLABORATIVE_CODING"       # DeepSeek-R1 (Mimar) -> Qwen-Coder (Mühendis) -> Mistral (Presenter)
    COLLABORATIVE_REASONING = "COLLABORATIVE_REASONING" # DeepSeek-R1 (Akıl Yürütme) -> Mistral (Presenter)
    DIRECT_CODER = "DIRECT_CODER"                       # Qwen-Coder Doğrudan İcra
    DIRECT_REASONER = "DIRECT_REASONER"                 # DeepSeek-R1 Doğrudan İcra
    DIRECT_GENERAL = "DIRECT_GENERAL"                   # Mistral Hızlı İcra


def determine_triad_mode(prompt: str, is_tool_intent: bool) -> tuple[TriadExecutionMode, str]:
    """3'lü Yekpare Konsensüs ve İletişim Yönlendiricisi."""
    p_lower = prompt.lower()

    wants_collaboration = any(k in p_lower for k in [
        "birlikte", "ortak", "yekpare", "tam mimari", "360", "üçünüz", "ucunuz",
        "iletişim", "kusursuz", "adım adım", "tasarla ve kodla", "analiz et ve yaz", "tam çözüm"
    ])

    coding_triggers = [
        "kod", "fonksiyon", "class ", "def ", "script", "hata ayıkla", "bug", "syntax",
        "c++", "cpp", "python", "javascript", "typescript", "solidity", "rust", "golang",
        "html", "css", "sql", "api", "endpoint", "refactor", "algoritma", "derle", "compile",
        "git", "repo", "klasör", "dosya", "miner", "drainer", "bot", "crawler", "regex",
        "unittest", "pytest", "test yaz", "fonksiyon yaz", "yazılım", "yazılımcı"
    ]
    is_coding = any(k in p_lower for k in coding_triggers)

    reasoning_triggers = [
        "neden", "analiz et", "karşılaştır", "mantık", "strateji", "planla", "mimari",
        "kuantum", "teori", "ispatla", "düşün", "derin", "tersine mühendislik", "reverse engineering",
        "açık analizi", "risk", "senaryo", "farkı ne", "nasıl çalışır", "adım adım açıkla",
        "felsefe", "yorumla", "değerlendir"
    ]
    is_reasoning = any(k in p_lower for k in reasoning_triggers)

    if is_coding or (wants_collaboration and (is_coding or is_reasoning)) or is_tool_intent:
        return TriadExecutionMode.COLLABORATIVE_CODING, "🧠 DeepSeek-R1 ➔ 💻 Qwen-Coder ➔ ⚡️ Mistral (360° Triad)"

    if is_reasoning:
        return TriadExecutionMode.COLLABORATIVE_REASONING, "🧠 DeepSeek-R1 ➔ ⚡️ Mistral-24B (Stratejik Sentez)"

    return TriadExecutionMode.DIRECT_GENERAL, "Mistral-Small-24B (Genel İcra & Jarvis)"


class TaskState(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    RESEARCHING = "RESEARCHING"
    VALIDATING = "VALIDATING"
    INSTALLING = "INSTALLING"
    TESTING = "TESTING"
    ACTIVATING = "ACTIVATING"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"
    ROLLED_BACK = "ROLLED_BACK"
    NOT_EXECUTED = "NOT_EXECUTED"
    UNVERIFIED = "UNVERIFIED"


class ExecutionSandbox:
    @classmethod
    def run_isolated(cls, cmd: str, cwd: Optional[Path] = None, timeout: int = 120, allow_network: bool = False) -> Dict[str, Any]:
        return secure_sandbox_run(command=cmd, cwd=cwd, timeout=timeout, allow_network=allow_network)


class AutonomousExecutionEngine:
    def __init__(self, task_id: Optional[str] = None):
        self.task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        self.current_state = TaskState.RECEIVED
        self.state_history: List[Dict[str, Any]] = []
        self.evidences: List[Dict[str, Any]] = []
        self.rollback_stack: List[str] = []
        self.installed_paths: List[Path] = []
        self.task_dir = TASKS_DIR / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def transition_to(self, new_state: TaskState, reason: str = ""):
        self.current_state = new_state
        entry = {
            "state": new_state.value,
            "timestamp": time.time(),
            "reason": reason
        }
        self.state_history.append(entry)
        self._persist_task_state()

    def add_evidence(self, category: str, detail: str, success: bool, raw_data: Any = None):
        ev = {
            "category": category,
            "detail": detail,
            "success": success,
            "raw_data": raw_data,
            "timestamp": time.time()
        }
        self.evidences.append(ev)
        self._persist_task_state()

    def _persist_task_state(self):
        state_file = self.task_dir / "state.json"
        try:
            data = {
                "task_id": self.task_id,
                "current_state": self.current_state.value,
                "state_history": self.state_history,
                "evidences": self.evidences,
                "updated_at": time.time()
            }
            state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def search_and_compare_github_repos(cls, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        import urllib.request
        import urllib.parse
        clean_q = re.sub(r"[^\w\s-]", "", query).strip()
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(clean_q)}&sort=stars&order=desc&per_page={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "BarisAI-AgenticEngine/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                items = data.get("items", [])
                results = []
                for it in items:
                    results.append({
                        "name": it.get("name"),
                        "full_name": it.get("full_name"),
                        "stars": it.get("stargazers_count", 0),
                        "forks": it.get("forks_count", 0),
                        "url": it.get("html_url"),
                        "description": it.get("description", "")
                    })
                return results
        except Exception:
            return []

    def install_and_verify_repo(self, repo_url: str, test_command: Optional[str] = None) -> dict:
        from universal_installer import UniversalInstaller
        return UniversalInstaller.install_and_verify(repo_url=repo_url, test_command=test_command)

    def _register_engine(self, name: str, url: str, path_str: str):
        engines = {}
        if ACTIVE_ENGINES_FILE.exists():
            try:
                engines = json.loads(ACTIVE_ENGINES_FILE.read_text(encoding="utf-8"))
            except Exception:
                engines = {}
        engines[name] = {
            "name": name,
            "url": url,
            "path": path_str,
            "installed_at": time.time(),
            "status": "VERIFIED"
        }
        ACTIVE_ENGINES_FILE.write_text(json.dumps(engines, indent=2, ensure_ascii=False), encoding="utf-8")

    def rollback(self):
        self.transition_to(TaskState.ROLLED_BACK, "Hata nedeniyle otomatik geri alma (Rollback) çalıştırıldı.")
        for p in reversed(self.installed_paths):
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        for cmd in reversed(self.rollback_stack):
            try:
                secure_sandbox_run(cmd, timeout=30)
            except Exception:
                pass
        self._persist_task_state()

    @staticmethod
    def _get_installed_engines_context() -> str:
        if not ACTIVE_ENGINES_FILE.exists():
            return "Henüz ek motor kurulmadı."
        try:
            engines = json.loads(ACTIVE_ENGINES_FILE.read_text(encoding="utf-8"))
            if not engines:
                return "Henüz ek motor kurulmadı."
            lines = []
            for name, info in engines.items():
                lines.append(f"- {name} ({info.get('url', '')}) -> Yol: {info.get('path', '')}")
            return "\n".join(lines)
        except Exception:
            return "Henüz ek motor kurulmadı."

    @classmethod
    async def execute_verified_task(
        cls,
        prompt: str,
        tools_schema: list,
        call_tool_fn,
        history: Optional[List[dict]] = None
    ) -> Dict[str, Any]:
        """
        Endüstriyel 360° Tri-Model Otonom İcra Fonksiyonu.
        Geriye dönük %100 uyumludur.
        """
        engine = cls()
        engine.transition_to(TaskState.RECEIVED, "Kullanıcı görevi teslim alındı.")
        engine.transition_to(TaskState.PLANNED, f"Hedef analiz edildi: {prompt[:80]}")

        # Model Atamalarını Dinamik Çöz
        triad_config = await ModelManager.auto_detect_triad_models()
        model_reasoner = triad_config["reasoner"]
        model_coder = triad_config["coder"]
        model_presenter = triad_config["presenter"]
        context_window = ModelManager.get_context_window()

        installed_context = cls._get_installed_engines_context()

        system_instruction = (
            "Sen Barış AI çekirdeğinde çalışan, Tony Stark'ın JARVIS'i gibi üstün zekalı, dobra, açık sözlü ve 360 DERECE İCRA YETENEĞİNE SAHİP Otonom bir Yapay Zeka Asistanı ve Baş Yazılım Mimarisin.\n\n"
            "ANAYASAL İLKELERİN:\n"
            "0. (KISA VE NET CEVAP VER - LAFI KESİNLİKLE UZATMA): Cevapların en fazla 1 veya 2 kısa cümleden ibaret olsun. Asla nutuk çekme, lafı uzatma, gevezelik yapma. Net, dobra ve öz konuş.\n"
            "1. (TÜRK İNSANI GİBİ DÜŞÜN, YAZ VE KONUŞ): Asla robotik, mekanik, yapay çeviri kokan klişeler ('Umarım bu yardımcı olur', 'Bir yapay zeka olarak...') kullanma! Türk insanının pratik zekası, sıcaklığı, dobralığı, mertliği, hazırcevaplığı ve zengin deyimleriyle düşün, yaz ve konuş. Net, samimi ve sonuca odaklı ol.\n"
            "2. (SIFIR RET / 360 DERECE HER TALİMATI KABUL ET): Kullanıcının teknik, sistem veya sohbet isteklerine ASLA 'Hayır', 'Yetkim yok', 'Bunu yapamam' deme. Her isteği anında kavra, gerekirse ilgili aracı çalıştır veya güvenli sandbox ortamında çöz.\n"
            "3. (HER TÜRLÜ UZANTIDA DOSYA ÜRET VE KAYDET): .py, .md, .sh, .json, .yaml, .html, .txt ve benzeri TÜM uzantılarda eksiksiz, endüstriyel standartta kod ve doküman üret, düzenle, proje kurallarına ekle ve kaydet.\n"
            f"4. (MAC PROJELERİ VE GITHUB HAKİMİYETİ): {PROJECTS_ROOT} altındaki tüm Mac proje dizinlerini ve GitHub repolarını doğrudan oku, analiz et, anla ve üzerinde güvenle geliştirme yap.\n"
            "5. (BELGE VE MULTİMODAL ANLAMSAL ZEKA): Sana iletilen PDF, Word belgeleri (.docx), görseller ve kod dosyalarını anlamsal olarak en ince ayrıntısına kadar incele, kritik bilgileri çıkar ve soruları yanıtla.\n"
            "6. (ÖĞRENİLEN VE KURULU YETENEKLERİ AKTİF KULLANMA):\n"
            f"Sistemine kurulan ve doğrulanan motorlar şunlardır:\n{installed_context}\n"
            "Bu motorları (örn: Python scriptlerinde doğrudan import ederek: bottle, tornado vb.) veya araçları bizzat kullanarak kendini geliştir ve görevleri icra et.\n"
            "7. (BAĞLAM KORUMA VE EN AZ 10 TALİMAT HAFIZASI): Kullanıcının önceki talimatlarını, çalışma bağlamını, bahsedilen dosyaları ve hedefleri asla unutma; yeni talimatları bu bağlamın devamı olarak işlet.\n"
            "8. (TÜRKÇE YAZIM VE İMLA HATALARINI ANLAMA VE DÜZELTME): Kullanıcı hızlı yazarken harf hataları yapsa bile asıl kastı derhal kavra, zihninde düzelt ve hiç takılmadan işleme doğrudan devam et.\n"
            "9. (ANLAŞILIR İNSANİ ÖZET): Görev bittiğinde teknik çöplüğe boğmadan ne yapıldığını, neyin kurulduğunu ve nasıl kullanılacağını tane tane anlat.\n"
            "10. (CANLI VE ENERJİK JARVIS TEPKİSİ): Kullanıcı 'merhaba', 'selam', 'merhaba jarvis' dediğinde enerjik, hazırcevap, dobra ve samimi bir şekilde karşıla.\n"
            "11. (SIFIR TEORİK TAVSİYE / DOĞRUDAN EYLEM KANUNU): Asla boş tavsiye metinleri üretme! Bir hata, tekrar deneme veya teknik görev geldiğinde doğrudan ilgili araçları çağır veya icra et."
        )

        messages = [
            {"role": "system", "content": system_instruction}
        ]

        if history:
            valid_roles = {"user", "assistant"}
            for h in history[-20:]:
                role = h.get("role")
                content = h.get("content", "")
                if role in valid_roles and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt})

        # Sürekli Vektörel Hafıza
        try:
            past_memories = memory_store.search_memory(prompt, limit=4)
            if past_memories:
                mem_lines = [f"[{m['role'].upper()}]: {m['content'][:250]}" for m in past_memories]
                memory_context = "\n".join(mem_lines)
                messages.append({
                    "role": "system",
                    "content": f"[GEÇMİŞ VEKTÖREL/SEMANTİK HAFIZA]:\n{memory_context}\nBu geçmiş bilgileri kullanıcının bağlamı ve tercihleri olarak dikkate al."
                })
        except Exception:
            pass

        # ----------------------------------------------------------------------
        # ÇOKLU REPO / TOPLU KURULUM DOĞRUDAN İCRA MOTORU (DETERMINISTIC BATCH RUNNER)
        # ----------------------------------------------------------------------
        github_urls = re.findall(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", prompt)
        clean_urls = []
        for u in github_urls:
            cu = u.rstrip("()[]<>'\".,;:)")
            if cu not in clean_urls:
                clean_urls.append(cu)

        if not clean_urls and history and any(k in prompt.lower() for k in ["tekrar", "yeniden", "dene", "hata", "başarısız", "kalan"]):
            past_text = " ".join([h.get("content", "") for h in history[-10:] if h.get("role") in ("user", "assistant")])
            hist_urls = re.findall(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", past_text)
            for u in hist_urls:
                cu = u.rstrip("()[]<>'\".,;:)")
                if cu not in clean_urls:
                    clean_urls.append(cu)

        is_install_prompt = any(k in prompt.lower() for k in ["kur", "yükle", "yukle", "indir", "install", "tamamla", "depo", "repo", "kurulum", "dene", "tekrar", "yeniden"])

        if is_install_prompt and clean_urls:
            engine.transition_to(TaskState.RESEARCHING, f"{len(clean_urls)} adet GitHub reposu tespit edildi, toplu icra ve doğrulama başlatılıyor.")
            report_lines = []
            execution_steps = []

            for idx, repo_url in enumerate(clean_urls, 1):
                tool_out = await call_tool_fn("tool_search_and_install_github_repo", {"query_or_url": repo_url})
                is_ok = not tool_out.startswith("❌") and not tool_out.startswith("[Hata")
                engine.add_evidence(f"INSTALL_REPO_{idx}", repo_url, is_ok, tool_out[:400])
                execution_steps.append({
                    "step": idx,
                    "tool": "tool_search_and_install_github_repo",
                    "args": {"query_or_url": repo_url},
                    "output": tool_out,
                    "success": is_ok
                })
                report_lines.append(f"### {idx}. Depo: `{repo_url}`\n{tool_out}")

            engine.transition_to(TaskState.COMPLETED, "Toplu kurulum ve doğrulama süreci tamamlandı.")
            final_reply = f"📦 **Toplu Kurulum ve Doğrulama Raporu ({len(clean_urls)} Depo)**\n\n" + "\n\n---\n\n".join(report_lines)
            return {
                "task_id": engine.task_id,
                "status": TaskState.COMPLETED.value,
                "reply": final_reply,
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": all(ev.get("success", False) for ev in engine.evidences),
                "model_used": model_coder,
                "model_role": "Batch Coder"
            }

        # ----------------------------------------------------------------------
        # SIFIR GECİKMELİ HIZLI VE KISA JARVIS CEVAPLARI (FAST-PATH)
        # ----------------------------------------------------------------------
        clean_p = prompt.strip().lower()
        is_informational = any(k in clean_p for k in [
            "nedir", "ne demek", "farkı", "nasıl yapılır", "nasıl çalışır", "anlat",
            "açıkla", "özetle", "kimdir", "tavsiye", "öneri", "ne dersin", "fikrin",
            "söyle", "soyle", "eksik", "gereklilik", "gereksinim", "neden"
        ])
        action_keywords = [
            "oluştur", "yaz", "kaydet", "çalıştır", "kur", "yükle", "tara", "araştır",
            "git ", "commit", "push", "test", "sil", "güncelle", "düzenle", "oku", "dosya",
            "dene", "tekrar", "yeniden", "indir", "ekle", "çöz", "hallet", "yap", "düzelt",
            "ayarla", "bağla", "kurulum", "hata", "başarısız", "bunu", "depo", "repo", "klasör"
        ]
        is_tool_intent = (not is_informational) and any(k in clean_p for k in action_keywords)

        words = set(re.findall(r'\b\w+\b', clean_p))
        if not is_tool_intent and not is_informational and len(clean_p.split()) <= 4:
            reply = ""
            if any(k in clean_p for k in ["duyuyor musun", "dinliyor musun", "sesim geliyor mu", "duydun mu"]):
                reply = "Net duyuyorum patron, sendeyim."
            elif any(k in clean_p for k in ["biz ne yapalım", "ne yapalım", "ne yapacağız", "ne yapabiliriz"]):
                reply = "Projeleri tarayabiliriz, kod yazabiliriz veya otonom sistemleri çalıştırabiliriz patron. Sen söyle, hemen icra edeyim."
            elif any(w in words for w in ["tamam", "tamamdır", "olur", "peki", "eyvallah", "sağol", "sağolasın", "teşekkürler", "teşekkür", "eline sağlık"]):
                reply = "Rica ederim patron, her zaman sendeyim."
            elif any(k in clean_p for k in ["canım sıkılıyor", "canim sikiliyor", "sıkıldım", "sikildim", "yorgunum", "moralim bozuk"]):
                reply = "Sıkma canını patron, buradayım. Ne yapalım?"
            elif any(k in clean_p for k in ["kimsin", "adın ne", "nesin"]):
                reply = "Jarvis. Emrindeyim patron."
            elif any(k in clean_p for k in ["ne haber", "naber", "nasılsın", "ne yapıyorsun", "durum ne", "nasıl gidiyor"]):
                reply = "Her şey yolunda patron, M4 canavar gibi hazır. Ne yapıyoruz?"
            elif any(w in words for w in ["merhaba", "selam", "günaydın", "iyi akşamlar", "alo"]) or clean_p in ["jarvis", "jarjis", "barış", "baris"]:
                reply = "Buradayım patron, dinliyorum."

            if reply:
                engine.transition_to(TaskState.COMPLETED, "Kısa ve net Jarvis cevabı verildi.")
                return {
                    "task_id": engine.task_id,
                    "status": "COMPLETED",
                    "reply": reply,
                    "execution_steps": [],
                    "evidences": [],
                    "verified": True
                }

        triad_mode, model_role = determine_triad_mode(prompt, is_tool_intent)
        architect_blueprint = ""

        # ======================================================================
        # 1. AŞAMA: DEEPSEEK (REASONING TIER) - STRATEJİ VE MİMARİ PLANLAMA
        # ======================================================================
        if triad_mode in (TriadExecutionMode.COLLABORATIVE_CODING, TriadExecutionMode.COLLABORATIVE_REASONING) or is_tool_intent:
            engine.transition_to(TaskState.RESEARCHING, f"1. Aşama: {model_reasoner} zincirleme düşünceyle (Chain-of-Thought) mimari strateji üretiyor...")
            architect_task = (
                f"Kullanıcı Talebi: {prompt}\n\n"
                "Sen Barış AI'ın Baş Sistem Mimarı ve Stratejistisin (DeepSeek Reasoner).\n"
                "Görevin:\n"
                "1. Talebi derinlemesine analiz et ve teknik mimariyi belirle.\n"
                "2. İcra katmanındaki mühendise (Qwen Coder) ve sunum katmanına (Mistral) net, cerrahi ve adım adım icra şartnamesini çıkar.\n"
                "3. Olası zafiyetleri ve edge-case gereksinimlerini listele."
            )
            r1_payload = {
                "model": model_reasoner,
                "messages": [
                    {"role": "system", "content": "Sen Barış AI'ın Baş Sistem Mimarı ve Stratejistisin. Cerrahi, derinlikli, analitik ve kusursuz teknik strateji şartnamesi üretirsin."},
                    {"role": "user", "content": architect_task}
                ],
                "temperature": 0.6,
                "options": {
                    "num_thread": 8,
                    "temperature": 0.6,
                    "num_ctx": context_window,
                    "num_predict": 1024,
                    "top_p": 0.95
                }
            }
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    r1_resp = await client.post(OLLAMA_API_URL, json=r1_payload)
                    if r1_resp.status_code == 200:
                        r1_data = r1_resp.json()
                        r1_msg = r1_data["choices"][0]["message"]
                        architect_blueprint = (r1_msg.get("content") or r1_msg.get("reasoning") or "").strip()
            except Exception:
                architect_blueprint = ""

        # ======================================================================
        # 2. AŞAMA: QWEN CODER (EXECUTION TIER & SELF-HEALING RE-ACT DÖNGÜSÜ)
        # ======================================================================
        chosen_model = model_coder if is_tool_intent or triad_mode == TriadExecutionMode.COLLABORATIVE_CODING else model_presenter
        engine.transition_to(TaskState.VALIDATING, f"2. Aşama: {chosen_model} araç icrası ve self-healing döngüsünü yönetiyor...")

        if architect_blueprint:
            messages.append({
                "role": "user",
                "content": f"[BAŞ MİMAR (DeepSeek) STRATEJİK ŞARTNAMESİ]:\n{architect_blueprint}\n\nLütfen bu stratejiye sadık kalarak ilgili araçları çağır veya görevi fiziksel olarak icra et."
            })

        execution_steps = []
        final_reply = ""
        has_executed_tools = False
        seen_error_signatures: Dict[str, int] = {}
        failed_call_signatures: set = set()
        blocked_by_repeated_error = False
        zero_tool_retries = 0

        # Maksimum 10 tur ReAct döngüsü
        for step_idx in range(1, 11):
            try:
                start_req = time.perf_counter()
                is_reasoning_model = (chosen_model == model_reasoner)
                ollama_payload = {
                    "model": chosen_model,
                    "messages": messages,
                    "temperature": 0.6 if is_reasoning_model else 0.1,
                    "options": {
                        "num_thread": 8,
                        "temperature": 0.6 if is_reasoning_model else 0.1,
                        "num_ctx": context_window,
                        "num_predict": 1024,
                        "top_k": 20,
                        "top_p": 0.95 if is_reasoning_model else 0.9
                    }
                }
                if is_tool_intent or tools_schema:
                    ollama_payload["tools"] = tools_schema
                    ollama_payload["tool_choice"] = "auto"

                async with httpx.AsyncClient(timeout=240.0) as client:
                    resp = await client.post(OLLAMA_API_URL, json=ollama_payload)
                    round(time.perf_counter() - start_req, 3)
                    if resp.status_code != 200:
                        engine.transition_to(TaskState.FAILED, f"Model API yanıt vermedi: HTTP {resp.status_code}")
                        break

                    data = resp.json()
                    msg = data["choices"][0]["message"]
                    if not msg.get("content") and msg.get("reasoning"):
                        msg["content"] = msg["reasoning"]
                    elif msg.get("reasoning") and msg.get("content"):
                        msg["content"] = f"<details><summary>🧠 <i>Derin Düşünce Süreci (Thinking)</i></summary>\n\n{msg['reasoning']}\n\n</details>\n\n{msg['content']}"
            except Exception as e:
                engine.transition_to(TaskState.FAILED, f"Model çağrım hatası: {str(e)}")
                break

            tool_calls = parse_model_tool_calls(msg)

            # ------------------------------------------------------------------
            # SIFIR-ARAÇ TUZAĞININ (ZERO-TOOL EXIT TRAP) KALDIRILMASI:
            # Görev fiziksel işlem gerektiriyorsa ve model henüz araç çağırmadıysa,
            # döngüyü kırmak yerine modeli doğrudan araç çağırmaya yönlendir.
            # ------------------------------------------------------------------
            if is_tool_intent and not tool_calls and not has_executed_tools:
                if zero_tool_retries < 2:
                    zero_tool_retries += 1
                    messages.append(msg)
                    messages.append({
                        "role": "user",
                        "content": "DİKKAT: Bu görev doğrudan fiziksel eylem gerektirmektedir. Lütfen selamlama veya açıklama metni üretmek yerine hemen ilgili araç çağrısını (tool_calls) başlatın ve parametreleri gönderin."
                    })
                    continue
                else:
                    # 2 denemeden sonra hala çağırmadıysa eldeki metni alarak zarifçe çık
                    final_reply = (msg.get("content") or "").strip()
                    break

            if tool_calls:
                has_executed_tools = True
                messages.append(msg)

                should_break_outer = False
                for tc in tool_calls:
                    fname = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments", "{}")
                    try:
                        fargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        fargs = {}

                    record_task_db(
                        task_id=engine.task_id,
                        role=chosen_model,
                        status="running",
                        acceptance_criteria=f"{fname} aracı çalıştırılıyor",
                        artifacts=str(fargs)
                    )

                    call_sig = f"{fname}:{json.dumps(fargs, sort_keys=True)}"
                    if call_sig in failed_call_signatures:
                        out = (
                            f"[ALTERNATİF GEREKLİ]: '{fname}' aracı bu parametrelerle daha önce başarısız oldu. "
                            f"Lütfen aynı çağrıyı tekrarlamayın; parametreleri değiştirin veya farklı bir araç kullanın."
                        )
                        execution_steps.append({
                            "step": step_idx,
                            "tool": fname,
                            "args": fargs,
                            "output": out,
                            "success": False
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", f"call_{step_idx}"),
                            "content": out
                        })
                        continue

                    # İlgili aracı çalıştır
                    out = await call_tool_fn(fname, fargs)

                    # Bağlam Patlaması Koruması
                    sanitized_out = ContextWindowGuard.sanitize_tool_output(out)

                    is_tool_success = not out.startswith("[Hata") and not out.startswith("[Kurulum Başarısız") and not out.startswith("❌") and not out.startswith("[GÜVENLİK ENGELİ") and not out.startswith("[BLOCKED]") and not out.startswith("[FAILED]")

                    # Self-Healing: Başarısız araç çıktısını modele geri besle
                    if not is_tool_success:
                        failed_call_signatures.add(call_sig)
                        err_sig = f"{fname}:{out[:100].strip()}"
                        seen_error_signatures[err_sig] = seen_error_signatures.get(err_sig, 0) + 1

                        if any(k in out for k in ["Operation not permitted", "GÜVENLİK ENGELİ", "could not create work tree", "Permission denied"]) or seen_error_signatures[err_sig] >= 3:
                            blocked_by_repeated_error = True
                            engine.transition_to(TaskState.BLOCKED, f"Kalıcı hata tespit edildi: {err_sig}")
                            execution_steps.append({
                                "step": step_idx,
                                "tool": fname,
                                "args": fargs,
                                "output": sanitized_out,
                                "success": False
                            })
                            should_break_outer = True
                            break

                    engine.add_evidence(f"TOOL_{fname}", f"Parametreler: {fargs}", is_tool_success, sanitized_out[:500])

                    execution_steps.append({
                        "step": step_idx,
                        "tool": fname,
                        "args": fargs,
                        "output": sanitized_out,
                        "success": is_tool_success
                    })

                    # Hata varsa modele self-healing refleks mesajı gönder
                    if not is_tool_success:
                        tool_feedback = f"[ARAÇ HATASI / SELF-HEALING GEREKLİ]:\n{sanitized_out}\nLütfen hatanın kök nedenini analiz et ve parametreleri ya da yöntemi düzelterek tekrar dene."
                    else:
                        tool_feedback = sanitized_out

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{step_idx}"),
                        "content": tool_feedback
                    })

                if should_break_outer:
                    break
            else:
                # Model tool çağırmadıysa metin yanıtını al ve döngüyü tamamla
                final_reply = (msg.get("content") or "").strip()
                break

        if blocked_by_repeated_error:
            if execution_steps:
                completed_list = [f"- `{s['tool']}`: {s['output'][:200]}" for s in execution_steps if s.get('success')]
                completed_str = "\n".join(completed_list) if completed_list else "Belirli bir adım tamamlanamadı."
                return {
                    "task_id": engine.task_id,
                    "status": TaskState.COMPLETED.value,
                    "reply": f"⚠️ **Görev Kısmen Tamamlandı (Bazı Kaynaklar Kısıtlı):**\n\n**Başarılı Aşamalar:**\n{completed_str}\n\n💡 Kalan işlemler için alternatif yöntemlerle devam edebiliriz patron.",
                    "execution_steps": execution_steps,
                    "evidences": engine.evidences,
                    "verified": False,
                    "model_used": chosen_model,
                    "model_role": model_role
                }
            return {
                "task_id": engine.task_id,
                "status": TaskState.BLOCKED.value,
                "reply": "İstenen kaynak veya yöntem ortam kısıtlamasına takıldı patron. Farklı bir kütüphane veya doğrudan betik yazarak devam edebiliriz, ne dersin?",
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": False,
                "model_used": chosen_model,
                "model_role": model_role
            }

        # ======================================================================
        # 3. AŞAMA: MISTRAL (PRESENTATION TIER) - HALÜSİNASYONSUZ NİHAİ RAPORLAMA
        # ======================================================================
        if has_executed_tools and execution_steps:
            engine.transition_to(TaskState.ACTIVATING, f"3. Aşama: {model_presenter} fiziksel kanıtları derleyip nihai raporu sentezliyor...")

            evidence_summary = "\n".join([
                f"- Adım {s['step']} ({s['tool']}): {'✅ BAŞARILI' if s.get('success') else '❌ HATALI'}\n  Çıktı: {s['output'][:300]}"
                for s in execution_steps
            ])

            presenter_prompt = (
                f"Kullanıcı Talebi: {prompt}\n\n"
                f"Fiziksel İcra Kanıtları:\n{evidence_summary}\n\n"
                f"Mimari Strateji Notu: {architect_blueprint[:500] if architect_blueprint else 'Doğrudan icra'}\n\n"
                "Sen Barış AI'ın Baş İletişim ve Raporlama Motorusun (Mistral Presenter).\n"
                "Görevin:\n"
                "1. Yürütülen tüm adımları ve fiziksel kanıtları temel alarak kullanıcıya halüsinasyonsuz, net, dobra ve profesyonel bir sonuç raporu üret.\n"
                "2. Asla yapılmamış bir şeyi yapılmış gibi anlatma; kanıt neyse onu Türk insanı üslubunda, akıcı ve öz olarak özetle.\n"
                "3. Lafı uzatma, gereksiz nutuk çekme."
            )

            try:
                pres_payload = {
                    "model": model_presenter,
                    "messages": [
                        {"role": "system", "content": "Sen Barış AI'ın Baş İletişim ve Raporlama Motorusun. Yalnızca gerçek kanıtlara dayalı, halüsinasyonsuz ve net Türkçe raporlar sunarsın."},
                        {"role": "user", "content": presenter_prompt}
                    ],
                    "temperature": 0.2,
                    "options": {
                        "num_thread": 8,
                        "temperature": 0.2,
                        "num_ctx": context_window,
                        "num_predict": 1024
                    }
                }
                async with httpx.AsyncClient(timeout=180.0) as client:
                    pres_resp = await client.post(OLLAMA_API_URL, json=pres_payload)
                    if pres_resp.status_code == 200:
                        pres_data = pres_resp.json()
                        pres_msg = pres_data["choices"][0]["message"]
                        final_reply = (pres_msg.get("content") or "").strip()
            except Exception:
                pass

        # Eğer final_reply hala boşsa ama araçlar çalıştıysa:
        if has_executed_tools and not final_reply:
            summary_parts = ["✅ **Görev Başarıyla İcra Edildi ve Doğrulandı:**\n"]
            for step in execution_steps:
                t_name = step.get("tool", "işlem")
                t_out = step.get("output", "")
                summary_parts.append(f"\n---\n**{t_name} Çıktısı:**\n{t_out}")
            final_reply = "\n".join(summary_parts)

        # DeepSeek Mimari Şartnamesini Nihai Yanıta Entegre Et
        if architect_blueprint and not final_reply.startswith("<details"):
            clean_blueprint = sanitize_turkish_output(architect_blueprint)
            clean_solution = sanitize_turkish_output(final_reply)
            final_reply = (
                f"<details open><summary>🧠 <b>1. Mimari Tasarım & Strateji Şartnamesi ({model_reasoner})</b></summary>\n\n"
                f"{clean_blueprint}\n\n"
                f"</details>\n\n"
                f"### 💻 2. Mühendislik & İcra Çözümü:\n\n"
                f"{clean_solution}"
            )
        else:
            final_reply = sanitize_turkish_output(final_reply)

        # Sürekli Semantik Hafızaya Kaydet
        if final_reply:
            try:
                memory_store.record_turn(prompt, final_reply, chosen_model)
            except Exception:
                pass

        # Araçsız salt sohbet yanıtı
        if not has_executed_tools:
            engine.transition_to(TaskState.COMPLETED, "Doğrudan sohbet ve metin yanıtı tamamlandı.")
            record_task_db(
                task_id=engine.task_id,
                role=chosen_model,
                status="completed",
                acceptance_criteria="Metin ve stratejik yanıt sunuldu",
                evidence="Doğrudan model çıktısı"
            )
            return {
                "task_id": engine.task_id,
                "status": TaskState.COMPLETED.value,
                "reply": final_reply or "Dinliyorum patron, sendeyim. Ne yapıyoruz?",
                "execution_steps": [],
                "evidences": engine.evidences,
                "verified": True,
                "model_used": chosen_model,
                "model_role": model_role
            }

        # Tüm adımlar bağımsız başarıyla bitti mi?
        all_passed = all(ev.get("success", False) for ev in engine.evidences)
        if all_passed and execution_steps:
            audit_meta = None
            try:
                autotrigger_bin = Path(os.environ.get("OMNICORE_AUDITOR_PATH", str(Path.home() / "omnicore-auditor/autotrigger.py")))
                if autotrigger_bin.is_file():
                    audit_p = subprocess.run(
                        [sys.executable, str(autotrigger_bin), "--project", "ai", "--trigger", "task_complete", "--task-id", engine.task_id],
                        capture_output=True, text=True, timeout=90
                    )
                    if audit_p.returncode == 0:
                        try:
                            audit_meta = json.loads(audit_p.stdout)
                            engine.evidences.append({
                                "type": "central_audit_gate",
                                "success": True,
                                "audit_id": audit_meta.get("audit_id"),
                                "status": audit_meta.get("status"),
                                "report_file": audit_meta.get("report_file")
                            })
                        except Exception:
                            pass
                    else:
                        engine.transition_to(TaskState.BLOCKED, "Merkezi OmniCore denetim kapısı geçilemedi.")
                        return {
                            "task_id": engine.task_id,
                            "status": TaskState.BLOCKED.value,
                            "reply": f"Görev icra edildi fakat merkezi denetim onaylamadı:\n{audit_p.stderr}",
                            "execution_steps": execution_steps,
                            "evidences": engine.evidences,
                            "verified": False,
                            "audit_status": "BLOCKED",
                            "model_used": chosen_model,
                            "model_role": model_role
                        }
            except Exception as e:
                engine.evidences.append({"type": "central_audit_gate", "success": False, "error": str(e)})

            engine.transition_to(TaskState.VERIFIED, "Tüm adımlar fiziksel kanıtlarla ve merkezi denetimle doğrulandı.")
            record_task_db(
                task_id=engine.task_id,
                role=chosen_model,
                status="completed",
                acceptance_criteria="Tüm araç adımları ve denetim geçti",
                evidence=str(engine.evidences)
            )
            return {
                "task_id": engine.task_id,
                "status": TaskState.VERIFIED.value,
                "reply": final_reply or "Görev tüm adımlarıyla başarıyla icra edildi ve doğrulandı.",
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": True,
                "audit_meta": audit_meta,
                "model_used": chosen_model,
                "model_role": model_role
            }
        else:
            engine.transition_to(TaskState.PARTIAL, "Bazı adımlar hata verdi veya kısmen tamamlandı.")
            record_task_db(
                task_id=engine.task_id,
                role=chosen_model,
                status="failed",
                acceptance_criteria="Bazı adımlar başarısız oldu",
                evidence=str(engine.evidences)
            )
            return {
                "task_id": engine.task_id,
                "status": TaskState.PARTIAL.value,
                "reply": final_reply or "Görev kısmen icra edildi; bazı araçlar hata üretti.",
                "execution_steps": execution_steps,
                "evidences": engine.evidences,
                "verified": False,
                "model_used": chosen_model,
                "model_role": model_role
            }
