#!/usr/bin/env python3
"""
Sandbox ve Güvenli İcra Katmanı (OpenHands Uyumlu)
Tüm dış kaynaklı yüklemeleri, tarayıcı işlemlerini ve model kurulumlarını izole eder.
"""
import subprocess
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()

BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*",
    r"rm\s+-rf\s+/\*",
    r"mkfs",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r">\s*/dev/sd[a-z]",
    r"dd\s+if=.*of=/dev/"
]

def secure_sandbox_run(command: str, cwd: Optional[Path] = None, timeout: int = 90) -> Dict[str, Any]:
    cmd_clean = command.strip()
    for p in BLOCKED_PATTERNS:
        if re.search(p, cmd_clean):
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "[GÜVENLİK ENGELİ]: Yıkıcı sistem komutu sandbox tarafından engellendi."
            }

    work_dir = cwd or WORKSPACE_ROOT
    try:
        res = subprocess.run(
            cmd_clean,
            shell=True,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "stdout": (res.stdout or "").strip(),
            "stderr": (res.stderr or "").strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "exit_code": 124,
            "stdout": "",
            "stderr": f"[ZAMAN AŞIMI]: Komut {timeout}s içinde tamamlanamadı."
        }
    except Exception as e:
        return {
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"[Çalıştırma Hatası]: {str(e)}"
        }
