#!/usr/bin/env python3
"""
INVERSIONCORE MİSYON-KRİTİK TEST SÜİTİ
Deterministik doğrulamalar:
1. ContractSurfaceExtractor regex sinyal tespiti
2. Pydantic Gatekeeper (Zafiyet & Yama) kural zorlamaları
3. SQLite WAL Defteri veri yazma/okuma bütünlüğü
4. FastAPI ve Web Arayüzü uç nokta testleri
"""

import os
import sqlite3
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from inversioncore_audit_engine import (
    ContractSurfaceExtractor,
    InversionCoreAuditReport,
    VulnerabilityFinding
)
from server import app

client = TestClient(app)

def test_ast_surface_extractor():
    """Statik regex çıkarıcının zafiyetli desenleri eksiksiz yakaladığını doğrular."""
    sample_code = """
    contract Test {
        function pay() external {
            require(tx.origin == owner);
            (bool s,) = msg.sender.call{value: 10}("");
            unchecked { count++; }
            if (address(this).balance == 0) revert();
        }
    }
    """
    telemetry = ContractSurfaceExtractor.extract_telemetry(sample_code)
    assert "[EXTERNAL_VALUE_CALL]" in telemetry
    assert "[AUTH_TX_ORIGIN]" in telemetry
    assert "[UNCHECKED_MATH]" in telemetry
    assert "[STRICT_BALANCE_EQ]" in telemetry
    print("[PASS] ContractSurfaceExtractor tüm sinyalleri başarıyla yakaladı.")

def test_gatekeeper_rejects_lazy_placeholders():
    """Gatekeeper'ın // TODO, ... gibi eksik kod yer tutucularını sertçe reddettiğini doğrular."""
    invalid_patch = "function withdraw() public { // TODO: implement fix }"
    try:
        InversionCoreAuditReport(
            audit_id="TEST-01",
            overall_security_posture="WARNING",
            risk_score=75,
            findings=[
                VulnerabilityFinding(
                    category="REENTRANCY",
                    severity="HIGH",
                    affected_function="withdraw",
                    state_transition_flaw="CEI ihlali"
                )
            ],
            remediated_solidity_code=invalid_patch,
            formal_invariants=["balance >= 0", "owner != address(0)"]
        )
        assert False, "Gatekeeper // TODO içeren yamayı reddetmedi!"
    except ValidationError as e:
        assert "YAMA REDDEDİLDİ" in str(e)
        print("[PASS] Gatekeeper yer tutucu içeren yamayı başarıyla engelledi.")

def test_gatekeeper_accepts_valid_contract():
    """Gatekeeper'ın eksiksiz ve geçerli Solidity yamalarını onayladığını doğrular."""
    valid_patch = """
    function withdraw(uint256 amount) external nonReentrant {
        require(balances[msg.sender] >= amount, "Insufficient");
        balances[msg.sender] -= amount;
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");
    }
    """
    report = InversionCoreAuditReport(
        audit_id="TEST-02",
        overall_security_posture="HARDENED",
        risk_score=5,
        findings=[],
        remediated_solidity_code=valid_patch,
        formal_invariants=["balances[msg.sender] invariant preserved", "total >= sum(balances)"]
    )
    assert report.audit_id == "TEST-02"
    assert report.risk_score == 5
    print("[PASS] Gatekeeper geçerli yamayı başarıyla onayladı.")

def test_sqlite_wal_persistence():
    """SQLite WAL veritabanının düzgün açılıp veri kaydettiğini doğrular."""
    test_db = "test_ledger.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    with sqlite3.connect(test_db) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contract_audits (
                audit_id TEXT PRIMARY KEY,
                timestamp_utc TEXT,
                code_sha256 TEXT,
                risk_score INTEGER,
                posture TEXT,
                latency_ms INTEGER,
                report_json TEXT
            )
        """)
        conn.execute(
            "INSERT INTO contract_audits VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("AUDIT-TEST", "2026-10-18T13:00:00Z", "hash123", 10, "HARDENED", 150, "{}")
        )
        cursor = conn.cursor()
        cursor.execute("SELECT audit_id, posture FROM contract_audits WHERE audit_id='AUDIT-TEST'")
        row = cursor.fetchone()
        assert row[0] == "AUDIT-TEST"
        assert row[1] == "HARDENED"

    if os.path.exists(test_db):
        os.remove(test_db)
    print("[PASS] SQLite WAL defteri yazma ve okuma testi başarılı.")

def test_fastapi_endpoints():
    """FastAPI REST uç noktalarını ve HTML arayüzünü test eder."""
    # 1. Ana sayfa HTML kontrolü
    resp = client.get("/")
    assert resp.status_code == 200
    assert "INVERSION" in resp.text
    assert "M4 24GB AIR-GAP" in resp.text

    # 2. Status uç noktası
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "endpoint" in data
    assert "slot_id" in data

    # 3. Denetim defteri geçmişi
    resp = client.get("/api/audits")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    print("[PASS] FastAPI uç noktaları ve Web Dashboard başarıyla doğrulandı.")

if __name__ == "__main__":
    print("=== INVERSIONCORE TEST SÜİTİ ÇALIŞTIRILIYOR ===")
    test_ast_surface_extractor()
    test_gatekeeper_rejects_lazy_placeholders()
    test_gatekeeper_accepts_valid_contract()
    test_sqlite_wal_persistence()
    test_fastapi_endpoints()
    print("=== TÜM TESTLER BAŞARIYLA GEÇTİ (5/5 PASS) ===")
