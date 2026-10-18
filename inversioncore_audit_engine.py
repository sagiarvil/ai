#!/usr/bin/env python3
"""
INVERSIONCORE: MISTRAL-24B ZIRHLI AKILLI KONTRAT & PROTOKOL GÜVENLİK DENETİM MOTORU
Mimari:
1. Deterministik Ön-İşleyici (State-Mutation & Threat Surface Extractor)
2. Pin'lenmiş KV-Cache (Slot-0 / 0ms System Prompt Overhead)
3. Sıfır-Entropi Zafiyet Teşhisi & Otomatik Güvenlik Yaması (Remediation) Üretimi
4. SQLite WAL Kriptografik Denetim İzi
"""

import asyncio
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import List, Literal
from pydantic import BaseModel, Field, field_validator
from openai import AsyncOpenAI

# ==============================================================================
# 1. SLOT-0 İLE BİREBİR EŞLEŞEN DEĞİŞTİRİLEMEZ SİSTEM ANAYASASI
# ==============================================================================
IMMUTABLE_SYSTEM_CORE = (
    "Sen görev-kritik (mission-critical) endüstriyel bir karar ve analiz çekirdeğisin. "
    "Sıfır tolerans prensibiyle çalışırsın. Spekülasyon, dolgu cümlesi veya belirsizlik yasaktır. "
    "Yalnızca kanıtlanabilir teknik bulguları ve eksiksiz prosedürleri JSON şemasında üret."
)

LLM_BASE_URL = "http://127.0.0.1:8080/v1"
PINNED_SLOT_ID = 0

# ==============================================================================
# 2. DETERMİNİSTİK ÖN-İŞLEYİCİ (AST / Tehdit Yüzeyi Damıtıcı)
# ==============================================================================
class ContractSurfaceExtractor:
    """
    Ham akıllı kontrat kodunu LLM'e göndermeden önce tarar;
    kritik durum değişimlerini, dış çağrıları ve yetki vektörlerini etiketler.
    """
    PATTERNS = {
        "EXTERNAL_VALUE_CALL": r"\.(call|delegatecall|staticcall|transfer|send)\s*[\(\{]",
        "AUTH_TX_ORIGIN": r"tx\.origin",
        "UNCHECKED_MATH": r"unchecked\s*\{",
        "STRICT_BALANCE_EQ": r"address\(this\)\.balance\s*==",
        "STATE_MODIFIERS": r"\b(onlyOwner|nonReentrant|whenNotPaused)\b",
        "TIMESTAMP_DEPENDENCE": r"block\.(timestamp|number)"
    }

    @classmethod
    def extract_telemetry(cls, source_code: str) -> str:
        clean_code = re.sub(r"//.*", "", source_code)
        clean_code = re.sub(r"/\*[\s\S]*?\*/", "", clean_code)

        signals = []
        for tag, regex in cls.PATTERNS.items():
            matches = re.findall(regex, clean_code)
            if matches:
                signals.append(f"- [{tag}]: {len(matches)} noktada tespit edildi.")

        signal_summary = "\n".join(signals) if signals else "- [STATİK SİNYAL]: Belirgin tehlikeli desen bulunmadı."
        return f"### STATİK ÖN-TARAMA SİNYALLERİ:\n{signal_summary}\n\n### KAYNAK KOD:\n{source_code.strip()}"

# ==============================================================================
# 3. KATI GÜVENLİK DENETİM ŞEMASI (Gatekeeper Contract)
# ==============================================================================
class VulnerabilityFinding(BaseModel):
    category: Literal[
        "REENTRANCY",
        "ACCESS_CONTROL",
        "ORACLE_MANIPULATION",
        "ARITHMETIC_PRECISION",
        "DENIAL_OF_SERVICE",
        "LOGIC_FLAW",
        "NONE"
    ]
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"]
    affected_function: str = Field(..., description="Zafiyetin bulunduğu fonksiyon veya modül adı")
    state_transition_flaw: str = Field(
        ...,
        description="Durum (state) değişimindeki hatanın adım adım mekanik açıklaması (Örn: CEI ihlali)"
    )

class InversionCoreAuditReport(BaseModel):
    audit_id: str
    overall_security_posture: Literal["COMPROMISED_RISK", "WARNING", "HARDENED"]
    risk_score: int = Field(..., ge=0, le=100, description="0 (Tam Güvenli) - 100 (Kritik Risk) arası puan")
    findings: List[VulnerabilityFinding]
    remediated_solidity_code: str = Field(
        ...,
        description="Tüm zafiyetlerin kapatıldığı, CEI ve güvenlik standartlarına uygun tam derlenebilir yama kodu"
    )
    formal_invariants: List[str] = Field(
        ...,
        min_length=2,
        description="Kontratın her koşulda koruması gereken matematiksel/mantıksal değişmezlik (invariant) kuralları"
    )

    @field_validator("remediated_solidity_code")
    @classmethod
    def verify_patch_completeness(cls, v: str) -> str:
        banned_tokens = ["// TODO", "...", "/* kod buraya */", "pass"]
        for token in banned_tokens:
            if token in v:
                raise ValueError(f"YAMA REDDEDİLDİ: Güvenlik yamasında eksik yer tutucu ('{token}') bırakılamaz!")
        if "function " not in v and "contract " not in v:
            raise ValueError("YAMA REDDEDİLDİ: Geçerli bir Solidity kontrat/fonksiyon bloğu üretilmedi!")
        return v

