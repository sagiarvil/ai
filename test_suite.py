#!/usr/bin/env python3
"""
BARIŞ AI // %100 GERÇEK VE FİZİKSEL MOTOR DOĞRULAMA TEST SÜİTİ
Tüm motorların canlı ve fiziksel çalıştığını test eder.
"""

import asyncio
from fastapi.testclient import TestClient

from omni_chat_panel import app
from real_engines import RealTorEngine, RealWebSearchEngine, RealCryptoEngine
from browser_controller import LocalBrowserEngine
from agentic_engine import AutonomousExecutionEngine, ExecutionSandbox, TaskState

client = TestClient(app)

def test_tor_network():
    """Fiziksel Tor daemonunun (127.0.0.1:9050) devrede olduğunu doğrular."""
    tor_check = RealTorEngine.verify_tor_circuit()
    assert tor_check.get("active") is True, f"Tor devresi aktif değil: {tor_check}"
    print(f"[PASS] 1. Tor SOCKS5: Aktif (Çıkış IP: {tor_check.get('exit_ip')})")

def test_deep_web_research():
    """DuckDuckGo Live üzerinden internette gerçek arama yapar."""
    result = RealWebSearchEngine.search_live_web("İzmir sanayi odası", max_results=3)
    assert len(result) > 0, "Arama sonucu boş döndü"
    assert "url" in result[0]
    print(f"[PASS] 2. Deep Web Research: Canlı Web Araması Başarılı ({len(result)} kaynak)")

def test_crypto_engines():
    """Binance ve DexScreener API'lerinden canlı veri çeker."""
    coin = asyncio.run(RealCryptoEngine.get_live_coin("BTC"))
    assert coin is not None and coin.get("price", 0) > 0, "Binance BTC fiyatı alınamadı"
    print(f"[PASS] 3. RealCryptoEngine: Binance BTC Canlı Fiyatı: ${coin['price']:,.2f}")

def test_browser_controller():
    """Google Chrome ikilisi ile canlı web sayfası gezinmesini doğrular."""
    res = asyncio.run(LocalBrowserEngine.open_and_extract(url="https://checkip.amazonaws.com", browser_name="chrome", use_tor=False))
    assert res.get("status") == "SUCCESS", f"Tarayıcı hatası: {res}"
    print(f"[PASS] 4. LocalBrowserEngine: Chrome Başarıyla Açıldı (IP: {res.get('content','').strip()})")

def test_sandbox_and_agentic_engine():
    """Çoklu repo araştırması ve sandbox komut çalıştırmayı test eder."""
    res = ExecutionSandbox.run_isolated("echo 'SANDBOX_OK'")
    assert res["success"] is True and "SANDBOX_OK" in res["stdout"]
    repos = AutonomousExecutionEngine.search_and_compare_github_repos("solana", limit=2)
    assert len(repos) > 0, "GitHub çoklu repo araması boş döndü"
    print(f"[PASS] 5. Agentic & Sandbox Engine: İzolasyon ve Çoklu Repo Arama Başarılı ({len(repos)} repo)")

def test_fastapi_system_status():
    """FastAPI REST uç noktasını doğrudan JSON yanıtıyla test eder."""
    s_resp = client.get("/api/system_status")
    assert s_resp.status_code == 200
    data = s_resp.json()
    assert data["status"] == "ONLINE"
    assert data.get("agentic_engine") is not None
    print(f"[PASS] 6. FastAPI: /api/system_status Çevrimiçi ({data['hardware']})")

if __name__ == "__main__":
    print("=== BARIŞ AI GERÇEK MOTOR TESTLERİ ÇALIŞTIRILIYOR ===")
    test_tor_network()
    test_deep_web_research()
    test_crypto_engines()
    test_browser_controller()
    test_sandbox_and_agentic_engine()
    test_fastapi_system_status()
    print("=== TÜM GERÇEK FİZİKSEL MOTORLAR DOĞRULANDI (6/6 PASS) ===")
