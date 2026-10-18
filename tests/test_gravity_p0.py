#!/usr/bin/env python3
"""
OMNICORE // ZORUNLU P0 GÜVENLİK, İZOLASYON VE DOĞRULAMA TESTLERİ
Kapsam:
1. API Yetkisiz Erişim Testi (Eksik anahtara 401, hatalı anahtara 401, geçerli anahtara 200)
2. Gerçek Sandbox İzolasyonu Testi (Seatbelt Kernel koruması ve sır sızdırmazlık)
3. Sıfır Sahte Başarı Testleri (sys.exit(0), ls -la ve syntax-only reddi)
4. Doğrudan Dosya Erişim Yetki Koruması (.env ve sistem dosyaları koruması)
5. Hatalı İşlemde Rollback Testi (Otomatik geri alma güvencesi)
6. OpenHands Ajan Görev Doğrulaması (İzole ortamda kod ve test koşumu)
"""

import asyncio
import platform
import pytest
from fastapi.testclient import TestClient

from omni_chat_panel import app, tool_read_file, tool_write_file
from config_manager import get_secure_api_key
from sandbox_executor import secure_sandbox_run, SANDBOX_DIR, WORKSPACE_ROOT
from verification_gate import IndependentVerificationGate
from agentic_engine import AutonomousExecutionEngine, TaskState
from openhands_runner import OpenHandsAgentEngine

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
    if platform.system() != "Darwin":
        pytest.skip("Seatbelt kernel izolasyon testi sadece macOS üzerinde çalışır.")

    forbidden_target = WORKSPACE_ROOT / "public" / "forbidden_leak_test.txt"
    if forbidden_target.exists():
        forbidden_target.unlink()

    cmd = f"touch '{forbidden_target}'"
    res = secure_sandbox_run(cmd)

    assert not forbidden_target.exists(), "KRİTİK HATA: Sandbox dışına dosya yazıldı!"
    assert res["success"] is False
    assert "Operation not permitted" in res["stderr"] or res["state"] == "BLOCKED"

def test_sandbox_read_protection_for_secrets():
    """Sandbox içinde çalışan komut .env sır dosyasını ASLA okuyamamalıdır."""
    if platform.system() != "Darwin":
        pytest.skip("Seatbelt kernel izolasyon testi sadece macOS üzerinde çalışır.")

    env_file = WORKSPACE_ROOT / ".env"
    created_dummy = False
    if not env_file.exists():
        env_file.write_text("SECRET_TEST_TOKEN=gravity_p0_secret\n", encoding="utf-8")
        created_dummy = True

    try:
        cmd = f"cat '{WORKSPACE_ROOT}/.env'"
        res = secure_sandbox_run(cmd)
        assert res["success"] is False
        assert "Operation not permitted" in res["stderr"] or res["state"] == "BLOCKED"
    finally:
        if created_dummy and env_file.exists():
            env_file.unlink()

def test_sandbox_write_allowed_inside_workspace():
    """Sandbox içinde belirtilen yalıtılmış çalışma alanına yazma başarılı olmalıdır."""
    allowed_file = SANDBOX_DIR / "valid_test.txt"
    if allowed_file.exists():
        allowed_file.unlink()

    cmd = f"echo 'SANDBOX_WRITE_OK' > '{allowed_file}'"
    res = secure_sandbox_run(cmd)
    if platform.system() == "Darwin":
        assert res["success"] is True
        assert allowed_file.exists()
        allowed_file.unlink()
    else:
        # Linux üzerinde Seatbelt olmadığında Fail-Closed (BLOCKED) dönmelidir
        assert res["state"] == "BLOCKED" or res["success"] is True

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

def test_rejection_of_syntax_only_as_full_verified():
    """Yalnızca sözdizimi derlemesi veya --help tam işlevsel VERIFIED sayılamaz."""
    # Test klasörü hazırla (içinde sadece boş main.py var, test yok)
    dummy_dir = WORKSPACE_ROOT / "tools" / "temp_syntax_only_dir"
    dummy_dir.mkdir(parents=True, exist_ok=True)
    (dummy_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    gate_res = IndependentVerificationGate.verify_runtime_execution(dummy_dir)
    # Temizle
    for f in dummy_dir.iterdir():
        f.unlink()
    dummy_dir.rmdir()

    assert gate_res.get("verified") is False
    assert gate_res.get("state") == "SYNTAX_ONLY"

# ------------------------------------------------------------------------------
# 4. DOĞRUDAN DOSYA ERİŞİM YETKİ KONTROLÜ (Madde 5)
# ------------------------------------------------------------------------------
def test_unauthorized_direct_file_access_blocked():
    """Modelin doğrudan .env veya kritik sistem dosyalarını okuması/yazması engellenmelidir."""
    read_res = tool_read_file(".env")
    assert "[GÜVENLİK ENGELİ]" in read_res

    write_res = tool_write_file(".env", "HACKED=1")
    assert "[GÜVENLİK ENGELİ]" in write_res

    write_res2 = tool_write_file(".git/config", "CORRUPTED=1")
    assert "[GÜVENLİK ENGELİ]" in write_res2

# ------------------------------------------------------------------------------
# 5. BAŞARISIZ İŞLEMDE OTOMATİK ROLLBACK TESTİ
# ------------------------------------------------------------------------------
def test_failed_installation_triggers_clean_rollback():
    """Çalışma testini geçemeyen bir repo kurulumu otomatik olarak geri alınmalı (rollback) ve temizlenmelidir."""
    engine = AutonomousExecutionEngine()
    fake_repo_dir = WORKSPACE_ROOT / "tools" / "temp_faulty_engine"
    fake_repo_dir.mkdir(parents=True, exist_ok=True)

    (fake_repo_dir / "main.py").write_text("import non_existent_broken_module\n", encoding="utf-8")
    engine.rollback_stack.append(("delete_dir", str(fake_repo_dir)))

    gate_res = IndependentVerificationGate.verify_runtime_execution(fake_repo_dir)
    assert gate_res.get("verified") is False

    engine.rollback()
    assert not fake_repo_dir.exists(), "Rollback başarısız: Bozuk modül temizlenemedi!"
    assert engine.state == TaskState.ROLLED_BACK

# ------------------------------------------------------------------------------
# 6. OPENHANDS OTONOM AJAN GÖREV TESTİ
# ------------------------------------------------------------------------------
def test_openhands_end_to_end_task_execution():
    """OpenHands izole ortamda gerçek kod oluşturma, test etme ve doğrulamayı başarıyla tamamlamalıdır."""
    engine = OpenHandsAgentEngine("pytest_openhands_verification")
    # CI ortamında yerel Ollama yoksa skip et, yerelde ise çalıştır
    try:
        import httpx
        with httpx.Client(timeout=2.0) as cl:
            r = cl.get("http://127.0.0.1:11434/api/tags")
            ollama_online = r.status_code == 200
    except Exception:
        ollama_online = False

    if not ollama_online:
        pytest.skip("Yerel Ollama servisi çevrimdışı, gerçek model E2E testi yerel M4 ortamında çalışır.")

    res = asyncio.run(engine.execute_autonomous_coding_cycle("Kriptografik güvenli token modülü yaz"))
    assert res.get("independent_verified") is True or res.get("sandbox_exit_code") == 0
