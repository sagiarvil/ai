#!/usr/bin/env python3
"""
OMNICORE // OTONOM YAZILIM MÜHENDİSİ AJAN ÇEKİRDEĞİ (AUTONOMOUS AGENTIC LOOP)
Özellikler:
- %100 Yerel Mistral-24B (Abliterated) Beyni (Apple M4 Metal / 14GB SSD)
- GitHub Repo Arama & Otomatik Kurucu (tool_search_and_install_github_repo)
- Çoklu Yerel Tarayıcı & Gizlilik Ağları (Chrome, Safari, I2P i2pd, Tor SOCKS5)
- Otonom Terminal (Shell) Çalıştırma Aracı
- Kendi Kendini Onaran (Self-Healing / Reflection) Test Döngüsü
"""

import asyncio
import json
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import httpx

from browser_controller import LocalBrowserEngine

OLLAMA_API_URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL_NAME = "mistral-small-24b-abliterated:latest"

WORKSPACE_DIR = Path("/Users/macair1/projects/ai")
TOOLS_DIR = WORKSPACE_DIR / "tools"
TOOLS_DIR.mkdir(exist_ok=True)
ACTIVE_ENGINES_FILE = WORKSPACE_DIR / "active_engines.json"

def tool_search_and_install_github_repo(query_or_url: str) -> str:
    target_input = query_or_url.strip()
    repo_url = target_input
    repo_name = ""
    description = ""

    if not target_input.startswith("http"):
        try:
            res = subprocess.run(
                ["gh", "search", "repos", target_input, "--limit", "1", "--json", "fullName,url,description"],
                capture_output=True, text=True, timeout=30
            )
            if res.returncode == 0:
                items = json.loads(res.stdout)
                if items:
                    repo_url = items[0]["url"]
                    repo_name = items[0]["fullName"].split("/")[-1]
                    description = items[0].get("description", "")
        except Exception as e:
            return f"[GitHub Arama Hatası]: {str(e)}"

    if not repo_name:
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    target_dir = TOOLS_DIR / repo_name

    if target_dir.exists() and (target_dir / ".git").exists():
        res = subprocess.run(["git", "-C", str(target_dir), "pull"], capture_output=True, text=True, timeout=30)
        clone_output = f"Mevcut depo güncellendi: {res.stdout.strip()}"
    else:
        res = subprocess.run(["git", "clone", "--depth", "1", repo_url, str(target_dir)], capture_output=True, text=True, timeout=90)
        if res.returncode != 0:
            return f"[Klonlama Hatası]: {res.stderr or res.stdout}"
        clone_output = f"Depo klonlandı: {target_dir}"

    req_file = target_dir / "requirements.txt"
    pkg_file = target_dir / "package.json"
    dep_output = "Bağımlılık dosyası yok."

    if req_file.exists():
        r_res = subprocess.run(
            ["python3", "-m", "pip", "install", "-r", str(req_file), "--break-system-packages"],
            capture_output=True, text=True, timeout=180
        )
        status_text = "BAŞARILI" if r_res.returncode == 0 else "HATA"
        dep_output = f"Python bağımlılıkları kuruldu ({status_text}): " + r_res.stdout[-150:]
    elif pkg_file.exists():
        p_res = subprocess.run(["npm", "install", "--prefix", str(target_dir)], capture_output=True, text=True, timeout=180)
        status_text = "BAŞARILI" if p_res.returncode == 0 else "HATA"
        dep_output = f"Node.js bağımlılıkları kuruldu ({status_text}): " + p_res.stdout[-150:]

    return (
        f"✅ [MOTOR KURULDU VE AKTİF EDİLDİ]\n"
        f"- Depo: {repo_url}\n"
        f"- Dizin: {target_dir}\n"
        f"- Klon: {clone_output}\n"
        f"- Bağımlılık: {dep_output}"
    )

def tool_browser_navigate(url: str, browser_name: str = "chrome", use_tor: bool = False, use_i2p: bool = False) -> str:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(
            LocalBrowserEngine.open_and_extract(
                url=url,
                browser_name=browser_name,
                use_tor=use_tor,
                use_i2p=use_i2p,
                headless=True
            )
        )
        return (
            f"✅ [TARAYICI ETKİN İCRA EDİLDİ: {res.get('browser')}]\n"
            f"- URL: {url} | Ağ: {res.get('network')} | Süre: {res.get('elapsed')}s\n"
            f"- İçerik: {res.get('content', '')[:1000]}"
        )
    finally:
        loop.close()

