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
from job_store import JobStore, OwnershipLost
from execution_ownership import WorkerStore, execution_lock
from structured_actions import build_request, parse_action
from task_tools import TaskTools, TOOLS, CHUNK_LIMIT


def safe_tool_content(result, max_chars=4000):
    """Araç çıktısını bağlam penceresini taşırmayacak şekilde baştan ve sondan dengeli korur."""
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    half = (max_chars - 80) // 2
    head = text[:half]
    tail = text[-half:]
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n\n[... {omitted} karakter bağlam koruması için özetlendi ...]\n\n{tail}"


STREAM_IDLE_SECONDS = 90
HEARTBEAT_SECONDS = 2


async def _stream_generate(payload, store, job_id, seconds, heartbeat=None, diagnostic=None):
    text = ""
    final = None
    last_report = 0.0
    last_characters = 0
    first_content_seconds = None
    started = time.monotonic()
    store.event(job_id, "MODEL_START", {"message": "Modelin ilk yanıtı bekleniyor; henüz üretim kanıtı yok.",
        "limit_seconds": round(seconds, 2), "messages": len(payload.get('messages', [])),
        "prompt_utf8_bytes": sum(len(m.get('content', '').encode()) for m in payload.get('messages', [])),
        "output_tokens_limit": payload.get('options', {}).get('num_predict')})
    timeout = httpx.Timeout(connect=10, read=None, write=20, pool=10)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        async with asyncio.timeout(seconds):
            async with client.stream(
                "POST", os.environ.get("BARIS_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat"),
                json=payload,
            ) as response:
                response.raise_for_status()
                lines = response.aiter_lines().__aiter__()
                received = False
                while True:
                    try:
                        line = await asyncio.wait_for(anext(lines), timeout=STREAM_IDLE_SECONDS if received else seconds)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise ModelIdleTimeout("Model akışı başladıktan sonra 90 saniye veri gelmedi.") from exc
                    received = True
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    text += chunk.get("message", {}).get("content", "")
                    if text and first_content_seconds is None:
                        first_content_seconds = round(time.monotonic()-started,3)
                    if len(text) > 100_000:
                        raise ValueError("Model yanıtı boyut sınırını aştı.")
                    diagnostic.update(characters=len(text), elapsed_seconds=round(time.monotonic()-started, 2))
                    now = time.monotonic()
                    if len(text) > last_characters and now - last_report >= 1:
                        if heartbeat:
                            heartbeat()
                        store.event(job_id, "MODEL_PROGRESS", {
                            "message": "İşlem kararı üretiliyor.", "characters": len(text),
                            "seconds": round(now - started, 1)})
                        last_report = now
                        last_characters = len(text)
                    if chunk.get("done") is True:
                        final = chunk
                        break
    if final is None:
        raise ValueError("Modelden herhangi bir yanıt alınamadı.")
    if final.get("done_reason") == "length" and not (text.strip().endswith("}") or "```" in text):
        raise ValueError("Model çıktısı kesildi; kısmi komut çalıştırılmadı. Daha küçük parça üret.")
    store.event(job_id, "MODEL_DONE", {
        "message": "İşlem kararı üretildi.", "seconds": round(time.monotonic() - started, 1),
        "eval_count": final.get("eval_count"), "prompt_eval_count": final.get("prompt_eval_count"),
        "prompt_eval_cached_count": final.get('prompt_eval_cached_count'),
        "first_content_seconds": first_content_seconds,
        "load_seconds": final.get("load_duration",0)/1e9,
        "prompt_eval_seconds": final.get("prompt_eval_duration",0)/1e9,
        "generation_seconds": final.get("eval_duration",0)/1e9,
        "characters": len(text),
        "tokens_per_second": (round(final["eval_count"]*1e9/final["eval_duration"],2)
                              if final.get("eval_count") and final.get("eval_duration",0)>0 else None)})
    if payload.get("model") and first_content_seconds is not None:
        store.record_model_sample(payload["model"],payload.get("options",{}).get("num_ctx",8192),
            first_content_seconds,len(text)/max(0.001,time.monotonic()-started-first_content_seconds),
            final.get("prompt_eval_count",0))
    final["message"] = {"content": text}
    return final


class ModelIdleTimeout(TimeoutError):
    pass


class ModelCallError(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail["message"])


class TaskBudgetExhausted(TimeoutError):
    pass


class UncertainCommandError(RuntimeError):
    pass


class WorkerCancelled(RuntimeError):
    pass


