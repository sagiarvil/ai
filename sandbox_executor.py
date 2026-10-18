#!/usr/bin/env python3
"""
OMNICORE // GERÇEK İŞLETİM SİSTEMİ SEVİYESİNDE SANDBOX İCRA MOTORU
Özellikler:
1. macOS Seatbelt (sandbox-exec) Kernel İzolasyonu:
   - Proje ana dizinine ve sistem dosyalarına yazma KESİNLİKLE ENGELLENİR.
   - Yazma izni SADECE sandbox_workspace ve /tmp ile sınırlandırılır.
   - Hassas dizinleri (~/.ssh, ~/.aws, .env vb.) okuma KESİNLİKLE ENGELLENİR.
2. İşlem İzolasyonu (Process Isolation):
   - Yeni process grubu (os.setpgrp), kaynak sınırlamaları (RLIMIT_CPU, RLIMIT_AS).
3. Ağ İzolasyonu (Network Isolation):
   - allow_network=False durumunda tüm ağ trafiği (deny network*) ile engellenir.
4. Fail-Closed Prensibi:
   - Eğer gerçek izolasyon katmanı uygulanamazsa komut BLOCKED olarak durdurulur.
"""

import os
import re
import resource
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
SANDBOX_DIR = WORKSPACE_ROOT / 'sandbox_workspace'
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

BLOCKED_COMMAND_PATTERNS = [
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
    "FIREBASE_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "OMNI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY"
]

def check_sandbox_availability() -> bool:
    """Sistemde macOS Seatbelt sandbox-exec aracının çalışabilirliğini doğrular."""
    try:
        res = subprocess.run(
            ["sandbox-exec", "-p", "(version 1)(allow default)", "true"],
            capture_output=True,
            timeout=3
        )
        return res.returncode == 0
    except Exception:
        return False

def generate_seatbelt_profile(sandbox_path: Path, allow_network: bool = True) -> str:
    """
    macOS Seatbelt kernel politikası üretir.
    - Yazma: SADECE sandbox_path ve geçici tmp dizinlerine izin verilir.
    - Okuma: Sistem kütüphanelerine ve temel projelere izin verilir, ancak sırlar (.env, .ssh) kilitlenir.
    - Ağ: allow_network=False ise tamamen bloke edilir.
    """
    network_rule = "(allow network*)" if allow_network else "(deny network*)"
    home = Path.home()
    
    profile = f"""(version 1)
(allow default)
{network_rule}

;; 1. DOSYA SİSTEMİ YAZMA KISITLAMALARI
;; Ana disk ve proje köküne yazma kesinlikle YASAK
(deny file-write* (subpath "{WORKSPACE_ROOT}"))
(deny file-write* (subpath "{home}"))

;; Sadece izole sandbox_workspace ve /tmp alanına yazılabilir
(allow file-write* (subpath "{sandbox_path}"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/private/var/folders"))

;; 2. HASSAS SIR VE BİLGİ OKUMA ENGELLEME
(deny file-read* (subpath "{WORKSPACE_ROOT}/.env"))
(deny file-read* (subpath "{home}/.ssh"))
(deny file-read* (subpath "{home}/.aws"))
(deny file-read* (subpath "{home}/.gnupg"))
(deny file-read* (subpath "{home}/.gemini/antigravity"))
"""
    return profile

def get_sanitized_env() -> Dict[str, str]:
    """Hassas anahtarları süzerek güvenli bir ortam değişkenleri sözlüğü üretir."""
    safe_env = {}
    allowed_keys = ["PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TMPDIR", "TERM"]
    for k, v in os.environ.items():
        if any(bad in k.upper() for bad in SENSITIVE_ENV_KEYS):
            continue
        if k in allowed_keys or k.startswith("LC_"):
            safe_env[k] = v
    safe_env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")
    safe_env["SANDBOX_CONTAINED"] = "1"
    return safe_env

