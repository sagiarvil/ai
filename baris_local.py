#!/usr/bin/env python3
"""Local UI launcher: one managed process, verified origin, no model downloads."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import socket
import secrets
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

SOURCE = Path(__file__).resolve().parent
BUILD = "local-ui-v10"


def process_command(pid):
    if sys.platform.startswith('linux'):
        return (Path('/proc') / str(int(pid)) / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
    return subprocess.check_output(['ps', '-p', str(int(pid)), '-o', 'command='],
                                   text=True, stderr=subprocess.DEVNULL, timeout=3)


def read_info(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(
        f"http://127.0.0.1:{port}/api/engine_info", timeout=3
    ) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('Motor bilgisi boyut sınırını aşıyor.')
        return json.loads(raw)


def own_info(info):
    return (info.get("build") == BUILD
            and info.get("source_root") == str(SOURCE)
            and info.get("engine_protocol") == "baris-execution-v2")


def shutdown_server(port, state, info):
    if state.get('manager_token') and info.get('managed_shutdown'):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(f'http://127.0.0.1:{port}/api/local_shutdown', data=b'{}',
            headers={'Content-Type': 'application/json', 'X-Baris-Manager': state['manager_token']})
        with opener.open(request, timeout=3) as response:
            if response.status != 202:
                raise ValueError('Sunucu kapatma isteğini doğrulamadı.')
        return
    # Compatibility for managed versions predating the private shutdown token.
    command = process_command(state['pid'])
    if not any(name in command for name in ('uvicorn omni_chat_panel:app', 'uvicorn durable_api:app')):
        raise ValueError('Sunucu süreç kimliği doğrulanamadı; hiçbir süreç durdurulmadı.')
    os.kill(state['pid'], 15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "status", "stop", "doctor", "verify-live"], nargs="?",
                        default="start")
    parser.add_argument("--port", type=int, default=5053)
    parser.add_argument("--shortcut", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--budget", type=int, default=900, choices=range(30, 1801), metavar='30..1800')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port 1024–65535 arasında olmalı.")
    if args.action == 'verify-live':
        from live_qualification import qualify
        report, path = qualify(SOURCE, f'http://127.0.0.1:{args.port}', args.budget)
        raise SystemExit(0 if report['passed'] else 1)
    if args.action == "doctor":
        from runtime_doctor import inspect_runtime
        report=inspect_runtime(SOURCE)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        raise SystemExit(0 if report["all_checks_passed"] else 1)
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
            shutdown_server(args.port, state, info)
            for _ in range(50):
                time.sleep(0.1)
                try:
                    read_info(args.port)
                except OSError:
                    state_file.unlink(missing_ok=True)
                    print("Yönetilen sunucu durduruldu.")
                    return
            raise SystemExit("Sunucu henüz kapanmadı; durum kaydı korundu.")

        current_release = subprocess.check_output(
            ['git','-C',str(SOURCE),'rev-parse','HEAD'], text=True).strip()
        try:
            info = read_info(args.port)
        except (OSError, ValueError):
            info = None
        if info is not None:
            if not own_info(info) or info.get("release") != current_release:
                managed_old = (
                    info.get('source_root') == str(SOURCE)
                    and info.get('engine_protocol') == 'baris-execution-v2'
                    and info.get('build') in {'local-ui-v4','local-ui-v5','local-ui-v6','local-ui-v7','local-ui-v8','local-ui-v9','local-ui-v10'}
                    and state.get('instance') == info.get('instance')
                    and state.get('pid') and not info.get('busy')
                )
                if not managed_old:
                    raise SystemExit('Port başka veya meşgul bir uygulamaya ait; süreçlere dokunulmadı.')
                shutdown_server(args.port, state, info)
                for _ in range(100):
                    time.sleep(0.1)
                    try:
                        read_info(args.port)
                    except OSError:
                        info = None
                        break
                if info is not None:
                    raise SystemExit('Eski sunucu kapanmadı; yeni süreç başlatılmadı.')
        if info is None:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", args.port)) == 0:
                    raise SystemExit("Port dolu; hiçbir süreç durdurulmadı.")
            print("Çevrimdışı motor ve entegrasyon testleri çalıştırılıyor...", flush=True)
            subprocess.run(
                [sys.executable, "-m", "unittest", "-v", "test_execution_loop",
                 "test_structured_actions", "test_acceptance_checks", "test_durable_runtime", "test_reliability",
                 "test_audit_regressions", "test_live_qualification", "test_http_smoke", "test_worker_ownership"],
                cwd=SOURCE, check=True)
            instance = uuid.uuid4().hex
            manager_token = secrets.token_hex(32)
            release = subprocess.check_output(
                ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
            env = dict(os.environ, BARIS_WORKSPACE=str(SOURCE),
                       BARIS_INSTANCE=instance, BARIS_RELEASE=release, BARIS_MANAGER_TOKEN=manager_token)
            log_path = runtime / f"server-{args.port}.log"
            with log_path.open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "durable_api:app",
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
            from live_qualification import atomic_json
            atomic_json(state_file, {"pid": process.pid, "instance": instance, "release": release,
                                     "manager_token": manager_token})

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