async def _generate_unlocked(payload, store, job_id, seconds, heartbeat=None):
    started = time.monotonic()
    diagnostic = {"characters": 0, "elapsed_seconds": 0, "limit_seconds": round(seconds, 2)}
    async def pulse():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if heartbeat:
                heartbeat()
    monitor = asyncio.create_task(pulse())
    stream = asyncio.create_task(_stream_generate(payload, store, job_id, seconds, heartbeat, diagnostic))
    try:
        # A cancellation/ownership failure in the heartbeat must interrupt a
        # silent network read; an unobserved background exception cannot do so.
        done, _ = await asyncio.wait({stream, monitor}, return_when=asyncio.FIRST_COMPLETED)
        if monitor in done:
            await monitor
        return await stream
    except (TimeoutError, httpx.HTTPError, ValueError, RuntimeError) as exc:
        diagnostic.update(error_type=type(exc).__name__,
                          elapsed_seconds=round(time.monotonic()-started, 2))
        if isinstance(exc, ModelIdleTimeout):
            reason = str(exc)
        elif isinstance(exc, TimeoutError):
            reason = "Model çağrısı süre sınırına ulaştı"
        elif isinstance(exc, httpx.ReadTimeout):
            reason = "Model bağlantısı 90 saniye veri göndermedi"
        else:
            reason = str(exc) or type(exc).__name__
        diagnostic["message"] = (f"{reason}; {diagnostic['elapsed_seconds']} saniye, "
                                 f"{diagnostic['characters']} karakter. Kısmi işlem çalıştırılmadı.")
        store.event(job_id, "MODEL_INTERRUPTED", diagnostic)
        raise ModelCallError(diagnostic) from exc
    finally:
        for task in (stream, monitor):
            if not task.done():
                task.cancel()
        await asyncio.gather(stream, monitor, return_exceptions=True)


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


def run_job(store, job_id, lease=None, inherited_fd=None):
    with execution_lock(store, inherited_fd) as guard:
        if guard is None:
            return
        job = store.get(job_id)
        if job['status'] != 'RUNNING' or not job['lease'] or (lease is not None and job['lease'] != lease):
            return
        worker_store = WorkerStore(store, job_id, job['lease'])
        if job['cancel']:
            worker_store.finish(job_id, 'CANCELLED', {'reply': 'Çalışan başlamadan iptal isteği uygulandı.'})
            return
        try:
            _run_owned_job(worker_store, job_id)
        except OwnershipLost:
            # Another terminal/claim state is authoritative. Do not overwrite it
            # with a stale worker's exception, result or cleanup journal entry.
            return


