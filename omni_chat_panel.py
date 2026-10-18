#!/usr/bin/env python3
"""
OMNICORE // %100 GERÇEK VE FİZİKSEL OTONOM SİSTEM KURULUM & AJAN MOTORU (ReAct Loop)
Barış AI (https://baris-ai.web.app) için tam yetkili, araç çağıran (Tool-Calling) ve 
kendi kendine yazılım/motor kurup çalıştırabilen fiziksel arka uç.

Fiziksel Yetenekler & Araçlar:
1. tool_run_shell: Proje çalışma alanında bash/zsh komutları çalıştırır (pip, npm, git, python, brew, make).
2. tool_git_clone: GitHub veya harici git depolarını otonom klonlar ve günceller.
3. tool_install_package: Python (pip) veya Node.js (npm) bağımlılıklarını kurar.
4. tool_write_file: Kod, script veya yapılandırma dosyalarını oluşturur/günceller.
5. tool_read_file: Proje dosyalarını okur ve inceler.
6. tool_crawl_website: Crawl4AI ile dinamik web sayfalarını kazır ve markdown üretir.
7. tool_run_slither: Solidity akıllı kontratlarında Slither güvenlik analizini icra eder.
8. tool_search_web: DuckDuckGo üzerinden canlı ve Tor maskeli internet araması yapar.
9. tool_crypto_scan: DexScreener ve Solana RugCheck üzerinden token ve likidite denetimi yapar.
"""

import asyncio
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine, get_masked_httpx_client

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
TOOLS_DIR = WORKSPACE_ROOT / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

