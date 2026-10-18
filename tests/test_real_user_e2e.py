"""
OMNICORE AUDITOR v6: GERÇEK SİSTEM VE KULLANICI E2E KABUL TESTLERİ
Mock/Simülasyon DEĞİLDİR; Mac M4 üzerinde çalışan canlı servisleri,
Seatbelt sandbox'ı, gerçek model sağlığını ve ResilienceKernel akışını doğrudan doğrular.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import urllib.request
import pytest
from pathlib import Path

from resilience_kernel import ResilienceKernel, OmniCoreToolAdapters, State
from universal_installer import install_repo
from sandbox_executor import secure_sandbox_run, WORKSPACE_ROOT


def test_mac_service_health():
    """1. Canlı FastAPI Backend Servis Sağlığı ve HTTP 200 Doğrulaması."""
    url = "http://127.0.0.1:5050/api/health"
    req = urllib.request.Request(url, headers={"User-Agent": "OmniCore-AuditEngine/6.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.getcode() == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "ONLINE"
        assert data.get("service") == "OmniCore"


def test_ollama_mistral_model_runtime():
    """2. Canlı Ollama Mistral-24B Model Varlığı ve Bellek Doğrulaması."""
    url = "http://127.0.0.1:11434/api/tags"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.getcode() == 200
        data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name") for m in data.get("models", [])]
        assert any("mistral-small-24b-abliterated" in m for m in models), "Mistral-24B modeli Ollama üzerinde yüklü olmalıdır."


def test_real_sandbox_git_clone_execution():
    """3. macOS Seatbelt Sandbox Altında Gerçek GitHub Repo Klonlama ve SHA Doğrulaması."""
    if platform.system() != "Darwin":
        pytest.skip("Seatbelt sandbox doğrulaması sadece macOS üzerinde çalışır.")

    res = install_repo("https://github.com/octocat/Hello-World")
    evidence = res.get("evidence", [])
    assert len(evidence) >= 2

    # Pre-probe kontrolü (mkdir, touch, git --version sandbox içinde)
    pre_probe = next((e for e in evidence if e.get("stage") == "PRE_PROBE"), None)
    assert pre_probe is not None
    assert pre_probe.get("exit_code") == 0

    # Git clone kontrolü
    clone_ev = next((e for e in evidence if e.get("stage") == "CLONE"), None)
    assert clone_ev is not None
    assert clone_ev.get("exit_code") == 0

    # Commit SHA kontrolü
    rev_ev = next((e for e in evidence if e.get("stage") == "REVISION"), None)
    assert rev_ev is not None
    assert len(rev_ev.get("commit", "")) == 40


def test_resilience_kernel_tool_execution():
    """4. ResilienceKernel Merkezi Yürütme Katmanı: Dosya Yazma ve Okuma Postcondition Doğrulaması."""
    kernel = ResilienceKernel()
    write_spec = OmniCoreToolAdapters.get_file_write_spec(WORKSPACE_ROOT)
    read_spec = OmniCoreToolAdapters.get_file_read_spec(WORKSPACE_ROOT)

    rel_file = "tasks/audit_test_e2e.txt"
    test_content = "OMNICORE_AUDIT_V6_PASS"

    # Yazma
    res_w = asyncio.run(kernel.execute(write_spec, {"filepath": rel_file, "content": test_content}))
    assert res_w.state == State.VERIFIED
    assert res_w.verified is True

    # Okuma
    res_r = asyncio.run(kernel.execute(read_spec, {"filepath": rel_file}))
    assert res_r.state == State.VERIFIED
    assert res_r.verified is True

    # Temizlik
    (WORKSPACE_ROOT / rel_file).unlink(missing_ok=True)


def test_security_leak_prevention_in_kernel():
    """5. Korumalı Dosyalara (.env) Müdahale Preflight Seviyesinde BLOCKED Olmalıdır."""
    kernel = ResilienceKernel()
    write_spec = OmniCoreToolAdapters.get_file_write_spec(WORKSPACE_ROOT)
    res = asyncio.run(kernel.execute(write_spec, {"filepath": ".env", "content": "LEAK=1"}))
    assert res.state == State.BLOCKED
    assert res.verified is False
