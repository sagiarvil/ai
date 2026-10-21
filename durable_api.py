"""Same-origin local UI + durable task API. No model work inside POST handlers."""
import asyncio
from contextlib import asynccontextmanager
import os
import shutil
import json
import sqlite3
import secrets
import signal
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from task_service import TaskService
from local_http import LocalHttpGuard

SOURCE_ROOT = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("BARIS_WORKSPACE", SOURCE_ROOT)).resolve()
BUILD = "local-ui-v10"


@asynccontextmanager
async def lifespan(app):
    service = TaskService(WORKSPACE)
    app.state.service = service
    await service.start()
    try:
        yield
    finally:
        await service.close()


app = FastAPI(title="Barış AI", lifespan=lifespan)
app.add_middleware(LocalHttpGuard)


def service(request: Request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Başka kaynaktan işlem isteği reddedildi.")
    return request.app.state.service


class TaskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30000)
    expected_files: dict[str, str] | None = None
    budget_seconds: int = Field(default=900, ge=30, le=1800)


def enqueue(req, request, engine):
    # The service owns the canonical root (e.g. macOS /var -> /private/var).
    root = engine.root
    if not req.message.strip():
        raise HTTPException(422, "Görev boş olamaz.")
    if req.expected_files is not None and (
        not req.expected_files or len(req.expected_files) > 100
        or sum(len(v) for v in req.expected_files.values()) > 30000
    ):
        raise HTTPException(422, "Dosya kabul koşulları boyut sınırını aşıyor.")
    if engine.loop_task is None or engine.loop_task.done():
        raise HTTPException(503, "Görev zamanlayıcısı çalışmıyor; yeni görev kabul edilmedi.")
    try:
        if engine.store.queue_state()['blocked']:
            raise HTTPException(503, 'Belirsiz dış komut kaydı var; kuyruk inceleme bekliyor. Yeni görev alınmadı.')
    except sqlite3.Error:
        raise HTTPException(503, 'Görev kuyruğu okunamadı; yeni görev kabul edilmedi.')
    try:
        if shutil.disk_usage(root).free < 64*1024*1024:
            raise HTTPException(507,"Diskte 64 MiB çalışma payı kalmadı; yeni görev kabul edilmedi.")
    except OSError as exc:
        raise HTTPException(503,"Çalışma diski denetlenemedi: " + str(exc))
    for name in (req.expected_files or {}):
        try:
            if not name or len(name) > 4096 or '\x00' in name:
                raise ValueError('Geçersiz yol.')
            target = (root / name).resolve()
        except (ValueError, OSError, RuntimeError):
            raise HTTPException(422, 'Kabul dosyası yolu geçersiz.')
        if not target.is_relative_to(root) or target.relative_to(root).parts[:1] in [(".git",),(".baris_runtime",)]:
            raise HTTPException(422,"Kabul dosyası çalışma alanı veya izin verilen kapsam dışında.")
    payload = req.model_dump()
    payload["workspace"] = str(root)
    key = request.headers.get("idempotency-key") or uuid.uuid4().hex
    if len(key) > 100:
        raise HTTPException(422, "İşlem anahtarı çok uzun.")
    try:
        task_id = engine.store.submit(payload, key)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except sqlite3.Error as exc:
        raise HTTPException(503,"Görev kaydedilemedi; başarı veya yürütme bildirilmedi: " + str(exc))
    except OverflowError as exc:
        raise HTTPException(429, str(exc))
    return task_id


@app.get("/")
async def index():
    return FileResponse(SOURCE_ROOT / "public/index.html", headers={"Cache-Control": "no-store"})


@app.get("/app.js")
async def script():
    return FileResponse(SOURCE_ROOT / "public/app.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/engine_info")
async def info(engine=Depends(service)):
    try:
        state = engine.store.queue_state()
    except sqlite3.Error:
        raise HTTPException(503, 'Görev kuyruğu okunamadı; motor hazır sayılmadı.')
    return {"engine_protocol": "baris-execution-v2", "build": BUILD, "tool_loop": True,
            "durable_tasks": True, "busy": state['running'] > 0, "queued": state['queued'],
            "scheduler_alive": engine.loop_task is not None and not engine.loop_task.done(),
            "queue_blocked": state['blocked'], "source_root": str(SOURCE_ROOT),
            "model": os.environ.get('BARIS_MODEL', 'mistral-small-24b-abliterated:latest'),
            "context_length": 8192, "os_sandbox": False,
            "managed_shutdown": bool(os.environ.get('BARIS_MANAGER_TOKEN')),
            "workspace": str(engine.root), "instance": os.environ.get("BARIS_INSTANCE", ""),
            "release": os.environ.get("BARIS_RELEASE", "")}


@app.post('/api/local_shutdown', status_code=202)
async def local_shutdown(request: Request, engine=Depends(service)):
    secret = os.environ.get('BARIS_MANAGER_TOKEN', '')
    supplied = request.headers.get('x-baris-manager', '')
    if not secret or not secrets.compare_digest(secret.encode(), supplied.encode()):
        raise HTTPException(403, 'Yönetilen başlatıcı kimliği doğrulanamadı.')
    # Signal this server only after the response; the launcher never targets an unverified PID.
    asyncio.get_running_loop().call_later(.1, os.kill, os.getpid(), signal.SIGTERM)
    return {'status': 'STOPPING'}


@app.post("/api/tasks", status_code=202)
async def submit(req: TaskRequest, request: Request, engine=Depends(service)):
    task_id = enqueue(req, request, engine)
    return {"task_id": task_id, "status_url": "/api/tasks/" + task_id}


@app.get("/api/tasks/{task_id}")
async def status(task_id: str, after: int = 0, engine=Depends(service)):
    try:
        return engine.store.public(task_id, max(0, after))
    except KeyError:
        raise HTTPException(404, "Görev bulunamadı.")


@app.post("/api/tasks/{task_id}/cancel", status_code=202)
async def cancel(task_id: str, engine=Depends(service)):
    try:
        engine.store.request_cancel(task_id)
    except KeyError:
        raise HTTPException(404, "Görev bulunamadı.")
    return {"task_id": task_id, "message": "Durdurma isteği kaydedildi."}


@app.post("/api/chat")
async def compatible_chat(req: TaskRequest, request: Request, engine=Depends(service)):
    task_id = enqueue(req, request, engine)
    # Existing curl clients get a result quickly or a durable job handle, never a lost job.
    for _ in range(50):
        job = engine.store.public(task_id)
        if job["result"]:
            return job["result"]
        await asyncio.sleep(0.1)
    return JSONResponse(status_code=202, content={
        "task_id": task_id, "status": "QUEUED_OR_RUNNING",
        "status_url": "/api/tasks/" + task_id,
        "verified": False, "reply": "Görev arka planda çalışıyor; durum bağlantısından izleyin."})