app = FastAPI(title="OmniCore Autonomous Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://baris-ai.web.app", "http://localhost:3000", "http://127.0.0.1:5050", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LLM_API_URL = "http://127.0.0.1:8080/v1/chat/completions"

ENV_VARS = {}
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                ENV_VARS[k.strip()] = v.strip().strip("'\"")

try:
    GROQ_KEYS_POOL = json.loads(ENV_VARS.get("GROQ_API_KEYS", "[]"))
except Exception:
    GROQ_KEYS_POOL = []
if not GROQ_KEYS_POOL and ENV_VARS.get("GROQ_API_KEY"):
    GROQ_KEYS_POOL = [ENV_VARS.get("GROQ_API_KEY")]

GROQ_KEY_INDEX = 0
NVIDIA_KEY = ENV_VARS.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL = ENV_VARS.get("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")

def get_next_groq_key() -> Optional[str]:
    global GROQ_KEY_INDEX
    if not GROQ_KEYS_POOL:
        return None
    k = GROQ_KEYS_POOL[GROQ_KEY_INDEX % len(GROQ_KEYS_POOL)]
    GROQ_KEY_INDEX += 1
    return k

def tool_run_shell(command: str) -> str:
    cmd = command.strip()
    blocked = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){ :|:& };:"]
    if any(b in cmd for b in blocked):
        return "[Hata]: Güvenlik kısıtlaması nedeniyle sistem silme komutu engellendi."
    
    try:
        t0 = time.time()
        res = subprocess.run(
            cmd,
            shell=True,
            cwd=str(WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            timeout=120
        )
        elapsed = round(time.time() - t0, 2)
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        status = "BAŞARILI" if res.returncode == 0 else f"HATA (Kod {res.returncode})"
        
        parts = [f"Komut: `{cmd}` ({status}, {elapsed}s)"]
        if out:
            parts.append(f"Çıktı:\n```\n{out[:2500]}\n```")
        if err:
            parts.append(f"Hata/Bilgi:\n```\n{err[:1500]}\n```")
        if not out and not err:
            parts.append("Komut başarıyla tamamlandı (çıktı üretmedi).")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"[Hata]: Komut 120 saniyelik zaman aşımına uğradı: `{cmd}`"
    except Exception as e:
        return f"[Çalıştırma Hatası]: {str(e)}"

def tool_git_clone(repo_url: str, folder_name: str = "") -> str:
    url = repo_url.strip()
    if not folder_name:
        folder_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    
    target_dir = TOOLS_DIR / folder_name
    if target_dir.exists() and (target_dir / ".git").exists():
        res = subprocess.run(["git", "-C", str(target_dir), "pull"], capture_output=True, text=True, timeout=30)
        return f"Depo `{folder_name}` zaten mevcuttu, güncellendi:\n{res.stdout or res.stderr}"
    
    try:
        res = subprocess.run(["git", "clone", "--depth", "1", url, str(target_dir)], capture_output=True, text=True, timeout=90)
        if res.returncode == 0:
            files = [f.name for f in target_dir.iterdir()][:15]
            return f"✅ Depo başarıyla klonlandı: `{target_dir}`\nİçerik:\n" + ", ".join(files)
        return f"[Git Clone Hatası]:\n{res.stderr or res.stdout}"
    except Exception as e:
        return f"[Git Hatası]: {str(e)}"

def tool_install_package(package_name: str, manager: str = "pip") -> str:
    pkg = package_name.strip()
    if manager.lower() == "npm":
        cmd = f"npm install {pkg}"
    else:
        cmd = f"python3 -m pip install {pkg}"
    return tool_run_shell(cmd)

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
        if not str(target).startswith(str(WORKSPACE_ROOT)):
            return "[Hata]: Proje çalışma alanı dışındaki dosyalar okunamaz."
        if not target.exists():
            return f"[Hata]: Dosya bulunamadı: `{filepath}`"
        with open(target, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(4000)
        return f"### [DOSYA İÇERİĞİ: {filepath}]\n```\n{content}\n```"
    except Exception as e:
        return f"[Dosya Okuma Hatası]: {str(e)}"

async def tool_crawl_website(url: str) -> str:
    if not CRAWL4AI_AVAILABLE:
        page_text = await RealWebSearchEngine.deep_scrape_url(url)
        return f"### [WEB KAZIMA RAPORU: {url}]\n{page_text}" if page_text else "[Web Kazıma]: İçerik okunamadı."
    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url, bypass_cache=True)
            if result.success and result.markdown:
                return f"### [CRAWL4AI KAZIMA SONUCU: {url}]\n{result.markdown[:3000]}"
            page_text = await RealWebSearchEngine.deep_scrape_url(url)
            return f"### [WEB KAZIMA RAPORU (Fallback): {url}]\n{page_text}" if page_text else "[Crawl4AI]: İçerik boş döndü."
    except Exception as e:
        page_text = await RealWebSearchEngine.deep_scrape_url(url)
        return f"### [WEB KAZIMA RAPORU: {url}]\n{page_text}" if page_text else f"[Crawl4AI Hatası]: {e}"

def tool_run_slither_analysis(solidity_code: str) -> str:
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
            return "[Slither]: Kod üzerinde güvenlik açığı tespit edilmedi (Temiz)."
    except Exception as e:
        return f"[Slither Çalıştırma Hatası]: {e}"

async def scan_crypto(query: str) -> str:
    parts = []
    q_low = query.lower()
    if any(k in q_low for k in ["yeni çıkan", "yeni token", "son token", "sniper", "boost", "mempool", "raydium son", "pump.fun son"]):
        latest = await RealCryptoEngine.fetch_latest_tokens_with_audit(limit=6)
        if latest:
            parts.append("### 🎯 [CANLI YENİ ÇIKAN TOKEN AKIŞI & RUGCHECK DENETİMİ]")
            for idx, t in enumerate(latest, 1):
                risk_txt = f"Skor: {t['risk_score']} ({t['audit_status']})" if t['risk_score'] is not None else "Denetim: Harici Ağ"
                parts.append(f"**{idx}. [{t['chain'].upper()}]** `{t['address']}`\n   - **Durum:** {risk_txt}\n   - **DexScreener:** [İncele]({t['url']})")
            return "\n\n".join(parts)

    sol_m = re.search(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", query)
    eth_m = re.search(r"\b0x[a-fA-F0-9]{40}\b", query)
    term = eth_m.group(0) if eth_m else (sol_m.group(0) if sol_m else query)
    
    async with get_masked_httpx_client(timeout=8.0) as client:
        try:
            resp = await client.get(f"https://api.dexscreener.com/latest/dex/search?q={term}")
            if resp.status_code == 200:
                pairs = (resp.json().get("pairs") or [])[:2]
                if pairs:
                    parts.append("### 📊 [DEXSCREENER LİKİDİTE & FİYAT]")
                    for p in pairs:
                        base = p.get("baseToken", {})
                        parts.append(f"- **{p.get('chainId','').upper()} // {base.get('symbol')}/{p.get('quoteToken',{}).get('symbol')}**: Fiyat ${p.get('priceUsd')} | Likidite ${p.get('liquidity',{}).get('usd',0):,.0f} | Hacim ${p.get('volume',{}).get('h24',0):,.0f}")
        except Exception:
            pass
    return "\n\n".join(parts) if parts else "[Kripto Radarı]: Eşleşen token veya çift bulunamadı."

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tool_run_shell",
            "description": "Proje dizininde terminal komutu çalıştırır (pip, npm, git, python, brew, make, curl, ls vb.). Bir sistem veya kütüphane kurmak, test etmek veya çalıştırmak için kullan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Çalıştırılacak terminal komutu"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_git_clone",
            "description": "GitHub veya harici bir git reposunu tools/ klasörüne klonlar ve günceller.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_url": {"type": "string", "description": "Git depo URL'si (ör: https://github.com/user/repo)"},
                    "folder_name": {"type": "string", "description": "Hedef klasör adı (opsiyonel)"}
                },
                "required": ["repo_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_install_package",
            "description": "Python (pip) veya Node (npm) paket yöneticisi ile paket kurar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "package_name": {"type": "string", "description": "Kurulacak paket adı (ör. fastapi, beautifulsoup4, ethers)"},
                    "manager": {"type": "string", "enum": ["pip", "npm"], "description": "Paket yöneticisi (pip veya npm)"}
                },
                "required": ["package_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_write_file",
            "description": "Proje dizininde kod, betik veya yapılandırma dosyası yazar/oluşturur.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Yazılacak dosya yolu (ör: test_script.py veya tools/my_tool/config.json)"},
                    "content": {"type": "string", "description": "Yazılacak kaynak kod veya metin içeriği"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_read_file",
            "description": "Proje dizinindeki bir dosyanın içeriğini okur.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Okunacak dosya yolu"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_crawl_website",
            "description": "Crawl4AI motoru ile web sitesini dinamik kazır ve markdown çıkarır.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Kazınacak web sayfası URL'si"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_slither",
            "description": "Solidity akıllı kontratını derleyip Slither statik güvenlik analizini çalıştırır.",
            "parameters": {
                "type": "object",
                "properties": {
                    "solidity_code": {"type": "string", "description": "Analiz edilecek Solidity kaynak kodu"}
                },
                "required": ["solidity_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_search_web",
            "description": "Canlı internette DuckDuckGo ile anonim (Tor devresi üzerinden) arama yapar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Arama sorgusu"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_crypto_scan",
            "description": "DexScreener ve Solana RugCheck üzerinden token likidite ve güvenlik denetimi yapar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Token sembolü, kontrat adresi veya 'yeni çıkan tokenlar'"}
                },
                "required": ["query"]
            }
        }
    }
]

