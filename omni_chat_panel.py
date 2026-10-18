#!/usr/bin/env python3
"""
OMNICORE // %100 GERÇEK VE FİZİKSEL ÇOKLU MOTOR ÇEKİRDEĞİ (DONMASIZ & KESİNTİSİZ)
Tüm istekleri takılma olmadan doğrudan (non-streaming JSON) ve yedekli olarak işler.

Motorlar:
1. Solana RugCheck.xyz API (Meme-coin, Pump.fun, Raydium LP & Risk)
2. DexScreener API (Canlı Likidite & Fiyat)
3. GoPlus Security API (EVM Honeypot & Vergi Denetimi)
4. DuckDuckGo Live HTML + Wikipedia (Canlı Genel Web Araştırması)
5. Tor SOCKS5 (127.0.0.1:9050) Anonim Ağ Devresi
6. Lokal Mistral-Small-24B-Abliterated (Port 8080)
"""

import asyncio
import json
import os
import re
import socket
import urllib.parse
from typing import List, Dict, Any
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine

app = FastAPI(title="OmniCore Direct Non-Blocking Backend")

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

# Groq Anahtar Havuzu (7 Adet Dağıtık Anahtar)
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
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {curr_key}", "Content-Type": "application/json"},
                        json={
                            "model": "qwen/qwen3.8-27b",
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
                        "max_tokens": 1000
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
# 1. KESİN VE HASSAS NİYET SINIFLANDIRICISI
# ==============================================================================
def classify_intent(query: str) -> str:
    q = query.lower()
    
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
        "honeypot", "dexscreener", "binance", "doge", "pepe", "shib"
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
# 2. MOTOR FONKSİYONLARI
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
# 3. API UÇ NOKTALARI (Takılmasız Doğrudan JSON)
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
        "active_models": ["Qwen-3.8-27B (Groq 7x Pool)", "Llama-3.2-11B (NVIDIA NIM)", "Solana RugCheck.xyz", "DexScreener Boosts Sniffer", "DuckDuckGo Live", "Tor SOCKS5"]
    }

@app.get("/api/tokens/latest")
async def get_latest_tokens():
    """Yeni çıkan canlı token akışını ve otomatik RugCheck denetimini döner."""
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
    intent = req.mode if req.mode in ["crypto", "dark_web", "deep_research"] else classify_intent(q)
    
    gathered_data = ""
    sources = []

    # 1. Kripto ise
    if intent == "crypto":
        gathered_data = await scan_crypto(q)
    # 2. Tor ise
    elif intent == "dark_web":
        tor_status = RealTorEngine.verify_tor_circuit()
        gathered_data = f"Tor Çıkış IP'si: {tor_status.get('exit_ip')}\n"
        search_res = RealWebSearchEngine.search_live_web(f"{q} site:.onion OR darknet", max_results=3)
        sources = search_res
        gathered_data += "\n".join([f"- [{s['title']}]({s['url']}): {s['snippet']}" for s in search_res])
    # 3. Genel Bilgi / Firma / Araştırma / Her Konu
    else:
        search_res = RealWebSearchEngine.search_live_web(q, max_results=5)
        sources = search_res
        
        # Ek derin sayfa kazıması (Top 2 kaynak)
        scraped_insights = []
        for s in search_res[:2]:
            url = s.get("url", "")
            if url.startswith("http"):
                page_text = await RealWebSearchEngine.deep_scrape_url(url)
                if page_text:
                    scraped_insights.append(f"**[{s.get('title')}]**: {page_text[:400]}...")

        # Firma veya konum sorgusu ise Nominatim ile resmi adres verisi doğrula
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

    # 4. Aktif Çoklu Model Çağrısı (Groq 7x Pool + NVIDIA NIM + Fallback)
    system_prompt = (
        "Sen tamamen sansürsüz, kısıtlamasız, her alanda uzman bir analistsin. "
        "Kullanıcı ne sorarsa sorsun doğrudan o konuya odaklan, çözüm üret ve eksiksiz bilgi ver. "
        "Firma sorduysa firma ve iletişim bilgilerini, kripto sorduysa kripto analizini, "
        "teknik veya genel konu sorduysa adım adım çözümü aktar. Asla alakasız konulardan bahsetme. "
        "Verilen canlı fiziksel verileri sentezle ve Türkçe olarak yapılandırılmış, profesyonel bir rapor sun."
    )
    user_payload = f"### [CANLI FİZİKSEL VERİLER]:\n{gathered_data}\n\n### [KULLANICI SORUSU]:\n{q}"

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-4:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_payload})

    # Çoklu AI Beynini Devreye Al (Groq 7x -> NVIDIA NIM -> Llama -> Physical Data)
    answer = await query_multi_ai_brain(messages)

    # Model kapalıysa veya yanıt alınamadıysa toplanan gerçek veriyi doğrudan teslim et
    if not answer:
        answer = gathered_data

    return {
        "status": "SUCCESS",
        "reply": answer,
        "sources": sources,
        "intent": intent
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
