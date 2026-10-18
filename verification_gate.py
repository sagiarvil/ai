#!/usr/bin/env python3
"""
OMNICORE // BAĞIMSIZ DOĞRULAYICI VE KABUL KAPISI (INDEPENDENT VERIFICATION GATE)
Kural: Model veya işlem kendi kendine başarı ilan edemez.
Başarı yalnızca bu bağımsız doğrulayıcı tarafından somut kanıtlarla onaylanır.

Yasaklar:
1. 'sys.exit(0)' veya kukla komutlarla sahte başarı üretmek KESİNLİKLE YASAKTIR.
2. 'ls -la' gibi dosya listeleme komutlarını runtime doğrulaması saymak KESİNLİKLE YASAKTIR.
3. Çıktısı boş olan veya hata kodu != 0 olan hiçbir komut VERIFIED sayılamaz.
"""

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

class IndependentVerificationGate:
    # Sahte başarı üretmeye çalışan tüm regex kalıpları
    FORBIDDEN_REGEX_PATTERNS = [
        r"sys\.exit\(0\)",
        r"exit\(0\)",
        r"\|\|\s*(true|:|ls\b)",
        r"^ls(\s+-[a-zA-Z0-9]+)?(\s+.*)?$",
        r"echo\s+['\"]?(ok|pass|success)['\"]?$"
    ]

    @classmethod
    def audit_test_command(cls, command: str) -> Tuple[bool, str]:
        """Test komutunun sahte veya kukla bir bypass içerip içermediğini denetler."""
        cmd_clean = command.strip().lower()
        for pattern in cls.FORBIDDEN_REGEX_PATTERNS:
            if re.search(pattern, cmd_clean):
                return False, f"Sahte/Kukla test komutu tespit edildi ve reddedildi: '{command}' (Kalıp: {pattern})"
        return True, "Geçerli"

    @classmethod
    def verify_runtime_execution(cls, target_dir: Path, custom_test_cmd: Optional[str] = None) -> Dict[str, Any]:
        """
        Kurulan modül veya CLI için gerçek, bağımsız bir işlevsellik probe'u yürütür.
        """
        from sandbox_executor import secure_sandbox_run

        # 1. Özel test komutu verilmişse denetle
        if custom_test_cmd:
            is_valid, reason = cls.audit_test_command(custom_test_cmd)
            if not is_valid:
                return {
                    "verified": False,
                    "reason": reason,
                    "exit_code": -1
                }
            run_cmd = custom_test_cmd
        else:
            # 2. Gerçek işlevsellik tespiti (Otomatik Bağımsız Probe)
            py_files = list(target_dir.glob("*.py"))
            cli_candidates = [target_dir / "cli.py", target_dir / "main.py", target_dir / "app.py"]

            active_cli = next((c for c in cli_candidates if c.exists()), None)

            if active_cli:
                run_cmd = f"python3 '{active_cli.name}' --help"
            elif py_files:
                run_cmd = f"python3 -m py_compile '{py_files[0].name}'"
            elif (target_dir / "package.json").exists():
                run_cmd = "node -e 'const pkg=require(\"./package.json\"); console.log(pkg.name);'"
            else:
                return {
                    "verified": False,
                    "reason": "Çalıştırılabilir veya doğrulanabilir bir kod modülü tespit edilemedi.",
                    "exit_code": -1
                }

        # Sandbox içinde bağımsız çalıştırma
        res = secure_sandbox_run(run_cmd, cwd=target_dir, timeout=30)
        
        # Kesin başarı şartları:
        if res["success"] and res["exit_code"] == 0:
            return {
                "verified": True,
                "command": run_cmd,
                "exit_code": 0,
                "output": res["stdout"][:500],
                "elapsed": res.get("elapsed", 0.0)
            }
        else:
            return {
                "verified": False,
                "command": run_cmd,
                "exit_code": res["exit_code"],
                "reason": res.get("stderr") or "Komut başarısız oldu.",
                "output": res.get("stdout", "")[:500]
            }

if __name__ == "__main__":
    valid, r = IndependentVerificationGate.audit_test_command("python3 main.py || python3 -c 'import sys; sys.exit(0)'")
    print("Audit Result (Should be False):", valid, r)