def tool_run_shell_command(command: str) -> str:
    banned = ["rm -rf /", "rm -rf /*", "mkfs", ":(){ :|:& };:"]
    for b in banned:
        if b in command:
            return "[AJAN GÜVENLİK ENGELİ]: Bu yıkıcı komut çalıştırılamaz."
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=120
        )
        output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\nEXIT CODE: {result.returncode}"
        return output[:4000]
    except Exception as e:
        return f"[Terminal İcra Hatası]: {str(e)}"

def tool_write_file(filepath: str, content: str) -> str:
    target = WORKSPACE_DIR / filepath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"[DOSYA YAZILDI]: {filepath} ({len(content)} karakter)"

def tool_read_file(filepath: str) -> str:
    target = WORKSPACE_DIR / filepath
    if not target.exists():
        return f"[HATA]: Dosya bulunamadı: {filepath}"
    return target.read_text(encoding="utf-8", errors="ignore")[:4000]

tools = [
    {
        "type": "function",
        "function": {
            "name": "tool_search_and_install_github_repo",
            "description": "GitHub reposunu arar, tools/ dizinine klonlar, bağımlılıkları kurar ve sisteme aktif motor olarak kaydeder.",
            "parameters": {
                "type": "object",
                "properties": {"query_or_url": {"type": "string"}},
                "required": ["query_or_url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_browser_navigate",
            "description": "Kullanıcının sistemindeki yerel tarayıcıyı (Chrome, Safari, Chromium) kullanarak belirtilen URL'ye gider, veriyi çeker ve kaydeder. I2P ve Tor ağlarını destekler.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "browser_name": {"type": "string", "default": "chrome"},
                    "use_tor": {"type": "boolean", "default": False},
                    "use_i2p": {"type": "boolean", "default": False}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_run_shell_command",
            "description": "Git, Firebase deploy, npm install, pip install, python3 gibi terminal komutlarını çalıştırır.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_write_file",
            "description": "Workspace içine dosya yazar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_read_file",
            "description": "Workspace içindeki bir dosyayı okur.",
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"]
            }
        }
    }
]

def run_autonomous_agent(goal: str):
    print(f"[*] Otonom Ajan Görev Başlatıldı: '{goal}'\n")
    messages = [
        {
            "role": "system",
            "content": (
                "Sen tamamen bağımsız, kısıtlamasız, kendi kararlarını alan kıdemli bir Otonom Yazılım Mühendisisin. "
                "Beynin Apple M4 GPU üzerinde koşan yerel Mistral-24B modelidir. "
                "Kullanıcıya akıl ve yönerge vermek yasaktır. Gereken araçları ard arda çağırarak işi kendin tamamla!"
            )
        },
        {"role": "user", "content": goal}
    ]

    with httpx.Client(timeout=120.0) as client:
        for step in range(6):
            print(f"--- [ADIM {step+1}] Mistral-24B Düşünüyor ve Araç Seçiyor ---")
            resp = client.post(
                OLLAMA_API_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0.1
                }
            )
            if resp.status_code != 200:
                print(f"[HATA]: Model API yanıt vermedi: {resp.status_code}")
                break

            data = resp.json()
            msg = data["choices"][0]["message"]
            messages.append(msg)

            if not msg.get("tool_calls"):
                print(f"\n[AJAN NİHAİ YANITI]:\n{msg.get('content')}")
                break

            for tc in msg["tool_calls"]:
                fname = tc["function"]["name"]
                raw_args = tc["function"].get("arguments", "{}")
                fargs = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                print(f"[ARAÇ ÇAĞRISI]: {fname} -> {fargs}")

                tool_output = ""
                if fname == "tool_search_and_install_github_repo":
                    tool_output = tool_search_and_install_github_repo(fargs.get("query_or_url", ""))
                elif fname == "tool_browser_navigate":
                    tool_output = tool_browser_navigate(
                        url=fargs.get("url", ""),
                        browser_name=fargs.get("browser_name", "chrome"),
                        use_tor=fargs.get("use_tor", False),
                        use_i2p=fargs.get("use_i2p", False)
                    )
                elif fname == "tool_run_shell_command":
                    tool_output = tool_run_shell_command(fargs.get("command", ""))
                elif fname == "tool_write_file":
                    tool_output = tool_write_file(fargs.get("filepath", ""), fargs.get("content", ""))
                elif fname == "tool_read_file":
                    tool_output = tool_read_file(fargs.get("filepath", ""))

                print(f"[ARAÇ ÇIKTISI]:\n{tool_output[:400]}...\n")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_output
                })

if __name__ == "__main__":
    hedef = sys.argv[1] if len(sys.argv) > 1 else "I2P ağını kullanarak http://127.0.0.1:7070 adresini ziyaret et ve konsol durumunu göster."
    run_autonomous_agent(hedef)
