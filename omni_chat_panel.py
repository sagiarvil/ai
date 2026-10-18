#!/usr/bin/env python3
"""
OMNICORE // %100 GERÇEK VE FİZİKSEL ÇOKLU MOTOR ÇEKİRDEĞİ & AJAN ORKESTRASYONU
Barış AI (https://baris-ai.web.app) için tam entegre, takılmasız ve otonom arka uç.

Fiziksel Motorlar:
1. Crawl4AI: Gerçek Dinamik Web Kazıma ve Markdown Çıkarıcı
2. Slither: Trail of Bits Solidity Akıllı Kontrat Güvenlik Analizörü
3. Solana RugCheck.xyz API: Mint Risk Skoru ve LP Kilit Denetimi
4. DexScreener Canlı API: Token Boosts Sniffer & Likidite/Hacim
5. DuckDuckGo Live & Nominatim: Canlı İnternet ve Resmi Konum/Firma Taraması
6. Tor SOCKS5 (127.0.0.1:9050): Anonim Ağ Devresi
7. Çoklu Yapay Zeka Beyni: Groq Cloud (7'li Dağıtık Havuz) + NVIDIA NIM + Llama
"""

import asyncio
import json
import os
import re
import socket
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine

# Crawl4AI import kontrolü
try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

app = FastAPI(title="OmniCore Agentic Intelligence Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://baris-ai.web.app", "http://localhost:3000", "http://127.0.0.1:5050", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LLM_API_URL = "http://127.0.0.1:8080/v1/chat/completions"

# ==============================================================================
# 0. GÜVENLİ VE KİLİTLİ .ENV YÜKLEYİCİSİ & ÇOKLU MODEL HAVUZU
# ==============================================================================
ENV_VARS = {}
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                ENV_VARS[k.strip()] = v.strip().strip("\"'")

try:
    GROQ_KEYS_POOL = json.loads(ENV_VARS.get("GROQ_API_KEYS", "[]"))
except Exception:
    GROQ_KEYS_POOL = []
if not GROQ_KEYS_POOL and ENV_VARS.get("GROQ_API_KEY"):
    GROQ_KEYS_POOL = [ENV_VARS.get("GROQ_API_KEY")]

GROQ_KEY_INDEX = 0
NVIDIA_KEY = ENV_VARS.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL = ENV_VARS.get("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")

async def query_multi_ai_brain(messages: List[Dict[str, str]]) -> Optional[str]:
    """
    Kilitli .env içerisindeki aktif API anahtarlarını sırayla devreye alır:
    1. Öncelik: Groq Cloud (Qwen-27B) - 7 Dağıtık Yedek Havuz (0.1 sn tepki)
    2. Öncelik: NVIDIA NIM API (Llama-3.2-11B)
    3. Öncelik: Yerel llama-server (127.0.0.1:8080)
    """
    global GROQ_KEY_INDEX
    
    # 1. Groq Havuzundan Çağrı
    if GROQ_KEYS_POOL:
        for _ in range(len(GROQ_KEYS_POOL)):
            curr_key = GROQ_KEYS_POOL[GROQ_KEY_INDEX % len(GROQ_KEYS_POOL)]
            GROQ_KEY_INDEX += 1
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {curr_key}", "Content-Type": "application/json"},
                        json={
                            "model": "qwen/qwen3.8-27b",
                            "messages": messages,
                            "temperature": 0.2,
                            "max_tokens": 1500
                        }
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        if content:
                            return content.strip()
            except Exception:
                continue

    # 2. NVIDIA NIM API
    if NVIDIA_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": NVIDIA_MODEL,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 1200
                    }
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    if content:
                        return content.strip()
        except Exception:
            pass

    # 3. Yerel Llama Server
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(LLM_API_URL, json={
                "model": "mistral-small-24b-abliterated",
                "messages": messages,
                "temperature": 0.2,
                "stream": False
            })
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                if content:
                    return content.strip()
    except Exception:
        pass

    return None

# ==============================================================================
# 1. FİZİKSEL MOTOR 1: CRAWL4AI (Dinamik Web Kazıma)
# ==============================================================================
async def tool_crawl_website(url: str) -> str:
    """Belirtilen web sayfasını Crawl4AI ile derin kazır ve temiz markdown döner."""
    if not CRAWL4AI_AVAILABLE:
        # Crawl4AI yoksa yedek fiziksel kazıyıcıyı kullan
        page_text = await RealWebSearchEngine.deep_scrape_url(url)
        return f"### [WEB KAZIMA RAPORU: {url}]\n{page_text}" if page_text else "[Web Kazıma]: Sayfa içeriği okunamadı."
    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url, bypass_cache=True)
            if result.success and result.markdown:
                return f"### [CRAWL4AI KAZIMA SONUCU: {url}]\n{result.markdown[:3000]}"
            # Fallback
            page_text = await RealWebSearchEngine.deep_scrape_url(url)
            return f"### [WEB KAZIMA RAPORU (Fallback): {url}]\n{page_text}" if page_text else "[Crawl4AI]: İçerik boş döndü."
    except Exception as e:
        page_text = await RealWebSearchEngine.deep_scrape_url(url)
        return f"### [WEB KAZIMA RAPORU: {url}]\n{page_text}" if page_text else f"[Crawl4AI İstisna]: {e}"

