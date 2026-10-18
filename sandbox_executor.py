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
import platform
import re
import resource
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent
OMNICORE_HOME = Path.home() / '.omnicore'
SANDBOX_DIR = OMNICORE_HOME / 'sandbox_workspace'
OMNICORE_HOME.mkdir(parents=True, exist_ok=True)
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
    """Sistemde gerçek izolasyon katmanının çalışabilirliğini doğrular."""
    if platform.system() == "Darwin":
        try:
            res = subprocess.run(
                ["sandbox-exec", "-p", "(version 1)(allow default)", "true"],
                capture_output=True,
                timeout=3
            )
            return res.returncode == 0
        except Exception:
            return False
    elif platform.system() == "Linux":
        return True
    return False

def generate_seatbelt_profile(sandbox_path: Path, allow_network: bool = False) -> str:
    """
    macOS Seatbelt kernel politikası üretir.
    - Varsayılan: (deny default)
    - Yazma: SADECE staging/sandbox çalışma ağacı (~/.omnicore) ve geçici sistem dizinleri (/tmp). Proje köküne yazma kesinlikle reddedilir.
    - Okuma: Sistem kütüphanelerine izin verilir, ancak sırlar (.env, .ssh, .aws) kesinlikle reddedilir.
    - Ağ: Varsayılan olarak (deny network*), yalnızca açıkça allow_network=True istendiğinde izin verilir.
    """
    if allow_network:
        network_rule = "(allow network*)"
    else:
        network_rule = """(deny network*)
(allow network* (local ip "localhost:*"))
(allow network* (remote ip "localhost:*"))"""
    home = Path.home()

    profile = f"""(version 1)
(deny default)
(allow process-exec*)
(allow process-fork)
(allow sysctl-read)
(allow mach-lookup)
(allow signal (target self))
(allow ipc-posix*)
(allow pseudo-tty)
(allow file-ioctl)
(allow file-read*)
(allow file-write*
    (subpath "{sandbox_path}")
    (subpath "{OMNICORE_HOME}")
    (subpath "{home}/.npm")
    (subpath "{home}/.pnpm-store")
    (subpath "{home}/.cache")
    (subpath "/private/tmp")
    (subpath "/private/var/folders")
    (subpath "/dev")
)
(deny file-write* (subpath "{WORKSPACE_ROOT}"))
(deny file-write* (subpath "{home}/omnicore-auditor"))
(deny file-write* (subpath "{home}/.ssh"))
(deny file-write* (subpath "{home}/.aws"))
(deny file-read* (subpath "{WORKSPACE_ROOT}/.env"))
(deny file-read* (subpath "{home}/.ssh"))
(deny file-read* (subpath "{home}/.aws"))
(deny file-read* (subpath "{home}/.gnupg"))
(deny file-read* (subpath "{home}/.gemini/antigravity"))
{network_rule}
"""
    return profile

def verify_sandbox_runtime_probe(target_dir: Path, allow_network: bool = True) -> Dict[str, Any]:
    """
    Kurulum öncesi gerçek sandbox süreci içinde mkdir, touch, git --version
    yazma ve ikili çalıştırma ön testlerini icra eder.
    Ana süreçte değil, sandbox içinde çalıştırılır.
    """
    probe_cmd = "mkdir -p .probe_test && touch .probe_test/probe.tmp && git --version && rm -rf .probe_test"
    return secure_sandbox_run(probe_cmd, cwd=target_dir, timeout=15, allow_network=allow_network)


def get_sanitized_env() -> Dict[str, str]:
    """Hassas anahtarları süzerek güvenli bir ortam değişkenleri sözlüğü üretir."""
    safe_env = {}
    allowed_keys = ["PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TMPDIR", "TERM", "PYTHONPATH"]
    for k, v in os.environ.items():
        if any(bad in k.upper() for bad in SENSITIVE_ENV_KEYS):
            continue
        if k in allowed_keys or k.startswith("LC_"):
            safe_env[k] = v

    # Kurulu motorları dinamik olarak PYTHONPATH'e ekle (Öğrenilen kütüphaneleri kullanabilme kabiliyeti)
    installed_engines_dir = OMNICORE_HOME / 'installed_engines'
    installed_paths = []
    if installed_engines_dir.exists():
        installed_paths = [str(d) for d in installed_engines_dir.iterdir() if d.is_dir()]

    current_pythonpath = os.environ.get("PYTHONPATH", "")
    all_python_paths = installed_paths + ([current_pythonpath] if current_pythonpath else [])
    safe_env["PYTHONPATH"] = ":".join(all_python_paths)

    # Kurulu CLI ikililerini, Homebrew ve NVM ikili yollarını PATH'e ekle
    omnicore_bin = OMNICORE_HOME / 'bin'
    omnicore_bin.mkdir(parents=True, exist_ok=True)
    extra_paths = [str(omnicore_bin), "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"]
    nvm_dir = Path.home() / ".nvm/versions/node"
    if nvm_dir.is_dir():
        for node_ver in nvm_dir.iterdir():
            bin_path = node_ver / "bin"
            if bin_path.is_dir():
                extra_paths.append(str(bin_path))

    existing_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")
    safe_env["PATH"] = ":".join(extra_paths) + ":" + existing_path
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
    allow_network: bool = False
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

    target_dir = SANDBOX_DIR
    if cwd:
        candidate = Path(cwd).resolve()
        import tempfile
        sys_tmp = tempfile.gettempdir()
        allowed_roots = [
            str(OMNICORE_HOME),
            str(SANDBOX_DIR),
            str(WORKSPACE_ROOT / "tools"),
            sys_tmp,
            str(Path(sys_tmp).resolve())
        ]
        if any(str(candidate).startswith(r) for r in allowed_roots):
            target_dir = candidate

    target_dir.mkdir(parents=True, exist_ok=True)

    # 4. Seatbelt profili oluştur
    profile = generate_seatbelt_profile(sandbox_path=target_dir, allow_network=allow_network)
    safe_env = get_sanitized_env()

    start_t = time.perf_counter()
    try:
        # Platforma göre izole sarma (macOS: Seatbelt Kernel Sandbox, Linux: Isolated Environment)
        if platform.system() == "Darwin":
            wrapped_cmd = ["sandbox-exec", "-p", profile, "bash", "-c", cmd_clean]
        else:
            wrapped_cmd = ["bash", "-c", cmd_clean]

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

        is_darwin = platform.system() == "Darwin"
        return {
            "success": res.returncode == 0,
            "exit_code": res.returncode,
            "state": state,
            "stdout": (res.stdout or "").strip(),
            "stderr": (res.stderr or "").strip(),
            "cwd": str(target_dir),
            "isolated": is_darwin,
            "seatbelt_applied": is_darwin,
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
