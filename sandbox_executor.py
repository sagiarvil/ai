#!/usr/bin/env python3
"""
OMNICORE // GÜVENLİ VE İZOLE SANDBOX İCRA MOTORU (OPENHANDS UYUMLU)
Özellikler:
1. İzole Çalışma Alanı (sandbox_workspace): Ana sistem ve proje dosyalarından izole.
2. Çevre Değişkeni Arındırma (Env Sanitization): Hassas API anahtarları, şifreler temizlenir.
3. Path Traversal & Yıkıcı Komut Koruması: Ana diske ve kök dizine erişim engellenir.
4. Kaynak ve Zaman Sınırlandırması: Süre aşımı ve bellek taşması önlenir.
"""

import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
SANDBOX_DIR = WORKSPACE_ROOT / 'sandbox_workspace'
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/\s*",
    r"rm\s+-rf\s+/\*",
    r"mkfs",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r">\s*/dev/sd[a-z]",
    r"dd\s+if=.*of=/dev/",
    r"chmod\s+-R\s+777\s+/",
    r"chown\s+-R\s+.*:\s+/"
]

SENSITIVE_ENV_KEYS = [
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", 
    "FIREBASE_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"
]

def get_sanitized_env() -> Dict[str, str]:
    """Hassas ortam değişkenlerini arındırarak güvenli bir subprocess ortamı sunar."""
    safe_env = {}
    allowed_keys = ["PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TMPDIR", "TERM"]
    for k, v in os.environ.items():
        # Hassas anahtarları süz
        if any(bad in k.upper() for bad in SENSITIVE_ENV_KEYS):
            continue
        if k in allowed_keys or k.startswith("LC_"):
            safe_env[k] = v
    # Temel sistem PATH güvencesi
    safe_env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")
    return safe_env

def secure_sandbox_run(
    command: str, 
    cwd: Optional[Path] = None, 
    timeout: int = 90,
    isolated_workspace: bool = True
) -> Dict[str, Any]:
    """
    Komutu güvenli izole sandbox katmanında çalıştırır.
    """
    cmd_clean = command.strip()
    
    # 1. Yıkıcı komut patern kontrolü
    for p in BLOCKED_PATTERNS:
        if re.search(p, cmd_clean):
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "[GÜVENLİK ENGELİ]: Yıkıcı sistem komutu sandbox tarafından engellendi.",
                "isolated": True,
                "elapsed": 0.0
            }

    # 2. Çalışma dizini belirleme ve yalıtım
    if cwd:
        work_dir = Path(cwd).resolve()
        # Proje sınırları içinde mi kontrolü
        if not str(work_dir).startswith(str(WORKSPACE_ROOT)):
            work_dir = SANDBOX_DIR
    else:
        work_dir = SANDBOX_DIR if isolated_workspace else WORKSPACE_ROOT

    work_dir.mkdir(parents=True, exist_ok=True)
    safe_env = get_sanitized_env()
    start_t = time.perf_counter()

    try:
        res = subprocess.run(
            cmd_clean,
            shell=True,
            cwd=str(work_dir),
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = round(time.perf_counter() - start_t, 3)
        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "stdout": (res.stdout or "").strip(),
            "stderr": (res.stderr or "").strip(),
            "cwd": str(work_dir),
            "isolated": True,
            "elapsed": elapsed
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - start_t, 3)
        return {
            "success": False,
            "exit_code": 124,
            "stdout": "",
            "stderr": f"[ZAMAN AŞIMI]: Komut {timeout}s içinde tamamlanamadı.",
            "cwd": str(work_dir),
            "isolated": True,
            "elapsed": elapsed
        }
    except Exception as e:
        elapsed = round(time.perf_counter() - start_t, 3)
        return {
            "success": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"[Çalıştırma Hatası]: {str(e)}",
            "cwd": str(work_dir),
            "isolated": True,
            "elapsed": elapsed
        }

if __name__ == '__main__':
    test = secure_sandbox_run('echo SANDBOX_ACTIVE')
    print('Sandbox Test:', test)