# ==============================================================================
# 4. ZIRHLI INVERSIONCORE MOTORU
# ==============================================================================
class InversionCoreEngine:
    def __init__(self, db_path: str = "inversioncore_ledger.db"):
        self.client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="inversion-core-local", timeout=90.0)
        self.gpu_lock = asyncio.Semaphore(1)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
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

    async def audit_contract(self, audit_id: str, contract_code: str) -> InversionCoreAuditReport:
        enriched_telemetry = ContractSurfaceExtractor.extract_telemetry(contract_code)
        code_hash = hashlib.sha256(contract_code.encode("utf-8")).hexdigest()

        async with self.gpu_lock:
            t0 = time.monotonic()
            messages = [
                {"role": "system", "content": IMMUTABLE_SYSTEM_CORE},
                {
                    "role": "user",
                    "content": (
                        f"[DENETİM KİMLİĞİ]: {audit_id}\n"
                        f"{enriched_telemetry}\n\n"
                        "[GÖREV]: Yukarıdaki akıllı kontratı mimari ve durum geçişleri (state transitions) açısından denetle. "
                        "Varsa Reentrancy (CEI ihlali), yetki kontrolü (`tx.origin` / eksik modifier) ve mantık hatalarını tespit et. "
                        "Zafiyetleri tamamen kapatan üretim kalitesinde (production-ready) yama kodunu (`remediated_solidity_code`) "
                        "ve kontratın matematiksel değişmezlik kurallarını (`formal_invariants`) üret."
                    )
                }
            ]

            schema_payload = {
                "type": "json_schema",
                "json_schema": {
                    "name": "inversioncore_audit_schema",
                    "strict": True,
                    "schema": InversionCoreAuditReport.model_json_schema()
                }
            }

            for attempt in range(1, 4):
                try:
                    response = await self.client.chat.completions.create(
                        model="mistral-small-24b-abliterated",
                        messages=messages,
                        response_format=schema_payload,
                        temperature=0.0,
                        seed=42,
                        extra_body={
                            "cache_prompt": True,
                            "id_slot": PINNED_SLOT_ID
                        }
                    )
                    raw_json = response.choices[0].message.content
                    report = InversionCoreAuditReport.model_validate_json(raw_json)

                    latency_ms = int((time.monotonic() - t0) * 1000)
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO contract_audits VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                audit_id,
                                datetime.now(timezone.utc).isoformat(),
                                code_hash,
                                report.risk_score,
                                report.overall_security_posture,
                                latency_ms,
                                raw_json
                            )
                        )
                    return report

                except Exception as err:
                    if attempt == 3:
                        raise RuntimeError(f"InversionCore doğrulama kapısı 3 denemede geçilemedi: {err}")
                    messages.append({"role": "assistant", "content": raw_json if 'raw_json' in locals() else "{}"})
                    messages.append({
                        "role": "user",
                        "content": f"[GATEKEEPER HATASI - DENEME {attempt}]: {err}. Eksiksiz yama kodu ve tam şema uyumu ile yeniden üret."
                    })

# ==============================================================================
# 5. DOĞRULAMA TESTİ
# ==============================================================================
async def main():
    engine = InversionCoreEngine()
    sample_vault = """
    pragma solidity ^0.8.20;
    contract VulnerableVault {
        mapping(address => uint256) public balances;
        address public owner;

        constructor() { owner = msg.sender; }

        function deposit() external payable {
            balances[msg.sender] += msg.value;
        }

        function withdraw(uint256 amount) external {
            require(balances[msg.sender] >= amount, "Insufficient balance");
            (bool success, ) = msg.sender.call{value: amount}("");
            require(success, "Transfer failed");
            balances[msg.sender] -= amount;
        }

        function sweepEmergency(address payable recipient) external {
            require(tx.origin == owner, "Not authorized");
            recipient.transfer(address(this).balance);
        }
    }
    """
    print("[*] InversionCore Zırhlı Denetim Başlatılıyor (Slot-0 Pinned KV)...")
    rapor = await engine.audit_contract(audit_id="INV-2026-VAULT-001", contract_code=sample_vault)
    print(rapor.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(main())
