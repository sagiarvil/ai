#!/usr/bin/env python3
"""
OMNICORE // BAĞIMSIZ DOĞRULAYICI VE KABUL KAPISI (INDEPENDENT VERIFICATION GATE)
Kural: Model veya işlem kendi kendine başarı ilan edemez.
Başarı yalnızca bu bağımsız doğrulayıcı tarafından somut kanıtlarla onaylanır.

Zorunlu İlkeler:
1. 'sys.exit(0)' veya kukla komutlarla sahte başarı üretmek KESİNLİKLE YASAKTIR.
2. 'ls -la' gibi dosya listeleme komutlarını runtime doğrulaması saymak KESİNLİKLE YASAKTIR.
3. Yalnızca sözdizimi derlemesi (py_compile) veya CLI --help çıktısı tam işlevsel VERIFIED olamaz.
4. Tam işlevsel VERIFIED için gerçek birim testi veya somut fonksiyon icra kanıtı zorunludur.
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

class IndependentVerificationGate:
    # Sahte başarı üretmeye çalışan tüm regex kalıpları
    FORBIDDEN_REGEX_PATTERNS = [
        r"sys\.exit\(0\)",
        r"exit\(0\)",
        r"^\s*true\s*$",
        r"^\s*:\s*$",
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
                return False, f"Sahte/Kukla test komutu tespit edildi ve reddedildi: '{command}'"
        return True, "Geçerli"

    @classmethod
    def verify_runtime_execution(cls, target_dir: Path, custom_test_cmd: Optional[str] = None) -> Dict[str, Any]:
        """
        Kurulan modül veya CLI için gerçek, bağımsız bir işlevsellik probe'u yürütür.
        Yalnızca derleme veya --help başarılıysa tam VERIFIED verilmez; somut test zorunludur.
        """
        from sandbox_executor import secure_sandbox_run

        is_functional_test = False
        if custom_test_cmd:
            is_valid, reason = cls.audit_test_command(custom_test_cmd)
            if not is_valid:
                return {
                    "verified": False,
                    "state": "REJECTED_DUMMY",
                    "reason": reason,
                    "exit_code": -1
                }
            run_cmd = custom_test_cmd
            # Birim test veya fonksiyonel test mi?
            if any(k in custom_test_cmd for k in ["unittest", "pytest", "test", "-c"]):
                is_functional_test = True
        else:
            # Otomatik test tespiti
            test_files = list(target_dir.glob("test_*.py")) or list(target_dir.glob("*_test.py"))
            cli_candidates = [target_dir / "cli.py", target_dir / "main.py", target_dir / "app.py"]
            active_cli = next((c for c in cli_candidates if c.exists()), None)

            if test_files:
                run_cmd = f"python3 -m unittest '{test_files[0].name}'"
                is_functional_test = True
            elif active_cli:
                # Sadece CLI var, --help çalıştırılabilir ama bu tek başına FUNCTIONAL_VERIFIED değildir
                run_cmd = f"python3 '{active_cli.name}' --help"
                is_functional_test = False
            else:
                py_files = list(target_dir.glob("*.py"))
                if py_files:
                    run_cmd = f"python3 -m py_compile '{py_files[0].name}'"
                    is_functional_test = False
                else:
                    return {
                        "verified": False,
                        "state": "NO_CODE",
                        "reason": "Çalıştırılabilir veya doğrulanabilir bir kod modülü tespit edilemedi.",
                        "exit_code": -1
                    }

        # Sandbox içinde bağımsız çalıştırma
        res = secure_sandbox_run(run_cmd, cwd=target_dir, timeout=30)

        # Başarı değerlendirmesi
        if res["success"] and res["exit_code"] == 0:
            if not is_functional_test:
                # Derleme veya --help başarılı ama tam işlev testi yok
                return {
                    "verified": False,
                    "state": "SYNTAX_ONLY",
                    "command": run_cmd,
                    "exit_code": 0,
                    "reason": "Sözdizimi veya --help başarılı ancak bağımsız fonksiyonel işlevsellik testi bulunamadı. Tam VERIFIED için birim testi zorunludur.",
                    "output": res.get("stdout", "")[:500]
                }
            return {
                "verified": True,
                "state": "VERIFIED",
                "command": run_cmd,
                "exit_code": 0,
                "output": res.get("stdout", "")[:500],
                "elapsed": res.get("elapsed", 0.0)
            }
        else:
            return {
                "verified": False,
                "state": "FAILED",
                "command": run_cmd,
                "exit_code": res["exit_code"],
                "reason": res.get("stderr") or "Komut başarısız oldu.",
                "output": res.get("stdout", "")[:500]
            }

if __name__ == "__main__":
    valid, r = IndependentVerificationGate.audit_test_command("python3 main.py || python3 -c 'import sys; sys.exit(0)'")
    print("Audit Result (Should be False):", valid, r)
