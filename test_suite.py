#!/usr/bin/env python3
"""
BARIŞ AI // ESKİ İSTEĞE BAĞLI DIŞ SERVİS ENTEGRASYONLARI
Bu dosya durable_api motorunu veya genel görev tamamlama başarısını doğrulamaz.
Doğrulanan Katmanlar:
1. Tor SOCKS5 yerel ağı (127.0.0.1:9050)
2. Canlı TLS doğrulamalı DuckDuckGo Web Araştırması
3. Slither Akıllı Kontrat Statik Güvenlik Analizi
4. Yerel Tarayıcı Motoru (Chrome Headless)
5. Gerçek Sandbox İzolasyonu ve Ortam Değişkeni Arındırma
6. Canlı Mistral-24B M4 Metal Çıkarım Testi (Inference Probe)
7. FastAPI Sıkılaştırılmış CORS ve Güvenli API Uç Noktası
"""

import asyncio
import os
import unittest
if __name__ != '__main__' and os.environ.get('BARIS_RUN_LEGACY_INTEGRATION') != '1':
    raise unittest.SkipTest('Eski Tor/Chrome/Slither testleri isteğe bağlıdır. Canlı görev kabulü: baris_local.py verify-live')
import subprocess
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from legacy_omni_chat_panel import app
from real_engines import RealTorEngine, RealWebSearchEngine
from browser_controller import LocalBrowserEngine
from agentic_engine import AutonomousExecutionEngine, ExecutionSandbox, TaskState
from sandbox_executor import secure_sandbox_run, SANDBOX_DIR
from model_manager import ModelManager

client = TestClient(app)

def test_tor_network():
    """Fiziksel Tor daemonunun (127.0.0.1:9050) devrede olduğunu doğrular."""
    tor_check = RealTorEngine.verify_tor_circuit()
    assert tor_check.get("active") is True, f"Tor devresi aktif değil: {tor_check}"
    print(f"[PASS] 1. Tor SOCKS5: Aktif (Çıkış IP: {tor_check.get('exit_ip')})")

def test_deep_web_research():
    """TLS doğrulamalı DuckDuckGo Live üzerinden internette gerçek arama yapar."""
    result = RealWebSearchEngine.search_live_web("İzmir sanayi odası", max_results=3)
    assert len(result) > 0, "Arama sonucu boş döndü"
    assert "url" in result[0]
    print(f"[PASS] 2. Deep Web Research: Canlı Web Araması Başarılı ({len(result)} kaynak, TLS Doğrulamalı)")

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

def test_sandbox_isolation_and_env_sanitization():
    """Gerçek izole çalışma alanı ve hassas anahtar sızdırmazlığını test eder."""
    os.environ["MOCK_API_KEY_SECRET"] = "TOP_SECRET_DO_NOT_LEAK"
    res = secure_sandbox_run("env")
    assert res["success"] is True
    assert "MOCK_API_KEY_SECRET" not in res["stdout"], "Hassas API anahtarı sandbox ortamına sızdı!"
    assert res.get("cwd") == str(SANDBOX_DIR), f"Sandbox izole dizinde çalışmadı: {res.get('cwd')}"
    print(f"[PASS] 5. Gerçek Sandbox İzolasyonu: Sır Sızdırmazlık ve Yalıtılmış Dizin Doğrulandı ({SANDBOX_DIR.name})")

def test_model_runtime_inference():
    """Canlı Mistral-24B modeline probe gönderir ve gerçek çıkarımı doğrular."""
    probe = asyncio.run(ModelManager.verify_model_runtime("mistral-small-24b-abliterated:latest"))
    assert probe.get("inference_pass") is True, f"Model çıkarım testi başarısız: {probe}"
    tps = probe.get("tokens_per_second", 0.0)
    lat = probe.get("latency_sec", 0.0)
    print(f"[PASS] 6. Model Runtime Inference: Canlı Çıkarım %100 PASS (M4 Metal, {tps} tok/s, {lat}s)")

def test_fastapi_security_and_cors():
    """FastAPI CORS sıkılaştırmasını ve sistem durumunu test eder."""
    # CORS options preflight
    opt_resp = client.options("/api/chat", headers={"Origin": "https://baris-ai.web.app", "Access-Control-Request-Method": "POST"})
    assert opt_resp.status_code == 200
    allow_origin = opt_resp.headers.get("access-control-allow-origin")
    assert allow_origin != "*", "CORS güvenliği başarısız: Wildcard '*' bulundu!"

    s_resp = client.get("/api/system_status")
    assert s_resp.status_code == 200
    data = s_resp.json()
    assert data["status"] == "ONLINE"
    assert data.get("model_verified") is True
    print(f"[PASS] 7. FastAPI Güvenlik & Durum: CORS Sıkılaştırıldı, Canlı Model Doğrulandı ({data['model']})")

if __name__ == "__main__":
    print("=== BARIŞ AI GERÇEK MOTOR TESTLERİ (7/7 KURUMSAL KABUL KAPISI) ===")
    test_tor_network()
    test_deep_web_research()
    test_slither_security_analysis()
    test_browser_controller()
    test_sandbox_isolation_and_env_sanitization()
    test_model_runtime_inference()
    test_fastapi_security_and_cors()
    print("=== TÜM GERÇEK MÜHENDİSLİK MOTORLARI DOĞRULANDI (7/7 PASS) ===")

