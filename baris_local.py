#!/usr/bin/env python3
"""Local UI launcher: one managed process, verified origin, no model downloads."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

SOURCE = Path(__file__).resolve().parent
BUILD = "local-ui-v4"


def read_info(port):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/engine_info", timeout=3
    ) as response:
        return json.load(response)


def own_info(info):
    return (info.get("build") == BUILD
            and info.get("source_root") == str(SOURCE)
            and info.get("engine_protocol") == "baris-execution-v2")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "status", "stop"], nargs="?",
                        default="start")
    parser.add_argument("--port", type=int, default=5053)
    parser.add_argument("--shortcut", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port 1024–65535 arasında olmalı.")
    runtime = SOURCE / ".baris_runtime"
    runtime.mkdir(exist_ok=True)
    with (runtime / "manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_file = runtime / f"server-{args.port}.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        if args.action == "status":
            print(json.dumps(read_info(args.port), ensure_ascii=False, indent=2))
            return
        if args.action == "stop":
            if not state:
                raise SystemExit("Yönetilen sunucu kaydı bulunamadı; hiçbir süreç durdurulmadı.")
            info = read_info(args.port)
            if not own_info(info) or info.get("instance") != state.get("instance"):
                raise SystemExit("Sunucu kimliği uyuşmuyor; hiçbir süreç durdurulmadı.")
            pid = state["pid"]
            command = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="], text=True)
            if "uvicorn omni_chat_panel:app" not in command:
                raise SystemExit("Süreç kimliği doğrulanamadı.")
            os.kill(pid, 15)
            for _ in range(50):
                time.sleep(0.1)
                try:
                    read_info(args.port)
                except OSError:
                    state_file.unlink(missing_ok=True)
                    print("Yönetilen sunucu durduruldu.")
                    return
            raise SystemExit("Sunucu henüz kapanmadı; durum kaydı korundu.")

        try:
            info = read_info(args.port)
        except (OSError, ValueError):
            info = None
        if info is not None:
            if not own_info(info):
                raise SystemExit("Port başka bir uygulamaya ait; süreçlere dokunulmadı.")
            if info.get("busy"):
                raise SystemExit("Bu sunucuda görev çalışıyor; yeniden başlatılmadı.")
        else:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", args.port)) == 0:
                    raise SystemExit("Port dolu; hiçbir süreç durdurulmadı.")
            print("29 çevrimdışı test çalıştırılıyor...", flush=True)
            subprocess.run(
                [sys.executable, "-m", "unittest", "-v", "test_execution_loop",
                 "test_structured_actions", "test_acceptance_checks"],
                cwd=SOURCE, check=True)
            instance = uuid.uuid4().hex
            release = subprocess.check_output(
                ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
            env = dict(os.environ, BARIS_WORKSPACE=str(SOURCE),
                       BARIS_INSTANCE=instance, BARIS_RELEASE=release)
            log_path = runtime / f"server-{args.port}.log"
            with log_path.open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "omni_chat_panel:app",
                     "--host", "127.0.0.1", "--port", str(args.port)],
                    cwd=SOURCE, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError(log_path.read_text(errors="replace")[-4000:])
                    try:
                        info = read_info(args.port)
                        if own_info(info) and info.get("instance") == instance:
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Sunucu 30 saniyede hazır olmadı.")
            except BaseException:
                process.terminate()
                raise
            state_file.write_text(json.dumps(
                {"pid": process.pid, "instance": instance, "release": release}),
                encoding="utf-8")

        url = f"http://127.0.0.1:{args.port}"
        if args.shortcut:
            desktop = Path.home() / "Desktop"
            if not desktop.is_dir():
                raise SystemExit("Masaüstü dizini bulunamadı; sunucu çalışıyor.")
            shortcut = desktop / "Baris-AI.command"
            body = ("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                    shlex.quote(str(SOURCE / "baris_local.py")) +
                    " start --port " + str(args.port) + "\n")
            if shortcut.exists() and "baris_local.py" not in shortcut.read_text():
                raise SystemExit("Aynı adlı farklı kısayol var; üzerine yazılmadı.")
            shortcut.write_text(body, encoding="utf-8")
            shortcut.chmod(0o700)
            print("Masaüstü kısayolu:", shortcut)
        print("Arayüz ve motor bağlı:", url, flush=True)
        if not args.no_open:
            webbrowser.open(url)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit("Başlatma hatası: " + str(exc))
