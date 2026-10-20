"""One durable task in its own process; no HTTP request owns its lifetime."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

import httpx

from acceptance_checks import AcceptanceGuard, inspect_expected_files
from job_store import JobStore
from structured_actions import build_request, parse_action
from task_tools import TaskTools, TOOLS, CHUNK_LIMIT


async def _stream_generate(payload, store, job_id, seconds, heartbeat=None, diagnostic=None):
    text = ""
    final = None
    last_report = 0.0
    started = time.monotonic()
    store.event(job_id, "MODEL_START", {"message": "Model sıradaki kısa işlemi üretiyor."})
    timeout = httpx.Timeout(connect=10, read=90, write=20, pool=10)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        async with asyncio.timeout(seconds):
            async with client.stream(
                "POST", os.environ.get("BARIS_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat"),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    text += chunk.get("message", {}).get("content", "")
                    if len(text) > 100_000:
                        raise ValueError("Model yanıtı boyut sınırını aştı.")
                    diagnostic.update(characters=len(text), elapsed_seconds=round(time.monotonic()-started, 2))
                    now = time.monotonic()
                    if now - last_report >= 1:
                        if heartbeat:
                            heartbeat()
                        store.event(job_id, "MODEL_PROGRESS", {
                            "message": "İşlem kararı üretiliyor.", "characters": len(text),
                            "seconds": round(now - started, 1)})
                        last_report = now
                    if chunk.get("done") is True:
                        final = chunk
    if final is None or final.get("done_reason") == "length":
        raise ValueError("Model çıktısı kesildi; kısmi komut çalıştırılmadı. Daha küçük parça üret.")
    store.event(job_id, "MODEL_DONE", {
        "message": "İşlem kararı üretildi.", "seconds": round(time.monotonic() - started, 1),
        "eval_count": final.get("eval_count"), "prompt_eval_count": final.get("prompt_eval_count")})
    final["message"] = {"content": text}
    return final


class ModelCallError(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail["message"])


async def _generate_unlocked(payload, store, job_id, seconds, heartbeat=None):
    started = time.monotonic()
    diagnostic = {"characters": 0, "elapsed_seconds": 0, "limit_seconds": round(seconds, 2)}
    try:
        return await _stream_generate(payload, store, job_id, seconds, heartbeat, diagnostic)
    except (TimeoutError, httpx.HTTPError, ValueError) as exc:
        diagnostic.update(error_type=type(exc).__name__,
                          elapsed_seconds=round(time.monotonic()-started, 2))
        if isinstance(exc, TimeoutError):
            reason = "Model çağrısı süre sınırına ulaştı"
        elif isinstance(exc, httpx.ReadTimeout):
            reason = "Model bağlantısı 90 saniye veri göndermedi"
        else:
            reason = str(exc) or type(exc).__name__
        diagnostic["message"] = (f"{reason}; {diagnostic['elapsed_seconds']} saniye, "
                                 f"{diagnostic['characters']} karakter. Kısmi işlem çalıştırılmadı.")
        store.event(job_id, "MODEL_INTERRUPTED", diagnostic)
        raise ModelCallError(diagnostic) from exc


async def generate(payload, store, job_id, seconds, heartbeat=None):
    import fcntl
    cache = Path.home() / '.cache' / 'baris-ai'
    cache.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + seconds
    with (cache / 'model.lock').open('a') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Diğer model çağrısı için bekleme sınırı doldu.')
                if heartbeat:
                    heartbeat()
                await asyncio.sleep(0.25)
        try:
            return await _generate_unlocked(payload, store, job_id,
                                           max(0.1, deadline-time.monotonic()), heartbeat)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def compact(messages):
    # Keep the original task and plan; only trim older tool output, never executable input.
    fixed = messages[:2]
    rest = messages[2:]
    if len(rest) > 10:
        summaries = []
        for item in rest[:-10]:
            if item.get("role") == "tool":
                summaries.append({"role": "tool", "content": item["content"][:600]})
        fixed += [{"role": "user", "content": "Önceki işlem özetleri: " + json.dumps(summaries[-8:], ensure_ascii=False)}]
        rest = rest[-10:]
    return fixed + rest


def run_job(store, job_id):
    job = store.get(job_id)
    payload = job["payload"]
    checkpoint = job["checkpoint"] or {}
    messages = checkpoint.get("messages", [
        {"role": "system", "content": (
            "Türkçe çalışan yerel uygulama ajanısın. Önce yalnızca kısa aşama planını çıkar. "
            "Sonra her çağrıda tek küçük işlemi tamamla. Büyük programları 700 karakterden "
            "küçük parçalarla yaz ve hash kontrollü append ile birleştir. İlk yanıtta bütün "
            "programı üretme. Kodun tamamını tek shell satırına gömme. Hataları araç çıktısıyla "
            "düzelt; aynı sonucu tekrarlama. Ağ veya paket kurulumu kullanıcı kapsamındaysa yap. "
            "Görevin kapsamı ve kabul koşulları yetki sınırıdır. Çalışma dizini: " + payload["workspace"])},
        {"role": "user", "content": payload["message"] + (
            "\nKesin kabul koşulları: " + json.dumps(payload["expected_files"], ensure_ascii=False)
            if payload.get("expected_files") else "")},
    ])
    plan = checkpoint.get("plan")
    steps = checkpoint.get("steps", [])
    stage = checkpoint.get("stage", 0)
    guard = AcceptanceGuard()
    tools = TaskTools(payload["workspace"], store, job_id)
    base_used = job["used"]
    start = time.monotonic()
    model_failures = 0
    chunk_limit = checkpoint.get("chunk_limit", CHUNK_LIMIT)
    repeats = {}
    progress_keys = set(checkpoint.get("progress_keys", []))
    acceptance = None
    store.update(job_id, worker_pid=os.getpid())

    def stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        tools.stop_child()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)

    def used():
        return base_used + time.monotonic() - start

    def finish(status, reply):
        store.update(job_id, used=used())
        result = {"task_id": job_id, "status": status, "verified": status == "VERIFIED",
                  "execution_completed": status in {"VERIFIED", "UNVERIFIED"},
                  "reply": reply, "execution_steps": steps, "acceptance": acceptance,
                  "plan": plan or [], "engine_protocol": "baris-execution-v2", "build": "local-ui-v6"}
        store.finish(job_id, status, result)

    try:
        for index in range(stage, 40):
            if store.get(job_id)["cancel"]:
                finish("CANCELLED", "Görev kullanıcı tarafından durduruldu.")
                return
            remaining = payload["budget_seconds"] - used()
            if remaining <= 0:
                raise TimeoutError("Toplam görev bütçesi doldu; tamamlanan işlemler korundu.")
            expected = payload.get("expected_files")
            if steps and expected:
                acceptance = inspect_expected_files(payload["workspace"], expected)
                if acceptance["success"]:
                    finish("VERIFIED", "Görev bağımsız kabul kontrolünden geçti.")
                    return
                guard.observe(acceptance)
                messages.append({"role": "user", "content": "Kabul kontrolü başarısız: " + json.dumps(acceptance, ensure_ascii=False)})
            selected = copy.deepcopy([TOOLS[0]] if plan is None else TOOLS[1:])
            for tool in selected:
                content_schema = tool["function"]["parameters"].get("properties", {}).get("content")
                if content_schema is not None:
                    content_schema["maxLength"] = chunk_limit
            tools.chunk_limit = chunk_limit
            request = build_request(os.environ.get("BARIS_MODEL", "mistral-small-24b-abliterated:latest"),
                                    compact(messages), selected)
            request["stream"] = True
            request["keep_alive"] = "10m"
            request["options"]["num_predict"] = 256 if plan is None else 1024
            request["messages"][0]["content"] += (
                f" Tek küçük işlem üret. content en fazla {chunk_limit} karakter olsun. "
                "Kalan büyük kodu sonraki çağrılarda append ile tamamla.")
            try:
                raw = asyncio.run(generate(
                    request, store, job_id, min(240, remaining),
                    heartbeat=lambda: store.update(job_id, used=used())))
                message = parse_action(raw, messages, selected)
                model_failures = 0
            except (ValueError, httpx.HTTPError, TimeoutError) as exc:
                model_failures += 1
                detail = getattr(exc, "detail", {"message": str(exc) or type(exc).__name__, "error_type": type(exc).__name__})
                store.event(job_id, "MODEL_ERROR", detail)
                if model_failures > 1:
                    raise
                chunk_limit = 350
                store.event(job_id, "MODEL_RETRY", {"message": "Kısmi çıktı atıldı; tek kontrollü deneme 350 karakter sınırıyla yapılacak.", "chunk_limit": chunk_limit})
                messages.append({"role": "user", "content": (str(exc) or type(exc).__name__) + " Tek kısa işlem üret; content en fazla 350 karakter olsun. Büyük dosyanın yalnızca ilk/devam parçasını yaz."})
                continue
            calls = message.get("tool_calls") or []
            if not calls:
                if not steps:
                    raise ValueError("Araç çalışmadan görev bitirilemez.")
                finish("UNVERIFIED", "Araç işlemleri tamamlandı; bağımsız görev kabulü sağlanmadı.")
                return
            call = calls[0]
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            fingerprint = hashlib.sha256(json.dumps([name, args], sort_keys=True).encode()).hexdigest()
            repeats[fingerprint] = repeats.get(fingerprint, 0) + 1
            if repeats[fingerprint] > 3:
                raise ValueError("Aynı işlem 3 kez tekrarlandı; ilerlemesiz döngü kesildi.")
            store.update(job_id, pending={"name": name, "args": args}, used=used())
            store.event(job_id, "TOOL_START", {"message": "Araç çalışıyor: " + name, "tool": name})
            try:
                tools.tool_seconds = max(0.1, min(90, payload["budget_seconds"] - used()))
                result = tools.execute(name, args)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            event = {"step": index + 1, "tool_call_id": call["id"], "tool": name,
                     "result": result, "success": result.get("success") is True}
            if name == "tool_plan_steps" and result.get("success"):
                plan = result["plan"]
                messages[0]["content"] += "\nAşama planı: " + json.dumps(plan, ensure_ascii=False)
            else:
                steps.append(event)
            progress_key = None
            if result.get('success') and name in {'tool_write_file', 'tool_append_file'}:
                progress_key = result.get('path', '') + ':' + result.get('sha256', '')
            elif result.get('success') and name == 'tool_run_shell':
                progress_key = fingerprint
            if progress_key and progress_key not in progress_keys:
                progress_keys.add(progress_key)
                guard = AcceptanceGuard()
            messages.extend([message, {"role": "tool", "tool_call_id": call["id"],
                                       "content": json.dumps(result, ensure_ascii=False)[:18000]}])
            # Atomically clear the uncertain action with its post-action checkpoint.
            store.update(job_id, pending=None, used=used(), checkpoint={
                "messages": messages, "steps": steps, "plan": plan, "stage": index + 1,
                "progress_keys": sorted(progress_keys), "chunk_limit": chunk_limit})
            store.event(job_id, "TOOL_DONE", event)
        raise TimeoutError("40 işlem sınırı doldu; sonuç doğrulanamadı.")
    except KeyboardInterrupt:
        finish("CANCELLED", "Görev durduruldu; tamamlanan adımlar kayıtta korundu.")
    except BaseException as exc:
        finish("FAILED", str(exc) or type(exc).__name__)
    finally:
        tools.stop_child()


if __name__ == "__main__":
    run_job(JobStore(sys.argv[1]), sys.argv[2])
