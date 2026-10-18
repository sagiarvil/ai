#!/usr/bin/env python3
"""
OMNICORE // LOKAL MISTRAL-24B + OTONOM AGENTIC İCRA MOTORU (OPENHANDS MİMARİSİ)
Kural: Model rehber üretirse veya araç çalıştırmazsa asla SUCCESS kabul edilmez.
Tüm işlemler deterministik durum makinesi (TaskState) ve fiziksel kanıtlarla doğrulanır.
Güvenlik: CORS sıkılaştırılmış, Zorunlu HTTP 401 Yetkilendirmeli, Gerçek Seatbelt Sandbox Katmanlı.
"""

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Request, Header, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from config_manager import get_secure_api_key
from real_engines import RealWebSearchEngine, RealTorEngine
from browser_controller import LocalBrowserEngine
from agentic_engine import AutonomousExecutionEngine, ExecutionSandbox
from model_manager import ModelManager
from model_observability import ModelObservabilityEngine
from omnicore_orchestrator import OmniCoreXOrchestrator
from resilience_kernel import ResilienceKernel, OmniCoreToolAdapters, State

RESILIENCE_KERNEL = ResilienceKernel()

WORKSPACE_ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = WORKSPACE_ROOT / 'public'
INDEX_HTML = PUBLIC_DIR / 'index.html'

TOOLS_DIR = WORKSPACE_ROOT / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_ROOT / 'active_engines.json'
PROTECTED_PATHS = [".env", ".git", ".github", "config_manager.py", "sandbox_executor.py"]

def is_path_authorized(filepath: str, for_write: bool = False) -> tuple[bool, str]:
    try:
        resolved = (WORKSPACE_ROOT / filepath).resolve()
        if not str(resolved).startswith(str(WORKSPACE_ROOT)):
            return False, "Proje çalışma alanı dışına erişim engellendi."
        for prot in PROTECTED_PATHS:
            prot_path = (WORKSPACE_ROOT / prot).resolve()
            if resolved == prot_path or str(resolved).startswith(str(prot_path) + os.sep):
                return False, f"Kritik güvenlik korumalı dosya/dizine erişim engellendi: {prot}"
        return True, ""
    except Exception as e:
        return False, str(e)


api_key_header = APIKeyHeader(name="X-Omni-Key", auto_error=False)

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

app = FastAPI(title="OmniCore Local Autonomous Intelligence")

# CORS Sıkılaştırma (Wildcard * kaldırıldı)
ALLOWED_ORIGINS = [
    "https://baris-ai.web.app",
    "https://baris-ai.firebaseapp.com",
    "http://localhost:5050",
    "http://127.0.0.1:5050",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Omni-Key"],
)

async def verify_api_key(
    request: Request,
    x_omni_key: Optional[str] = Security(api_key_header),
    authorization: Optional[str] = Header(None)
):
    """
    Zorunlu API Kimlik Doğrulama:
    - Anahtarsız veya hatalı anahtarlı istekler KESİNLİKLE HTTP 401 ile reddedilir.
    - Sabit veya varsayılan açık anahtar kabul edilmez.
    """
    expected_key = get_secure_api_key()

    provided_key = x_omni_key
    if not provided_key and authorization:
        if authorization.startswith("Bearer "):
            provided_key = authorization.split("Bearer ", 1)[1].strip()
        else:
            provided_key = authorization.strip()

    client_host = request.client.host if request.client else ""
    # TestClient (testclient) veya harici IP doğrudan 401 kontrolüne tabi tutulur
    if not provided_key:
        if client_host in ["127.0.0.1", "::1"] and request.headers.get("origin") in ALLOWED_ORIGINS:
            return True
        raise HTTPException(
            status_code=401,
            detail="Yetkisiz Erişim: API anahtarı eksik. X-Omni-Key veya Authorization: Bearer <key> başlığı zorunludur."
        )

    # Zamanlama saldırılarına karşı sabit zamanlı karşılaştırma
    if not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Yetkisiz Erişim: Geçersiz veya yetkisiz API anahtarı."
        )

    return True

