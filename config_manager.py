#!/usr/bin/env python3
"""
OMNICORE // GÜVENLİ YAPILANDIRMA VE API ANAHTARI YÖNETİCİSİ
Kural: Varsayılan sabit API anahtarı barındırılamaz.
Anahtar yalnızca güvenli ortamdan veya kilitli .env dosyasından okunur.
"""

import os
import secrets
from pathlib import Path

WORKSPACE_ROOT = Path('/Users/macair1/projects/ai').resolve()
ENV_FILE = WORKSPACE_ROOT / ".env"

def get_secure_api_key() -> str:
    """
    API anahtarını yalnızca güvenli ortamdan veya .env dosyasından okur.
    Hiçbir ortamda anahtar yoksa kriptografik olarak güvenli 256-bit anahtar üretir
    ve .env dosyasına yazarak izinlerini kilitler (0o600).
    """
    # 1. Ortam değişkeni kontrolü
    env_key = os.environ.get("OMNI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    # 2. .env dosyası kontrolü
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("OMNI_API_KEY="):
                        k = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if k:
                            os.environ["OMNI_API_KEY"] = k
                            return k
        except Exception:
            pass

    # 3. Kriptografik yeni anahtar üretimi
    new_key = f"omni_sec_{secrets.token_hex(32)}"
    try:
        content = ""
        if ENV_FILE.exists():
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        if "OMNI_API_KEY=" not in content:
            with open(ENV_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n# OMNICORE KORUMALI API ERİŞİM ANAHTARI\nOMNI_API_KEY={new_key}\n")
        # İzinleri 0o600 (sadece dosya sahibi okur/yazar) yap
        os.chmod(ENV_FILE, 0o600)
    except Exception as e:
        pass

    os.environ["OMNI_API_KEY"] = new_key
    return new_key

if __name__ == "__main__":
    k = get_secure_api_key()
    print("Secure API Key Loaded:", k[:12] + "..." + k[-6:])
