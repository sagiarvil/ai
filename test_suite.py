#!/usr/bin/env python3
"""
BARIŞ AI // FİZİKSEL MOTOR DOĞRULAMA TEST SÜİTİ
1. RealWebSearchEngine (DuckDuckGo Live)
2. RealTorEngine (127.0.0.1:9050 SOCKS5)
3. RealCryptoEngine (Binance Live)
4. FastAPI REST Uç Noktaları (/api/status, /api/market, /api/chat)
"""

import asyncio
from fastapi.testclient import TestClient

from real_engines import RealWebSearchEngine, RealTorEngine, RealCryptoEngine
from server import app

client = TestClient(app)

def test_real_tor_socket():
    """Fiziksel Tor daemonunun (127.0.0.1:9050) devrede olduğunu doğrular."""
    result = RealTorEngine.verify_tor_circuit()
    assert result.get("active") is True, f"Tor devresi aktif değil: {result}"
    print(f"[PASS] RealTorEngine: Tor Devresi Aktif (Çıkış IP: {result.get('exit_ip')})")

def test_real_crypto_binance():
    """Binance REST API'den fiziksel canlı BTC fiyatı çeker."""
    coin = asyncio.run(RealCryptoEngine.get_live_coin("BTC"))
    assert coin is not None, "Binance BTC verisi çekilemedi"
    assert coin["price"] > 1000, f"Geçersiz BTC fiyatı: {coin['price']}"
    print(f"[PASS] RealCryptoEngine: Canlı BTC Fiyatı Alındı (${coin['price']:,.2f})")

def test_real_web_search():
    """DuckDuckGo üzerinden internette canlı arama yapar."""
    results = RealWebSearchEngine.search_live_web("Bitcoin", max_results=2)
    assert len(results) > 0, "Arama sonucu dönmedi"
    assert "url" in results[0], "Sonuçta URL yok"
    print(f"[PASS] RealWebSearchEngine: Canlı İnternet Taraması Başarılı ({len(results)} sonuç)")

def test_api_endpoints():
    """FastAPI sunucu uç noktalarını test eder."""
    # Status
    s_resp = client.get("/api/status")
    assert s_resp.status_code == 200
    assert s_resp.json()["status"] == "ONLINE"

    # Market
    m_resp = client.get("/api/market")
    assert m_resp.status_code == 200
    assert "watchlist" in m_resp.json()

    # Chat (Crypto Scan)
    c_resp = client.post("/api/chat", json={"message": "BTC analizi", "mode": "crypto_scan"})
    assert c_resp.status_code == 200
    assert "reply" in c_resp.json()
    assert "BTC" in c_resp.json()["reply"]

    print("[PASS] FastAPI: /api/status, /api/market ve /api/chat başarıyla doğrulandı.")

if __name__ == "__main__":
    print("=== BARIŞ AI GERÇEK MOTOR TESTLERİ ÇALIŞTIRILIYOR ===")
    test_real_tor_socket()
    test_real_crypto_binance()
    test_real_web_search()
    test_api_endpoints()
    print("=== TÜM GERÇEK MOTORLAR BAŞARIYLA GEÇTİ (4/4 PASS) ===")
