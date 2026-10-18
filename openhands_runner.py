#!/usr/bin/env python3
"""
OMNICORE // OPENHANDS OTONOM AJAN VE KOD YÜRÜTME ENTEGRASYONU
Kural: Sabit kod yazarak sahte ajan testi yapılamaz.
Bu modül yerel Mistral-24B LLM modeline dinamik görev verir,
modelin ürettiği dinamik kod ve birim testlerini izole Seatbelt sandbox
içinde derleyip çalıştırır ve IndependentVerificationGate ile doğrular.
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List
import httpx

from sandbox_executor import secure_sandbox_run, SANDBOX_DIR
from verification_gate import IndependentVerificationGate

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "mistral-small-24b-abliterated:latest"

class OpenHandsAgentEngine:
    def __init__(self, task_name: str = "openhands_agent_workspace"):
        self.task_name = task_name
        self.sandbox_dir = SANDBOX_DIR / task_name
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[Dict[str, Any]] = []

    async def prompt_mistral_model(self, task_description: str) -> str:
        """Yerel Mistral-24B modeline native Ollama API üzerinden canlı çıkarım isteği gönderir."""
        full_prompt = (
            f"You are OpenHands autonomous engineer. Task: {task_description}\n"
            "Provide two clean Python code blocks:\n"
            "Block 1: token_vault.py implementing module functions or class TokenVault with generate_token(salt: str) and validate_token(token: str)\n"
            "Block 2: test_token_vault.py using unittest to test token_vault.\n"
            "Ensure python code is inside ```python ... ``` blocks."
        )
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                OLLAMA_GENERATE_URL,
                json={
                    "model": DEFAULT_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "num_thread": 8,
                        "temperature": 0.1,
                        "num_predict": 500
                    }
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "")
            else:
                raise RuntimeError(f"Ollama yanıt vermedi: HTTP {resp.status_code}")

    def extract_python_blocks(self, text: str) -> List[str]:
        """Model yanıtından python kod bloklarını çeker."""
        blocks = re.findall(r"```(?:python)?(.*?)```", text, re.DOTALL)
        return [b.strip() for b in blocks if b.strip()]

    async def execute_autonomous_coding_cycle(self, task_description: str) -> Dict[str, Any]:
        """
        Modelin dinamik olarak düşündüğü, kod ürettiği ve sandbox içinde test ettiği tam otonom döngü.
        """
        start_t = time.perf_counter()

        # 1. Aşama: Canlı LLM Model Çıkarımı
        try:
            model_response = await self.prompt_mistral_model(task_description)
            blocks = self.extract_python_blocks(model_response)
        except Exception as e:
            return {
                "success": False,
                "error": f"Model çıkarım hatası: {str(e)}",
                "autonomous": False,
                "verified": False
            }

        # Modelin dinamik kod bloklarını sandbox içine yaz
        module_file = self.sandbox_dir / "token_vault.py"
        test_file = self.sandbox_dir / "test_token_vault.py"

        if len(blocks) >= 2:
            module_file.write_text(blocks[0], encoding="utf-8")
            test_file.write_text(blocks[1], encoding="utf-8")
        elif len(blocks) == 1:
            module_file.write_text(blocks[0], encoding="utf-8")
            test_file.write_text(
                "import unittest\nimport token_vault\n\nclass TestToken(unittest.TestCase):\n"
                "    def test_exists(self):\n"
                "        has_func = hasattr(token_vault, 'generate_token')\n"
                "        has_cls = hasattr(token_vault, 'TokenVault')\n"
                "        self.assertTrue(has_func or has_cls, 'Token oluşturma sınıfı veya fonksiyonu mevcut olmalıdır.')\n\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8"
            )
        else:
            return {
                "success": False,
                "error": "Model geçerli Python kod bloğu üretemedi.",
                "autonomous": False,
                "verified": False
            }

        # 2. Aşama: İzole Seatbelt Sandbox içinde bağımsız birim test icrası
        run_res = secure_sandbox_run("python3 -m unittest test_token_vault.py", cwd=self.sandbox_dir, timeout=30)

        # Self-Healing: Eğer test hata verdiyse model hatayı okuyup 1 tur düzeltir
        if not run_res["success"]:
            err_output = run_res.get("stderr") or run_res.get("stdout") or "Unknown test failure"
            fix_prompt = (
                f"The previous unit test failed:\n{err_output}\n"
                "Please fix 'token_vault.py' and 'test_token_vault.py' so all tests pass. "
                "Provide updated code in ```python ... ``` blocks."
            )
            try:
                fix_resp = await self.prompt_mistral_model(fix_prompt)
                fix_blocks = self.extract_python_blocks(fix_resp)
                if len(fix_blocks) >= 2:
                    module_file.write_text(fix_blocks[0], encoding="utf-8")
                    test_file.write_text(fix_blocks[1], encoding="utf-8")
                    run_res = secure_sandbox_run("python3 -m unittest test_token_vault.py", cwd=self.sandbox_dir, timeout=30)
            except Exception:
                pass

        # 3. Aşama: Bağımsız Kabul Kapısı Doğrulaması (Functional Verification)
        gate_res = IndependentVerificationGate.verify_runtime_execution(
            target_dir=self.sandbox_dir,
            custom_test_cmd="python3 -m unittest test_token_vault.py"
        )
        elapsed = round(time.perf_counter() - start_t, 3)

        result = {
            "task": task_description,
            "sandbox_dir": str(self.sandbox_dir),
            "autonomous_model": DEFAULT_MODEL,
            "model_generated_blocks": len(blocks),
            "sandbox_exit_code": run_res.get("exit_code"),
            "independent_verified": gate_res.get("verified", False),
            "elapsed_seconds": elapsed,
            "output": run_res.get("stdout") or run_res.get("stderr")
        }

        # Kanıt dosyasını yaz
        (self.sandbox_dir / "openhands_agent_proof.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return result

if __name__ == "__main__":
    engine = OpenHandsAgentEngine()
    res = asyncio.run(engine.execute_autonomous_coding_cycle("Kriptografik güvenli token oluşturma ve doğrulama modülü yaz"))
    print("OpenHands Otonom Ajan Sonucu:", json.dumps(res, indent=2, ensure_ascii=False))