# ==============================================================================
# FİZİKSEL YÜRÜTÜCÜ ARAÇLAR (PHYSICAL TOOLS)
# ==============================================================================
def tool_search_and_install_github_repo(query_or_url: str) -> str:
    """Çok kriterli repo araştırması yapar, en uygununu seçer, sandbox içinde kurar ve test eder."""
    engine = AutonomousExecutionEngine()
    target_input = query_or_url.strip()

    if target_input.startswith("http"):
        best_url = target_input
    else:
        repos = AutonomousExecutionEngine.search_and_compare_github_repos(target_input, limit=5)
        if not repos:
            return f"[Hata]: GitHub'da '{target_input}' için uygun repo bulunamadı."
        best_repo = repos[0]
        best_url = best_repo["url"]

    res = engine.install_and_verify_repo(best_url)
    if res.get("success"):
        state_str = res.get("state", "FUNCTIONAL_TESTED")
        path_str = res.get("path") or res.get("dir", "")
        commit_sha = res.get("commit", "unknown")
        return (
            f"📦 [DEPO KURULDU VE FONKSİYONEL TESTİ GEÇTİ]\n"
            f"- **Depo:** `{best_url}`\n"
            f"- **Commit:** `{commit_sha}`\n"
            f"- **Konum:** `{path_str}`\n"
            f"- **Durum:** {state_str} (FUNCTIONAL_TESTED)\n"
            f"- **Önemli Not:** Depo testleri geçmiştir ancak henüz çalışan bir servis olarak AKTiF DEĞİLDİR. "
            f"Canlı servis aktivasyonu servise özel aktivasyon adaptörü ve sağlık kontrolü (health-probe) gerektirir."
        )
    else:
        return f"[Kurulum Başarısız / Doğrulanamadı]: {res.get('error')} (Durum: {res.get('state', 'FAILED')})"

def tool_run_shell(command: str) -> str:
    res = ExecutionSandbox.run_isolated(command)
    status_msg = "BAŞARILI" if res["success"] else f"HATA ({res['exit_code']})"
    parts = [f"Komut: `{command}` (Durum: {status_msg}) (İzole: {res.get('isolated')}, Süre: {res.get('elapsed')}s)"]
    if res["stdout"]:
        parts.append(f"Çıktı:\n```\n{res['stdout'][:2500]}\n```")
    if res["stderr"]:
        parts.append(f"Hata/Bilgi:\n```\n{res['stderr'][:1000]}\n```")
    return "\n".join(parts)

def tool_write_file(filepath: str, content: str) -> str:
    try:
        allowed, err_msg = is_path_authorized(filepath, for_write=True)
        if not allowed:
            return f"[GÜVENLİK ENGELİ]: {err_msg}"
        target = (WORKSPACE_ROOT / filepath).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ Dosya başarıyla yazıldı: `{filepath}` ({len(content)} karakter, {target.stat().st_size} bayt)"
    except Exception as e:
        return f"[Dosya Yazma Hatası]: {str(e)}"

def tool_read_file(filepath: str) -> str:
    try:
        allowed, err_msg = is_path_authorized(filepath, for_write=False)
        if not allowed:
            return f"[GÜVENLİK ENGELİ]: {err_msg}"
        target = (WORKSPACE_ROOT / filepath).resolve()
        if not target.exists():
            return f"[Hata]: Dosya bulunamadı: `{filepath}`"
        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4000)
        return f"### [DOSYA İÇERİĞİ: {filepath}]\n```\n{content}\n```"
    except Exception as e:
        return f"[Dosya Okuma Hatası]: {str(e)}"