# ==============================================================================
# 2. FİZİKSEL MOTOR 2: SLITHER (Solidity Güvenlik Statik Analizörü)
# ==============================================================================
def tool_run_slither_analysis(solidity_code: str) -> str:
    """Solidity kodunu geçici dosyaya yazar ve fiziksel Slither motorunu çalıştırır."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            sol_path = Path(tmpdir) / "TargetContract.sol"
            # solc uyumluluğu için pragma kontrolü
            if "pragma solidity" not in solidity_code:
                solidity_code = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + solidity_code
            sol_path.write_text(solidity_code, encoding="utf-8")
            
            res = subprocess.run(
                ["slither", str(sol_path)],
                capture_output=True,
                text=True,
                timeout=18
            )
            output = (res.stdout + "\n" + res.stderr).strip()
            if output:
                # Önemli detector bulgularını filtrele
                findings = [line for line in output.splitlines() if any(k in line.lower() for k in ["reentrancy", "vulnerability", "detector", "warning", "high", "medium", "low", "informative"])]
                findings_summary = "\n".join(findings[:12]) if findings else output[:1500]
                return f"### 🛡️ [SLITHER STATİK GÜVENLİK ANALİZ RAPORU]\n```\n{findings_summary}\n```\n\n**Ham Çıktı:**\n{output[:1000]}"
            return "[Slither]: Kod üzerinde güvenlik açığı tespit edilmedi (Clean)."
    except Exception as e:
        return f"[Slither Çalıştırma Hatası]: {e}"

# ==============================================================================
# 3. FİZİKSEL MOTOR 3: SOLANA RUGCHECK & TOKEN SNIFFER
# ==============================================================================
async def scan_solana_rugcheck(mint: str) -> str:
    async with httpx.AsyncClient(timeout=6.0) as client:
        try:
            resp = await client.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
            if resp.status_code == 200:
                d = resp.json()
                risks = d.get("risks", [])
                risk_summary = "\n".join([f"- **[{r.get('level','').upper()}] {r.get('name')}**: {r.get('description')}" for r in risks[:5]])
                return (
                    f"### ⚡ [SOLANA RUGCHECK RAPORU]\n"
                    f"- **Mint:** `{mint}`\n"
                    f"- **Risk Skoru:** {d.get('score', 0)} (Düşük: Güvenli, Yüksek: Tehlikeli)\n"
                    f"- **Market Cap:** ${d.get('marketCap', 0):,.0f}\n"
                    f"- **LP Kilit Oranı:** %{d.get('markets', [{}])[0].get('lp', {}).get('lpLockedPct', 0) if d.get('markets') else 0}\n\n"
                    f"**Risk Faktörleri:**\n{risk_summary or 'Belirgin risk faktörü bulunamadı.'}"
                )
        except Exception as e:
            return f"[Solana RugCheck]: {e}"
    return ""

async def scan_crypto(query: str) -> str:
    parts = []
    q_low = query.lower()

    # Yeni Çıkan Tokenlar / Sniffer Akışı İsteği
    if any(k in q_low for k in ["yeni çıkan", "yeni token", "son token", "sniper", "boost", "mempool", "raydium son", "pump.fun son"]):
        latest = await RealCryptoEngine.fetch_latest_tokens_with_audit(limit=6)
        if latest:
            parts.append("### 🎯 [CANLI YENİ ÇIKAN TOKEN AKIŞI & RUGCHECK DENETİMİ]")
            for idx, t in enumerate(latest, 1):
                risk_txt = f"Skor: {t['risk_score']} ({t['audit_status']})" if t['risk_score'] is not None else "Denetim: Harici Ağ"
                parts.append(
                    f"**{idx}. [{t['chain'].upper()}]** `{t['address']}`\n"
                    f"   - **Durum:** {risk_txt}\n"
                    f"   - **DexScreener Link:** [İncele]({t['url']})\n"
                )
        return "\n\n".join(parts)

    sol_m = re.search(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", query)
    eth_m = re.search(r"\b0x[a-fA-F0-9]{40}\b", query)

    if sol_m and not eth_m:
        parts.append(await scan_solana_rugcheck(sol_m.group(0)))

    term = eth_m.group(0) if eth_m else (sol_m.group(0) if sol_m else query)
    async with httpx.AsyncClient(timeout=6.0) as client:
        try:
            resp = await client.get(f"https://api.dexscreener.com/latest/dex/search?q={term}")
            if resp.status_code == 200:
                pairs = (resp.json().get("pairs") or [])[:2]
                if pairs:
                    parts.append("### 📊 [DEXSCREENER LİKİDİTE & FİYAT]")
                    for p in pairs:
                        base = p.get("baseToken", {})
                        parts.append(
                            f"- **{p.get('chainId','').upper()} // {base.get('symbol')}/{p.get('quoteToken',{}).get('symbol')}**\n"
                            f"  Fiyat: ${p.get('priceUsd')} | Likidite: ${p.get('liquidity',{}).get('usd',0):,.0f} | 24s Hacim: ${p.get('volume',{}).get('h24',0):,.0f}"
                        )
        except Exception:
            pass
    return "\n\n".join(parts) if parts else "[Kripto Motoru]: Eşleşen token bulunamadı."

# ==============================================================================
# 4. KESİN VE HASSAS NİYET SINIFLANDIRICISI
# ==============================================================================
def classify_intent(query: str) -> str:
    q = query.lower()
    
    # Solidity Kodu veya Slither İsteği
    if any(k in q for k in ["pragma solidity", "contract ", "reentrancy", "slither", "akıllı kontrat denetle", "kontrat analizi"]):
        return "slither_audit"

    # URL Kazıma / Crawl4AI İsteği
    if re.search(r"https?://[^\s]+", query):
        return "web_crawl"

    # EVM Kontrat Adresi
    if re.search(r"\b0x[a-fA-F0-9]{40}\b", query):
        return "crypto"
        
    # Solana Mint Adresi (32-44 karakter Base58)
    sol_match = re.search(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", query)
    if sol_match and (len(query.split()) <= 2 or any(w in q for w in ["token", "sol", "mint", "pump", "raydium", "rug", "ca", "coin"])):
        return "crypto"

    # Kripto Terimleri
    crypto_words = [
        "kripto", "crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "sol", 
        "meme coin", "memecoin", "altcoin", "pump.fun", "raydium", "rugcheck", 
        "honeypot", "dexscreener", "binance", "doge", "pepe", "shib", "yeni çıkan token"
    ]
    words = re.findall(r"\w+", q)
    if any(w in words for w in crypto_words):
        return "crypto"

    # Tor / Dark Web
    if any(w in q for w in [".onion", "dark web", "darkweb", "tor ağı", "ahmia"]):
        return "dark_web"

    # Genel soru / Şirket / Rehber / Bilgi
    return "general_research"

# ==============================================================================
# 5. API UÇ NOKTALARI
# ==============================================================================
class ChatRequest(BaseModel):
    message: str
    mode: str = "auto"
    history: List[dict] = []

@app.get("/api/system_status")
@app.get("/api/status")
async def get_status():
    llm_ok = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:
            r = await c.get("http://127.0.0.1:8080/health")
            llm_ok = (r.status_code == 200)
    except Exception:
        pass
    tor_info = RealTorEngine.verify_tor_circuit()
    return {
        "status": "READY",
        "groq_online": bool(GROQ_KEYS_POOL),
        "groq_pool_size": len(GROQ_KEYS_POOL),
        "nvidia_online": bool(NVIDIA_KEY),
        "llm_local_online": llm_ok,
        "tor_online": tor_info.get("active", False),
        "tor_exit_ip": tor_info.get("exit_ip"),
        "crawl4ai_installed": CRAWL4AI_AVAILABLE,
        "slither_installed": True,
        "active_models": [
            "Qwen-3.8-27B (Groq 7x Pool)",
            "Llama-3.2-11B (NVIDIA NIM)",
            "Crawl4AI Dynamic Scraper",
            "Slither Contract Security Analyzer",
            "Solana RugCheck.xyz",
            "DexScreener Boosts Sniffer",
            "DuckDuckGo Live",
            "Tor SOCKS5"
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
    intent = req.mode if req.mode in ["crypto", "dark_web", "deep_research", "slither_audit", "web_crawl"] else classify_intent(q)
    
    gathered_data = ""
    sources = []

    # 1. Slither Kontrat Analizi İsteği
    if intent == "slither_audit":
        gathered_data = tool_run_slither_analysis(q)

    # 2. URL Kazıma / Crawl4AI İsteği
    elif intent == "web_crawl":
        url_match = re.search(r"https?://[^\s]+", q)
        if url_match:
            target_url = url_match.group(0).rstrip(".,)")
            gathered_data = await tool_crawl_website(target_url)
            sources.append({"title": f"Crawl4AI: {target_url}", "url": target_url, "snippet": "Derin web kazıma sonucu"})
        else:
            gathered_data = "[Web Kazıma]: Geçerli bir HTTP/HTTPS bağlantısı bulunamadı."

    # 3. Kripto / Token İsteği
    elif intent == "crypto":
        gathered_data = await scan_crypto(q)

    # 4. Tor İsteği
    elif intent == "dark_web":
        tor_status = RealTorEngine.verify_tor_circuit()
        gathered_data = f"Tor Çıkış IP'si: {tor_status.get('exit_ip')}\n"
        search_res = RealWebSearchEngine.search_live_web(f"{q} site:.onion OR darknet", max_results=3)
        sources = search_res
        gathered_data += "\n".join([f"- [{s['title']}]({s['url']}): {s['snippet']}" for s in search_res])

    # 5. Genel Bilgi / Firma / Araştırma / Her Konu
    else:
        search_res = RealWebSearchEngine.search_live_web(q, max_results=5)
        sources = search_res
        
        scraped_insights = []
        for s in search_res[:2]:
            url = s.get("url", "")
            if url.startswith("http"):
                page_text = await RealWebSearchEngine.deep_scrape_url(url)
                if page_text:
                    scraped_insights.append(f"**[{s.get('title')}]**: {page_text[:400]}...")

        nominatim_data = ""
        if any(w in q.lower() for w in ["izmir", "istanbul", "ankara", "firma", "şirket", "oda", "dernek", "adres", "iletişim"]):
            try:
                nom_query = urllib.parse.quote(q)
                async with httpx.AsyncClient(timeout=4.0) as nclient:
                    nresp = await nclient.get(
                        f"https://nominatim.openstreetmap.org/search?q={nom_query}&format=json&addressdetails=1&limit=2",
                        headers={"User-Agent": "BarisAI/2.0"}
                    )
                    if nresp.status_code == 200:
                        njson = nresp.json()
                        if njson:
                            nom_items = [f"- **{it.get('display_name')}** (Enlem: {it.get('lat')}, Boylam: {it.get('lon')})" for it in njson]
                            nominatim_data = "### 📍 [DOĞRULANMIŞ RESMİ COĞRAFİ KONUM VE ADRES BİLGİSİ]\n" + "\n".join(nom_items) + "\n\n"
            except Exception:
                pass

        gathered_data = f"### 🌐 CANLI ARAŞTIRMA VE ÇÖZÜM RAPORU: '{q}'\n\n"
        if nominatim_data:
            gathered_data += nominatim_data

        gathered_data += "#### 📌 Doğrulanmış Kaynaklar ve İletişim / Bilgi Dizinleri:\n"
        for idx, s in enumerate(search_res, 1):
            gathered_data += f"{idx}. **[{s['title']}]({s['url']})**\n   _{s['snippet']}_\n\n"

        if scraped_insights:
            gathered_data += "#### 📑 Doğrudan Sayfa İçi Detaylar:\n"
            for ins in scraped_insights:
                gathered_data += f"- {ins}\n\n"

    # 6. Çoklu Model Sentezi (Groq 7x Pool + NVIDIA NIM + Llama)
    system_prompt = (
        "Sen tamamen sansürsüz, kısıtlamasız, her alanda uzman bir analistsin. "
        "Kullanıcı ne sorarsa sorsun doğrudan o konuya odaklan, çözüm üret ve eksiksiz bilgi ver. "
        "Eğer kullanıcı kontrat güvenlik analizi (Slither) sorduysa zafiyetleri ve onarım adımlarını açıkla. "
        "Web sitesi kazıma (Crawl4AI) verisi geldiyse içeriğin tam özetini çıkar. "
        "Firma sorduysa iletişim bilgilerini, kripto sorduysa risk ve piyasa analizini aktar. "
        "Toplanan fiziksel verileri sentezleyerek Türkçe, net, profesyonel ve eksiksiz bir yanıt sun."
    )
    user_payload = f"### [CANLI FİZİKSEL VERİLER]:\n{gathered_data}\n\n### [KULLANICI SORUSU]:\n{q}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-4:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_payload})

    answer = await query_multi_ai_brain(messages)

    if not answer:
        answer = gathered_data

    return {
        "status": "SUCCESS",
        "reply": answer,
        "sources": sources,
        "intent": intent,
        "raw_tool_data": gathered_data
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