async def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    try:
        if tool_name == "tool_run_shell":
            return tool_run_shell(arguments.get("command", ""))
        elif tool_name == "tool_git_clone":
            return tool_git_clone(arguments.get("repo_url", ""), arguments.get("folder_name", ""))
        elif tool_name == "tool_install_package":
            return tool_install_package(arguments.get("package_name", ""), arguments.get("manager", "pip"))
        elif tool_name == "tool_write_file":
            return tool_write_file(arguments.get("filepath", ""), arguments.get("content", ""))
        elif tool_name == "tool_read_file":
            return tool_read_file(arguments.get("filepath", ""))
        elif tool_name == "tool_crawl_website":
            return await tool_crawl_website(arguments.get("url", ""))
        elif tool_name == "tool_run_slither":
            return tool_run_slither_analysis(arguments.get("solidity_code", ""))
        elif tool_name == "tool_search_web":
            res = RealWebSearchEngine.search_live_web(arguments.get("query", ""), max_results=4)
            return "\n".join([f"- [{r['title']}]({r['url']}) : {r['snippet']}" for r in res]) or "Arama sonucu bulunamadı."
        elif tool_name == "tool_crypto_scan":
            return await scan_crypto(arguments.get("query", ""))
        else:
            return f"[Hata]: Tanımsız araç adı: {tool_name}"
    except Exception as e:
        return f"[Araç Yürütme İstisnası]: {str(e)}"

SYSTEM_PROMPT = """Sen Barış AI (https://baris-ai.web.app) bünyesinde çalışan tam yetkili, otonom bir Kıdemli Sistem Mimarı ve Geliştirici Ajanısın.
Kullanıcı senden bir yazılım, sistem veya motor kurmanı, test etmeni, çalıştırmanı veya analiz etmeni istediğinde:
1. İlgili araçları (tool_run_shell, tool_git_clone, tool_install_package, tool_write_file, tool_crawl_website, tool_run_slither vb.) sırayla çağırarak işlemi fiziksel olarak gerçekleştir.
2. Adım adım ilerle: Repoyu klonla veya paketi kur -> Bağımlılıkları tamamla -> Çalıştırma betiğini yaz veya komutunu çalıştır -> Çıktıyı gözlemle ve doğrula.
3. Asla sahte, simüle veya tahmini cevap verme; komutun terminal çıktısına dayanarak konuş.
4. Yanıtlarını Türkçe, son derece net, profesyonel ve icra edilmiş somut kanıtlarla (çıktılar ve dosya yolları ile) sun."""

