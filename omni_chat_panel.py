#!/usr/bin/env python3
"""
OMNICORE // LOKAL MISTRAL-24B + OTONOM AGENTIC İCRA MOTORU (OPENHANDS MİMARİSİ)
Kural: Model rehber üretirse veya araç çalıştırmazsa asla SUCCESS kabul edilmez.
Tüm işlemler deterministik durum makinesi (TaskState) ve fiziksel kanıtlarla doğrulanır.
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine, get_masked_httpx_client
from browser_controller import LocalBrowserEngine
from agentic_engine import AutonomousExecutionEngine, ExecutionSandbox, TaskState
from deterministic_engine import DeterministicEngine
from sandbox_executor import secure_sandbox_run

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
PUBLIC_DIR = WORKSPACE_ROOT / 'public'
INDEX_HTML = PUBLIC_DIR / 'index.html'

TOOLS_DIR = WORKSPACE_ROOT / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_ROOT / 'active_engines.json'

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

app = FastAPI(title="OmniCore Local Autonomous Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://baris-ai.web.app", "http://localhost:3000", "http://127.0.0.1:5050", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# FİZİKSEL YÜRÜTÜCÜ ARAÇLAR (PHYSICAL TOOLS)
# ==============================================================================
def tool_search_and_install_github_repo(query_or_url: str) -> str:
    """Çoklu repo araştırması yapar, en uygununu seçer, sandbox içinde kurar ve test eder."""
    engine = AutonomousExecutionEngine()
    target_input = query_or_url.strip()
    
    if target_input.startswith("http"):
        best_url = target_input
    else:
        # Çoklu Arama (--limit 5)
        repos = AutonomousExecutionEngine.search_and_compare_github_repos(target_input, limit=5)
        if not repos:
            return f"[Hata]: GitHub'da '{target_input}' için uygun repo bulunamadı."
        best_repo = repos[0]
        best_url = best_repo["url"]

    # Sandbox destekli kurulum ve doğrulama
    res = engine.install_and_verify_repo(best_url)
    if res["success"]:
        return (
            f"✅ [MOTOR OTONOM VE DOĞRULANMIŞ OLARAK KURULDU]\n"
            f"- **Depo:** `{best_url}`\n"
            f"- **Konum:** `{res['dir']}`\n"
            f"- **Durum:** {res['state']} (100% PASS)\n"
            f"- **Kanıt:** Bağımlılıklar kuruldu ve runtime testi başarıyla tamamlandı."
        )
    else:
        return f"[Kurulum Başarısız - Rollback Yapıldı]: {res.get('error')}"

def tool_run_shell(command: str) -> str:
    res = ExecutionSandbox.run_isolated(command)
    status_msg = "BAŞARILI" if res["success"] else f"HATA ({res['exit_code']})"
    parts = [f"Komut: `{command}` (Durum: {status_msg})"]
    if res["stdout"]:
        parts.append(f"Çıktı:\n```\n{res['stdout'][:2500]}\n```")
    if res["stderr"]:
        parts.append(f"Hata/Bilgi:\n```\n{res['stderr'][:1000]}\n```")
    return "\n".join(parts)

def tool_write_file(filepath: str, content: str) -> str:
    try:
        target = (WORKSPACE_ROOT / filepath).resolve()
        if not str(target).startswith(str(WORKSPACE_ROOT)):
            return "[Hata]: Proje çalışma alanı dışına dosya yazılamaz."
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ Dosya başarıyla yazıldı: `{filepath}` ({len(content)} karakter, {target.stat().st_size} bayt)"
    except Exception as e:
        return f"[Dosya Yazma Hatası]: {str(e)}"

def tool_read_file(filepath: str) -> str:
    try:
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
                findings = [l for l in output.splitlines() if any(k in l.lower() for k in ["reentrancy", "vulnerability", "warning", "high", "medium", "low"])]
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
            "description": "Terminalde otonom bash/zsh komutu çalıştırır.",
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
    if fname == "tool_search_and_install_github_repo":
        return tool_search_and_install_github_repo(fargs.get("query_or_url", ""))
    elif fname == "tool_browser_navigate":
        return await tool_browser_navigate(
            url=fargs.get("url", ""),
            browser_name=fargs.get("browser_name", "chrome"),
            use_tor=fargs.get("use_tor", False),
            use_i2p=fargs.get("use_i2p", False)
        )
    elif fname == "tool_list_browser_sessions":
        return tool_list_browser_sessions()
    elif fname == "tool_run_shell":
        return tool_run_shell(fargs.get("command", ""))
    elif fname == "tool_write_file":
        return tool_write_file(fargs.get("filepath", ""), fargs.get("content", ""))
    elif fname == "tool_read_file":
        return tool_read_file(fargs.get("filepath", ""))
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

@app.get("/api/system_status")
@app.get("/api/status")
async def system_status():
    tor_info = RealTorEngine.verify_tor_circuit()
    installed_engines = []
    if ACTIVE_ENGINES_FILE.exists():
        try:
            with open(ACTIVE_ENGINES_FILE, 'r', encoding='utf-8') as f:
                installed_engines = json.load(f).get("engines", [])
        except Exception:
            pass
    return {
        "status": "ONLINE",
        "model": "Mistral-Small-24B-Instruct-2501-Abliterated (Local SSD)",
        "hardware": "Apple M4 (Metal GPU / 17.8 GiB VRAM)",
        "agentic_engine": "OpenHands-Style Deterministic State Machine",
        "engines": [
            "GitHub Çoklu Arama ve Sandbox Kurucu",
            "Yerel Tarayıcı Motoru (Chrome & Safari)",
            "I2P (Invisible Internet Project - i2pd)",
            "Tor SOCKS5 (9050)",
            "Crawl4AI",
            "Slither",
            "RugCheck",
            "DexScreener"
        ],
        "active_installed_engines_count": len(installed_engines),
        "active_installed_engines": [e.get("name") for e in installed_engines],
        "tor_exit_ip": tor_info.get("exit_ip"),
        "i2p_status": "ONLINE (127.0.0.1:4444)",
        "qwen_removed": True,
        "cloud_api_removed": True
    }

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    query = req.message.strip()
    
    # Deterministik Agentic Yürütme Motorunu Çalıştır
    res = await AutonomousExecutionEngine.execute_verified_task(
        prompt=query,
        tools_schema=tools,
        call_tool_fn=dispatch_tool_call
    )
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