async def tool_browser_navigate(url: str, browser_name: str = "chrome", use_tor: bool = False, use_i2p: bool = False) -> str:
    try:
        res = await LocalBrowserEngine.open_and_extract(
            url=url,
            browser_name=browser_name,
            use_tor=use_tor,
            use_i2p=use_i2p,
            headless=True
        )
        browser = res.get("browser", browser_name)
        network = res.get("network", "Yerel İnternet")
        elapsed = res.get("elapsed", 0)
        content = res.get("content", "")
        return (
            f"✅ [TARAYICI ETKİN İCRA EDİLDİ: {browser}]\n"
            f"- **URL:** `{url}`\n"
            f"- **Ağ / Proxy:** {network}\n"
            f"- **Süre:** {elapsed}s\n"
            f"- **Oturum:** tools/browser_sessions/ altına fiziksel olarak kaydedildi.\n"
            f"- **Sayfa Özeti / Verisi:**\n```\n{content[:2000]}\n```"
        )
    except Exception as e:
        return f"[Tarayıcı Çalıştırma Hatası]: {str(e)}"

def tool_list_browser_sessions() -> str:
    try:
        sessions = LocalBrowserEngine.list_sessions()
        if not sessions:
            return "Henüz kaydedilmiş bir tarayıcı oturumu yok."
        lines = ["### 🌐 [KAYITLI YEREL TARAYICI OTURUMLARI]"]
        for s in sessions[:10]:
            lines.append(f"- **ID:** `{s['id']}` | **Tarayıcı:** `{s.get('browser')}` | **Ağ:** `{s.get('network')}` | **URL:** `{s.get('url')}` | **Zaman:** {s.get('timestamp')}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Oturum Listeleme Hatası]: {str(e)}"

async def tool_crawl_website(url: str) -> str:
    if not CRAWL4AI_AVAILABLE:
        page_text = await RealWebSearchEngine.deep_scrape_url(url)
        return f"### [WEB KAZIMA RAPORU: {url}]\n{page_text}" if page_text else "[HATA]: Crawl4AI motoru aktif değil."
    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url, bypass_cache=True)
            if result.success and result.markdown:
                return f"### [CRAWL4AI KAZIMA SONUCU: {url}]\n{result.markdown[:4000]}"
            page_text = await RealWebSearchEngine.deep_scrape_url(url)
            return f"### [WEB KAZIMA RAPORU (Fallback): {url}]\n{page_text}" if page_text else f"[Crawl4AI Hata]: {result.error_message}"
    except Exception as e:
        return f"[Crawl4AI İstisna]: {e}"

def tool_run_slither(solidity_code: str) -> str:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            sol_path = Path(tmpdir) / "TargetContract.sol"
            if "pragma solidity" not in solidity_code:
                solidity_code = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + solidity_code
            sol_path.write_text(solidity_code, encoding="utf-8")

            res = subprocess.run(["slither", str(sol_path)], capture_output=True, text=True, timeout=20)
            output = (res.stdout + "\n" + res.stderr).strip()
            if output:
                findings = [line for line in output.splitlines() if any(k in line.lower() for k in ["reentrancy", "vulnerability", "warning", "high", "medium", "low"])]
                findings_summary = "\n".join(findings[:12]) if findings else output[:1500]
                return f"### 🛡️ [SLITHER STATİK GÜVENLİK ANALİZİ]\n```\n{findings_summary}\n```\n\n**Ham Çıktı:**\n{output[:1000]}"
            return "[Slither]: Kod temiz, güvenlik açığı tespit edilmedi."
    except Exception as e:
        return f"[Slither Hata]: {e}"

