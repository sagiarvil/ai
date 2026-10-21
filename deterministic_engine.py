#!/usr/bin/env python3
"""
Deterministik Durum Makinesi ve Runtime Doğrulama Kanıt Şeması (OpenHands Mimarisi)
Durumlar: RECEIVED -> PLANNED -> RESEARCHING -> VALIDATING -> INSTALLING -> TESTING -> ACTIVATING -> VERIFIED
Hata Durumları: FAILED, BLOCKED, PARTIAL, ROLLED_BACK, NOT_EXECUTED, UNVERIFIED
"""
import time
import json
import os
from pathlib import Path

TASKS_LOG_DIR = Path(os.environ.get('BARIS_WORKSPACE', Path(__file__).resolve().parent)).resolve() / 'tasks'

class DeterministicEngine:
    def __init__(self, task_id: str = None):
        self.task_id = task_id or f"task_{int(time.time())}"
        self.state = "RECEIVED"
        self.evidence_log = []

    def transition(self, new_state: str, proof: dict):
        self.state = new_state
        entry = {"state": new_state, "timestamp": time.time(), "proof": proof}
        self.evidence_log.append(entry)
        self._persist()

    def _persist(self):
        TASKS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = TASKS_LOG_DIR / f"{self.task_id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": self.task_id,
                "current_state": self.state,
                "evidence_log": self.evidence_log
            }, f, indent=2, ensure_ascii=False)

    def verify_success(self) -> bool:
        """Sahte başarıyı engellemek için zorunlu runtime doğrulama kanıtı."""
        return any(
            e["state"] == "VERIFIED" and e.get("proof", {}).get("inference_pass") 
            for e in self.evidence_log
        )

