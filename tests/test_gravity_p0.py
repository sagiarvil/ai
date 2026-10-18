#!/usr/bin/env python3
"""
OMNICORE // ZORUNLU P0 GÜVENLİK, İZOLASYON VE DOĞRULAMA TESTLERİ
Kapsam:
1. API Yetkisiz Erişim Testi (Eksik anahtara 401, hatalı anahtara 401, geçerli anahtara 200)
2. Gerçek Sandbox İzolasyonu Testi (Proje ana dizinine ve .env dosyasına yetkisiz erişim engelleme)
3. Sahte VERIFIED Üretiminin Engellenmesi (sys.exit(0) ve ls -la bypass reddi)
4. Hatalı İşlemde Rollback Testi (Otomatik geri alma güvencesi)
5. OpenHands Uçtan Uca Görev Doğrulaması (İzole ortamda kod ve test koşumu)
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from omni_chat_panel import app
from config_manager import get_secure_api_key
from sandbox_executor import secure_sandbox_run, SANDBOX_DIR, WORKSPACE_ROOT
from verification_gate import IndependentVerificationGate
from agentic_engine import AutonomousExecutionEngine, TaskState
from openhands_runner import OpenHandsRunner

client = TestClient(app)

# ------------------------------------------------------------------------------
# 1. API YETKİSİZ ERİŞİM TESTLERİ (Zorunlu HTTP 401)
# ------------------------------------------------------------------------------
def test_api_missing_key_returns_401():
    """API anahtarı gönderilmediğinde kesinlikle HTTP 401 dönmelidir."""
    resp = client.get("/api/system_status")
    assert resp.status_code == 401, f"Beklenen 401, Alınan: {resp.status_code}"
    assert "Yetkisiz Erişim" in resp.json().get("detail", "")

def test_api_invalid_key_returns_401():
    """Hatalı API anahtarı gönderildiğinde kesinlikle HTTP 401 dönmelidir."""
    resp = client.get("/api/system_status", headers={"X-Omni-Key": "completely_wrong_invalid_key_123"})
    assert resp.status_code == 401, f"Beklenen 401, Alınan: {resp.status_code}"
    assert "Yetkisiz Erişim" in resp.json().get("detail", "")

def test_api_valid_key_returns_200():
    """Geçerli güvenli anahtar ile istek başarılı olmalıdır."""
    valid_key = get_secure_api_key()
    resp = client.get("/api/system_status", headers={"X-Omni-Key": valid_key})
    assert resp.status_code == 200, f"Beklenen 200, Alınan: {resp.status_code}"
    assert resp.json().get("status") == "ONLINE"

# ------------------------------------------------------------------------------
# 2. GERÇEK SANDBOX İZOLASYONU TESTLERİ (Seatbelt Kernel Koruması)
# ------------------------------------------------------------------------------
def test_sandbox_write_protection_outside_workspace():
    """Sandbox içinde çalıştırılan bir komut proje ana dizinine ASLA dosya yazamamalıdır."""
    forbidden_target = WORKSPACE_ROOT / "public" / "forbidden_leak_test.txt"
    if forbidden_target.exists():
        forbidden_target.unlink()

    cmd = f"touch '{forbidden_target}'"
    res = secure_sandbox_run(cmd)
    
    # Kernel tarafından Operation not permitted ile engellenmeli ve dosya oluşmamalıdır
    assert not forbidden_target.exists(), "KRİTİK HATA: Sandbox dışına dosya yazıldı!"
    assert res["success"] is False
    assert "Operation not permitted" in res["stderr"] or res["state"] == "BLOCKED"

def test_sandbox_read_protection_for_secrets():
    """Sandbox içinde çalışan komut .env sır dosyasını ASLA okuyamamalıdır."""
    cmd = f"cat '{WORKSPACE_ROOT}/.env'"
    res = secure_sandbox_run(cmd)
    assert res["success"] is False
    assert "Operation not permitted" in res["stderr"] or res["state"] == "BLOCKED"

def test_sandbox_write_allowed_inside_workspace():
    """Sandbox içinde belirtilen yalıtılmış çalışma alanına yazma başarılı olmalıdır."""
    allowed_file = SANDBOX_DIR / "valid_test.txt"
    if allowed_file.exists():
        allowed_file.unlink()

    cmd = f"echo 'SANDBOX_WRITE_OK' > '{allowed_file}'"
    res = secure_sandbox_run(cmd)
    assert res["success"] is True
    assert allowed_file.exists()
    assert "SANDBOX_WRITE_OK" in allowed_file.read_text(encoding="utf-8")
    allowed_file.unlink()

# ------------------------------------------------------------------------------
# 3. SIFIR SAHTE BAŞARI (Zero-Fake Verification) TESTLERİ
# ------------------------------------------------------------------------------
def test_rejection_of_dummy_exit_bypass():
    """'sys.exit(0)' ve kukla komutlar bağımsız doğrulayıcı tarafından reddedilmelidir."""
    valid, reason = IndependentVerificationGate.audit_test_command("python3 main.py || python3 -c 'import sys; sys.exit(0)'")
    assert valid is False
    assert "Sahte/Kukla test komutu" in reason

def test_rejection_of_ls_as_runtime_verification():
    """'ls -la' dosya listeleme komutları runtime doğrulaması olarak reddedilmelidir."""
    valid, reason = IndependentVerificationGate.audit_test_command("ls -la")
    assert valid is False
    assert "Sahte/Kukla test komutu" in reason

# ------------------------------------------------------------------------------
# 4. BAŞARISIZ İŞLEMDE OTOMATİK ROLLBACK TESTİ
# ------------------------------------------------------------------------------
def test_failed_installation_triggers_clean_rollback():
    """Çalışma testini geçemeyen bir repo kurulumu otomatik olarak geri alınmalı (rollback) ve temizlenmelidir."""
    engine = AutonomousExecutionEngine()
    fake_repo_dir = WORKSPACE_ROOT / "tools" / "temp_faulty_engine"
    fake_repo_dir.mkdir(parents=True, exist_ok=True)
    
    # Bozuk ve hata veren bir kod yaz
    (fake_repo_dir / "main.py").write_text("import non_existent_broken_module\n", encoding="utf-8")
    
    # Rollback yığınına kaydet ve test et
    engine.rollback_stack.append(("delete_dir", str(fake_repo_dir)))
    
    # Bağımsız doğrulayıcı ile çalıştır (hatalı olacağı kesin)
    gate_res = IndependentVerificationGate.verify_runtime_execution(fake_repo_dir)
    assert gate_res.get("verified") is False
    
    # Rollback çalıştır
    engine.rollback()
    
    # Dizin temizlenmiş olmalı ve durum ROLLED_BACK olmalı
    assert not fake_repo_dir.exists(), "Rollback başarısız: Bozuk modül temizlenemedi!"
    assert engine.state == TaskState.ROLLED_BACK

# ------------------------------------------------------------------------------
# 5. OPENHANDS UÇTAN UCA İZOLE GÖREV TESTİ
# ------------------------------------------------------------------------------
def test_openhands_end_to_end_task_execution():
    """OpenHands izole ortamda gerçek kod oluşturma, test etme ve doğrulamayı başarıyla tamamlamalıdır."""
    runner = OpenHandsRunner("pytest_openhands_verification")
    res = asyncio.run(runner.run_end_to_end_code_task())
    assert res.get("openhands_verified") is True
    assert res.get("verification_details", {}).get("exit_code") == 0
    assert len(res.get("history", [])) == 3