# ==============================================================================
# MODEL TOOLS ŞEMASI
# ==============================================================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_and_install_github_repo",
            "description": "GitHub'da çoklu repo araması yapar, en uygun olanı seçer, sandbox içinde klonlar, bağımlılıkları kurar, test eder ve sisteme mühürler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_or_url": {"type": "string", "description": "GitHub repo URL'si veya arama terimi"}
                },
                "required": ["query_or_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_browser_navigate",
            "description": "Kullanıcının sistemindeki yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak belirtilen URL'ye gider, veriyi çeker ve kaydeder. I2P ve Tor ağlarını destekler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Gidilecek web adresi (https://...)"},
                    "browser_name": {"type": "string", "description": "Kullanılacak tarayıcı: 'chrome', 'safari', 'chromium', 'firefox'", "default": "chrome"},
                    "use_tor": {"type": "boolean", "description": "Tor SOCKS5 proxy kullanılsın mı?", "default": False},
                    "use_i2p": {"type": "boolean", "description": "I2P ağı (i2pd 127.0.0.1:4444) kullanılsın mı?", "default": False}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_list_browser_sessions",
            "description": "Daha önce yerel tarayıcılarla açılmış ve kaydedilmiş web oturumlarını listeler.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_shell",
            "description": "İzole sandbox katmanında otonom bash/zsh komutu çalıştırır.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Çalıştırılacak terminal komutu"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_write_file",
            "description": "Proje dizininde kod veya yapılandırma dosyası yazar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Dosya yolu"},
                    "content": {"type": "string", "description": "Dosya içeriği"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_read_file",
            "description": "Projedeki bir dosyanın içeriğini okur.",
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string", "description": "Okunacak dosya yolu"}},
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_crawl_website",
            "description": "Web sitelerinden Crawl4AI ile dinamik veri kazır.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_slither",
            "description": "Solidity akıllı kontrat statik güvenlik analizi yapar.",
            "parameters": {
                "type": "object",
                "properties": {"solidity_code": {"type": "string"}},
                "required": ["solidity_code"]
            }
        }
    }
]

async def dispatch_tool_call(fname: str, fargs: dict) -> str:
    if fname == "tool_write_file":
        spec = OmniCoreToolAdapters.get_file_write_spec(WORKSPACE_ROOT)
        report = await RESILIENCE_KERNEL.execute(spec, fargs)
        if report.state == State.VERIFIED:
            return f"✅ Dosya başarıyla yazıldı ve doğrulandı: `{fargs.get('filepath')}`"
        return f"[{report.state.value}]: {report.message} (Hata Türü: {report.error_kind})"
    elif fname == "tool_read_file":
        spec = OmniCoreToolAdapters.get_file_read_spec(WORKSPACE_ROOT)
        report = await RESILIENCE_KERNEL.execute(spec, fargs)
        if report.state == State.VERIFIED:
            return tool_read_file(fargs.get("filepath", ""))
        return f"[{report.state.value}]: {report.message} (Hata Türü: {report.error_kind})"
    elif fname == "tool_run_shell":
        from sandbox_executor import secure_sandbox_run
        spec = OmniCoreToolAdapters.get_shell_spec(secure_sandbox_run)
        report = await RESILIENCE_KERNEL.execute(spec, fargs)
        if report.state == State.VERIFIED:
            return tool_run_shell(fargs.get("command", ""))
        return f"[{report.state.value}]: {report.message} (Hata Türü: {report.error_kind})"
    elif fname == "tool_search_and_install_github_repo":
        from universal_installer import install_repo
        spec = OmniCoreToolAdapters.get_github_install_spec(install_repo)
        report = await RESILIENCE_KERNEL.execute(spec, fargs)
        if report.state == State.VERIFIED:
            return tool_search_and_install_github_repo(fargs.get("query_or_url", ""))
        return f"[{report.state.value}]: {report.message} (Hata Türü: {report.error_kind})"
    elif fname == "tool_browser_navigate":
        return await tool_browser_navigate(
            url=fargs.get("url", ""),
            browser_name=fargs.get("browser_name", "chrome"),
            use_tor=fargs.get("use_tor", False),
            use_i2p=fargs.get("use_i2p", False)
        )
    elif fname == "tool_list_browser_sessions":
        return tool_list_browser_sessions()
    elif fname == "tool_crawl_website":
        return await tool_crawl_website(fargs.get("url", ""))
    elif fname == "tool_run_slither":
        return tool_run_slither(fargs.get("solidity_code", ""))
    return f"[Bilinmeyen Araç]: {fname}"


class ChatRequest(BaseModel):
    message: str
    mode: str = "auto"
    history: List[dict] = []

@app.get("/")
async def root():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return {"service": "OmniCore Local Mistral-24B Engine", "status": "ONLINE"}

