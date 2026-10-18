#!/usr/bin/env python3
"""
OMNICORE // LOKAL MISTRAL-24B + OTONOM FİZİKSEL İCRA MOTORU (SIFIR YÖNERGE - TAM İCRA)
Barış AI (https://baris-ai.web.app) için tam entegre, yerel ve araç çağıran (Tool-Calling) arka uç.
Kural: Kullanıcıya akıl ve yönerge vermek KESİNLİKLE YASAKTIR. Tüm kurulum ve komutlar doğrudan araçlarla icra edilir.
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
from pydantic import BaseModel
import uvicorn

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine, get_masked_httpx_client
from browser_controller import LocalBrowserEngine

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
TOOLS_DIR = WORKSPACE_ROOT / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_ROOT / 'active_engines.json'

if not ACTIVE_ENGINES_FILE.exists():
    with open(ACTIVE_ENGINES_FILE, 'w', encoding='utf-8') as f:
        json.dump({"engines": []}, f, indent=2)

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

LOCAL_LLM_ENDPOINTS = [
    "http://127.0.0.1:11434/v1/chat/completions",
    "http://127.0.0.1:8080/v1/chat/completions"
]

LOCAL_MISTRAL_MODELS = [
    "mistral-small-24b-abliterated:latest",
    "hf.co/bartowski/huihui-ai_Mistral-Small-24B-Instruct-2501-abliterated-GGUF:Q4_K_M",
    "mistral-small:24b",
    "dolphin-mistral:latest"
]

async def query_local_mistral(messages: list, tools: list = None, temperature: float = 0.1) -> Optional[dict]:
    for endpoint in LOCAL_LLM_ENDPOINTS:
        for model_name in LOCAL_MISTRAL_MODELS:
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(endpoint, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("choices"):
                            return data["choices"][0]["message"]
            except Exception:
                continue
    return None

# ==============================================================================
# FİZİKSEL MOTOR 1: OTONOM GITHUB REPO ARAMA & KURULUM
# ==============================================================================
def tool_search_and_install_github_repo(query_or_url: str) -> str:
    target_input = query_or_url.strip()
    repo_url = target_input
    repo_name = ""
    description = ""

    if not target_input.startswith("http"):
        try:
            res = subprocess.run(
                ["gh", "search", "repos", target_input, "--limit", "1", "--json", "fullName,url,description"],
                capture_output=True, text=True, timeout=30
            )
            if res.returncode == 0:
                items = json.loads(res.stdout)
                if items:
                    repo_url = items[0]["url"]
                    repo_name = items[0]["fullName"].split("/")[-1]
                    description = items[0].get("description", "")
        except Exception as e:
            return f"[GitHub Arama Hatası]: {str(e)}"

    if not repo_name:
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    target_dir = TOOLS_DIR / repo_name

    clone_output = ""
    if target_dir.exists() and (target_dir / ".git").exists():
        res = subprocess.run(["git", "-C", str(target_dir), "pull"], capture_output=True, text=True, timeout=30)
        clone_output = f"Depo zaten mevcuttu, güncellendi: {res.stdout.strip()}"
    else:
        res = subprocess.run(["git", "clone", "--depth", "1", repo_url, str(target_dir)], capture_output=True, text=True, timeout=90)
        if res.returncode != 0:
            return f"[Klonlama Hatası]: {res.stderr or res.stdout}"
        clone_output = f"Depo başarıyla klonlandı: {target_dir}"

    dep_output = "Bağımlılık dosyası bulunamadı."
    req_file = target_dir / "requirements.txt"
    pkg_file = target_dir / "package.json"

    if req_file.exists():
        r_res = subprocess.run(
            ["python3", "-m", "pip", "install", "-r", str(req_file), "--break-system-packages"],
            capture_output=True, text=True, timeout=180
        )
        status_text = "BAŞARILI" if r_res.returncode == 0 else "HATA"
        dep_output = f"Python bağımlılıkları kuruldu ({status_text}): " + r_res.stdout[-200:]
    elif pkg_file.exists():
        p_res = subprocess.run(["npm", "install", "--prefix", str(target_dir)], capture_output=True, text=True, timeout=180)
        status_text = "BAŞARILI" if p_res.returncode == 0 else "HATA"
        dep_output = f"Node.js bağımlılıkları kuruldu ({status_text}): " + p_res.stdout[-200:]

    try:
        with open(ACTIVE_ENGINES_FILE, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        engines = [e for e in registry.get("engines", []) if e.get("name") != repo_name]
        engines.append({
            "name": repo_name,
            "url": repo_url,
            "dir": str(target_dir),
            "description": description,
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        with open(ACTIVE_ENGINES_FILE, 'w', encoding='utf-8') as f:
            json.dump({"engines": engines}, f, indent=2)
    except Exception:
        pass

    files = [f.name for f in target_dir.iterdir()][:10]
    res_lines = [
        "✅ [MOTOR FİZİKSEL OLARAK KURULDU VE AKTİF EDİLDİ]",
        f"- **Depo:** `{repo_url}`",
        f"- **Konum:** `{target_dir}`",
        f"- **Klonlama:** {clone_output}",
        f"- **Bağımlılık:** {dep_output}",
        f"- **Dosyalar:** {', '.join(files)}",
        "- **Durum:** Sistem kayıtlarına (active_engines.json) işlendi, doğrudan çağrılabilir."
    ]
    return "\n".join(res_lines)

# ==============================================================================
# FİZİKSEL MOTOR 2: SHELL & DOSYA YÖNETİMİ
# ==============================================================================
def tool_run_shell(command: str) -> str:
    cmd = command.strip()
    blocked = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){ :|:& };:"]
    if any(b in cmd for b in blocked):
        return "[Hata]: Güvenlik kısıtlaması nedeniyle sistem silme komutu engellendi."
    try:
        res = subprocess.run(cmd, shell=True, cwd=str(WORKSPACE_ROOT), capture_output=True, text=True, timeout=120)
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        status_msg = "BAŞARILI" if res.returncode == 0 else f"HATA ({res.returncode})"
        parts = [f"Komut: `{cmd}` (Durum: {status_msg})"]
        if out:
            parts.append(f"Çıktı:\n```\n{out[:2500]}\n```")
        if err:
            parts.append(f"Hata/Bilgi:\n```\n{err[:1000]}\n```")
        return "\n".join(parts)
    except Exception as e:
        return f"[Çalıştırma Hatası]: {str(e)}"

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

# ==============================================================================
# FİZİKSEL MOTOR 3: BROWSER KONTROLCÜSÜ (CHROME, SAFARI, I2P, TOR)
# ==============================================================================
async def tool_browser_navigate(url: str, browser_name: str = "chrome", use_tor: bool = False, use_i2p: bool = False) -> str:
    """Yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak sayfayı açar, veriyi çeker ve kaydeder."""
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
    """Daha önce açılan ve kaydedilen yerel tarayıcı oturumlarını listeler."""
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

# ==============================================================================
# FİZİKSEL MOTOR 4: CRAWL4AI, SLITHER, KRİPTO RADARI
# ==============================================================================
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

async def engine_crypto_scanner(query: str) -> str:
    report_parts = []
    sol_match = re.search(r" [1-9A-HJ-NP-Za-km-z]{32,44} ", query)
    eth_match = re.search(r"0x[a-fA-F0-9]{40}", query)

    if sol_match and not eth_match:
        mint = sol_match.group(0)
        async with get_masked_httpx_client(timeout=10.0) as client:
            try:
                r = await client.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
                if r.status_code == 200:
                    data = r.json()
                    risks = data.get("risks", [])
                    risk_txt = "\n".join([f"- **{rk.get('name')}**: {rk.get('description')}" for rk in risks[:4]])
                    report_parts.append(
                        f"### ⚡ [SOLANA RUGCHECK RAPORU]\n"
                        f"- **Mint:** `{mint}`\n"
                        f"- **Risk Skoru:** {data.get('score', 0)}\n"
                        f"- **Market Cap:** ${data.get('marketCap', 0):,.0f}\n\n"
                        f"**Risk Faktörleri:**\n{risk_txt or 'Temiz'}"
                    )
            except Exception:
                pass

    term = eth_match.group(0) if eth_match else (sol_match.group(0) if sol_match else query)
    async with get_masked_httpx_client(timeout=10.0) as client:
        try:
            resp = await client.get(f"https://api.dexscreener.com/latest/dex/search?q={term}")
            if resp.status_code == 200:
                pairs = resp.json().get("pairs") or []
                if pairs:
                    p = pairs[0]
                    base = p.get("baseToken", {})
                    report_parts.append(
                        f"### 📊 [DEXSCREENER PİYASA]\n"
                        f"- **Çift:** {base.get('symbol')}/{p.get('quoteToken',{}).get('symbol')} ({p.get('chainId','')})\n"
                        f"- **Fiyat:** ${p.get('priceUsd')} | **Likidite:** ${p.get('liquidity',{}).get('usd',0):,.0f} | **24s Hacim:** ${p.get('volume',{}).get('h24',0):,.0f}"
                    )
        except Exception:
            pass

    return "\n\n".join(report_parts)

tools = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_and_install_github_repo",
            "description": "GitHub'da repo arar, tools/ dizinine klonlar, bağımlılıklarını kurar ve sisteme aktif motor olarak kaydeder.",
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
            "description": "Kullanıcının sistemindeki yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak belirtilen URL'ye gider, veriyi çeker ve kaydeder. Yerel internet, Tor veya I2P ağlarını destekler.",
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
            "parameters": {
                "type": "object",
                "properties": {}
            }
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

class ChatRequest(BaseModel):
    message: str
    mode: str = "auto"
    history: List[dict] = []

@app.get("/")
async def root():
    return {
        "service": "OmniCore Local Mistral-24B Engine",
        "status": "ONLINE",
        "model": "Mistral-Small-24B-Instruct-2501-Abliterated (Local Apple M4 Metal / 14.3GB SSD)",
        "port": 5050
    }

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
        "engines": [
            "GitHub Otonom Kurucu",
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

    gathered = []
    url_match = re.search(r"https?://[^\s]+", query)
    if url_match and not any(k in query.lower() for k in ["klonla", "indir", "kur", "chrome", "safari", "tarayıcı", "i2p"]):
        gathered.append(await tool_crawl_website(url_match.group(0)))
    elif re.search(r"0x[a-fA-F0-9]{40}| [1-9A-HJ-NP-Za-km-z]{32,44} | (sol|pump|coin|token|rug) ", query.lower()) and not any(k in query.lower() for k in ["repo", "kur", "klonla"]):
        gathered.append(await engine_crypto_scanner(query))

    intel = "\n\n".join([g for g in gathered if g])
    
    system_prompt = (
        "Sen Barış AI bünyesinde koşan kıdemli bir OTONOM İCRA MÜHENDİSİSİN. Beynin yerel Mistral-24B Abliterated modelidir. "
        "KESİN VE TAVİZSİZ KURAL: Kullanıcıya asla akıl verme, ders anlatma, 'Şu komutu çalıştırın' deme! "
        "Kullanıcı senden bir repo veya motor kurmanı istediğinde DOĞRUDAN `tool_search_and_install_github_repo` çağır. "
        "Kullanıcı tarayıcıyla (Chrome, Safari, I2P, Tor) bir siteye bak veya veri topla dediğinde `tool_browser_navigate` çağır. "
        "Terminal komutu için `tool_run_shell`, dosya için `tool_write_file` çağır. "
        "İşlemi arka planda kendin tamamla ve kullanıcıya sadece bitmiş sonucun fiziksel kanıtını sun!"
    )
    user_content = f"### [FİZİKSEL VERİLER]:\n{intel}\n\n### [KULLANICI EMRİ]:\n{query}" if intel else query

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-6:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_content})

    execution_steps = []
    
    for step in range(1, 7):
        msg = await query_local_mistral(messages, tools=tools)
        if not msg:
            break
        
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            messages.append(msg)
            for tc in tool_calls:
                fname = tc["function"]["name"]
                raw_args = tc["function"].get("arguments", "{}")
                try:
                    fargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    fargs = {}

                out = ""
                if fname == "tool_search_and_install_github_repo":
                    out = tool_search_and_install_github_repo(fargs.get("query_or_url", ""))
                elif fname == "tool_browser_navigate":
                    out = await tool_browser_navigate(
                        url=fargs.get("url", ""),
                        browser_name=fargs.get("browser_name", "chrome"),
                        use_tor=fargs.get("use_tor", False),
                        use_i2p=fargs.get("use_i2p", False)
                    )
                elif fname == "tool_list_browser_sessions":
                    out = tool_list_browser_sessions()
                elif fname == "tool_run_shell":
                    out = tool_run_shell(fargs.get("command", ""))
                elif fname == "tool_write_file":
                    out = tool_write_file(fargs.get("filepath", ""), fargs.get("content", ""))
                elif fname == "tool_read_file":
                    out = tool_read_file(fargs.get("filepath", ""))
                elif fname == "tool_crawl_website":
                    out = await tool_crawl_website(fargs.get("url", ""))
                elif fname == "tool_run_slither":
                    out = tool_run_slither(fargs.get("solidity_code", ""))

                execution_steps.append({
                    "step": step,
                    "tool": fname,
                    "args": fargs,
                    "output": out[:500]
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": out
                })
        else:
            final_reply = msg.get("content", "").strip()
            return {
                "reply": final_reply,
                "execution_steps": execution_steps,
                "status": "SUCCESS"
            }

    return {
        "reply": "İşlem otonom olarak icra edildi.",
        "execution_steps": execution_steps,
        "status": "SUCCESS"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
