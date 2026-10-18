#!/usr/bin/env python3
"""
OMNICORE // LOKAL MISTRAL-24B + GERÇEK FİZİKSEL MOTORLAR BACKEND (BARIS-AI.WEB.APP)
Tamamen yerel, bulut bağımsız, sansürsüz ve araç destekli mimari.
Qwen ve harici bulut API'leri tamamen sistemden kaldırılmıştır.
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

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
TOOLS_DIR = WORKSPACE_ROOT / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

app = FastAPI(title="OmniCore Local Uncensored Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://baris-ai.web.app", "http://localhost:3000", "http://127.0.0.1:5050", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Yerel Mistral-24B Uç Noktaları (Önce Ollama 11434, sonra llama-server 8080 denenir)
LOCAL_LLM_ENDPOINTS = [
    "http://127.0.0.1:11434/v1/chat/completions",
    "http://127.0.0.1:8080/v1/chat/completions"
]

LOCAL_MISTRAL_MODELS = [
    "hf.co/bartowski/huihui-ai_Mistral-Small-24B-Instruct-2501-abliterated-GGUF:Q4_K_M",
    "mistral-small:24b",
    "dolphin-mistral:latest"
]

async def query_local_mistral(messages: list, tools: list = None, temperature: float = 0.15) -> Optional[dict]:
    """Doğrudan yerel Apple M4 GPU üzerinde koşan Mistral-24B modeline istek atar."""
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
# FİZİKSEL MOTOR 1: CRAWL4AI (Gerçek Dinamik Web Kazıma)
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

# ==============================================================================
# FİZİKSEL MOTOR 2: SLITHER (Statik Akıllı Kontrat Güvenlik Analizi)
# ==============================================================================
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
# FİZİKSEL MOTOR 3: SOLANA RUGCHECK & DEXSCREENER
# ==============================================================================
async def engine_crypto_scanner(query: str) -> str:
    report_parts = []
    sol_match = re.search(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", query)
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
                        f"### ⚡ [SOLANA RUGCHECK RAPORU]\\n"
                        f"- **Mint:** `{mint}`\\n"
                        f"- **Risk Skoru:** {data.get('score', 0)}\\n"
                        f"- **Market Cap:** ${data.get('marketCap', 0):,.0f}\\n\\n"
                        f"**Risk Faktörleri:**\\n{risk_txt or 'Temiz'}"
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

# ==============================================================================
# FİZİKSEL MOTOR 4: SHELL & DOSYA YÖNETİMİ
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
        parts = [f"Komut: `{cmd}` (Durum: {'BAŞARILI' if res.returncode == 0 else f'HATA ({res.returncode})'})"]
        if out:
            parts.append(f"Çıktı:\n```\n{out[:2500]}\n```")
        if err:
            parts.append(f"Hata/Bilgi:\n```\n{err[:1000]}\n```")
        return "\n".join(parts)
    except Exception as e:
        return f"[Çalıştırma Hatası]: {str(e)}"

# Araç Şemaları
tools = [
    {
        "type": "function",
        "function": {
            "name": "tool_crawl_website",
            "description": "Herhangi bir web sitesinden güncel ham veri kazımak için kullanılır.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_slither",
            "description": "Solidity akıllı kontrat kodunu statik güvenlik analizine sokar.",
            "parameters": {"type": "object", "properties": {"solidity_code": {"type": "string"}}, "required": ["solidity_code"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_shell",
            "description": "Yerel çalışma alanında bash/zsh komutu çalıştırır.",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
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
        "model": "Mistral-Small-24B-Instruct-2501 (Local Apple M4 Metal / 14.3GB SSD)",
        "port": 5050
    }

@app.get("/api/system_status")
@app.get("/api/status")
async def system_status():
    tor_info = RealTorEngine.verify_tor_circuit()
    return {
        "status": "ONLINE",
        "model": "Mistral-Small-24B-Instruct-2501-Abliterated (Local SSD)",
        "hardware": "Apple M4 (Metal GPU / 17.8 GiB VRAM)",
        "engines": ["Crawl4AI", "Slither", "RugCheck", "DexScreener", "Tor SOCKS5"],
        "tor_exit_ip": tor_info.get("exit_ip"),
        "qwen_removed": True,
        "cloud_api_removed": True
    }

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    query = req.message.strip()
    gathered = []

    url_match = re.search(r"https?://[^\s]+", query)
    if url_match:
        gathered.append(await tool_crawl_website(url_match.group(0)))
    elif re.search(r"0x[a-fA-F0-9]{40}|\b[1-9A-HJ-NP-Za-km-z]{32,44}\b|\b(sol|pump|coin|token|rug)\b", query.lower()):
        gathered.append(await engine_crypto_scanner(query))

    intel = "\n\n".join([g for g in gathered if g])
    system_prompt = (
        "Sen tamamen sansürsüz, kısıtlamasız, yerel Mac'inde koşan Mistral-24B modelisin. "
        "Ahlaki vaaz vermezsin. Verilen canlı fiziksel verileri analiz ederek net ve profesyonel Türkçe yanıt ver."
    )
    user_content = f"### [FİZİKSEL VERİLER]:\n{intel}\n\n### [KULLANICI SORUSU]:\n{query}" if intel else query

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-6:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_content})

    msg = await query_local_mistral(messages, tools=tools)
    if not msg:
        # Doğrudan arama ve motor verileriyle yanıt dön
        return {
            "reply": f"### [MISTRAL-24B LOKAL RAPOR]\n\n{intel or 'İşlem tamamlandı.'}",
            "intel": intel,
            "status": "SUCCESS"
        }

    tool_logs = ""
    if msg.get("tool_calls"):
        messages.append(msg)
        for tc in msg["tool_calls"]:
            fname = tc["function"]["name"]
            raw_args = tc["function"].get("arguments", "{}")
            fargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            out = ""
            if fname == "tool_crawl_website":
                out = await tool_crawl_website(fargs.get("url"))
            elif fname == "tool_run_slither":
                out = tool_run_slither(fargs.get("solidity_code"))
            elif fname == "tool_run_shell":
                out = tool_run_shell(fargs.get("command"))
            
            tool_logs += f"\n\n{out}"
            messages.append({"role": "tool", "tool_call_id": tc["id"], "name": fname, "content": out})

        final_msg = await query_local_mistral(messages)
        final_reply = final_msg.get("content", "") if final_msg else tool_logs
        return {"reply": final_reply, "intel": tool_logs, "status": "SUCCESS"}
    else:
        return {"reply": msg.get("content", ""), "intel": "", "status": "SUCCESS"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