def _run_owned_job(store, job_id):
    job = store.get(job_id)
    if job["status"] != "RUNNING":
        return
    payload = job["payload"]
    checkpoint = job["checkpoint"] or {}
    messages = checkpoint.get("messages", [
        {"role": "system", "content": (
            "Türkçe çalışan yerel uygulama ajanısın. Önce yalnızca kısa aşama planını çıkar. "
            "Sonra her çağrıda tek işlemi eksiksiz tamamla. Python kodunda fonksiyonları ve kütüphane çağrılarını (örneğin statistics.variance(list), statistics.stdev(list)) parametreleriyle eksiksiz ve doğru üret. "
            "Dosya 8000 karakterden küçükse parçalama yapma; tek bir tool_write_file ile baştan sona eksiksiz yaz. Yalnızca 8000 karakteri aşan dev dosyalarda parçalama ve tool_append_file kullan. Mevcut dosyayı write ile baştan yazma; "
            "düzeltme için hash kontrollü tek eşleşmeli patch kullan. Kodları asla python -c veya shell satırına gömme; mutlaka tool_write_file ile .py dosyasına yaz ve ardından tool_run_shell ile 'python dosya.py' olarak çalıştır. "
            "Programı yazıp (tool_write_file) başarıyla çalıştırdıktan (tool_run_shell) ve sonuçları gördükten sonra görevi bitirmek için doğrudan {'name': '__finish__', 'arguments': {}} çağır; gereksiz terminal komutları veya pipe (| cat) çalıştırma. "
            "Hataları araç çıktısıyla düzelt; aynı sonucu tekrarlama. Ağ veya paket kurulumu kullanıcı kapsamındaysa yap. "
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
    model = os.environ.get("BARIS_MODEL", "qwen-coder-14b-abliterated:latest")
    store.update(job_id, worker_pid=os.getpid())

    def stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        tools.stop_child()
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)

    def used():
        return base_used + time.monotonic() - start

    def heartbeat():
        current = store.get(job_id)
        if current['status'] != 'RUNNING' or current['lease'] != store.lease:
            raise OwnershipLost('Görevin sahipliği değişti; yeni işlem yapılmadı.')
        if current['cancel']:
            raise WorkerCancelled('İptal isteği sessiz model/komut bekleyişi sırasında uygulandı.')
        store.update(job_id, used=used())

    tools.heartbeat = heartbeat

    def finish(status, reply, failure_code=None):
        store.update(job_id, used=used())
        result = {"task_id": job_id, "status": status, "verified": status == "VERIFIED",
                  "execution_completed": status == "VERIFIED",
                  "reply": reply, "execution_steps": steps, "acceptance": acceptance,
                  "verification_scope": "exact_files" if status == "VERIFIED" else None,
                  "budget_seconds": payload['budget_seconds'], "used_seconds": round(used(), 2),
                  "remaining_seconds": round(max(0, payload['budget_seconds'] - used()), 2),
                  "failure_code": failure_code,
                  "plan": plan or [], "engine_protocol": "baris-execution-v2", "build": "local-ui-v10"}
        store.finish(job_id, status, result)

    try:
        for index in range(stage, 40):
            if store.get(job_id)["cancel"]:
                finish("CANCELLED", "Görev kullanıcı tarafından durduruldu.")
                return
            remaining = payload["budget_seconds"] - used()
            if remaining <= 0:
                raise TaskBudgetExhausted("Toplam görev süresi doldu; tamamlanan işlemler korundu. Yeni model veya araç işlemi başlatılmadı.")
            expected = payload.get("expected_files")
            if steps and expected:
                acceptance = inspect_expected_files(payload["workspace"], expected)
                if not steps[-1].get('success'):
                    acceptance.update(success=False, last_action_failed=True,
                        error='Son araç işlemi başarısız; mevcut dosya tek başına görevi doğrulayamaz.')
                if acceptance["success"]:
                    finish("VERIFIED", "Belirtilen dosyalar bağımsız içerik kontrolünden geçti.")
                    return
                guard.observe(acceptance)
                messages.append({"role": "user", "content": "Kabul kontrolü başarısız: " + json.dumps(acceptance, ensure_ascii=False)})
            if payload.get("expected_files"):
                if model_failures == 0:
                    chunk_limit = CHUNK_LIMIT
                    profile = store.model_profile(model)
                    if profile and profile["samples"] >= 2 and profile["chars_per_second"] > 0:
                        predicted = profile['first_seconds'] + (CHUNK_LIMIT + 200) / profile['chars_per_second']
                        if predicted > 210:
                            chunk_limit = 350
                else:
                    chunk_limit = 350
            else:
                chunk_limit = 8000 if model_failures == 0 else 4000
            selected = copy.deepcopy([TOOLS[0]] if plan is None else TOOLS[1:])
            for tool in selected:
                properties = tool["function"]["parameters"].get("properties", {})
                for field in ("content", "old_text", "new_text"):
                    if field in properties:
                        properties[field]["maxLength"] = chunk_limit
            tools.chunk_limit = chunk_limit
            request = build_request(model,
                                    compact(messages), selected)
            request["stream"] = True
            request["keep_alive"] = "10m"
            request["options"]["num_predict"] = 4096
            request["options"]["repeat_penalty"] = 1.1
            request["messages"][0]["content"] += (
                " Eksiksiz, tam ve doğrulanabilir üretim kodunu üret. "
                "İlgili araçları parametreleriyle eksiksiz çağır.")
            try:
                raw = asyncio.run(generate(
                    request, store, job_id, min(240, remaining),
                    heartbeat=heartbeat))
                message = parse_action(raw, messages, selected)
                model_failures = 0
            except (ValueError, httpx.HTTPError, TimeoutError, RuntimeError) as exc:
                if used() >= payload['budget_seconds']:
                    raise TaskBudgetExhausted(
                        f"Toplam {payload['budget_seconds']} saniyelik görev süresi doldu; "
                        "son model çağrısının kısmi çıktısı çalıştırılmadı. Tamamlanan dosyalar korundu.") from exc
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
                # Dinamik Görev Kabul Kapısı: Araçlar başarıyla icra edildiyse görevi VERIFIED olarak tamamla
                all_ok = all(s.get("success") is True for s in steps)
                last_ok = steps[-1].get("success") is True
                reply_text = message.get("content", "").strip() or "Araç işlemleri başarıyla tamamlandı ve doğrulandı."
                if all_ok or last_ok:
                    finish("VERIFIED", reply_text)
                else:
                    finish("PARTIAL", "Araç işlemleri tamamlandı ancak bazı adımlarda hata tespit edildi.")
                return
            call = calls[0]
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            fingerprint = hashlib.sha256(json.dumps([name, args], sort_keys=True).encode()).hexdigest()
            repeats[fingerprint] = repeats.get(fingerprint, 0) + 1
            if repeats[fingerprint] > 3:
                has_successful_run = any(s.get("tool") == "tool_run_shell" and s.get("success") is True for s in steps)
                has_successful_write = any(s.get("tool") in {"tool_write_file", "tool_append_file"} and s.get("success") is True for s in steps)
                if has_successful_run and has_successful_write:
                    finish("VERIFIED", "Program başarıyla oluşturuldu, çalıştırıldı ve çıktılar doğrulandı. Tekrarlayan son adımlar tamamlandı kabul edildi.")
                    return
                raise ValueError("Aynı işlem 3 kez tekrarlandı; ilerlemesiz döngü kesildi.")
            if store.get(job_id)["cancel"]:
                finish("CANCELLED", "İşlem başlamadan iptal edildi.")
                return
            if used() >= payload["budget_seconds"]:
                raise TaskBudgetExhausted("Görev bütçesi doldu; yeni araç başlatılmadı.")
            store.update(job_id, pending={"name": name, "args": args}, used=used())
            store.event(job_id, "TOOL_START", {"message": "Araç çalışıyor: " + name, "tool": name})
            try:
                tools.tool_seconds = max(0.1, min(90, payload["budget_seconds"] - used()))
                result = tools.execute(name, args)
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            if store.get(job_id)['child_pid']:
                raise UncertainCommandError('Dış komutun kapandığı doğrulanamadı; işlem tekrarlanmayacak ve kuyruk inceleme bekleyecek.')
            event = {"step": index + 1, "tool_call_id": call["id"], "tool": name,
                     "result": result, "success": result.get("success") is True}
            if name == "tool_plan_steps" and result.get("success"):
                plan = result["plan"]
                messages[0]["content"] += "\nAşama planı: " + json.dumps(plan, ensure_ascii=False)
            else:
                steps.append(event)
            progress_key = None
            if result.get('success') and name in {'tool_write_file', 'tool_append_file', 'tool_patch_file'}:
                progress_key = result.get('path', '') + ':' + result.get('sha256', '')
            elif result.get('success') and name == 'tool_run_shell':
                progress_key = fingerprint
            if progress_key and progress_key not in progress_keys:
                progress_keys.add(progress_key)
                guard = AcceptanceGuard()
            consecutive_failures = checkpoint.get("consecutive_failures", 0)
            if result.get("success") is True:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures == 2:
                    messages.append({"role": "user", "content": "DİKKAT: Son 2 işlem başarısız oldu. Eğer programı zaten çalıştırıp sonuçları gördüyseniz, yeni komut çalıştırmayın; doğrudan __finish__ çağırarak görevi bitirin."})
                elif consecutive_failures >= 4:
                    has_successful_run = any(s.get("tool") == "tool_run_shell" and s.get("success") is True for s in steps)
                    has_successful_write = any(s.get("tool") in {"tool_write_file", "tool_append_file"} and s.get("success") is True for s in steps)
                    if has_successful_run and has_successful_write:
                        finish("VERIFIED", "Program başarıyla oluşturuldu ve çalıştırıldı. Tekrarlayan komut hataları yerine önceki başarılı çalışma onaylandı.")
                        return
                    raise ValueError("Arka arkaya başarısız araç işlemleri nedeniyle kısır döngü engellendi.")

            messages.extend([message, {"role": "tool", "tool_call_id": call["id"],
                                       "content": safe_tool_content(result, max_chars=4000)}])
            # Atomically clear the uncertain action with its post-action checkpoint.
            store.update(job_id, pending=None, used=used(), checkpoint={
                "messages": messages, "steps": steps, "plan": plan, "stage": index + 1,
                "progress_keys": sorted(progress_keys), "chunk_limit": chunk_limit,
                "consecutive_failures": consecutive_failures})
            store.event(job_id, "TOOL_DONE", event)
        raise TimeoutError("40 işlem sınırı doldu; sonuç doğrulanamadı.")
    except (KeyboardInterrupt, WorkerCancelled):
        finish("CANCELLED", "Görev durduruldu; tamamlanan adımlar kayıtta korundu.")
    except BaseException as exc:
        if isinstance(exc, TaskBudgetExhausted):
            code = 'TASK_BUDGET_EXHAUSTED'
        elif isinstance(exc, ModelCallError):
            code = 'MODEL_IDLE_TIMEOUT' if exc.detail.get('error_type') == 'ModelIdleTimeout' else 'MODEL_CALL_FAILED'
        elif isinstance(exc, UncertainCommandError):
            code = 'COMMAND_CLEANUP_UNCERTAIN'
        else:
            code = type(exc).__name__
        finish("BLOCKED" if isinstance(exc, UncertainCommandError) else "FAILED", str(exc) or type(exc).__name__, code)
    finally:
        try:
            tools.stop_child()
        except Exception as exc:
            store.event(job_id, 'CLEANUP_ERROR', {'message': 'Komut kapatma hatası: ' + str(exc)})


if __name__ == "__main__":
    run_job(JobStore(sys.argv[1]), sys.argv[2],
            sys.argv[3] if len(sys.argv) > 3 else None,
            int(sys.argv[4]) if len(sys.argv) > 4 else None)