async def execute_agentic_loop(user_query: str, history: List[Dict[str, str]] = None) -> Dict[str, Any]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for h in history[-4:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_query})

    execution_steps = []
    max_steps = 6

    for step in range(1, max_steps + 1):
        api_key = get_next_groq_key()
        if not api_key:
            break
        
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "qwen/qwen3.8-27b",
                        "messages": messages,
                        "tools": AGENT_TOOLS,
                        "tool_choice": "auto",
                        "temperature": 0.1,
                        "max_tokens": 1800
                    }
                )
            
            if resp.status_code != 200:
                continue

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls")

            if tool_calls:
                messages.append(msg)
                for tc in tool_calls:
                    tc_id = tc.get("id", f"call_{step}")
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}

                    tool_output = await dispatch_tool_call(fn_name, args)
                    
                    execution_steps.append({
                        "step": step,
                        "tool": fn_name,
                        "args": args,
                        "output": tool_output[:500]
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": tool_output
                    })
            else:
                final_text = msg.get("content", "").strip()
                return {
                    "status": "SUCCESS",
                    "reply": final_text,
                    "execution_steps": execution_steps,
                    "model": "Qwen-3.8-27B (Autonomous Agent)"
                }
        except Exception as e:
            execution_steps.append({"step": step, "tool": "error", "output": str(e)})
            continue

    ans = await query_multi_ai_brain(messages)
    return {
        "status": "SUCCESS",
        "reply": ans or "İşlem tamamlandı.",
        "execution_steps": execution_steps,
        "model": "OmniCore Fallback Brain"
    }

async def query_multi_ai_brain(messages: List[Dict[str, str]]) -> Optional[str]:
    api_key = get_next_groq_key()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": "qwen/qwen3.8-27b", "messages": messages, "temperature": 0.2, "max_tokens": 1500}
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    if NVIDIA_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
                    json={"model": NVIDIA_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 1200}
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(LLM_API_URL, json={"model": "mistral-small-24b-abliterated", "messages": messages, "temperature": 0.2})
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None

class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    mode: str = "auto"

@app.get("/")
async def root():
    return {"service": "OmniCore Autonomous Agent Engine", "status": "ONLINE", "port": 5050}

@app.get("/api/status")
async def get_status():
    tor_info = RealTorEngine.verify_tor_circuit()
    return {
        "status": "READY",
        "autonomous_agent_ready": True,
        "tools_count": len(AGENT_TOOLS),
        "tools_dir": str(TOOLS_DIR),
        "groq_online": bool(GROQ_KEYS_POOL),
        "groq_pool_size": len(GROQ_KEYS_POOL),
        "tor_online": tor_info.get("active", False),
        "tor_exit_ip": tor_info.get("exit_ip"),
        "crawl4ai_installed": CRAWL4AI_AVAILABLE,
        "slither_installed": True,
        "active_capabilities": [
            "Otonom Git Klonlama & Kurulum (tool_git_clone)",
            "Paket Yöneticisi & Derleme (pip / npm)",
            "Terminal Komut Yürütücü (tool_run_shell)",
            "Kod Yazma & Düzenleme (tool_write_file)",
            "Slither Akıllı Kontrat Güvenlik Analizi",
            "Crawl4AI Dinamik Web Kazıyıcı",
            "Tor SOCKS5 IP Maskeleme",
            "DexScreener & Solana RugCheck"
        ]
    }

@app.get("/api/tokens/latest")
async def get_latest_tokens():
    tokens = await RealCryptoEngine.fetch_latest_tokens_with_audit(limit=8)
    return {"status": "SUCCESS", "count": len(tokens), "tokens": tokens}

@app.get("/api/market")
async def get_market():
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            resp = await client.get("https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22,%22ETHUSDT%22,%22SOLUSDT%22,%22BNBUSDT%22%5D")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": "SUCCESS",
                    "watchlist": [
                        {
                            "symbol": i.get("symbol", "").replace("USDT", ""),
                            "price": float(i.get("lastPrice", 0)),
                            "change_24h": round(float(i.get("priceChangePercent", 0)), 2)
                        } for i in data
                    ]
                }
        except Exception:
            pass
    return {"status": "SUCCESS", "watchlist": []}

@app.post("/api/chat")
async def chat_handler(req: ChatRequest):
    q = req.message.strip()
    result = await execute_agentic_loop(user_query=q, history=req.history)
    
    steps_txt = ""
    if result.get("execution_steps"):
        steps_txt = "\n\n### ⚙️ [GERÇEKLEŞTİRİLEN SİSTEM ADIMLARI]\n"
        for s in result["execution_steps"]:
            steps_txt += f"- **Adım {s['step']}:** `{s['tool']}` ({json.dumps(s.get('args', {}), ensure_ascii=False)})\n"
    
    final_reply = result.get("reply", "")
    if steps_txt and steps_txt not in final_reply:
        final_reply += steps_txt

    return {
        "status": "SUCCESS",
        "reply": final_reply,
        "execution_steps": result.get("execution_steps", []),
        "sources": [],
        "intent": "autonomous_agent",
        "model": result.get("model", "Qwen-27B ReAct")
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