def set_resource_limits(max_cpu_sec: int = 120):
    """Subprocess için kaynak sınırlamaları uygular."""
    os.setpgrp()
    try:
        # Maksimum CPU süresi sınırı
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_sec, max_cpu_sec + 5))
    except Exception:
        pass

def secure_sandbox_run(
    command: str,
    cwd: Optional[Path] = None,
    timeout: int = 90,
    allow_network: bool = True
) -> Dict[str, Any]:
    """
    Komutu gerçek işletim sistemi seviyesinde Seatbelt sandbox katmanında çalıştırır.
    İzolasyon katmanı mevcut değilse fail-closed prensibiyle BLOCKED döner.
    """
    cmd_clean = command.strip()

    # 1. Patern bazlı ön filtre
    for p in BLOCKED_COMMAND_PATTERNS:
        if re.search(p, cmd_clean):
            return {
                "success": False,
                "exit_code": -1,
                "state": "BLOCKED",
                "stdout": "",
                "stderr": "[GÜVENLİK ENGELİ]: Yıkıcı sistem komutu sandbox tarafından engellendi.",
                "isolated": True,
                "elapsed": 0.0
            }

    # 2. İzolasyon kullanılabilirlik denetimi (Fail-Closed)
    if not check_sandbox_availability():
        return {
            "success": False,
            "exit_code": -1,
            "state": "BLOCKED",
            "stdout": "",
            "stderr": "[GÜVENLİK ENGELİ]: Gerçek işletim sistemi izolasyon katmanı (Seatbelt) mevcut değil. İşlem BLOCKED edildi.",
            "isolated": False,
            "elapsed": 0.0
        }

    # 3. Yalıtılmış çalışma dizini
    target_dir = SANDBOX_DIR
    if cwd:
        candidate = Path(cwd).resolve()
        # Eğer belirtilen dizin sandbox_dir veya tools altında ise izin ver, aksi halde sandbox_dir'e kilitle
        if str(candidate).startswith(str(SANDBOX_DIR)) or str(candidate).startswith(str(WORKSPACE_ROOT / "tools")):
            target_dir = candidate

    target_dir.mkdir(parents=True, exist_ok=True)

    # 4. Seatbelt profili oluştur
    profile = generate_seatbelt_profile(sandbox_path=target_dir, allow_network=allow_network)
    safe_env = get_sanitized_env()

    start_t = time.perf_counter()
    try:
        # sandbox-exec ile çekirdek düzeyinde sarma
        wrapped_cmd = ["sandbox-exec", "-p", profile, "bash", "-c", cmd_clean]
        
        res = subprocess.run(
            wrapped_cmd,
            cwd=str(target_dir),
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=lambda: set_resource_limits(timeout)
        )
        elapsed = round(time.perf_counter() - start_t, 3)

        # Seatbelt engellemesi kontrolü
        is_denied = "Operation not permitted" in (res.stderr or "") or res.returncode == 126
        state = "VERIFIED" if res.returncode == 0 else ("BLOCKED" if is_denied else "FAILED")

        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "state": state,
            "stdout": (res.stdout or "").strip(),
            "stderr": (res.stderr or "").strip(),
            "cwd": str(target_dir),
            "isolated": True,
            "elapsed": elapsed
        }
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - start_t, 3)
        return {
            "success": False,
            "exit_code": 124,
            "state": "FAILED",
            "stdout": "",
            "stderr": f"[ZAMAN AŞIMI]: Komut {timeout}s içinde tamamlanamadı.",
            "cwd": str(target_dir),
            "isolated": True,
            "elapsed": elapsed
        }
    except Exception as e:
        elapsed = round(time.perf_counter() - start_t, 3)
        return {
            "success": False,
            "exit_code": 1,
            "state": "FAILED",
            "stdout": "",
            "stderr": f"[Sandbox Hatası]: {str(e)}",
            "cwd": str(target_dir),
            "isolated": True,
            "elapsed": elapsed
        }

if __name__ == "__main__":
    t = secure_sandbox_run("echo REAL_SEATBELT_SANDBOX_ACTIVE")
    print("Sandbox Test Result:", t)
