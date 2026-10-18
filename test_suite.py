#!/usr/bin/env python3
"""
BARIŞ AI // %100 GERÇEK VE FİZİKSEL MOTOR DOĞRULAMA TEST SÜİTİ
Fiyat çekme modülleri kaldırılmıştır; saf mühendislik, güvenlik, ağ ve araştırma motorları test edilir.
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from omni_chat_panel import app
from real_engines import RealTorEngine, RealWebSearchEngine
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

def test_slither_security_analysis():
    """Slither ile statik akıllı kontrat analizi yapar."""
    sol_code = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract TestBank {
    mapping(address => uint) public balances;
    function withdraw() public {
        uint bal = balances[msg.sender];
        (bool s,) = msg.sender.call{value: bal}("");
        require(s);
        balances[msg.sender] = 0;
    }
}"""
    with tempfile.TemporaryDirectory() as tmpdir:
        sol_file = Path(tmpdir) / "TestBank.sol"
        sol_file.write_text(sol_code, encoding="utf-8")
        res = subprocess.run(["slither", str(sol_file)], capture_output=True, text=True, timeout=20)
        assert "reentrancy" in (res.stdout + res.stderr).lower()
    print("[PASS] 3. Slither Statik Güvenlik Analizi: Reentrancy Başarıyla Tespit Edildi")

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
    print("=== BARIŞ AI GERÇEK MOTOR TESTLERİ ÇALIŞTIRILIYOR (FİYAT ÇEKME SIFIRLANDI) ===")
    test_tor_network()
    test_deep_web_research()
    test_slither_security_analysis()
    test_browser_controller()
    test_sandbox_and_agentic_engine()
    test_fastapi_system_status()
    print("=== TÜM GERÇEK MÜHENDİSLİK MOTORLARI DOĞRULANDI (6/6 PASS) ===")
