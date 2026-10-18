#!/usr/bin/env python3
"""
OMNICORE X // FAZ 7: INDUSTRIAL VERIFICATION CONTRACT
Zorunlu Sözleşme Şeması:
- task_id
- requested_goal
- execution_state
- tools_executed
- artifacts_created
- tests_passed
- tests_failed
- runtime_verified
- evidence_paths
- model_id
- commit_sha
- rollback_available
- final_decision (VERIFIED, PARTIAL, FAILED, BLOCKED, ROLLED_BACK)

Kural: Modelin metinsel 'başardım' iddiası ASLA kabul edilemez.
Yalnızca bağımsız yürütme ve test kanıtları varsa VERIFIED kararı verilebilir.
"""

import json
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class FinalDecision(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    ROLLED_BACK = "ROLLED_BACK"

class IndustrialVerificationReport(BaseModel):
    task_id: str
    requested_goal: str
    execution_state: str
    tools_executed: List[str] = Field(default_factory=list)
    artifacts_created: List[str] = Field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    runtime_verified: bool = False
    evidence_paths: List[str] = Field(default_factory=list)
    model_id: str
    commit_sha: Optional[str] = None
    rollback_available: bool = False
    final_decision: FinalDecision

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def write_proof(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        proof_file = output_dir / f"verification_proof_{self.task_id}.json"
        proof_file.write_text(self.to_json(), encoding="utf-8")
        return proof_file

class IndustrialVerificationEngine:
    @classmethod
    def evaluate(
        cls,
        task_id: str,
        requested_goal: str,
        execution_state: str,
        tools_executed: List[str],
        artifacts_created: List[str],
        tests_passed: int,
        tests_failed: int,
        runtime_verified: bool,
        evidence_paths: List[str],
        model_id: str,
        commit_sha: Optional[str] = None,
        rollback_available: bool = False,
        is_blocked_by_security: bool = False,
        is_rolled_back: bool = False
    ) -> IndustrialVerificationReport:
        """
        Endüstriyel karar matrisi:
        - Güvenlik ihlali / Sandbox engeli varsa -> BLOCKED
        - Rollback uygulandıysa -> ROLLED_BACK
        - runtime_verified = True ve tests_passed > 0 ve tests_failed == 0 -> VERIFIED
        - Hiçbir test veya somut runtime yok ama araçlar kısmi çalıştıysa -> PARTIAL (Asla sahte VERIFIED yok!)
        - Testler başarısız olduysa -> FAILED
        """
        if is_blocked_by_security:
            decision = FinalDecision.BLOCKED
        elif is_rolled_back:
            decision = FinalDecision.ROLLED_BACK
        elif tests_failed > 0:
            decision = FinalDecision.FAILED
        elif runtime_verified and tests_passed > 0 and tests_failed == 0:
            decision = FinalDecision.VERIFIED
        elif len(tools_executed) > 0 and not runtime_verified:
            # Araç çalıştı fakat bağımsız test/icra kanıtı henüz tamamlanmadı
            decision = FinalDecision.PARTIAL
        else:
            decision = FinalDecision.FAILED

        return IndustrialVerificationReport(
            task_id=task_id,
            requested_goal=requested_goal,
            execution_state=execution_state,
            tools_executed=tools_executed,
            artifacts_created=artifacts_created,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            runtime_verified=runtime_verified,
            evidence_paths=evidence_paths,
            model_id=model_id,
            commit_sha=commit_sha,
            rollback_available=rollback_available,
            final_decision=decision
        )
