#!/usr/bin/env python3
"""
BARIŞ AI // %100 GERÇEK VE FİZİKSEL MOTOR DOĞRULAMA TEST SÜİTİ
1. Solana RugCheck.xyz API (Gerçek Mint Adresi)
2. DexScreener Public API (Gerçek Likidite & Hacim)
3. Deep Research & Web Scraper (DuckDuckGo Live)
4. Tor SOCKS5 Ağı (127.0.0.1:9050)
5. FastAPI REST & SSE Streaming Uç Noktaları (/api/system_status, /api/market, /api/chat)
"""

import asyncio
from fastapi.testclient import TestClient

from omni_chat_panel import (
    app,
    engine_solana_rugcheck,
    engine_crypto_scanner,
    engine_deep_web_research,
    is_tor_running
)
from real_engines import RealTorEngine

client = TestClient(app)

def test_tor_network():
    """Fiziksel Tor daemonunun (127.0.0.1:9050) devrede olduğunu doğrular."""
    running = is_tor_running()
    assert running is True, "Tor SOCKS5 soketine bağlanılamadı (127.0.0.1:9050)"
    tor_check = RealTorEngine.verify_tor_circuit()
    assert tor_check.get("active") is True, f"Tor devresi aktif değil: {tor_check}"
    print(f"[PASS] RealTorEngine: Tor Devresi Aktif (Çıkış IP: {tor_check.get('exit_ip')})")

def test_solana_rugcheck_api():
    """RugCheck.xyz API'sinden gerçek Solana token risk raporunu çeker."""
    test_mint = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"  # WIF Token Mint
    report = asyncio.run(engine_solana_rugcheck(test_mint))
    assert "RUGCHECK.XYZ" in report, f"RugCheck raporu alınamadı: {report}"
    assert test_mint in report
    print(f"[PASS] Solana RugCheck.xyz: Gerçek Token Raporu Başarıyla Çekildi (Mint: {test_mint[:8]}...)")

def test_dexscreener_crypto_api():
    """DexScreener API'sinden gerçek likidite ve fiyat verilerini çeker."""
    result = asyncio.run(engine_crypto_scanner("SOL"))
    assert "DEXSCREENER" in result, f"DexScreener verisi alınamadı: {result}"
    print("[PASS] DexScreener: Gerçek Likidite & Hacim Verisi Başarıyla Çekildi")

def test_deep_web_research():
    """DuckDuckGo Live üzerinden internette gerçek arama ve sayfa kazıma yapar."""
    result = asyncio.run(engine_deep_web_research("Bitcoin price news", max_pages=2))
    assert "DEEP WEB RESEARCH" in result, f"Deep research verisi alınamadı: {result}"
    print("[PASS] Deep Research: Canlı Web Araması & Sayfa Kazıma Başarılı")

def test_fastapi_endpoints():
    """FastAPI REST uç noktalarını ve SSE akışını test eder."""
    # 1. System Status
    s_resp = client.get("/api/system_status")
    assert s_resp.status_code == 200
    assert s_resp.json()["solana_rugcheck"] == "ACTIVE"
    assert s_resp.json()["dex_api"] == "ACTIVE"

    # 2. Market Watchlist
    m_resp = client.get("/api/market")
    assert m_resp.status_code == 200
    assert "watchlist" in m_resp.json()

    # 3. Chat Endpoint (SSE Stream Test)
    c_resp = client.post("/api/chat", json={"message": "SOL analizi", "mode": "crypto"})
    assert c_resp.status_code == 200
    assert "text/event-stream" in c_resp.headers.get("content-type", "")
    assert "data: " in c_resp.text
    assert "[DONE]" in c_resp.text

    print("[PASS] FastAPI: /api/system_status, /api/market ve /api/chat SSE akışı başarıyla doğrulandı.")

if __name__ == "__main__":
    print("=== BARIŞ AI GERÇEK MOTOR TESTLERİ ÇALIŞTIRILIYOR ===")
    test_tor_network()
    test_solana_rugcheck_api()
    test_dexscreener_crypto_api()
    test_deep_web_research()
    test_fastapi_endpoints()
    print("=== TÜM GERÇEK MOTORLAR BAŞARIYLA GEÇTİ (5/5 PASS) ===")