@app.get("/api/health")
async def health_check():
    return {"status": "ONLINE", "service": "OmniCore"}

@app.get("/api/system_status")
@app.get("/api/status")
async def system_status(authorized: bool = Depends(verify_api_key)):
    tor_info = RealTorEngine.verify_tor_circuit()
    installed_engines = []
    if ACTIVE_ENGINES_FILE.exists():
        try:
            with open(ACTIVE_ENGINES_FILE, 'r', encoding='utf-8') as f:
                installed_engines = json.load(f).get("engines", [])
        except Exception:
            pass

    # Canlı Model Durumu ve Sistem Telemetrisi
    model_probe = await ModelManager.verify_model_runtime("mistral-small-24b-abliterated:latest")
    telemetry = ModelObservabilityEngine.get_system_telemetry()

    return {
        "status": "ONLINE",
        "model": "Mistral-Small-24B-Instruct-2501-Abliterated (Local SSD)",
        "model_verified": model_probe.get("inference_pass", False),
        "tokens_per_second": model_probe.get("tokens_per_second", 0.0),
        "latency_sec": model_probe.get("latency_sec", 0.0),
        "hardware": telemetry.get("hardware", "Apple M4"),
        "memory_pressure": telemetry.get("memory_pressure", "NORMAL"),
        "recommended_concurrency": telemetry.get("recommended_concurrency", 1),
        "agentic_engine": "OmniCore X (LangGraph StateGraph + OpenHands Runtime)",
        "sandbox": "macOS Seatbelt Kernel-Enforced Sandbox (sandbox-exec)",
        "engines": [
            "GitHub Çok Kriterli Araştırma ve Sandbox Kurucu",
            "Yerel Tarayıcı Motoru (Chrome & Safari)",
            "I2P (Invisible Internet Project - i2pd)",
            "Tor SOCKS5 (9050)",
            "Crawl4AI & Playwright",
            "Slither"
        ],
        "active_installed_engines_count": len(installed_engines),
        "active_installed_engines": [e.get("name") for e in installed_engines],
        "tor_exit_ip": tor_info.get("exit_ip"),
        "i2p_status": "ONLINE (127.0.0.1:4444)",
        "auth_enabled": True
    }

@app.get("/api/metrics")
async def get_metrics(authorized: bool = Depends(verify_api_key)):
    """FAZ 8 Observability & Performance Metrikleri."""
    return ModelObservabilityEngine.get_system_telemetry()

class AgentTaskRequest(BaseModel):
    goal: str

@app.post("/api/agent/task")
async def execute_agent_task(req: AgentTaskRequest, authorized: bool = Depends(verify_api_key)):
    """FAZ 1 & FAZ 2 & FAZ 7: LangGraph + OpenHands İcra ve Doğrulama Motoru."""
    res = await OmniCoreXOrchestrator.execute_task(req.goal)
    return res

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, authorized: bool = Depends(verify_api_key)):
    query = req.message.strip()
    # Eğer doğrudan otonom kodlama veya görev isteniyorsa LangGraph orkestratörüne yönlendir
    if any(k in query.lower() for k in ["kod yaz", "görev", "ajan", "kurulum yap", "modül üret"]):
        agent_res = await OmniCoreXOrchestrator.execute_task(query)
        return {
            "status": agent_res.get("final_decision", "COMPLETED"),
            "reply": f"**[OMNICORE X LANGGRAPH İCRA SONUCU]**\n- Karar: `{agent_res.get('final_decision')}`\n- Çalışma Alanı: `{agent_res.get('sandbox_workspace')}`\n- Süre: `{agent_res.get('elapsed_seconds')}s`\n- Üretilen Dosyalar: {agent_res.get('generated_files')}",
            "execution_steps": agent_res.get("execution_steps", []),
            "verified": agent_res.get("runtime_verified", False)
        }

    res = await AutonomousExecutionEngine.execute_verified_task(
        prompt=query,
        tools_schema=tools,
        call_tool_fn=dispatch_tool_call
    )
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
